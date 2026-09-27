import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from humble_catalog import bundle_preview, db, import_games, series, titles

FIXTURES = Path(__file__).parent / "fixtures"


def _bundle():
    return json.loads((FIXTURES / "bundle_data.json").read_text(encoding="utf-8"))


def _conn(tmp_path):
    """A catalog holding three items, one of them reached only via merges.

    'quietharbor_reissue_examplepress' is not an items row: it is a
    machine_name that was merged away. It still names a book that is in
    the library, so the preview must count it as owned.
    """
    conn = db.connect(tmp_path / "catalog.db")
    for machine_name, name in (
            ("quietharbor_examplepress", "The Quiet Harbor: A Novel"),
            ("shadowhound_vol1_examplecomics", "Shadow Hound Vol 1"),
            ("moonfall_vol1_examplecomics", "MOONFALL, Vol. 1")):
        conn.execute("INSERT INTO items (machine_name, name, type) "
                     "VALUES (?, ?, 'ebook')", (machine_name, name))
    conn.execute("INSERT INTO merges (dropped_machine_name, kept_item_id) "
                 "VALUES ('quietharbor_reissue_examplepress', 1)")
    conn.commit()
    return conn


def _tiers(tmp_path):
    conn = _conn(tmp_path)
    try:
        return bundle_preview.preview(conn, _bundle())["tiers"]
    finally:
        conn.close()


def test_preview_reports_the_bundle_name_and_currency(tmp_path):
    conn = _conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _bundle())
    finally:
        conn.close()
    assert report["name"] == "Humble Book Bundle: The World of Examplia"
    assert report["currency"] == "EUR"


def test_tiers_come_out_price_descending_whatever_tier_order_says(tmp_path):
    # tier_order in the fixture is ["bt13", "initial", "bt21"]. Sorting on
    # the numeric amount cannot be broken by Humble reordering that key.
    assert [t["price"] for t in _tiers(tmp_path)] == [21.9, 13.13, 5.47]


def test_each_tier_counts_owned_against_its_own_cumulative_item_list(tmp_path):
    # The tiers are already cumulative in the source data, so "new at this
    # tier" is one set difference with no accumulation of our own.
    top, middle, bottom = _tiers(tmp_path)
    assert (top["total"], top["owned"], top["new"]) == (6, 2, 4)
    assert (middle["total"], middle["owned"], middle["new"]) == (3, 2, 1)
    assert (bottom["total"], bottom["owned"], bottom["new"]) == (1, 1, 0)


def test_a_merged_away_machine_name_counts_as_owned(tmp_path):
    # The single most important rule: a duplicate merged away still names a
    # book in the library. Missing it would report an owned item as new and
    # overstate the gain -- the one direction of error this must not make.
    middle = _tiers(tmp_path)[1]
    assert middle["owned"] == 2
    assert "The Quiet Harbor: A Novel" not in middle["adds"]


def test_adds_lists_display_names_not_machine_names(tmp_path):
    # A machine_name is not a thing anyone reads, which is why new_items
    # was replaced rather than merely rendered.
    adds = _tiers(tmp_path)[0]["adds"]
    assert "Unrelated Book" in adds
    assert not any("_examplepress" in name for name in adds)


def test_an_empty_catalog_reports_every_item_as_new(tmp_path):
    conn = db.connect(tmp_path / "empty.db")
    try:
        tiers = bundle_preview.preview(conn, _bundle())["tiers"]
    finally:
        conn.close()
    assert (tiers[0]["total"], tiers[0]["owned"], tiers[0]["new"]) == (6, 0, 6)


def test_a_bundle_owned_outright_reports_no_new_items(tmp_path):
    conn = _conn(tmp_path)
    for machine_name in ("shadowhound_omnibus_examplecomics",
                         "moonfall_omnibus_examplecomics",
                         "unrelatedbook_examplepress",
                         "hollowcrypt_examplegames"):
        conn.execute("INSERT INTO items (machine_name, name, type) "
                     "VALUES (?, 'Bundle One', 'ebook')", (machine_name,))
    conn.commit()
    try:
        tiers = bundle_preview.preview(conn, _bundle())["tiers"]
    finally:
        conn.close()
    assert all(t["new"] == 0 for t in tiers)
    assert all(t["adds"] == [] for t in tiers)


def test_each_tier_lists_only_what_it_adds_over_the_cheaper_tiers(tmp_path):
    # Tiers are cumulative, so a full list per tier would print the same
    # title once per tier. Incremental lists are disjoint and each answers
    # the question asked at its own row: is this step up worth it?
    top, middle, bottom = _tiers(tmp_path)
    assert top["adds"] == ["Moonfall Vol. 1-3", "The Hollow Crypt",
                           "Unrelated Book"]
    assert middle["adds"] == ["Shadow Hound Vol. 1-6"]
    assert bottom["adds"] == []


def test_the_adds_lists_are_disjoint_across_tiers(tmp_path):
    tiers = _tiers(tmp_path)
    everything = [name for t in tiers for name in t["adds"]]
    assert len(everything) == len(set(everything))


def test_the_adds_lists_sum_to_the_richest_tiers_new_count(tmp_path):
    # The invariant that makes an incremental list safe to read beside a
    # cumulative count.
    tiers = _tiers(tmp_path)
    assert sum(len(t["adds"]) for t in tiers) == tiers[0]["new"]


def test_adds_sorts_case_insensitively(tmp_path):
    adds = _tiers(tmp_path)[0]["adds"]
    assert adds == sorted(adds, key=str.lower)


def test_a_tier_that_is_not_a_superset_does_not_duplicate_a_title(tmp_path):
    # Humble's tiers nest today, but nothing guarantees a bonus tier will.
    # A pairwise difference against the next tier down would emit the
    # shared title twice; the running set is why this holds.
    bundle = _bundle()
    bundle["tier_display_data"]["bonus"] = {
        "identifier": "bonus",
        "tier_item_machine_names": ["hollowcrypt_examplegames",
                                    "unrelatedbook_examplepress"]}
    bundle["tier_pricing_data"]["bonus"] = {
        "price|money": {"currency": "EUR", "amount": 30.0}}
    conn = _conn(tmp_path)
    try:
        tiers = bundle_preview.preview(conn, bundle)["tiers"]
    finally:
        conn.close()
    everything = [name for t in tiers for name in t["adds"]]
    assert len(everything) == len(set(everything))
    assert "The Hollow Crypt" in everything


def test_adds_falls_back_to_the_machine_name_when_a_page_omits_the_title(
        tmp_path):
    bundle = _bundle()
    bundle["tier_item_data"]["hollowcrypt_examplegames"] = {}
    conn = _conn(tmp_path)
    try:
        tiers = bundle_preview.preview(conn, bundle)["tiers"]
    finally:
        conn.close()
    assert "hollowcrypt_examplegames" in tiers[0]["adds"]


def _overlaps(tmp_path):
    conn = _conn(tmp_path)
    try:
        return bundle_preview.preview(conn, _bundle())["overlaps"]
    finally:
        conn.close()


def test_an_omnibus_matching_an_owned_volume_becomes_a_series_line(tmp_path):
    # Was an overlap scored 0.92 under "possibly already owned in part".
    # It is now a series line, which says strictly more: which volumes are
    # held, and -- because this spelling states its span -- out of how many.
    conn = _conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _bundle())
    finally:
        conn.close()
    hit = next(h for h in report["series"]
               if h["offered"] == "Shadow Hound Vol. 1-6")
    assert hit["owned_display"] == "Vol. 1"
    assert hit["span"] == [1, 6]
    # and it is still counted as new, because it is not owned. Read off the
    # same report: the two facts must hold together, and re-seeding the
    # same tmp_path database twice would violate items.machine_name.
    # It is added by the €13.13 tier, not the top one: the lists are
    # incremental, so a title appears under the cheapest tier that unlocks it.
    assert "Shadow Hound Vol. 1-6" in report["tiers"][1]["adds"]


def test_overlaps_carry_the_item_id_so_the_viewer_can_link_to_the_row(tmp_path):
    # The fixture's two omnibus titles are series lines now, so this needs
    # a genuine overlap with no volume marker anywhere. The edition-variant
    # pair from docs/TEST-DATA.md scores 100 through clean_title.
    conn = db.connect(tmp_path / "overlap.db")
    conn.execute("INSERT INTO items (machine_name, name, type) "
                 "VALUES ('widgetservices_examplepress', "
                 "'Building Widget Services, 2nd Edition', 'ebook')")
    conn.commit()
    bundle = {
        "basic_data": {"human_name": "The World of Examplia by Example Press"},
        "tier_pricing_data": {"initial": {"price|money": {"amount": 5.0}}},
        "tier_item_data": {"widgetservices_2e_examplepress": {
            "human_name": "Building Widget Services 2e"}},
        "tier_display_data": {"initial": {
            "tier_item_machine_names": ["widgetservices_2e_examplepress"]}},
    }
    try:
        overlaps = bundle_preview.preview(conn, bundle)["overlaps"]
    finally:
        conn.close()
    assert overlaps[0]["item_id"] == 1
    assert overlaps[0]["item_name"] == "Building Widget Services, 2nd Edition"


def test_overlaps_are_sorted_by_score_descending(tmp_path):
    # Its own fixture: the shared one's overlaps all became series lines,
    # which left this asserting [] == sorted([]). Three genuine overlaps,
    # none carrying a volume marker, offered in the order 0.92, 1.00, 0.97
    # -- neither sorted nor reversed, so dropping the sort fails, and so
    # does sorting the wrong way.
    conn = db.connect(tmp_path / "sorted.db")
    for machine_name, name in (
            ("widgetservices_examplepress",
             "Building Widget Services, 2nd Edition"),
            ("saltsextant_examplepress", "Salt and Sextant"),
            ("copperalmanac_examplepress", "The Copper Almanac")):
        conn.execute("INSERT INTO items (machine_name, name, type) "
                     "VALUES (?, ?, 'ebook')", (machine_name, name))
    conn.commit()
    offered = {"saltsextant_amp_examplepress": "Salt & Sextant",
               "widgetservices_2e_examplepress": "Building Widget Services 2e",
               "copperalmanacs_examplepress": "The Copper Almanacs"}
    bundle = {
        "basic_data": {"human_name": "The World of Examplia by Example Press"},
        "tier_pricing_data": {"initial": {"price|money": {"amount": 5.0}}},
        "tier_item_data": {name: {"human_name": title}
                           for name, title in offered.items()},
        "tier_display_data": {"initial": {
            "tier_item_machine_names": list(offered)}},
    }
    try:
        overlaps = bundle_preview.preview(conn, bundle)["overlaps"]
    finally:
        conn.close()
    scores = [o["score"] for o in overlaps]
    assert len(scores) >= 2, "fixture no longer yields overlaps to sort"
    assert len(set(scores)) == len(scores)
    assert scores == sorted(scores, reverse=True)


def test_an_already_owned_item_is_never_also_an_overlap(tmp_path):
    # 'quietharbor_reissue_examplepress' carries a human_name identical to
    # an owned item's, so it would score 100 -- but it is owned via merges,
    # and the overlap pass runs only over what did not match exactly.
    assert all(o["offered"] != "The Quiet Harbor: A Novel"
               for o in _overlaps(tmp_path))


def test_unrelated_titles_do_not_become_overlaps(tmp_path):
    # An empty result is the point here, not an accident: both titles are
    # sold, unowned and carry no volume marker, so they DO reach _overlaps
    # -- a threshold loosened to admit everything lists them.
    offered = {o["offered"] for o in _overlaps(tmp_path)}
    assert "Unrelated Book" not in offered
    assert "The Hollow Crypt" not in offered


def test_a_title_below_the_threshold_is_not_an_overlap(tmp_path):
    # 'The Quiet Harbor' against 'A Quiet Life in Harbors' scores about 72
    # -- close enough to look plausible, far enough to be noise. Pins that
    # OVERLAP is doing real work rather than admitting everything.
    conn = db.connect(tmp_path / "foil.db")
    conn.execute("INSERT INTO items (machine_name, name, type) "
                 "VALUES ('quietlife_examplepress', "
                 "'A Quiet Life in Harbors', 'ebook')")
    conn.commit()
    try:
        overlaps = bundle_preview.preview(conn, _bundle())["overlaps"]
    finally:
        conn.close()
    assert overlaps == []


def test_overlap_threshold_is_local_and_not_borrowed_from_matching():
    # matching's thresholds decide whether to WRITE enrichment onto a row.
    # This one decides whether to show a human a hint. Different question,
    # different tolerance -- documented in the design spec.
    from humble_catalog import matching
    assert bundle_preview.OVERLAP == 90.0
    assert bundle_preview.OVERLAP / 100 != matching.REVIEW
    assert bundle_preview.OVERLAP / 100 != matching.AUTO


def _bundle_with_unsold(entry, machine_name="shadowhound_bonus_examplecomics"):
    """The book fixture plus one tier_item_data entry no tier sells.

    Real bundles carry these -- a bonus wallpaper, an art pack, an item
    pulled from a tier after the page data was assembled. The game
    fixture has one already ('bonuswallpaper_examplegames').
    """
    bundle = _bundle()
    assert machine_name not in bundle["tier_item_data"]
    bundle["tier_item_data"][machine_name] = entry
    sold = {name for display in bundle["tier_display_data"].values()
            for name in display["tier_item_machine_names"]}
    assert machine_name not in sold          # the premise of every test below
    return bundle


# Scores 100.0 against the owned 'Shadow Hound Vol 1': token_set_ratio
# returns a perfect score when one side's tokens are wholly contained in
# the other's. Deliberate -- it outscores both genuine overlaps, so a
# regression appears at the HEAD of the list rather than buried in it.
_BONUS_BOOK = {"human_name": "Shadow Hound Vol 1 Bonus Art Pack",
               "platforms_and_oses": {}}


def test_an_item_no_tier_sells_is_never_an_overlap(tmp_path):
    # tier_item_data is a metadata dict, not the item list. An entry no
    # tier sells cannot be bought by buying this bundle, so hinting that
    # part of it may already be owned answers a question nobody asked.
    conn = _conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _bundle_with_unsold(_BONUS_BOOK))
    finally:
        conn.close()
    assert all("Bonus Art Pack" not in o["offered"] for o in report["overlaps"])
    # It must not reach the series list either: a phantom is unbuyable
    # whichever list would name it.
    assert all("Bonus Art Pack" not in h["offered"] for h in report["series"])
    # The two genuine hints still land, which is what stops an over-broad
    # exclusion passing this test. They are series lines rather than
    # overlaps now -- both name a range, so both state their own span.
    assert [h["offered"] for h in report["series"]] == [
        "Moonfall Vol. 1-3", "Shadow Hound Vol. 1-6"]


def test_an_item_no_tier_sells_does_not_change_any_count(tmp_path):
    # The counts were already right -- they derive from tier_display_data.
    # Pins that the fix stayed on the overlap list, which is the way this
    # change could do damage.
    conn = _conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _bundle_with_unsold(_BONUS_BOOK))
    finally:
        conn.close()
    counted = [(t["total"], t["owned"], t["new"]) for t in report["tiers"]]
    assert counted == [(6, 2, 4), (3, 2, 1), (1, 1, 0)]
    assert report["game_matching"] is False


def test_an_unsold_game_entry_is_not_matched_against_books(tmp_path):
    # The cross-media half, and it fails for a different reason than the
    # first test: game_names is accumulated by the tier walk, so a
    # phantom is never in it and the `owned | game_names` exclusion could
    # not name it. A game scored against the book catalog is exactly what
    # preview's call-site comment says was fixed.
    entry = {"human_name": "Shadow Hound Vol 1 Bonus Art Pack",
             "platforms_and_oses": {"game": {"steam": ["windows"]}}}
    conn = _conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _bundle_with_unsold(entry))
    finally:
        conn.close()
    assert all("Bonus Art Pack" not in o["offered"] for o in report["overlaps"])


def _http(text, status=200, ctype="text/html; charset=utf-8"):
    """A stub session whose one response carries `text`."""
    http = Mock()
    resp = Mock(status_code=status)
    resp.text = text
    resp.url = "https://www.humblebundle.com/books/the-world-of-examplia-books"
    resp.headers = {"Content-Type": ctype}
    resp.encoding = "utf-8"
    resp.iter_content = Mock(return_value=[text.encode("utf-8")])
    resp.raise_for_status = Mock()
    http.request.return_value = resp
    return http


def _page():
    return (FIXTURES / "bundle_page.html").read_text(encoding="utf-8")


def test_fetch_bundle_parses_the_embedded_data_blob():
    bundle = bundle_preview.fetch_bundle(
        "https://www.humblebundle.com/books/the-world-of-examplia-books",
        http=_http(_page()))
    assert bundle["basic_data"]["human_name"] == (
        "Humble Book Bundle: The World of Examplia")
    assert len(bundle["tier_item_data"]) == 6


def test_fetch_bundle_rejects_a_non_humble_host_before_any_request():
    http = _http(_page())
    with pytest.raises(ValueError, match="not a HumbleBundle URL"):
        bundle_preview.fetch_bundle("https://example.test/books/x", http=http)
    http.request.assert_not_called()


def test_fetch_bundle_accepts_a_url_without_a_scheme():
    bundle = bundle_preview.fetch_bundle(
        "www.humblebundle.com/books/the-world-of-examplia-books",
        http=_http(_page()))
    assert bundle["basic_data"]["currency"] == "EUR"


def test_fetch_bundle_rejects_a_page_with_no_data_blob():
    # What a retired bundle redirected to the storefront also produces.
    with pytest.raises(ValueError, match="not a Humble bundle page"):
        bundle_preview.fetch_bundle(
            "https://www.humblebundle.com/books/gone",
            http=_http("<html><body>Nothing here</body></html>"))


def test_fetch_bundle_lets_a_404_propagate(monkeypatch):
    # Aimed at live pages: a dead bundle is reported as the HTTP error it
    # is, not modelled as a state of its own.
    monkeypatch.setattr("time.sleep", lambda s: None)
    http = _http("", status=404)
    http.request.return_value.raise_for_status = Mock(
        side_effect=requests.HTTPError(
            "404 Client Error",
            response=Mock(status_code=404)))
    with pytest.raises(requests.HTTPError):
        bundle_preview.fetch_bundle(
            "https://www.humblebundle.com/books/gone", http=http)


def _report(tmp_path):
    conn = _conn(tmp_path)
    try:
        return bundle_preview.preview(
            conn, _bundle(),
            url="https://www.humblebundle.com/books/the-world-of-examplia-books")
    finally:
        conn.close()


def test_format_report_lists_every_tier_highest_first(tmp_path):
    out = bundle_preview.format_report(_report(tmp_path))
    # keyed on "owned" AND "new": not "items", since a one-item tier reads
    # "1 item", and not "owned" alone, which the overlap heading also has
    lines = [l for l in out.splitlines() if "owned" in l and "new" in l]
    assert len(lines) == 3
    assert "21.90" in lines[0] and "owned 2" in lines[0] and "new 4" in lines[0]
    assert "5.47" in lines[2] and "owned 1" in lines[2] and "new 0" in lines[2]


def test_format_report_says_item_not_items_for_a_single_item_tier(tmp_path):
    # Cosmetic, but "1 items" reads as unfinished. Caught in a browser,
    # not by a test -- so it gets one now.
    out = bundle_preview.format_report(_report(tmp_path))
    assert "1 item " in out
    assert "1 items" not in out


def test_format_report_never_prints_a_price_per_new_item(tmp_path):
    # Decided against in the spec: it is arithmetic the reader can do, and
    # printing it invites reading "cheap per item" as "worth buying" --
    # exactly the misjudgement this feature exists to correct.
    out = bundle_preview.format_report(_report(tmp_path))
    assert "/new" not in out and "per item" not in out and "each" not in out


def test_format_report_lists_the_overlaps_under_their_own_heading(tmp_path):
    # The fixture's two omnibus titles are series lines now, so the heading
    # needs an overlap carrying no volume marker on either side. The
    # edition-variant pair from docs/TEST-DATA.md scores 100 and does.
    conn = db.connect(tmp_path / "overlap.db")
    conn.execute("INSERT INTO items (machine_name, name, type) "
                 "VALUES ('widgetservices_examplepress', "
                 "'Building Widget Services, 2nd Edition', 'ebook')")
    conn.commit()
    bundle = {
        "basic_data": {"human_name": "The World of Examplia by Example Press"},
        "tier_pricing_data": {"initial": {"price|money": {"amount": 5.0}}},
        "tier_item_data": {"widgetservices_2e_examplepress": {
            "human_name": "Building Widget Services 2e"}},
        "tier_display_data": {"initial": {
            "tier_item_machine_names": ["widgetservices_2e_examplepress"]}},
    }
    try:
        out = bundle_preview.format_report(bundle_preview.preview(conn, bundle))
    finally:
        conn.close()
    assert "Possibly already owned in part (1):" in out
    assert "Building Widget Services 2e" in out
    assert "Building Widget Services, 2nd Edition" in out


def test_format_report_omits_the_overlap_block_when_there_is_none(tmp_path):
    conn = db.connect(tmp_path / "empty.db")
    try:
        report = bundle_preview.preview(conn, _bundle())
    finally:
        conn.close()
    assert "Possibly already owned" not in bundle_preview.format_report(report)


def test_format_report_degrades_a_currency_symbol_the_console_cannot_encode(
        tmp_path):
    # cp437 is a real Windows console default and has no euro sign. capsys
    # captures as UTF-8, so no test of run() could observe this -- it has
    # to be checked at the formatting boundary.
    out = bundle_preview.format_report(_report(tmp_path), encoding="cp437")
    out.encode("cp437")            # the point: this must not raise
    # Falls back to the ISO code rather than console_safe's replacement
    # character: "?21.90" reads as a broken price, "EUR 21.90" as a price.
    assert "EUR 21.90" in out
    assert "?" not in out


def test_format_report_keeps_the_currency_symbol_when_the_console_can_take_it(
        tmp_path):
    # cp1252 does carry the euro, so the fallback must NOT fire there --
    # degrading a symbol the console can print would be its own bug.
    report = _report(tmp_path)     # once: _conn re-seeds the same tmp_path
    for encoding in ("utf-8", "cp1252"):
        assert "€21.90" in bundle_preview.format_report(
            report, encoding=encoding)


def test_format_report_lists_what_each_tier_adds(tmp_path):
    out = bundle_preview.format_report(_report(tmp_path))
    assert "adds 3 new:" in out
    assert "Moonfall Vol. 1-3" in out
    assert "The Hollow Crypt" in out
    assert "adds 1 new:" in out
    assert "Shadow Hound Vol. 1-6" in out


def test_format_report_omits_the_block_for_a_tier_that_adds_nothing(tmp_path):
    # The cheapest tier's `new 0` still prints; only the list is skipped,
    # so a bundle owned outright stays three clean rows.
    out = bundle_preview.format_report(_report(tmp_path))
    assert out.count("adds ") == 2
    assert "adds 0 new" not in out


def test_format_report_indents_the_list_under_its_tier(tmp_path):
    out = bundle_preview.format_report(_report(tmp_path)).splitlines()
    heading = next(i for i, l in enumerate(out) if "adds 3 new:" in l)
    tier_line = next(i for i, l in enumerate(out)
                     if "owned 2" in l and "new 4" in l)
    assert heading == tier_line + 1
    # each title sits deeper than the heading that introduces it
    indent = len(out[heading]) - len(out[heading].lstrip())
    assert all(len(l) - len(l.lstrip()) > indent
               for l in out[heading + 1:heading + 4])


def _game_bundle():
    return json.loads(
        (FIXTURES / "game_bundle_data.json").read_text(encoding="utf-8"))


def _game_conn(tmp_path):
    """A catalog holding one book and a small imported game library.

    Neon Drifter is owned on two stores on purpose: a bundle item that
    matches both must still count once.
    """
    conn = db.connect(tmp_path / "catalog.db")
    conn.execute("INSERT INTO items (machine_name, name, type) "
                 "VALUES ('quietharbor_examplepress', "
                 "'The Quiet Harbor: A Novel', 'ebook')")
    conn.commit()
    for store, rows in (
            ("steam", [("440", "Widget Quest"), ("220", "Neon Drifter"),
                       ("330", "Starfall Rally")]),
            ("gog", [("1207658691", "Pixel Harbor\u2122"),
                     ("1207658713", "Neon Drifter")]),
            ("epic", [("grove-of-echoes", "Grove of Echoes")])):
        import_games.store_games(conn, store, [
            {"store_id": sid, "title": t,
             "normalized_title": titles.clean_game_title(t),
             "source_timestamp": None} for sid, t in rows], "test")
    return conn


def _game_tiers(tmp_path):
    conn = _game_conn(tmp_path)
    try:
        return bundle_preview.preview(conn, _game_bundle())["tiers"]
    finally:
        conn.close()


def test_a_game_owned_on_a_store_counts_as_owned(tmp_path):
    top = _game_tiers(tmp_path)[0]
    # 8 items: 5 owned (Pixel Harbor, Widget Quest DE, Neon Drifter,
    # Grove of Echoes, and the book), 1 possible, 2 new.
    assert (top["total"], top["owned"], top["possible"], top["new"]) == (8, 5, 1, 2)


def test_an_edition_suffix_over_an_owned_base_reads_as_owned(tmp_path):
    top = _game_tiers(tmp_path)[0]
    assert "Widget Quest: Definitive Edition" not in top["adds"]


def test_a_sequel_never_matches_its_predecessor(tmp_path):
    # Widget Quest is owned; Widget Quest II is a different game and must
    # be reported as new -- not owned, and not merely "possible".
    top = _game_tiers(tmp_path)[0]
    assert "Widget Quest II" in top["adds"]
    assert "Widget Quest II" not in [p["offered"] for p in top["possible_items"]]


def test_an_ambiguous_title_lands_in_possible_and_neither_count(tmp_path):
    top = _game_tiers(tmp_path)[0]
    assert [p["offered"] for p in top["possible_items"]] == ["Starfall Rally Turbo"]
    assert "Starfall Rally Turbo" not in top["adds"]


def test_a_game_owned_on_two_stores_counts_once(tmp_path):
    # Neon Drifter is in both the steam and gog rows.
    top = _game_tiers(tmp_path)[0]
    assert top["owned"] + top["possible"] + top["new"] == top["total"]


def test_a_book_item_in_a_game_bundle_still_matches_by_machine_name(tmp_path):
    # Routing is per item, so a mixed bundle needs no global decision.
    top = _game_tiers(tmp_path)[0]
    assert "The Quiet Harbor: A Novel" not in top["adds"]


def test_game_titles_never_produce_book_overlap_hints(tmp_path):
    # The bug this fixes: game titles fuzzy-matched against the book
    # catalog invented "possibly already owned" hints across media.
    conn = _game_conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _game_bundle())
    finally:
        conn.close()
    assert report["overlaps"] == []


def test_an_item_with_no_platform_data_routes_to_the_book_path(tmp_path):
    # Verified against a live bundle: one entry had {} and no content type.
    assert bundle_preview.delivery_stores(
        {"platforms_and_oses": {}}) == set()
    assert bundle_preview.delivery_stores(
        {"platforms_and_oses": {"game": {"steam": ["windows"]}}}) == {"steam"}


def test_a_bundle_with_no_games_imported_names_the_missing_stores(tmp_path):
    # The dangerous case: an empty games table must not read as "owns none".
    conn = db.connect(tmp_path / "catalog.db")
    try:
        report = bundle_preview.preview(conn, _game_bundle())
    finally:
        conn.close()
    assert report["unimported_stores"] == ["gog", "steam"]
    text = bundle_preview.format_report(report)
    assert "never been imported" in text
    assert "import-games" in text


def test_a_store_delivered_but_never_imported_is_named(tmp_path):
    # Import steam alone and gog must be reported as missing.
    conn = db.connect(tmp_path / "catalog.db")
    try:
        import_games.store_games(conn, "steam", [
            {"store_id": "440", "title": "Widget Quest",
             "normalized_title": "widget quest", "source_timestamp": None}],
            "test")
        report = bundle_preview.preview(conn, _game_bundle())
    finally:
        conn.close()
    assert report["unimported_stores"] == ["gog"]


def test_a_fully_imported_bundle_reports_no_missing_stores(tmp_path):
    conn = _game_conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _game_bundle())
    finally:
        conn.close()
    assert report["unimported_stores"] == []


def test_the_report_always_says_game_counts_are_approximate(tmp_path):
    conn = _game_conn(tmp_path)
    try:
        text = bundle_preview.format_report(
            bundle_preview.preview(conn, _game_bundle()))
    finally:
        conn.close()
    assert "approximate" in text.lower()


def test_a_book_only_bundle_carries_no_game_footer(tmp_path):
    # Nothing about the existing book report may change.
    conn = _conn(tmp_path)
    try:
        text = bundle_preview.format_report(
            bundle_preview.preview(conn, _bundle()))
    finally:
        conn.close()
    assert "approximate" not in text.lower()


def test_the_footer_lists_each_imported_library(tmp_path):
    conn = _game_conn(tmp_path)
    try:
        text = bundle_preview.format_report(
            bundle_preview.preview(conn, _game_bundle()))
    finally:
        conn.close()
    assert "steam" in text and "gog" in text


def test_possible_matches_are_listed_under_their_tier(tmp_path):
    conn = _game_conn(tmp_path)
    try:
        text = bundle_preview.format_report(
            bundle_preview.preview(conn, _game_bundle()))
    finally:
        conn.close()
    assert "Starfall Rally Turbo" in text
    assert "possible" in text


# --- Ownership held as a Humble key -------------------------------------
#
# A game bought in an earlier Humble bundle arrives as a store key, not as
# an items row: harvest files it in external_keys. Until the owner actually
# activates that key it is in no imported library either, so the preview
# used to report a game the owner had already paid for as new -- observed
# live on a bundle whose games all came from one past order.
#
# Built inline rather than added to game_bundle_data.json on purpose: that
# fixture's counts are pinned by the tests above, and this case needs rows
# in two more tables (bundles, external_keys) to mean anything.

def _keyed_bundle():
    """A one-tier bundle offering two games that exist only as keys."""
    return {
        "basic_data": {"human_name": "Humble Game Bundle: Story Sampler",
                       "currency": "EUR"},
        "tier_pricing_data": {"initial": {"price|money": {"currency": "EUR",
                                                         "amount": 7.5}}},
        "tier_display_data": {"initial": {"tier_item_machine_names": [
            "cindervale_examplegames", "verdantreach_examplegames"]}},
        "tier_item_data": {
            "cindervale_examplegames": {
                "human_name": "Cinder Vale", "item_content_type": "game",
                "platforms_and_oses": {"game": {"steam": ["windows"]}}},
            "verdantreach_examplegames": {
                "human_name": "Verdant Reach", "item_content_type": "game",
                "platforms_and_oses": {"game": {"uplay": ["windows"]}}}},
    }


def _keyed_conn(tmp_path):
    """A catalog whose only game ownership is two unactivated keys.

    The games table is deliberately non-empty but irrelevant: an empty one
    would also make every item "new", and this must fail for the right
    reason.
    """
    conn = db.connect(tmp_path / "catalog.db")
    conn.execute("INSERT INTO bundles (gamekey, name, url) VALUES "
                 "('kv789', 'Humble Game Bundle: Key Vault', "
                 "'https://example.invalid/kv789')")
    for name, key_type in (("Cinder Vale", "steam"),
                           ("Verdant Reach", "uplay")):
        conn.execute(
            "INSERT INTO external_keys "
            "(gamekey, machine_name, human_name, key_type, raw) "
            "VALUES ('kv789', ?, ?, ?, ?)",
            (name.lower().replace(" ", "") + "_" + key_type, name, key_type,
             json.dumps({"human_name": name, "key_type": key_type})))
    conn.commit()
    import_games.store_games(conn, "steam", [
        {"store_id": "440", "title": "Widget Quest",
         "normalized_title": titles.clean_game_title("Widget Quest"),
         "source_timestamp": None}], "test")
    return conn


def test_a_game_held_only_as_a_humble_key_counts_as_owned(tmp_path):
    # The reported bug: both games were already paid for in an earlier
    # bundle, and both read as new.
    conn = _keyed_conn(tmp_path)
    try:
        tier = bundle_preview.preview(conn, _keyed_bundle())["tiers"][0]
    finally:
        conn.close()
    assert (tier["total"], tier["owned"], tier["new"]) == (2, 2, 0)
    assert tier["adds"] == []


def test_a_keyed_game_is_listed_apart_from_a_library_match(tmp_path):
    # Counted inside `owned`, but named: an unactivated key can be dead or
    # region-locked in a way a library entry cannot, and folding the two
    # together would hide which kind of answer the number rests on.
    conn = _keyed_conn(tmp_path)
    try:
        tier = bundle_preview.preview(conn, _keyed_bundle())["tiers"][0]
    finally:
        conn.close()
    assert [k["offered"] for k in tier["keyed_items"]] == ["Cinder Vale",
                                                          "Verdant Reach"]
    assert tier["keyed"] == 2
    steam_hit = tier["keyed_items"][0]
    assert steam_hit["key_type"] == "steam"
    assert steam_hit["bundle"] == "Humble Game Bundle: Key Vault"


def test_a_key_for_a_store_with_no_importer_still_counts(tmp_path):
    # uplay has no importer at all, so a key is the only evidence of
    # ownership there will ever be. Steam-only would leave it unmatched.
    conn = _keyed_conn(tmp_path)
    try:
        tier = bundle_preview.preview(conn, _keyed_bundle())["tiers"][0]
    finally:
        conn.close()
    assert [k["key_type"] for k in tier["keyed_items"]
            if k["offered"] == "Verdant Reach"] == ["uplay"]


def test_a_game_both_keyed_and_activated_is_not_flagged_as_keyed(tmp_path):
    # The precedence rule. Once a key is activated the library knows the
    # game outright, and reporting it as "unredeemed" would make the flag
    # meaningless -- most keys in a real library are activated.
    conn = _keyed_conn(tmp_path)
    try:
        import_games.store_games(conn, "steam", [
            {"store_id": sid, "title": t,
             "normalized_title": titles.clean_game_title(t),
             "source_timestamp": None}
            for sid, t in (("440", "Widget Quest"), ("550", "Cinder Vale"))],
            "test")
        tier = bundle_preview.preview(conn, _keyed_bundle())["tiers"][0]
    finally:
        conn.close()
    assert tier["owned"] == 2
    assert [k["offered"] for k in tier["keyed_items"]] == ["Verdant Reach"]


def test_the_same_game_keyed_in_two_bundles_counts_once(tmp_path):
    conn = _keyed_conn(tmp_path)
    try:
        conn.execute("INSERT INTO bundles (gamekey, name, url) VALUES "
                     "('kv790', 'Bundle One', 'https://example.invalid/kv790')")
        conn.execute("INSERT INTO external_keys (gamekey, machine_name, "
                     "human_name, key_type, raw) VALUES ('kv790', "
                     "'cindervale_steam', 'Cinder Vale', 'steam', NULL)")
        conn.commit()
        tier = bundle_preview.preview(conn, _keyed_bundle())["tiers"][0]
    finally:
        conn.close()
    assert tier["keyed"] == 2
    assert tier["owned"] + tier["possible"] + tier["new"] == tier["total"]


def test_format_report_lists_keyed_games_under_their_tier(tmp_path):
    conn = _keyed_conn(tmp_path)
    try:
        text = bundle_preview.format_report(
            bundle_preview.preview(conn, _keyed_bundle()))
    finally:
        conn.close()
    # "unredeemed" would be a lie: Humble marks a key redeemed as soon as
    # its value is revealed, which says nothing about whether the game ever
    # reached a store account. Absence from every imported library is the
    # condition actually detected, so it is the condition named.
    assert "2 owned via Humble keys (not in any imported library):" in text
    assert "Cinder Vale  (steam key, Humble Game Bundle: Key Vault)" in text


def test_format_report_says_key_not_keys_for_a_single_keyed_game(tmp_path):
    # Activating one of the two leaves exactly one keyed game behind.
    conn = _keyed_conn(tmp_path)
    try:
        import_games.store_games(conn, "steam", [
            {"store_id": "550", "title": "Cinder Vale",
             "normalized_title": titles.clean_game_title("Cinder Vale"),
             "source_timestamp": None}], "test")
        text = bundle_preview.format_report(
            bundle_preview.preview(conn, _keyed_bundle()))
    finally:
        conn.close()
    assert "1 owned via a Humble key (not in any imported library):" in text


def test_a_store_whose_every_item_is_covered_by_a_key_is_not_named(tmp_path):
    # uplay has no importer, but a key already answered for everything it
    # delivers here. Warning about it would be noise, and the sentence it
    # prints -- that those items were counted as new -- would be false.
    conn = _keyed_conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _keyed_bundle())
    finally:
        conn.close()
    assert report["unimported_stores"] == []
    assert "never been imported" not in bundle_preview.format_report(report)


def test_a_store_is_still_named_when_one_of_its_items_matched_nothing(tmp_path):
    # The other direction, and the reason the warning exists: an unmatched
    # item on a store nothing has imported was counted as new by default,
    # which is a guess. One keyed sibling must not silence that.
    bundle = _keyed_bundle()
    bundle["tier_item_data"]["quartzmeridian_examplegames"] = {
        "human_name": "Quartz Meridian", "item_content_type": "game",
        "platforms_and_oses": {"game": {"uplay": ["windows"]}}}
    bundle["tier_display_data"]["initial"]["tier_item_machine_names"].append(
        "quartzmeridian_examplegames")
    conn = _keyed_conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, bundle)
    finally:
        conn.close()
    assert report["unimported_stores"] == ["uplay"]
    text = bundle_preview.format_report(report)
    # Reworded with the fix: "its items are counted as new" claimed all of
    # them, and one of uplay's two is owned via a key.
    assert "its unmatched items are counted as new by default" in text


def test_format_report_omits_the_keyed_block_when_nothing_is_keyed(tmp_path):
    # A book bundle's report must stay byte-identical to before keys existed.
    conn = _game_conn(tmp_path)
    try:
        text = bundle_preview.format_report(
            bundle_preview.preview(conn, _game_bundle()))
    finally:
        conn.close()
    assert "Humble key" not in text


def _series(tmp_path):
    conn = _conn(tmp_path)
    try:
        return bundle_preview.preview(conn, _bundle())["series"]
    finally:
        conn.close()


def test_an_offered_range_reports_the_denominator_it_states(tmp_path):
    # The bundle sells Vol. 1-6 and the catalog holds Vol 1. This is the
    # one spelling that carries its own size, so it is the one case where
    # "you own 1 of 6" is derivable rather than guessed.
    hit = next(h for h in _series(tmp_path)
               if h["offered"] == "Shadow Hound Vol. 1-6")
    assert hit["kind"] == "collection"
    assert hit["span"] == [1, 6]
    assert hit["owned"] == [1]
    assert hit["already_owned"] is False


def test_a_series_hit_is_not_also_an_overlap(tmp_path):
    # Reported once, and accurately. Leaving it in `overlaps` too would
    # claim partial ownership under a heading beside a richer line saying
    # the same thing better.
    conn = _conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _bundle())
    finally:
        conn.close()
    offered = {h["offered"] for h in report["series"]}
    assert "Shadow Hound Vol. 1-6" in offered
    assert all(o["offered"] not in offered for o in report["overlaps"])


def test_a_series_the_catalog_does_not_hold_produces_no_line(tmp_path):
    assert all(h["offered"] != "Unrelated Book" for h in _series(tmp_path))


def test_series_lines_are_sorted_re_buys_first(tmp_path):
    keys = [series.sort_key(h) for h in _series(tmp_path)]
    assert keys == sorted(keys)


def test_an_offered_volume_already_held_is_flagged_on_a_live_report(tmp_path):
    # Seeded locally rather than through the shared fixture: this needs an
    # offered volume that matches no machine_name but IS a held volume.
    conn = db.connect(tmp_path / "rebuy.db")
    conn.execute("INSERT INTO items (machine_name, name, type) "
                 "VALUES ('shadowhound_vol1_examplecomics', "
                 "'Shadow Hound Vol 1', 'comic')")
    conn.commit()
    bundle = {
        "basic_data": {"human_name": "Humble Comics Bundle: Shadow Hound"},
        "tier_pricing_data": {"initial": {"price|money": {"amount": 5.0}}},
        "tier_item_data": {
            "shadowhound_vol1_reissue_examplecomics": {
                "human_name": "Shadow Hound Vol. 1"}},
        "tier_display_data": {"initial": {
            "tier_item_machine_names": ["shadowhound_vol1_reissue_examplecomics"]}},
    }
    try:
        report = bundle_preview.preview(conn, bundle)
    finally:
        conn.close()
    hit = report["series"][0]
    assert hit["already_owned"] is True
    assert hit["offered_volume"] == 1


def _report_text(tmp_path):
    conn = _conn(tmp_path)
    try:
        return bundle_preview.format_report(
            bundle_preview.preview(conn, _bundle()))
    finally:
        conn.close()


def test_the_cli_prints_a_series_block(tmp_path):
    text = _report_text(tmp_path)
    assert "Series you already hold (2):" in text
    assert "you own 1 of 6" in text


def test_the_cli_omits_the_series_block_when_there_is_nothing_to_say():
    report = {"name": "Bundle One", "url": "", "currency": "USD", "tiers": [],
              "series": [], "overlaps": [], "game_matching": False}
    assert "Series you already hold" not in bundle_preview.format_report(report)


def test_a_re_buy_is_shouted_because_it_should_stop_a_purchase():
    assert bundle_preview._series_note({
        "already_owned": True, "kind": "volume", "offered_volume": 2,
        "owned": [1, 2], "owned_display": "Vol. 1-2", "span": None,
    }) == "ALREADY OWNED -- you hold Vol. 2"


def test_a_continuation_names_the_run_you_hold():
    assert bundle_preview._series_note({
        "already_owned": False, "kind": "volume", "offered_volume": 7,
        "owned": [1, 2, 3, 5, 6], "owned_display": "Vol. 1-3, 5-6", "span": None,
    }) == "you own Vol. 1-3, 5-6"


def test_a_collection_without_a_span_states_no_denominator():
    # No title carries an omnibus's volume count, so none is invented.
    assert bundle_preview._series_note({
        "already_owned": False, "kind": "collection", "offered_volume": None,
        "owned": [1, 2], "owned_display": "Vol. 1-2", "span": None,
    }) == "you own 2 volumes (Vol. 1-2)"


def test_a_collection_of_one_volume_reads_as_a_volume():
    assert "you own 1 volume (" in bundle_preview._series_note({
        "already_owned": False, "kind": "collection", "offered_volume": None,
        "owned": [1], "owned_display": "Vol. 1", "span": None,
    })


def test_a_range_counts_only_the_volumes_inside_it():
    # Owning Vol. 9 says nothing about a bundle selling Vol. 1-6.
    assert bundle_preview._series_note({
        "already_owned": False, "kind": "collection", "offered_volume": None,
        "owned": [1, 2, 9], "owned_display": "Vol. 1-2, 9", "span": [1, 6],
    }) == "you own 2 of 6 (Vol. 1-2, 9)"


# -- A word for the score (#93) ------------------------------------------
# "(0.91)" did not say what scale it was on or which way was better. Each
# scored entry now carries a word, from one line shared by both panels;
# the number stays in the payload for the tooltip and the CLI.

@pytest.mark.parametrize("score,word", [
    (1.0, "close match"), (0.95, "close match"),
    (0.94, "loose match"), (0.90, "loose match"), (0.80, "loose match"),
])
def test_strength_splits_at_the_close_line(score, word):
    assert bundle_preview.strength(score) == word


def test_the_close_line_sits_inside_the_overlap_band():
    # Otherwise every book overlap would read the same word.
    assert bundle_preview.OVERLAP < bundle_preview.CLOSE <= 100


def test_every_overlap_carries_its_word(tmp_path):
    # _overlaps(tmp_path) is empty since its omnibus titles became series
    # lines, so this builds the genuine overlap the item-id test uses.
    conn = db.connect(tmp_path / "overlap.db")
    conn.execute("INSERT INTO items (machine_name, name, type) "
                 "VALUES ('widgetservices_examplepress', "
                 "'Building Widget Services, 2nd Edition', 'ebook')")
    conn.commit()
    bundle = {
        "basic_data": {"human_name": "The World of Examplia by Example Press"},
        "tier_pricing_data": {"initial": {"price|money": {"amount": 5.0}}},
        "tier_item_data": {"widgetservices_2e_examplepress": {
            "human_name": "Building Widget Services 2e"}},
        "tier_display_data": {"initial": {
            "tier_item_machine_names": ["widgetservices_2e_examplepress"]}},
    }
    try:
        overlaps = bundle_preview.preview(conn, bundle)["overlaps"]
    finally:
        conn.close()
    assert overlaps
    assert overlaps[0]["strength"] == "close match"      # scores 1.00


def test_a_game_tier_possible_carries_its_word(tmp_path):
    possible = _game_tiers(tmp_path)[0]["possible_items"]
    assert possible and all(
        p["strength"] == bundle_preview.strength(p["score"]) for p in possible)


# -- Which titles are already owned (#92) --------------------------------
# The report listed each tier's NEW titles but only COUNTED the owned
# ones, which is half of "should I buy this". owned_items lists every
# sold item counted as owned, once, bundle-wide (tiers are cumulative, so
# per tier would repeat them). Books carry the catalog row to link to.

def _book_report(tmp_path):
    conn = _conn(tmp_path)
    try:
        return bundle_preview.preview(conn, _bundle())
    finally:
        conn.close()


def test_owned_items_list_every_owned_book_with_its_row(tmp_path):
    owned = _book_report(tmp_path)["owned_items"]
    # The direct match and the merged-away reissue: both count toward
    # "owned 2", so both are listed, and both lead to the kept row.
    assert [(o["offered"], o["item_id"]) for o in owned] == [
        ("The Quiet Harbor: A Novel", 1), ("The Quiet Harbor: A Novel", 1)]


def test_owned_items_match_the_richest_tiers_owned_count(tmp_path):
    report = _book_report(tmp_path)
    assert len(report["owned_items"]) == max(t["owned"] for t in report["tiers"])


def test_owned_games_name_what_they_matched_and_link_nowhere(tmp_path):
    conn = _game_conn(tmp_path)
    try:
        report = bundle_preview.preview(conn, _game_bundle())
    finally:
        conn.close()
    owned = report["owned_items"]
    assert len(owned) == max(t["owned"] for t in report["tiers"])
    games = [o for o in owned if o["item_id"] is None]
    assert games and all(o["owned_title"] for o in games)
    assert any(o["offered"] == "Widget Quest: Definitive Edition"
               and o["owned_title"] == "Widget Quest" for o in games)


def test_owned_items_are_sorted_by_title(tmp_path):
    conn = _game_conn(tmp_path)
    try:
        owned = bundle_preview.preview(conn, _game_bundle())["owned_items"]
    finally:
        conn.close()
    titles_ = [o["offered"].lower() for o in owned]
    assert titles_ == sorted(titles_)


def test_format_report_lists_what_is_already_owned(tmp_path):
    out = bundle_preview.format_report(_report(tmp_path))
    assert "Already owned (2):" in out
    block = out[out.index("Already owned (2):"):]
    assert block.count("The Quiet Harbor: A Novel") >= 2


def test_an_owned_book_carries_the_name_of_its_row(tmp_path):
    # The viewer's jump searches Library for the button's text, which must
    # be the row's own name, not the bundle's spelling of it.
    conn = _conn(tmp_path)
    conn.execute("UPDATE items SET name = 'Quiet Harbor (Reissue)' WHERE id = 1")
    conn.commit()
    try:
        owned = bundle_preview.preview(conn, _bundle())["owned_items"]
    finally:
        conn.close()
    assert {o["item_name"] for o in owned} == {"Quiet Harbor (Reissue)"}


def test_format_report_names_the_row_when_it_is_spelled_differently(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("UPDATE items SET name = 'Quiet Harbor (Reissue)' WHERE id = 1")
    conn.commit()
    try:
        out = bundle_preview.format_report(bundle_preview.preview(conn, _bundle()))
    finally:
        conn.close()
    assert "The Quiet Harbor: A Novel  ~  Quiet Harbor (Reissue)" in out


# -- The live bundles, from Humble's own listing pages (#95) --------------
# Measured 2026-09-27: a logged-out GET of /books (and /games) embeds a
# landingPage-json-data block whose data.<section>.mosaic[].products hold
# every live bundle: product_url, tile_name, machine_name, end date. One
# request per listing. The fixture is invented and shaped like it, with a
# software tile, a duplicate, and entries that must never become a link.

def _listing():
    return (FIXTURES / "listing_page.html").read_text(encoding="utf-8")


def test_live_bundles_lists_the_books_and_games_on_the_listing():
    live = bundle_preview.live_bundles(http=_http(_listing()))
    assert [(b["kind"], b["name"]) for b in live] == [
        ("books", "Humble Book Bundle: Lantern & Lockpick"),
        ("books", "Humble Book Bundle: The World of Examplia"),
        ("games", "Widget Quest Collection"),
    ]


def test_live_bundles_carry_an_absolute_humble_url_and_end_date():
    b = bundle_preview.live_bundles(http=_http(_listing()))[0]
    assert b["url"] == "https://www.humblebundle.com/books/lantern-and-lockpick-books"
    assert b["ends"] == "2026-10-02T18:00:00"


def test_live_bundles_never_link_anywhere_but_a_humble_bundle_page():
    urls = [b["url"] for b in bundle_preview.live_bundles(http=_http(_listing()))]
    assert all(u.startswith("https://www.humblebundle.com/books/")
               or u.startswith("https://www.humblebundle.com/games/") for u in urls)
    assert not any(".." in u or "example.test" in u or "software" in u
                   for u in urls)


def test_live_bundles_fetch_only_the_two_listing_pages():
    http = _http(_listing())
    bundle_preview.live_bundles(http=http)
    asked = [c.args[1] for c in http.request.call_args_list]
    assert asked == ["https://www.humblebundle.com/books",
                     "https://www.humblebundle.com/games"]


def test_a_listing_without_its_data_block_says_so():
    with pytest.raises(ValueError, match="listing"):
        bundle_preview.live_bundles(http=_http("<html><body>shell</body></html>"))


def test_a_listing_whose_data_is_not_the_expected_shape_lists_nothing():
    page = ('<script id="landingPage-json-data" type="application/json">'
            '["not", "an", "object"]</script>')
    assert bundle_preview.live_bundles(http=_http(page)) == []
