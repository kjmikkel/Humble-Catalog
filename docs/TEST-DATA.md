# Canonical invented test data

All examples in committed text (tests, fixtures, docs, commit messages)
must use invented names — never real items from the owner's library
(see `CLAUDE.md`). This file is the shared universe of invented data:
pull from it so examples stay consistent, and add new entries here when
a test needs something new. `scripts/leak_check.py` verifies nothing
from the real library leaks into the repo; run it after adding tests
or fixtures that name books, bundles, or people.

## Bundles

| Name | Used for |
|---|---|
| Humble Book Bundle: Test by Example Press | ebook order fixture (`order_book.json`, gamekey `abc123`) |
| Humble Book Bundle: Samples by Example Press | anonymized capture output (`capture_order_fixture.py`) |
| The World of Examplia by Example Press | large multi-book bundle example |
| Humble Audiobook Bundle: Epic Tales 2020 by Example Audio | audiobook classification |
| Sample Authors and More Audiobooks from Example Press | audiobook bundle without "Bundle" in the name |
| Humble Comics Bundle: Shadow Hound | comic classification |
| Humble Mobile Bundle: Indie Games | android order fixture (`order_android.json`, gamekey `apk456`) |
| Humble Game Bundle: Samples | game/music (soundtrack) classification |
| Sample Studios: TTRPG Audio Compendium | non-"Humble"-prefixed audio bundle |
| Bundle One | minimal placeholder bundle |
| Humble Game Bundle: Key Vault | a past order whose games arrived as store keys, not as items (`external_keys`); bundle-preview keyed-ownership example |
| Humble Game Bundle: Expiring Keys | an order whose keys carry expiry dates; key-report sort-order example |

## User tags

The owner's personal vocabulary is separate from genre and is never
titleized, so these keep the casing they are written with here.

| Tag | Used for |
|---|---|
| lent out | bulk tagging and bulk-undo examples; the tag whose loss has no revert |
| to reread | second tag, for asserting that an operation touches one and not the other |
| Lent Out / To Reread | title-case variants, for the snap-to-an-existing-spelling tests |

## E-books

| Title | Author(s) | Publisher | Notes |
|---|---|---|---|
| Building Widget Services 2e / Building Widget Services, 2nd Edition / , 2nd ed. | — | Example Press | edition-variant duplicate pair; also the 1.00 overlap in the bundle-preview overlap-sort test |
| Learning Widget-Driven Design, 1st Edition | — | — | edition-suffix title cleanup |
| Learn C# / Learn C / Learn Java | — | — | `#`/`+` significance in dedupe |
| The Widget Programming Language, 2nd Edition | Sam Coder, Alex Dev | — | O'Reilly-source payload |
| The Quiet Harbor: A Novel | — | — | subtitle cleanup |
| Wings of Autumn Dusk (Book 1) | — | — | series-number-in-title cleanup |
| Unrelated Book | — | — | non-duplicate control row |
| Café of Broken Clocks | — | — | accent folding in fuzzy search; also the accent-not-the-deciding-character case in the harvest worklist sort |
| Gray Waters / gray waters | — | — | case-only pair for the worklist-order tie test; `Gray Waters` alone is the plain ebook row in `test_harvest.py` |
| A Quiet Life in Harbors | — | — | relevance-ordering foil for *The Quiet Harbor* |
| The World of Examplia | — | — | acronym-tier fuzzy search ("woe"); also a bundle name |
| Salt and Sextant | — | — | ebook half of the marker-suffix edition pair (`editions.edition_key`) |
| Salt & Sextant | — | — | ampersand drift offered against the owned *Salt and Sextant*; scores 0.92 through `clean_title` + `token_set_ratio`, the lowest overlap in the bundle-preview overlap-sort test |
| The Copper Almanac | — | — | ebook half of the `(audio)`-classification edition pair |
| The Copper Almanacs | — | — | plural drift offered against the owned *The Copper Almanac*; scores 0.97, the middle overlap in the bundle-preview overlap-sort test |
| Compass | — | — | one-word subset-trap foil: `token_set_ratio` scores it 100 against *The Compass of Broken Years Audiobook*, and it must **not** group |
| Nightjar Post | — | — | comic↔ebook edition pair; the case the catalog does not yet hold |
| Audio Engineering Handbook | — | — | a leading "audio" that is part of the title, pinning the trailing-only marker strip |

## Audiobooks

| Title | Author | Narrator | Series | Notes |
|---|---|---|---|---|
| Axebearer (Grim & Fell) | Alex Penner | Sam Reader | The Elder Realm | spreadsheet-import row (sheet "Grimdark", bundle "Epic Tales") |
| The Starless War | — | — | — | exact-duplicate pair (twice as audiobook) |
| The Endless Wars: Inferno! | — | — | — | punctuation-heavy title normalization |
| How Sound Behaves | — | — | — | non-fiction row with N/A cells |
| Circle of Storms | — | — | (is a series) | hand-edit series example |
| Dune (Audiobook) | — | — | — | "(Audiobook)" suffix cleanup |
| Salt and Sextant Audiobook | — | — | — | trailing bare-marker edition pair, against the ebook *Salt and Sextant* |
| The Copper Almanac (audio) | — | — | — | trailing "(audio)" label; classified `music` before the classify fix, which is why the pair was invisible |
| The Compass of Broken Years Audiobook | — | — | — | subset-trap foil against the ebook *Compass* |
| Audio Ambience for Deep Space | — | — | — | leading "audio" in a game bundle; the regression guard that keeps the `(audio)` rule trailing-only |

## Comics / manga

| Title | Credits | Publisher | Notes |
|---|---|---|---|
| Shadow Hound Vol 1 | Bo Writer (writer), Alex Artist (artist) | Example Comics | ComicVine payloads; URL slug `shadow-hound` |
| Shadow Hound: Origins | Bo Writer (writer), Ann Inker (illustrator) | — | URL-import candidate |
| MOONFALL, Vol. 1 / Moonfall Vol. 1 | — | — | case/comma cosmetic duplicate pair |
| _(role-policy cast, no title)_ | Pat Pencil (penciler, inker), Ann Art (artist, cover), Ink Only (inker), Col Only (colorist), Cov Only (cover), Let Only (letterer), Ed Only (editor), Jo Journo (journalist) | — | one invented name per real Comic Vine role atom; pins the narrow illustrator policy in `test_split_credits_keeps_illustrator_narrow` |
| Innkeeper’s Ledger / Innkeeper's Ledger | — | — | curly-vs-straight apostrophe pair |
| Shadow Hound Vol. 1-6 | — | Example Comics | omnibus offered by a bundle against the owned *Shadow Hound Vol 1*; bundle-preview series example. **Measured 2026-08-01: this spelling occurs zero times among owned titles.** Kept because tests depend on it and because a range must still be *recognized* — parsed as its lower bound it would match the owned Vol. 1 and report the whole collection as already owned. It is also the only spelling stating its own denominator, so "you own 1 of 6" is derivable here and nowhere else |
| Moonfall Vol. 1-3 | — | — | second range/volume pair, against *MOONFALL, Vol. 1*; also the comma-versus-no-comma case for `series_key` |
| Shadow Hound Vol. 22 (#127-132) | — | Example Comics | an issue range annotating a **single** volume — the shape every real range in the catalog has, 8 of 11 of them. `clean_title` strips the parenthetical, so `parse_series` sees `Vol. 22`; pins that an issue range never becomes a volume count |
| S.H.A.D.O.W Vol. 1 / S.H.A.D.O.W. Vol. 2 / S.H.A.D.O.W.: Vol. 3 | — | — | one series split three ways by punctuation drift; pins that `series_key` merges them |
| Shadow-Hound Quest Vol. 1 / Shadow-Hound-Quest Vol. 2 | — | — | space-versus-hyphen drift, the second measured fragmentation |
| Moonfalls Vol. 1 | — | — | the negative: differs from *Moonfall* by more than punctuation and holds an overlapping volume set, so it must **not** merge |
| Shadow Hound Vol. 1: Origins | — | — | a marker followed by a subtitle — 113 of 679 volume markers in the catalog, so the parser cannot anchor to end-of-string alone |
| Shadow Hound Omnibus | — | Example Comics | a collection word, which carries no volume count and so states no denominator — "you own 2 volumes", never "2 of N" |
| Shadow Hound Vol. 2 | — | Example Comics | offered against an owned *Shadow Hound Vol 2* under a different machine_name: the re-buy case, reported ALREADY OWNED. Also the plain bare-marker row for the `enrich --series` fill |
| Shadow Hound Vol. 5 | — | Example Comics | a hand-edited row carrying the typed series name *Shadow Hound Legends*; pins that the `enrich --series` top-up leaves both the value and the `hand_edited` flag alone |
| _(series name only)_ Shadow Hound Chronicles | — | Example Comics | a series name a **source** supplied, deliberately unlike the *Shadow Hound* base a title split produces — the shape of the 78 catalog rows where the two disagree. Pins that the fill adds a number without touching the name. Both invented series names must stay distinct from the derived base, or a fixture cannot show which one was preferred |
| Nightjar Post | — | — | comic half of the comic↔ebook edition pair |
| Shadow Hound Vol 1 Bonus Art Pack | — | Example Comics | described in a bundle's `tier_item_data` but sold by no tier; bundle-preview phantom-item tests. Contains *Shadow Hound Vol 1*'s tokens, so `token_set_ratio` scores it 100 and it heads the overlap list if the exclusion regresses |

## Android / games / music

| Name | Publisher | Notes |
|---|---|---|
| Cool Tower Defense (+ " + OST" variant) | Indie Dev Co | android item, machine name `cooltower_android`. Also seeded as a `music` row of the bare name for the edition false-positive test — the committed `+ OST` variant classifies as android, so it cannot serve. This is the measured shape of every android/music collision: a game plus its own soundtrack |
| Sample Game OST | — | soundtrack in a game bundle |
| Sample Ambience Pack | — | audio pack in a TTRPG bundle |
| Some Album | — | generic music item |
| Bonus Wallpaper | — | non-book subproduct that parsers must skip |

## Owned game libraries (Steam / Heroic imports)

Rows an `import-games` run puts in the `games` table, and the bundle
items they are matched against. Store names are the values the importer
records: `steam`, `gog`, `epic`, `amazon`, `zoom`.

| Title | Store(s) | Notes |
|---|---|---|
| Widget Quest | steam | plain owned title; base of the edition/sequel pairs |
| Widget Quest: Definitive Edition | — (offered only) | edition suffix over an owned base — must read as **owned** |
| Widget Quest II | — (offered only) | sequel foil — must read as **new**, never as the owned *Widget Quest* |
| Pixel Harbor™ | gog | trademark symbol normalization |
| Neon Drifter | steam + gog | same game owned on two stores; must count once |
| Grove of Echoes | epic | owned only on a Heroic-backed store |
| Starfall Rally | steam | ambiguous-band pair against *Starfall Rally Turbo* |
| Starfall Rally Turbo | — (offered only) | close but not equal — the **possible** bucket, counted neither way |
| Lantern & Lockpick | — (offered only) | offered and owned nowhere — the plain **new** case |
| Humble Game Bundle: Story Sampler | — | invented game bundle for the preview fixture |
| Cinder Vale | — (keyed only) | held as an unactivated Humble **steam** key from *Key Vault*, so it is in no imported library — must read as **owned**, flagged as key-only |
| Verdant Reach | — (keyed only) | held as a Humble **uplay** key; uplay has no importer at all, so a key is the only evidence there can be |
| Quartz Meridian | — (offered only) | offered on uplay and owned nowhere, keyed or otherwise — the unmatched item that keeps the never-imported-store warning honest. Renamed once already: the first invented title contained a private term as a substring, invisibly. Vet a new title against `leak_check.build_terms()` before using it — `leak_check` matches substrings, so a word buried mid-title trips it |
| Amber Hollow | — (keyed only) | held as a Humble **steam** key carrying a live `expiry_date`; the key-report row that can still be lost |
| Glass Meridian | — (keyed only) | held as a Humble **steam** key whose `expiry_date` has passed; the key-report row that was lost |
| Humble Choice: January 2031 | — | invented Choice month for the choice-preview fixtures (`choice_hub.json`, `choice_page.html`). A future month on purpose, so it can never name a real one the owner subscribed to |
| Twin Lantern | — (keyed only) | one product keyed on **two** storefronts in a single order (`twinlantern_steam`, `twinlantern_gog`), so both tpks share the `human_name` "Twin Lantern". The `external_keys` primary-key collision fixture: under the old `(gamekey, human_name)` key the second write silently replaced the first |
| Hollowmere | — (keyed only) | second `human_name` collision, one key lost, so the migration's "still missing" message has more than one product to name |

## RPG supplements

| Title | Publisher | Notes |
|---|---|---|
| The Hollow Crypt | Example Games | RPG supplement on a storefront with no API; generic OpenGraph scrape and link-only fallback examples |
| Delve Deeper: Companion | Example Games | link-only row whose page blocks automated fetches (403) |

## Allowed real-world names (exceptions)

- **All Systems Red / Martha Wells / Kevin R. Free / The Murderbot
  Diaries** — the public house example used across tests and the
  Hardcover fixture. Famous public book; kept deliberately.
- **1632** — numeric-title edge case; reads as a number.
- Generic vocabulary: genre names (Fantasy, Science Fiction, Manga, …),
  major publishers (O'Reilly, Pearson, Wiley, No Starch Press, …), and
  platform names (Humble Bundle). Full reviewed list lives in
  `ALLOWED` in `scripts/leak_check.py` — extend it there, with a
  comment, when a new benign term trips the check.
