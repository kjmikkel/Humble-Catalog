# Humble Catalog

Local searchable catalog of HumbleBundle e-books, audiobooks, and comics.

> **Unaffiliated with Humble Bundle.** This is an independent hobby
> project, not endorsed by, sponsored by, or connected to Humble Bundle
> in any way; "Humble Bundle" is their trademark, used here only to say
> what the tool reads. It signs in to _your own_ account in a browser
> window you drive yourself, to catalogue purchases you already made.
> Nothing leaves your machine: the catalog, covers, and cached API
> responses are all local files, no credentials are stored by this
> project, and there is no server anywhere but the one you run.

Runs on Windows, macOS, and Linux. Python 3.12 or newer.

![The catalog viewer: a sortable table of owned books with genre, author, publisher and bundle columns, filtered here to a single bundle](docs/screenshot-viewer.png)

_The viewer, filtered to one bundle — search, the column filters and the
status chips all narrow the same table. This screenshot predates the
sections described below and shows the older one-page layout._

The viewer has five sections, switched by the tabs and addressable by
URL: **Library** (the table, its filters and the statistics summary),
**Maintenance** (the review queue and possible duplicates), **Keys**
(store keys whose game is in none of your imported libraries),
**Bundles** (paste a bundle URL, or check this month's Humble Choice, to
see what you already own), and **Tasks** (run the catalog commands —
fetching, harvesting, enriching, importing, backing up — and watch them
go). A tab shows
a count when its section is waiting on something — a queue you can empty,
never an optional backlog. In Library the filters live in a sidebar that
folds away; whatever is currently narrowing the table stays listed beside
the toolbar, so a folded sidebar can never hide the reason a search looks
empty. The filters survive a reload, but never silently: a banner says
they were restored and offers to start fresh. They are kept in the
browser, never in the address bar, where author and tag names would end
up in history; the phone viewer does not keep them at all.

## One-time setup

Only this section differs by platform. Create and activate a virtual
environment:

|          | Windows (PowerShell)         | macOS / Linux               |
| -------- | ---------------------------- | --------------------------- |
| Create   | `py -3.12 -m venv .venv`     | `python3.12 -m venv .venv`  |
| Activate | `.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |

Then, with it active, the rest is the same everywhere:

```
python -m pip install -e ".[dev]"
playwright install chromium
```

Two platform notes. If PowerShell refuses the activation script, it is
the execution policy, not the project:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once will allow it.
On Debian and Ubuntu, `apt install python3.12-venv` first — they ship
`venv` without `ensurepip`, so otherwise you get an environment with no
pip in it.

Every command below assumes that activated environment. Forget it and
the tool says so, naming the interpreter it is actually running under
rather than failing with a puzzling `ModuleNotFoundError` — worth knowing
because on Windows a missed activation is otherwise silent, `python`
being the Microsoft Store stub, which exists.

If you would rather not activate anything, two options avoid the
question: name the interpreter explicitly, as in `.venv\Scripts\python -m
humble_catalog enrich` (`.venv/bin/python` elsewhere), or use the per-OS
wrappers in `scripts/`, which locate the environment themselves — see
[scripts/README.md](scripts/README.md).

### Optional API keys (better enrichment)

- `HARDCOVER_API_KEY` - free from hardcover.app (Settings -> Hardcover API).
  Paste it with or without the leading "Bearer " - both work.
- `COMICVINE_API_KEY` - free from comicvine.gamespot.com/api
- `GOOGLE_BOOKS_API_KEY` - optional; Google Books is skipped without it
  (Google no longer allows keyless Books API queries). Free key via
  console.cloud.google.com -> APIs -> Books API -> Credentials.

The keys are read from the environment, so set them however your system
persists environment variables — on Windows, Settings -> Environment
Variables; on macOS and Linux, an `export HARDCOVER_API_KEY=...` line in
`~/.zshrc` or `~/.bashrc`. Rotating a key later is safe: keys are never
stored in the database or used to index the harvested cache, so a new
key still finds everything the old one fetched.

### Optional: Steam, for game-bundle previews

Only needed if you want `bundle` to tell you which games in a game
bundle you already own. Book bundles need none of this, and `bundle`
works without it — it just reports Steam titles as a store you have
never imported rather than guessing.

Steam's local files cannot answer "what do I own": `appmanifest_*.acf`
lists only _installed_ games, and a game from a Humble key is typically
activated and never installed — precisely the ones a bundle is most
likely to duplicate. So this goes through Steam's Web API, which needs
three things.

**1. An API key.** Free from
[steamcommunity.com/dev/apikey](https://steamcommunity.com/dev/apikey),
signed in as yourself. The form asks for a domain name; it is not used
for anything here, so `localhost` is fine. Set it as `STEAM_API_KEY`.

**2. Your SteamID64** — the 17-digit numeric id, not your display name.
If your profile URL looks like `steamcommunity.com/profiles/7656119…`,
the number _is_ your SteamID64. If it looks like
`steamcommunity.com/id/somename`, you chose a custom URL and the number
is hidden; with the key from step 1 you can resolve it:

```
https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?key=YOUR_KEY&vanityurl=somename
```

Set the result as `STEAM_ID`.

**3. Game details set to public.** Steam -> Profile -> Privacy Settings
-> Game details -> Public. This is the step people miss, and Steam makes
it easy to miss: a private profile does not return an error, it returns
an empty list, which is indistinguishable from owning nothing. The
import treats that as a failure rather than wiping your imported library
— you will see `steam FAILED: Steam returned no games …` and the
previous rows are kept.

With both variables set, `python -m humble_catalog import-games` reports
`steam <n> games (Web API)`. With either missing it prints
`steam skipped (set STEAM_API_KEY and STEAM_ID)` and imports the other
stores normally.

## Usage

Everything below is a subcommand of `python -m humble_catalog`. The
sections run in the order you would use them: build the catalog, enrich
it, then read it.

### Building the catalog

- `python -m humble_catalog update` - the whole import in one go:
  `extract`, `harvest`, `enrich` and `enrich --series`, in that order,
  each described below. It stops at the first step that fails (an
  expired login stops it before anything is harvested), with a line
  saying which step. A harvest that runs out of a source's daily quota
  does **not** stop it: enrichment works with what is cached, the
  summary names the sources still behind, and running `update` again
  later continues the harvest where it stopped. `--games` also imports
  your game libraries at the end, and `--no-harvest` refreshes from the
  cache without any metadata requests. This is what the viewer's
  **Update everything** card runs. Use the individual commands below
  when you want one step on its own.
- `python -m humble_catalog extract` - fetch your library.
  First run opens a normal browser window: log in to HumbleBundle
  (Google + TFA), then close the window when your library is visible.
  Later runs are unattended and only fetch new bundles.
  (`... -m humble_catalog login` re-opens the login window on its own.)
- `python -m humble_catalog reparse` - rebuild the catalog
  from the local bundle cache without contacting HumbleBundle: re-applies
  parsing/classification and re-links any covers already on disk. It runs
  automatically at the start of every `extract`; run it on its own to
  rebuild after a `reset` or a parser change.
- `python -m humble_catalog reset` - wipe the derived catalog
  for a clean rebuild without re-downloading. The download caches
  (`raw_orders`, the harvested `source_cache`, and the harvest's failure
  and run history), your cover files, and your ratings/tags/comments are
  kept; hand edits, type overrides, and merges are not. It asks you to
  type `RESET` first and refuses to run non-interactively. Afterwards
  rebuild with `reparse`, then `harvest` (a no-op if already cached),
  then `enrich` - all offline against the caches.

### Enriching

Enrichment runs in three phases so the slow network work happens once and
matching stays cheap:

- `python -m humble_catalog harvest` - fetch every relevant
  metadata source for every book/comic into the local cache, all sources
  in parallel (one thread each, each keeping its own courteous throttle).
  This is the long one - hours, dominated by Comic Vine's 200-requests/hour
  limit - but it is **resumable**: interrupt it and rerun `harvest` to pick
  up where it stopped (already-fetched titles are served from cache, for
  free). Run it once, fine to leave overnight.
  Each source shows its own counter and a state mark: `▸` still working,
  `✓` finished, `✗` gave up, `⏸` out of quota (falling back to
  `~ + x =` on consoles that cannot draw them). The counter is how many
  titles that source _has data for_, so a source that gave up shows how
  far it got rather than rounding itself up.
  A source that exhausts its daily quota is marked `⏸`, keeps serving
  its cached titles to the end of the run, and the run remembers when
  the limit lifts. The next `harvest` therefore serves that source from
  cache without spending a request to rediscover the same wall, and says
  when to come back instead of reporting a fresh failure. Google Books
  has the smallest daily allowance and typically needs several days of
  runs. Use `harvest --ignore-quota` to retry a recorded source anyway —
  after adding a key with a bigger allowance, say; any successful
  request clears the record by itself.
  When a harvest looks slower than it should, see [Diagnosing
  enrichment](#diagnosing-enrichment) below.

- `python -m humble_catalog enrich` - match items against the
  harvested cache and fill genre/series/ratings/narrator. Purely local,
  runs in seconds, safe to re-run as often as you like (e.g. after tuning
  the matcher). `--retry` also re-scores items that previously found no
  match.
  Hand-edited rows are left alone; queue one for re-enrichment with the
  row's `↻` button in the viewer, or all of them at once with
  `enrich --override-edited` (which asks you to type OVERRIDE first).
  Either way only a confident match is applied, and the values it
  replaces become the row's new Revert target.
- `python -m humble_catalog enrich --credits` - fill
  writer/illustrator for matched comics from Comic Vine (a second per-comic
  request, so slower). Resumable.
- `python -m humble_catalog enrich --series` - fill the series name and
  number for items whose own title states a volume ("Shadow Hound Vol. 2"),
  where no source supplied them. Local and instant. Never overwrites a
  value you or a source already set, so it is safe to repeat - and you
  will want to after `enrich --reset`, which clears both fields.

### Diagnosing enrichment

Three read-only reports, for when enrichment is emptier or slower than
expected. All of them read the database (or make one tiny request) and
exit, so none costs you a harvest.

- `python -m humble_catalog check` - one live search against
  every metadata source to verify each API (and key) works. Start here
  when a source is filling nothing at all: a missing key shows as SKIP
  and a rejected one as FAIL, and both look identical from the catalog.

The other two explain a harvest that runs but is slow. A title a source
could not fetch caches nothing, so the next run asks it again — at its
own place in the alphabetical worklist, which is ahead of every title
the budget has not reached yet. Each run ends by naming the five worst
titles that have now failed in two or more runs (and counting the rest);
`harvest --failures` lists every one of them, at any time:

```
runs  last failed  source        title
   5  2026-07-31   google_books  Learn C#
   4  2026-07-31   google_books  The Endless Wars: Inferno!
   2  2026-07-31   google_books  Moonfall Vol. 1-3
   1  2026-07-28   comicvine     Shadow Hound Vol. 1-6

Errors seen:
  3x  503 Server Error: Service Unavailable
  1x  ConnectionError: connection aborted
```

`runs` is how many separate harvests that title has failed in, and it is
the number that matters. A title sitting at 1 was unlucky; one that
climbs by one after every run is failing reproducibly, which points at
the query rather than at the network. The error tally groups by kind, so
a single cause behind many titles shows up as one large count rather
than as noise.

`harvest --runs` shows what each run cost:

```
harvest runs, newest first

started           source        titles   live  failed   rate  quota
2026-07-31 21:25  google_books    1718    573     427    43%  spent
2026-07-31 21:25  hardcover       1320      7       0     0%
2026-07-31 21:25  oreilly         1214      0       0      -
```

`titles` is how many that source resolved in the run, cache hits
included; `live` is how many it actually fetched; `rate` is the share of
live attempts that failed. `quota` marks a source whose daily budget ran
out during that run — and only then is its `rate` measured against a
full day's allowance, which is what makes google_books' 43% above a fair
figure and not a sample of seven. A source that attempted nothing live
is served entirely from cache and shows `-` rather than `0%`, which
would claim it never fails; `oreilly` above is finished, `hardcover`
genuinely fetched seven titles without a failure. `harvest
--forget-runs` clears the history, which is capped at the newest 500
runs regardless.

A harvest that is stopped partway through (Ctrl+C, a closed window, a
job cancelled from the viewer) still gets a row, but only once the next
harvest starts: that is when it can tell the run is over rather than
still going somewhere else. Until then `--runs` names it at the top.
Its rows are marked `interrupted` and show `?` under `titles`, a count
that only ever lived in the stopped process. `live`, `failed` and `rate`
are real, counted from what the run had already written, and bad runs
are the ones most likely to be stopped, so they are worth keeping.

In practice: read `--runs` after a harvest to see whether the failure
rate is steady or climbing, and `--failures` once two or more runs have
happened to see whether the same titles keep coming back. A steady rate
with titles that rarely repeat is a source that is merely slow, and it
will finish. Titles whose `runs` count keeps rising are a source that
will never finish those particular titles, however many days you give
it.

**`harvest --failures` prints titles you own; `harvest --runs` does
not.** If you are pasting output into an issue or a message, the run
table is counts, source names and timestamps only.

### Browsing

- `python -m humble_catalog serve` - open the catalog. Progress of a
  running extract/enrich shows in a banner; closing the browser never
  interrupts them.

The viewer's **Tasks** tab runs the catalog commands for you. **Update
everything** at the top runs `update`, which is all a routine refresh
needs. Below it, under **Individual steps**: fetching new bundles,
harvesting, enriching, importing a spreadsheet or your game libraries,
and taking a backup. Each runs as a separate process with its
progress, its output and a Cancel button on the page. A command started
in a terminal still shows in the banner, as it always did.

`login`, `reset` and `restore` are there too, marked **uses the
terminal**, because each needs something a background process cannot
have: a browser window to click through, a database file nobody holds
open, or a word typed at a console. Clicking one twice hands it to the
terminal you started `serve` from: the viewer steps down, the command
runs there — `reset` and `restore` still ask you to type `RESET` or
`RESTORE` — and the page reconnects by itself when it finishes. Ctrl-C
during the command cancels it and brings the viewer back; a second
Ctrl-C quits `serve` as usual. A restore is chosen from the snapshots
already in `backups/`. The handoff needs a viewer started with
`python -m humble_catalog serve` in a terminal you can see. A viewer
with no terminal — started detached, or with `serve --no-handoff` —
shows those three cards disabled, with the command to run yourself.

The viewer's tabs are described [at the top of this
page](#humble-catalog); what follows is what the Library table itself
can do.

**Search.** The box matches names loosely: word order may differ, words
may be skipped, and small typos, accents and apostrophes are tolerated.
Initials work too — "woe" finds "The World of Examplia". While the box
has text, rows are ordered by how well they match (the count line says
"by relevance"); clicking a column header returns to sorting by that
column.

**Reading status.** Each row has a Status dropdown (Want to read /
Unread / Reading / Read / DNF). The status chips above the table filter
to any set of statuses, and the Status column sorts by reading order
rather than alphabetically. Status is independent of your rating, and
both are kept when you `reset`.

**Ratings.** Click a star in the Mine column to rate a row one to five.
Clicking the star that matches the current rating clears it instead, so a
rating set by mistake is one click from gone; each star's tooltip names
what its own click will do. On a phone the edit sheet has a named
**Clear** button beside the stars.

**Hand edits and re-enrichment.** A row you edit by hand carries an
"edited" badge, `↩` to revert it and `↻` to queue it for the next enrich
run. Queued rows show "re-enrich queued" and are listed by the "Queued
for re-enrich" flag filter, so you can review or clear the whole set
before running `enrich`. Once a run replaces one, it reads "re-enriched"
and `↩` gives your typed values back.

### Getting data in and out

- `python -m humble_catalog import-sheets [file.xlsx ...]` - import
  ratings and metadata you already keep in a spreadsheet. Ratings go to
  "Mine", and genre/series/author/narrator fill empty fields (never
  overwriting enrichment or your edits; filled rows show the "edited"
  badge and can be reverted). Rows it can't match with certainty are
  listed with a closest-title hint - fix those by hand in the viewer.
  Safe to re-run any time.
  Any `.xlsx` works, not just the author's own two files: row 1 holds
  the headers, `Name` is the only required column, and columns it does
  not recognise are now listed at the end of the run rather than
  ignored in silence. One rule is easy to trip over — a workbook is
  matched against audiobooks only if its **file name** contains
  "audiobook", and against ebooks and comics otherwise.
  [docs/SPREADSHEET-FORMAT.md](docs/SPREADSHEET-FORMAT.md) is the full
  specification: accepted headers, value rules, matching, and what to
  check when an import does nothing.
- `python -m humble_catalog export [file]` - write the whole
  catalog for Excel/Sheets. The suffix picks the format: `catalog.csv`
  (the default) or `catalog.xlsx` for a styled workbook with a frozen
  header, an autofilter and typed rating/date cells. Add
  `--columns title,authors,my_rating` for a subset; the columns always
  come out in their usual order whatever order you ask in, and an
  unrecognized name is an error rather than a quietly missing column.
- In the viewer, the Download button exports every row the current
  filters and search match, in the order shown - including any past the
  first 200 the list draws before "Show all". Filter or search first and
  the button says how many rows will leave. The dropdown beside it picks CSV or XLSX, and
  the "Columns" panel picks which columns go in; that selection is
  remembered between visits, and the summary always shows how many of the
  20 are ticked. Narrowing either rows or columns names the file
  `catalog-filtered.*`, so a partial export never overwrites the full
  one. Untouched, it is the whole catalog (`catalog.csv`), the same file
  the CLI writes.

### Backups

- `python -m humble_catalog backup [dir]` - write a
  timestamped snapshot of `catalog.db` to `backups/` (or a directory you
  name - an external drive works). The copy goes through SQLite's online
  backup API, so it is consistent even while `serve` is running, and it
  is a single self-contained file. `--covers` also archives `covers/`
  beside it as a zip. Nothing is ever deleted: old snapshots stay until
  you remove them.
- `python -m humble_catalog restore <snapshot>` - put a
  snapshot back. It checks the file is a readable database first, shows
  what is being replaced, and asks you to type `RESTORE`; it refuses to
  run non-interactively. Your current catalog is snapshotted first, so a
  mistaken restore is itself undoable. Stop `serve` before restoring -
  with the viewer running the swap refuses rather than risking the file.
  `--covers` also restores the cover archive paired with that snapshot.

### Before you buy

These work together: `import-games` is what gives `bundle`, `choice` and
`keys` a library to check a game against.

- `python -m humble_catalog bundle <url>` - point it at a
  live HumbleBundle page and see, for each tier, how many items it holds,
  how many you already own, how many would be new, and which titles that
  tier adds over the cheaper ones. For books ownership is
  exact - the page names each item with the same internal id your
  catalog stores - so a re-run of a bundle you bought before reads as
  owned rather than as a guess. Titles that merely _look_ like something
  you own (a Vol. 1-6 omnibus against a Vol. 1 you have) are listed
  separately as possible partial overlaps rather than counted either way.
  Read-only and needs no login: nothing is written to the catalog.
  Game bundles are matched differently. Steam and GOG titles have no
  shared id with your imported libraries, so ownership for games is
  matched **by title and is approximate** - a near-miss can read as
  owned, and a re-release or edition difference can read as new. Treat
  the game counts as a strong hint, not a fact, and check anything you'd
  base a purchase on against the launcher itself. Titles it cannot
  decide about are counted as neither owned nor new and listed as
  "possible", and a game delivered on a store you have never imported is
  reported as such rather than quietly counted as new.
- `python -m humble_catalog choice` - the same question for this
  month's Humble Choice: how many of its games you already own, how many
  would be new, and the one price it all costs. Ownership is counted
  wherever it comes from - a game in an imported library, and a game you
  hold as a Humble key from an earlier bundle whether or not you ever
  claimed it. Unlike `bundle` this **needs your Humble login**, because a
  signed-out Choice page carries no data at all; it uses the same saved
  session as `extract` and prompts you through a browser if it has
  expired. Everything a Choice month offers is a game, so ownership is
  matched **by title and is approximate** throughout - run `import-games`
  first or every game reads as new, and check anything you would buy on.
  Titles it cannot decide about are counted as neither owned nor new.
  Read-only: nothing is written to the catalog.
- `python -m humble_catalog import-games` - import your game
  libraries so `bundle` can tell which games you already own. GOG, Epic,
  Amazon and Zoom are read from the caches
  [Heroic](https://heroicgameslauncher.com/) already keeps on disk - no
  login and no network, but Heroic must be installed and logged in, and
  the data is only as fresh as its last refresh. Steam comes from its Web
  API and needs `STEAM_API_KEY`, `STEAM_ID`, and a public game-details
  setting — see [Optional: Steam, for game-bundle
  previews](#optional-steam-for-game-bundle-previews) above; without
  them Steam is skipped and the other stores still import. Re-run it any
  time; each store is replaced whole, a store that fails leaves its
  previous rows alone, and an import that comes back empty is treated as
  an error rather than as "you own nothing". Games are kept apart from
  the book catalog: they are never enriched, never given covers, and
  never shown in the viewer - your launchers already do that.
- `python -m humble_catalog keys` - list the store keys from past
  bundles whose game appears in none of the libraries you have imported:
  what you have paid for and, as far as this can tell, never claimed. It
  prints the counts and the keys with an expiry date still ahead of them,
  which are the ones you can still lose; `--all` adds the undated ones
  and the ones already expired. Rows you have hidden in the viewer are
  left out, behind a count; `--hidden` lists those instead, with the date
  you hid each one. A key is matched only against **its own
  store** - a Steam key whose game sits in your GOG library is still an
  unactivated Steam key - and the match is **by title and approximate**,
  the same warning `bundle` carries, so treat a row as somewhere to look
  rather than as a verdict. Keys for stores with no importer (Uplay,
  Paizo, DriveThruRPG and a long tail below them) are reported apart and
  never counted as unclaimed: with no library to check against, "not in
  any library" cannot be true or false there. Note also that Humble marks
  a key redeemed the moment its value is *revealed*, which says nothing
  about whether the game ever reached a store account - which is why the
  report matches libraries instead of trusting that flag. The `keys`
  command itself is read-only; the one thing that writes is **hiding** a
  row, which is done from the viewer's Keys section and records your
  assertion that wherever that key ended up, you know it is resolved.
  A hide is per key rather than per game, so the same game keyed in two
  bundles stays two rows - one may have landed and the other not - and
  it survives `reset`, since no rebuild can recover what you know about
  what happened off this machine.
All data lives in `catalog.db` + `covers/` (both git-ignored).

## Development

`scripts/verify` (per-OS wrappers in `scripts/windows|macos|linux/`) runs
everything that must pass before a commit: the test suite, then the
privacy checks. See [scripts/README.md](scripts/README.md).

Three privacy checks guard the same rule — that nothing revealing the
owner's actual library reaches the repo:

- `scripts/check_no_data_tracked.py` asks whether a data _file_ is
  tracked — the catalog, a cover, a spreadsheet, an export — in the
  current tree or anywhere in history. Path names only, so it needs no
  catalog and is a real gate on any clone. Part of `verify`.
- `scripts/leak_check.py` scans the working tree for private _terms_.
  Part of `verify`, so it runs constantly.
- `scripts/leak_check_history.py` runs the same terms against every git
  object and commit message. Slower and not part of `verify`; run it
  before a first push to a public remote, and after any history rewrite.
  A clean working tree says nothing about the commits beneath it.

The two term checks derive their search terms at runtime from
`catalog.db` and the reference spreadsheets, so neither file contains
personal data — and on a clone without those, both report `SKIPPED`
rather than a misleading "clean".

**CI** (`.github/workflows/ci.yml`) runs the test suite on every push
and pull request, on Linux, Windows and macOS with Python 3.12, and on
Linux with Python 3.13 as well, plus both checks a runner can
meaningfully make: `check_no_data_tracked.py` is a genuine gate there,
while `leak_check.py` reports `SKIPPED` for want of a catalog and only
proves the gate still executes on a fresh clone. The term check that
means something is the local one, before you commit.
A new push to a pull request cancels that PR's run still in progress;
every push to `main` keeps its own complete run. Dependabot
(`.github/dependabot.yml`) checks weekly for new versions of the
workflows' actions, and for Python releases that fall outside a
requirement in `pyproject.toml`, and opens a PR labelled
`dependencies` for each group.

A second CI job, `smoke`, builds the wheel, installs it into a fresh
environment and opens the viewer in a real browser against the demo
catalog of invented titles (`scripts/smoke_viewer.py`). It fails on any
console error, failed request, empty Library or section that will not
open: the failures the unit tests cannot see, because none of them run
a browser.

**Releases** (`.github/workflows/release.yml`) are cut by pushing a
tag. Bump `version` in `pyproject.toml` in a PR, merge it, then tag the
merge commit on `main`:

```
git tag v0.3.0
git push origin v0.3.0
```

The workflow builds the wheel and sdist, then runs
`scripts/check_release.py`. It refuses a tag that does not match the
version, a `dist/` holding anything but one wheel and one sdist, a wheel
missing any of the viewer's files, and a tag on a commit that is not on
`main`. It then installs the wheel into a fresh environment, checks
that it serves the viewer, and only then publishes a GitHub release with
both files attached and notes generated from the merged PRs. A pull
request that changes any of the release files gets the same run as a
dry run, which publishes nothing. There is no PyPI upload.

**PR labels** (`.github/workflows/pr-labels.yml`): when a pull request
is opened or its description edited, the labels of the issues it closes
(`Fixes #N`) are copied onto it. It only adds labels, never removes
them. It runs for PRs from forks too, which needs a token that can
write, so it deliberately never checks out or runs anything from the
PR: it reads the PR's number and talks to GitHub's API, nothing more.

### Viewing on your phone

`python -m humble_catalog serve --lan` also serves a **read-only** copy of
the viewer to your home network, over HTTPS. Phones see Library and Keys,
can search and filter, and can follow each item's bundle link to its
Humble download page. Nothing can be edited from the phone, and on a
narrow screen each item is a card rather than a table row.

**Once:** run `serve --lan --setup`. It prints a link and a QR code for a
certificate. Open it on the phone, then install it under Settings →
Security → Encryption & credentials → Install a certificate → CA
certificate. Compare the SHA-256 fingerprint shown under Trusted
credentials → User with the one printed in the terminal.

**Each device:** open the pairing link `serve --lan` prints (or scan its
QR code). The phone stays paired until you run
`serve --lan --new-token`, which unpairs every device.

The pairing link is a password to your catalog: never paste it anywhere.
Everything `--lan` keeps is in a `lan/` folder next to `catalog.db`;
delete that folder to start over, then run `--setup` again and reinstall
the certificate. Use `--lan-host` if the address it picks is wrong and
`--lan-port` if the port is taken. The server certificate lasts 30 days,
so restart a `serve --lan` left running longer than that. Editing needs
the full viewer on the PC in a window wider than 600 px.

### The viewer's exposure

`serve` binds `127.0.0.1` only, so nothing on your network can reach it,
and it never enables Flask's debugger. Werkzeug still prints "This is a
development server. Do not use it in a production deployment." on every
start — that warning is about serving the public internet, which this
never does; it is expected here, not a sign of misconfiguration.

Two application-level defences matter more than the server it runs on,
because a production WSGI server would not provide either:

- **Requests addressed to any host but localhost are refused** (403,
  before routing). Loopback binding alone does not stop DNS rebinding: a
  page on `evil.com` whose name is re-pointed at `127.0.0.1` becomes
  same-origin with the viewer and can then read your whole catalog. The
  browser keeps sending `Host: evil.com`, so checking it closes the hole.
- **Every write endpoint takes JSON only.** A cross-origin HTML form can
  send only form-encoded, multipart, or plain-text bodies, all of which
  are refused; a cross-origin `fetch` sending JSON needs a CORS preflight
  the app never grants. So a page you visit cannot drive the API.

Since the Tasks tab, the viewer can also **start catalog commands** as child
processes, through its `/api/jobs` endpoints. That widens what a program on
your own machine could do through the port — it could begin a harvest, or an
import — so it is worth knowing. Three things bound it. The two defences above are unchanged, so a page you
visit still cannot drive any of it. The command line is built from a fixed
table of commands and flags, never from anything in the request, so no
string from a caller reaches a process argument. And the destructive
commands cannot be run this way, only handed over: a program on your
machine could make the viewer hand `reset` or `restore` to its terminal,
but nothing is wiped or replaced until a person types `RESET` or
`RESTORE` there, and a restore can only name a snapshot already in
`backups/`. Handing over `login` at most opens a browser window.

Note that any process on your own machine can still reach the port —
worth knowing if the machine is shared.

`serve --lan` adds a second server on your LAN address. It is bounded by
four things. It is a separate app that **has** no write routes, rather
than one that refuses them, and a test pins the exact list it serves. It
answers only requests addressed to its own LAN address, which refuses DNS
rebinding the same way the loopback check does. Every request needs the
pairing cookie. And it is HTTPS from a certificate authority that is
constrained to private addresses, so even a leaked `lan/ca.key` could not
impersonate a real website. A paired device can read the whole catalog,
order keys included, for as long as `--lan` runs.

## License

[MIT](LICENSE).
