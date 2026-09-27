"""Preview how much of a live Humble bundle the catalog already holds.

Read-only throughout: nothing in this module writes to catalog.db. The
report is a question the owner asks before buying, not a fact about the
library, so there is deliberately no persistence and no cache.

Split at the network seam -- fetch_bundle() does the HTTP, preview() is
pure -- so every counting rule is testable from a committed fixture with
no network and no live bundle. Same split, and same reason, as
harvest/enrich.
"""
import json
import re
import sys
from urllib.parse import urlparse

from rapidfuzz import fuzz, process

from humble_catalog import db, import_games, series, shapes, stats, url_import
from humble_catalog.game_match import (classify_game, keyed_games,
                                       owned_games, prepare_pool)
from humble_catalog.titles import clean_title

# Titles that clear this score are shown as a possible partial overlap.
# Deliberately NOT matching.AUTO/REVIEW: those decide whether to write
# enrichment onto a row, this decides whether to show a human a hint.
# Measured against a live 36-item bundle: 0.60 and 0.75 were both
# unusable (unrelated titles sharing a volume suffix score 75), 0.90
# caught exactly the genuine omnibus/volume pairs.
OVERLAP = 90.0

# Where a shown score stops reading "loose" and starts reading "close"
# (#93). One line for both panels, so the word means the same score in
# each: book overlaps (OVERLAP and up) split across it, and a Choice
# `possible` (below game_match.GAME_OWNED) is always loose, which is true:
# none was close enough to count as owned.
CLOSE = 95.0


def strength(score):
    """The word the viewer shows for a 0-1 similarity score."""
    return "close match" if score * 100 >= CLOSE - 1e-9 else "loose match"

# The game-ownership cutoffs and classify_game live in game_match, which
# this module imports: the key report is a second caller, and it treats the
# band between them the opposite way round. See that module's docstring.

HOST = "humblebundle.com"
# The blob sits ~3/4 of the way into a ~650 KB page, so this path needs a
# bigger read than url_import's <head>-oriented default.
MAX_PAGE_BYTES = 8 * 1024 * 1024
_BLOB = re.compile(
    r'<script id="webpack-bundle-page-data" type="application/json">'
    r'(.*?)</script>', re.S)


def fetch_bundle(url, http=None):
    """The bundleData dict embedded in a live bundle page.

    Reuses url_import's fetch guards -- scheme allowlist, post-redirect
    re-check, size cap, shared retry policy -- but not its OpenGraph
    fallback: a bundle page needs its own parser, so this is a new
    handler rather than a degradation of that one.

    Raises ValueError for a non-Humble host or a page carrying no bundle
    data; lets HTTP and network errors propagate as themselves.

    The blob is third-party content, so it is read through `shapes`: a
    page whose JSON parses but is not the expected object yields an empty
    dict, which `preview` reports as a bundle selling nothing, rather than
    an AttributeError surfacing as a 500 from the viewer route.
    """
    parts = urlparse(url_import.normalize_url(url))
    host = parts.netloc.lower().removeprefix("www.")
    if host != HOST and not host.endswith("." + HOST):
        raise ValueError(f"not a HumbleBundle URL: {host or url}")
    page = url_import._read_capped(
        url_import._fetch_html(parts.geturl(), http), limit=MAX_PAGE_BYTES)
    match = _BLOB.search(page)
    if not match:
        # Measured 2026-07-31, and the old wording was wrong: a closed
        # bundle does not redirect. It serves its own URL with its own
        # <title>, ~530 KB of marketing shell, and no blob -- not even
        # its machine_name survives. Nor does an archive have it: every
        # Wayback capture of a sampled bundle is the shell, and Humble
        # exposes no JSON endpoint. So the message closes the door
        # rather than inviting a hunt for the working URL; the reasoning
        # is the out-of-scope entry in docs/BACKLOG.md.
        raise ValueError(
            "not a Humble bundle page (no bundle data found) -- a bundle "
            "that has closed still serves its page, but without its "
            "contents; they are not recoverable")
    blob = shapes.as_mapping(json.loads(match.group(1)))
    return shapes.as_mapping(blob.get("bundleData"))


# The live bundles are listed on Humble's own storefront pages (#95).
# Measured 2026-09-27: a logged-out GET of /books or /games embeds this
# block, whose data.<section>.mosaic[].products hold every live bundle --
# product_url, tile_name, machine_name, end date -- so one request per
# listing lists them all. The owned/new headline is NOT fetched here: it
# needs each bundle's own ~500 KB page, so the viewer asks for it one
# bundle at a time, when the owner clicks Check.
LISTING_KINDS = ("books", "games")
_LISTING_BLOB = re.compile(
    r'<script id="landingPage-json-data" type="application/json">'
    r'(.*?)</script>', re.S)
# A bundle page's path, and nothing else: no scheme, no host, no "..".
# Anything that fails this is dropped rather than made into a link.
_BUNDLE_PATH = re.compile(r"^/(books|games)/[a-z0-9][a-z0-9-]*$")


def _listing_tiles(node):
    """Every dict carrying a product_url, anywhere under `node`."""
    if isinstance(node, dict):
        if "product_url" in node:
            yield node
        for value in node.values():
            yield from _listing_tiles(value)
    elif isinstance(node, list):
        for value in node:
            yield from _listing_tiles(value)


def live_bundles(http=None, kinds=LISTING_KINDS):
    """[{kind, name, url, ends}] for the bundles live on Humble right now.

    One logged-out GET per listing page, through the same guarded fetch
    as fetch_bundle, and no cookies: the list is public. The blob is
    third-party content, so every field is read through `shapes` and a
    tile whose URL is not a plain /books/ or /games/ path is dropped --
    the viewer turns these into links and checks. Deduplicated on the
    URL (a "popular" section repeats tiles), sorted by kind, then the
    soonest to end.

    Raises ValueError when a listing no longer carries the block, which
    would mean the page changed shape; network errors propagate.
    """
    found = {}
    for kind in kinds:
        page = url_import._read_capped(
            url_import._fetch_html(f"https://www.{HOST}/{kind}", http),
            limit=MAX_PAGE_BYTES)
        match = _LISTING_BLOB.search(page)
        if not match:
            raise ValueError(f"the /{kind} listing carries no bundle list -- "
                             "Humble may have changed the page")
        try:
            blob = json.loads(match.group(1))
        except ValueError:
            blob = None
        for tile in _listing_tiles(blob):
            path = shapes.as_text(tile.get("product_url")) or ""
            if not _BUNDLE_PATH.match(path) or path in found:
                continue
            found[path] = {
                "kind": path.split("/")[1],
                "name": (shapes.as_text(tile.get("tile_name"))
                         or shapes.as_text(tile.get("machine_name")) or path),
                "url": f"https://www.{HOST}{path}",
                "ends": shapes.as_text(tile.get("end_date|datetime")) or "",
            }
    return sorted(found.values(),
                  key=lambda b: (b["kind"], b["ends"] or "~", b["name"].lower()))


def _owned(conn):
    """{machine_name: item_id} for every machine_name the catalog accounts for.

    The merges half is load-bearing. A duplicate merged away is not an
    items row any more, but it still names a book that is in the library;
    omitting it would report an owned item as new. It maps to the row it
    was merged INTO, which is the one the viewer can link to (#92).
    """
    rows = conn.execute(
        "SELECT machine_name, id FROM items "
        "UNION SELECT dropped_machine_name, kept_item_id FROM merges").fetchall()
    return {row[0]: row[1] for row in rows}


def _overlaps(conn, candidates):
    """Offered titles that look like partial matches for owned rows.

    `candidates` is {machine_name: offered_title} for the items a tier
    actually sells that matched no owned machine_name and took the book
    path. preview's tier walk builds it, having already decided both of
    those questions -- so an owned item, a game, and an item described in
    tier_item_data but sold by no tier are all unrepresentable here
    rather than filtered out. The exclusions used to be two sets passed
    in and re-applied; both were keyed to the sold set, so neither could
    name an entry the sold set never mentioned.

    Titles are compared through clean_title, the same normalization enrich
    matches on, so ": A Novel" and edition suffixes do not depress a score
    on either side.
    """
    rows = conn.execute("SELECT id, name FROM items").fetchall()
    if not rows:
        return []
    names = [clean_title(row["name"])[0] for row in rows]
    found = []
    for offered in candidates.values():
        hit = process.extractOne(
            clean_title(offered)[0], names, scorer=fuzz.token_set_ratio,
            processor=str.lower, score_cutoff=OVERLAP)
        if hit is None:
            continue
        row = rows[hit[2]]
        # The word from the ROUNDED score, the one the tooltip shows: from
        # the raw one, 0.949 read "loose" beside a printed 0.95.
        score = round(hit[1] / 100, 2)
        found.append({"offered": offered, "item_id": row["id"],
                      "item_name": row["name"], "score": score,
                      "strength": strength(score)})
    found.sort(key=lambda o: o["score"], reverse=True)
    return found


def _adds(ordered, items):
    """Fill each tier's `adds` with what it gains over the cheaper tiers.

    `ordered` is [(tier_dict, new_machine_names)] sorted price DESCENDING.
    Walks it cheapest-first against a running set, so the lists are
    disjoint and sum to the richest tier's `new` count.

    A running set rather than a difference against the next tier down:
    identical while the tiers nest, which they do today, but a bonus tier
    that is not a strict superset would make the pairwise form emit the
    same title twice, silently.

    Sorted case-insensitively rather than left in bundle order. The list
    is scanned -- is the one I want in here? -- and Humble's own ordering
    is a marketing decision that means nothing for that question.
    """
    seen = set()
    for tier, new_names in reversed(ordered):
        tier["adds"] = sorted(
            (shapes.as_text(shapes.as_mapping(items.get(name))
                            .get("human_name")) or name
             for name in new_names if name not in seen),
            key=str.lower)
        seen.update(new_names)


def delivery_stores(item):
    """The storefronts a bundle item is delivered on, as a set.

    Verified against a live bundle: `platforms_and_oses` is shaped
    {"game": {"steam": ["windows", "mac"]}} -- the inner key is the
    delivery store. An item with no game entry (a book, or the one
    observed entry carrying {}) yields an empty set and routes to the
    book path, so a mixed bundle needs no global decision.

    Read through `shapes` because this is third-party content and the
    quiet failure is the dangerous one: `set()` over a STRING yields its
    characters, so a `game` field arriving as "steam" produced five
    single-letter storefronts, each of which then read as a store the
    owner had never imported. Accepts any shape and answers with a set.
    """
    game = shapes.as_mapping(shapes.as_mapping(item).get("platforms_and_oses"))
    return set(shapes.as_mapping(game.get("game")))


def preview(conn, bundle, url=None):
    """The ownership report for one parsed bundleData dict.

    Pure: no network, no writes. `bundle` is what fetch_bundle returns.

    Two kinds of answer share this report and never share a line. Book
    items are matched on machine_name and are exact. Game items are
    matched on the title and are approximate, so they carry a third
    bucket -- `possible` -- for the band where the tool declines to guess.
    """
    owned = _owned(conn)
    # Prepared once, above the per-tier loop. This module scores tens of
    # items rather than thousands and was never slow; it prepares its
    # pools so game_match owns the sorted-key invariant, rather than
    # having it stated in the key report and not here.
    games = prepare_pool(owned_games(conn))
    # Tried only after the imported libraries have said "new", so a game
    # that is both keyed and activated reports as the plain library match
    # it is, and the keyed list stays what it claims to be: the games whose
    # only evidence is a key.
    keyed = keyed_games(conn)
    keyed_pool = prepare_pool(
        [(normalized, display) for normalized, display, _t, _b in keyed])
    # Keyed on the display title, which is what classify_game hands back.
    keyed_extra = {display: (key_type, bundle_name)
                   for _n, display, key_type, bundle_name in keyed}
    # Every read of `bundle` below goes through `shapes`: it is the parsed
    # bundle page, which the envelope classes adversarial, and `x or {}`
    # is not a type check - a NON-EMPTY list is truthy and reaches the
    # attribute access, which is why the empty-list cases looked clean.
    bundle = shapes.as_mapping(bundle)
    basic = shapes.as_mapping(bundle.get("basic_data"))
    pricing = shapes.as_mapping(bundle.get("tier_pricing_data"))
    items = shapes.as_mapping(bundle.get("tier_item_data"))
    # Sold, unowned, book-path items, keyed by machine_name so the same
    # name in two cumulative tiers is one candidate. A dict rather than a
    # set: _overlaps sorts by score and Python's sort is stable, so tie
    # order is input order -- and set iteration order of strings varies
    # between processes under hash randomization. Same trap the harvest
    # worklist sort documents.
    candidates = {}
    game_names = set()   # machine_names routed to title matching
    # Storefronts this bundle delivers on that still have an item nothing
    # accounted for. Deliberately not every store it delivers on: the
    # warning these feed says those items were counted as new by default,
    # and a store whose every item matched -- by key, or by a title the
    # owner has on another store -- makes that sentence false. Only a `new`
    # verdict counts; a `possible` was not counted as new either.
    unmatched_stores = set()
    # What is counted as owned, by machine_name so the same item in two
    # cumulative tiers is listed once (#92). The counts said how many;
    # this says which, which is the other half of "should I buy this".
    owned_found = {}
    # The row's own name, which the viewer's jump searches Library for;
    # the bundle's spelling of a title need not match it.
    row_names = dict(conn.execute("SELECT id, name FROM items").fetchall())
    ordered = []
    for key, display in shapes.as_mapping(
            bundle.get("tier_display_data")).items():
        # text_list, not as_list: a list field that arrived unwrapped as a
        # bare string is ONE name, never its characters. That is the rule
        # shapes.first_text and shapes.text_list already state, and the
        # defect this replaced counted a 1-item tier as 10 and offered
        # single letters as titles the owner would be buying.
        names = shapes.text_list(
            shapes.as_mapping(display).get("tier_item_machine_names")) or []
        new_names, possible, owned_count, keyed_hits = [], [], 0, []
        for name in names:
            item = shapes.as_mapping(items.get(name))
            if name in owned:
                owned_count += 1
                owned_found.setdefault(name, {
                    "offered": shapes.as_text(item.get("human_name")) or name,
                    "item_id": owned[name],
                    "item_name": row_names.get(owned[name]),
                    "owned_title": None, "keyed": False})
                continue
            if not delivery_stores(item):
                new_names.append(name)
                # Guarded on membership, not on `item`: a sold name that
                # tier_item_data does not describe is skipped, which is
                # what happens today -- it is not a key of items, so the
                # old iteration never reached it. The tier counts above
                # fall back to the bare machine_name and are right to;
                # counting must be exhaustive. Hinting must not be, and a
                # machine_name is not a title.
                if name in items:
                    candidates[name] = shapes.as_text(
                        item.get("human_name")) or name
                continue
            game_names.add(name)
            offered = shapes.as_text(item.get("human_name")) or name
            verdict, match = classify_game(offered, games)
            if verdict == "new":
                # Only an outright keyed 'owned' is honoured. A keyed
                # 'possible' would be a guess about a guess, so it is left
                # to fall through to whatever the libraries decided.
                keyed_verdict, keyed_match = classify_game(offered, keyed_pool)
                if keyed_verdict == "owned":
                    key_type, bundle_name = keyed_extra.get(
                        keyed_match["owned_title"], (None, None))
                    keyed_hits.append({**keyed_match, "key_type": key_type,
                                       "bundle": bundle_name})
                    owned_count += 1
                    owned_found.setdefault(name, {
                        "offered": offered, "item_id": None, "item_name": None,
                        "owned_title": keyed_match["owned_title"],
                        "keyed": True})
                    continue
            if verdict == "owned":
                owned_count += 1
                # A game has no catalog row: it names what it matched in
                # an imported library instead, and links nowhere.
                owned_found.setdefault(name, {
                    "offered": offered, "item_id": None, "item_name": None,
                    "owned_title": match["owned_title"], "keyed": False})
            elif verdict == "possible":
                possible.append({**match, "strength": strength(match["score"])})
            else:
                new_names.append(name)
                unmatched_stores |= delivery_stores(item)
        ordered.append(({
            # as_number, not a bare get: the amount is formatted with
            # `:.2f` downstream, so a string here raises inside the
            # report rather than at the read that accepted it.
            "price": shapes.as_number(
                shapes.as_mapping(shapes.as_mapping(pricing.get(key))
                                  .get("price|money")).get("amount")) or 0.0,
            "total": len(names),
            "owned": owned_count,
            "possible": len(possible),
            "possible_items": sorted(possible,
                                     key=lambda p: p["offered"].lower()),
            # Counted inside `owned` above, listed separately here: the
            # count answers "how much of this do I already have", the list
            # answers "and how sure is that" -- an unactivated key can be
            # region-locked or dead in a way a library entry cannot.
            "keyed": len(keyed_hits),
            "keyed_items": sorted(keyed_hits,
                                  key=lambda k: k["offered"].lower()),
            "new": len(new_names),
        }, new_names))
    # Sorted on the numeric amount, never on tier_order: that key was
    # observed descending but nothing documents that it must be.
    ordered.sort(key=lambda pair: pair[0]["price"], reverse=True)
    # Series lines are computed before _overlaps runs, and take their
    # candidates OUT of it. An offered Vol. 7 scores 94.7 against an owned
    # Vol. 3 -- over the 0.90 cutoff -- so it printed as "possibly already
    # owned in part" when it is certainly not owned at all, and the score
    # rises with the error: Vol. 7 against Vol. 17 scores 97.4. Meanwhile
    # an omnibus scores 77.4 against an owned volume and never appeared,
    # though that is the genuine partial-ownership case. The list showed
    # the wrong pairs and hid the right ones; each is reported once now,
    # in the place that describes it accurately.
    volumes = series.owned_volumes(conn)
    series_hits = []
    for machine_name, offered in list(candidates.items()):
        hit = series.describe(offered, volumes)
        if hit is None:
            continue
        series_hits.append(hit)
        del candidates[machine_name]
    series_hits.sort(key=series.sort_key)
    _adds(ordered, items)
    tiers = [tier for tier, _new_names in ordered]
    libraries = import_games.imported_stores(conn)
    return {
        "name": shapes.as_text(basic.get("human_name")) or "Humble Bundle",
        "url": url or shapes.as_text(bundle.get("page_url")) or "",
        "currency": shapes.as_text(basic.get("currency")) or "USD",
        "tiers": tiers,
        "game_matching": bool(game_names),
        "libraries": libraries,
        # A store this bundle delivers on that has never been imported and
        # still has an item nothing accounted for. That item was counted as
        # "new" by default, which is a guess dressed as a fact -- so the
        # report says so out loud. Scoped to the unmatched ones since keys
        # began answering for stores that have no importer at all: warning
        # about a store whose every item is already owned is noise, and the
        # kind that teaches an owner to skip the warning that matters.
        "unimported_stores": sorted(unmatched_stores - set(libraries)),
        # Collected by the tier walk above, which is the only thing that
        # knows what this bundle actually sells. Games are absent because
        # they took the other branch, owned items because they never
        # reached it, and an item no tier sells because it was never
        # walked -- all three by construction rather than by filtering.
        # A game fuzzy-matched against the book catalog invents an
        # overlap across media; that was observed on a live bundle, and
        # the filter that fixed it could not cover an unsold entry.
        #
        # Facts about which volumes are held, where an overlap is a
        # suspicion -- so they are separate fields and never summed.
        "series": series_hits,
        "overlaps": _overlaps(conn, candidates),
        "owned_items": sorted(owned_found.values(),
                              key=lambda o: o["offered"].lower()),
    }


# Symbols for the currencies Humble actually quotes. A currency not
# listed prints its ISO code, which is unambiguous if less pretty.
SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CAD": "CA$", "AUD": "A$"}


def _series_note(hit):
    """The right-hand side of one series line."""
    if hit["already_owned"]:
        # Shouted, like the APPROXIMATE warning below. This is the one
        # line in the whole report that should stop a purchase: the
        # offered volume matched no machine_name yet is already held, so
        # it is a re-issue or another edition of a book on the shelf.
        return f"ALREADY OWNED -- you hold Vol. {hit['offered_volume']}"
    if hit["kind"] == "collection":
        span = hit["span"]
        if span:
            # A range states its own size, so this is the one case where a
            # denominator is known rather than guessed. Counted over the
            # volumes INSIDE the range: owning Vol. 9 says nothing about a
            # collection selling Vol. 1-6.
            inside = sum(1 for v in hit["owned"] if span[0] <= v <= span[1])
            return (f"you own {inside} of {span[1] - span[0] + 1} "
                    f"({hit['owned_display']})")
        noun = "volume" if len(hit["owned"]) == 1 else "volumes"
        return f"you own {len(hit['owned'])} {noun} ({hit['owned_display']})"
    return f"you own {hit['owned_display']}"


def format_report(report, encoding="utf-8"):
    """The report as printable text, safe for a console using `encoding`.

    Highest tier first: that is the tier being decided against. There is
    deliberately no price-per-new-item column -- see the design spec.
    """
    symbol = SYMBOLS.get(report["currency"], report["currency"] + " ")
    # A console that cannot encode the symbol falls back to the ISO code
    # rather than to console_safe's replacement character: "?21.90" reads
    # as a bug, "EUR 21.90" reads as a price. Same reasoning that makes
    # console_safe map the star to an asterisk instead of dropping it.
    # Not hypothetical: cp1252 carries the euro, but the Windows *console*
    # defaults to cp437/cp850, and neither of those does.
    try:
        symbol.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        symbol = report["currency"] + " "
    lines = [report["name"], report["url"], ""]
    width = max((len(f"{symbol}{t['price']:.2f}") for t in report["tiers"]),
                default=0)
    for tier in report["tiers"]:
        price = f"{symbol}{tier['price']:.2f}"
        noun = "item " if tier["total"] == 1 else "items"
        # The possible column appears only when there is something in it,
        # so a book bundle's report is byte-identical to before games
        # existed -- a third number that is always zero would just be noise.
        middle = f"possible {tier['possible']:<3} " if tier.get("possible") else ""
        lines.append(f"  {price:>{width}}   {tier['total']:>3} {noun}    "
                     f"owned {tier['owned']:<3} {middle}new {tier['new']}")
        # Skipped entirely when a tier adds nothing, so a bundle owned
        # outright still prints as clean rows rather than empty headings.
        # The heading names what the list is: the count above it is
        # cumulative and this is incremental, so the two disagree.
        if tier["adds"]:
            lines.append(f"              adds {len(tier['adds'])} new:")
            lines.extend(f"                {name}" for name in tier["adds"])
            lines.append("")
        # Inside the owned count, so this heading explains a number rather
        # than adding one -- which is why there is no column for it above.
        # Never "unredeemed": Humble marks a key redeemed the moment its
        # value is revealed, which says nothing about whether the game ever
        # reached a store account -- the bug that started this counted a
        # revealed-but-unactivated key's game as new. Absence from every
        # imported library is what is actually known, so it is what is said.
        if tier.get("keyed_items"):
            count = len(tier["keyed_items"])
            noun = "a Humble key" if count == 1 else "Humble keys"
            lines.append(f"              {count} owned via {noun} "
                         f"(not in any imported library):")
            for hit in tier["keyed_items"]:
                where = ", ".join(part for part in (
                    f"{hit['key_type']} key" if hit.get("key_type") else None,
                    hit.get("bundle")) if part)
                lines.append(f"                {hit['offered']}"
                             + (f"  ({where})" if where else ""))
            lines.append("")
        # Listed, never folded into owned or new. The whole point of the
        # middle band is that the tool declines to decide, so printing a
        # bare count would hide which title it could not decide about.
        if tier.get("possible_items"):
            lines.append(f"              {len(tier['possible_items'])} possible "
                         f"(counted as neither owned nor new):")
            for hit in tier["possible_items"]:
                lines.append(f"                {hit['offered']}  ~  "
                             f"{hit['owned_title']}  ({hit['score']:.2f})")
            lines.append("")
    # Which titles the owned counts are, once for the whole bundle (#92):
    # the tiers are cumulative, so per tier would repeat them. A game says
    # what it matched, since that match is by title and approximate.
    if report.get("owned_items"):
        lines += ["", f"  Already owned ({len(report['owned_items'])}):"]
        for hit in report["owned_items"]:
            line = f"    {hit['offered']}"
            other = hit.get("owned_title") or hit.get("item_name")
            if other and other != hit["offered"]:
                line += f"  ~  {other}"
            if hit.get("keyed"):
                line += "  (Humble key)"
            lines.append(line)
    # Before the overlap list and after the tiers: these are facts about
    # which volumes are held, where an overlap is a suspicion. Omitted
    # entirely when empty, as `adds` and `keyed_items` are.
    if report.get("series"):
        lines += ["", f"  Series you already hold ({len(report['series'])}):"]
        width = max(len(hit["offered"]) for hit in report["series"])
        for hit in report["series"]:
            lines.append(f"    {hit['offered']:<{width}}  {_series_note(hit)}")
    if report["overlaps"]:
        lines += ["", f"  Possibly already owned in part "
                      f"({len(report['overlaps'])}):"]
        offered = max(len(o["offered"]) for o in report["overlaps"])
        for hit in report["overlaps"]:
            lines.append(f"    {hit['offered']:<{offered}}  ~  "
                         f"{hit['item_name']}  ({hit['score']:.2f})")
    # Printed only when game matching actually happened, so the book report
    # is untouched. The warning and the data's age travel together: an
    # approximate answer from a stale library is the one worth distrusting
    # most, and neither fact is much use without the other.
    if report.get("game_matching"):
        lines += ["", "  Game ownership is matched by title and is "
                      "APPROXIMATE -- verify anything you would buy on."]
        libraries = report.get("libraries") or {}
        if libraries:
            listed = ", ".join(
                f"{store} {info['count']} "
                f"{'game' if info['count'] == 1 else 'games'} (imported "
                f"{info['imported_at'][:10]})"
                for store, info in sorted(libraries.items()))
            lines.append(f"  Libraries: {listed}")
        for store in report.get("unimported_stores") or []:
            # "its unmatched items", not "its items": the store is only
            # named when at least one item there matched nothing, and its
            # others may well be owned via a key.
            lines.append(f"  WARNING: this bundle delivers on '{store}', which "
                         f"has never been imported -- its unmatched items are "
                         f"counted as new by default.")
        if report.get("unimported_stores"):
            lines.append("  Run `python -m humble_catalog import-games` first.")
    # Degraded at the CLI boundary only: the web route keeps the symbol,
    # and the item names are arbitrary data that may hold anything.
    # rstrip so a trailing adds block leaves no dangling blank line.
    return stats.console_safe("\n".join(lines).rstrip(), encoding)


def run(url):
    """Fetch, count, and print. The `bundle` subcommand's entry point."""
    bundle = fetch_bundle(url)
    conn = db.connect()
    try:
        report = preview(conn, bundle, url=url)
    finally:
        conn.close()
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(format_report(report, encoding))
