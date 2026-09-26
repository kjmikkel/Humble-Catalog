import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from humble_catalog import choice_preview, db, humble_api, import_games, titles

FIXTURES = Path(__file__).parent / "fixtures"


def _hub():
    return json.loads((FIXTURES / "choice_hub.json").read_text(encoding="utf-8"))


def _conn(tmp_path):
    """A catalog with a small imported steam library and one keyed game.

    Widget Quest is the base the Definitive Edition must match and the
    sequel must NOT. Starfall Rally is the foil that puts Starfall Rally
    Turbo in the ambiguous band. Cinder Vale exists only as an
    unactivated Humble key, so it is in no imported library.
    """
    conn = db.connect(tmp_path / "catalog.db")
    import_games.store_games(conn, "steam", [
        {"store_id": sid, "title": t,
         "normalized_title": titles.clean_game_title(t),
         "source_timestamp": None}
        for sid, t in (("440", "Widget Quest"), ("220", "Neon Drifter"),
                       ("330", "Starfall Rally"))], "test")
    conn.execute("INSERT INTO bundles (gamekey, name, url) VALUES "
                 "('kv789', 'Humble Game Bundle: Key Vault', "
                 "'https://example.invalid/kv789')")
    conn.execute(
        "INSERT INTO external_keys "
        "(gamekey, machine_name, human_name, key_type, raw) "
        "VALUES ('kv789', 'cindervale_steam', 'Cinder Vale', 'steam', ?)",
        (json.dumps({"human_name": "Cinder Vale", "key_type": "steam"}),))
    conn.commit()
    return conn


def _report(tmp_path):
    conn = _conn(tmp_path)
    try:
        return choice_preview.preview(conn, _hub())
    finally:
        conn.close()


def test_preview_reports_the_month_and_its_price(tmp_path):
    report = _report(tmp_path)
    assert report["name"] == "Humble Choice: January 2031"
    assert report["price"] == 11.99
    assert report["currency"] == "EUR"


def test_owned_possible_and_new_partition_the_month(tmp_path):
    # The invariant the whole report rests on: `possible` is counted as
    # neither owned nor new, so the three must still sum to the total.
    report = _report(tmp_path)
    assert report["total"] == 6
    assert report["owned"] + report["possible"] + report["new"] == 6


def test_an_edition_suffix_over_an_owned_base_reads_as_owned(tmp_path):
    assert "Widget Quest: Definitive Edition" in _report(tmp_path)["owned_items"]


def test_a_sequel_reads_as_new_and_never_as_the_owned_base(tmp_path):
    # Every fuzzy scorer rates "Widget Quest" and "Widget Quest II" as
    # near-identical, and they are the one near-identical pair that is
    # definitely a different product.
    report = _report(tmp_path)
    assert "Widget Quest II" in report["new_items"]
    assert "Widget Quest II" not in report["owned_items"]


def test_the_ambiguous_band_is_counted_as_neither_owned_nor_new(tmp_path):
    report = _report(tmp_path)
    offered = [p["offered"] for p in report["possible_items"]]
    assert offered == ["Starfall Rally Turbo"]
    assert "Starfall Rally Turbo" not in report["owned_items"]
    assert "Starfall Rally Turbo" not in report["new_items"]


def test_a_title_owned_nowhere_reads_as_new(tmp_path):
    assert "Lantern & Lockpick" in _report(tmp_path)["new_items"]


def test_lists_are_sorted_case_insensitively_not_left_in_display_order(
        tmp_path):
    # display_order is Humble's marketing decision. This list gets
    # scanned -- "is the one I want in here?" -- so it sorts.
    report = _report(tmp_path)
    assert report["new_items"] == sorted(report["new_items"], key=str.lower)
    assert report["owned_items"] == sorted(report["owned_items"], key=str.lower)


def test_an_empty_catalog_reports_every_game_as_new(tmp_path):
    # The dangerous case: an empty games table must not read as "owns none
    # of it" by accident and must not crash.
    conn = db.connect(tmp_path / "empty.db")
    try:
        report = choice_preview.preview(conn, _hub())
    finally:
        conn.close()
    assert (report["total"], report["owned"], report["new"]) == (6, 0, 6)


def test_a_game_held_only_as_a_humble_key_counts_as_owned(tmp_path):
    # Cinder Vale was paid for in an earlier bundle and never activated,
    # so it is in no imported library. Reporting it as new would push
    # toward paying for it twice.
    report = _report(tmp_path)
    assert "Cinder Vale" in report["owned_items"]
    assert "Cinder Vale" not in report["new_items"]


def test_a_keyed_game_is_listed_apart_from_a_library_match(tmp_path):
    # Counted inside `owned`, but named: an unactivated key can be dead or
    # region-locked in a way a library entry cannot.
    report = _report(tmp_path)
    assert report["keyed"] == 1
    hit = report["keyed_items"][0]
    assert hit["offered"] == "Cinder Vale"
    assert hit["key_type"] == "steam"
    assert hit["bundle"] == "Humble Game Bundle: Key Vault"


def test_keyed_is_a_subset_of_owned_and_is_never_added_to_it(tmp_path):
    report = _report(tmp_path)
    assert report["keyed"] <= report["owned"]
    assert report["owned"] + report["possible"] + report["new"] == report["total"]


def test_a_library_match_is_not_reported_as_keyed(tmp_path):
    # Keys are tried only after the libraries say "new", so a game both
    # keyed and activated reports as the plain library match it is.
    assert [k["offered"] for k in _report(tmp_path)["keyed_items"]] == [
        "Cinder Vale"]


def test_extras_are_listed_and_never_counted(tmp_path):
    # Extras are coupon-class entries, not games. Folding them into the
    # total would corrupt every count derived from it.
    report = _report(tmp_path)
    assert report["extras"] == ["Bonus Wallpaper", "Sample Ambience Pack"]
    assert report["total"] == 6
    assert report["owned"] + report["possible"] + report["new"] == 6


def test_a_month_with_no_choices_made_reads_as_unclaimed(tmp_path):
    assert _report(tmp_path)["claimed"] is False


def test_a_month_with_choices_made_reads_as_claimed(tmp_path):
    hub = _hub()
    hub["contentChoiceOptions"]["contentChoiceState"]["initial"][
        "choices_made"] = ["neondrifter_choice"]
    conn = _conn(tmp_path)
    try:
        assert choice_preview.preview(conn, hub)["claimed"] is True
    finally:
        conn.close()


def test_a_store_with_an_unmatched_game_and_no_import_is_named(tmp_path):
    # Lantern & Lockpick is delivered on gog, is owned nowhere, and gog
    # has never been imported -- so it was counted as new by DEFAULT, and
    # the report says so rather than presenting a guess as a fact.
    assert _report(tmp_path)["unimported_stores"] == ["gog"]


def test_other_key_is_never_named_as_an_unimported_store(tmp_path):
    # 'other-key' rides along on Widget Quest II, which is new. It is not
    # a storefront, so no importer could ever satisfy the advice the
    # warning gives.
    assert "other-key" not in _report(tmp_path)["unimported_stores"]


def test_a_store_whose_games_all_matched_is_not_warned_about(tmp_path):
    # Only an unmatched game earns a warning. steam is imported here, but
    # even were it not, warning about a store whose every game is already
    # owned is the noise that teaches an owner to skip the real warning.
    hub = _hub()
    del hub["contentChoiceOptions"]["contentChoiceData"]["game_data"][
        "lanternlockpick_choice"]
    conn = _conn(tmp_path)
    try:
        report = choice_preview.preview(conn, hub)
    finally:
        conn.close()
    assert report["unimported_stores"] == []


def test_delivery_stores_reads_a_bare_string_as_one_store(tmp_path):
    # shapes.text_list, not as_list: a list field that arrived unwrapped
    # is ONE name, never its characters. set() over a string yields five
    # single-letter storefronts.
    assert choice_preview.delivery_stores(
        {"delivery_methods": "steam"}) == {"steam"}
    assert choice_preview.delivery_stores({}) == set()
    assert choice_preview.delivery_stores(
        {"delivery_methods": ["steam", "other-key"]}) == {"steam"}


def test_libraries_reports_what_was_imported(tmp_path):
    assert "steam" in _report(tmp_path)["libraries"]


def _text(tmp_path):
    return choice_preview.format_report(_report(tmp_path))


def test_format_report_leads_with_the_month_and_the_three_counts(tmp_path):
    out = _text(tmp_path)
    assert "Humble Choice: January 2031" in out
    assert "owned 3" in out and "possible 1" in out and "new 2" in out


def test_format_report_lists_the_new_games(tmp_path):
    out = _text(tmp_path)
    assert "Lantern & Lockpick" in out
    assert "Widget Quest II" in out


def test_format_report_names_the_key_a_count_is_trusting(tmp_path):
    out = _text(tmp_path)
    assert "owned via a Humble key" in out
    assert "Humble Game Bundle: Key Vault" in out


def test_format_report_says_a_possible_is_counted_as_neither(tmp_path):
    out = _text(tmp_path)
    assert "counted as neither owned nor new" in out
    assert "Starfall Rally Turbo" in out


def test_format_report_always_warns_that_matching_is_approximate(tmp_path):
    # Unlike the bundle report, this warning is unconditional: every
    # answer here is a title match, so there is no book path that earns
    # the warning's absence.
    assert "APPROXIMATE" in _text(tmp_path)


def test_format_report_warns_about_a_store_with_no_import(tmp_path):
    out = _text(tmp_path)
    assert "never been imported" in out
    assert "gog" in out


def test_format_report_degrades_a_symbol_the_console_cannot_encode(tmp_path):
    # cp437 is the Windows console default and has no euro sign. capsys
    # captures as UTF-8, so no other test can observe this.
    out = choice_preview.format_report(_report(tmp_path), "cp437")
    assert "EUR 11.99" in out
    assert "€" not in out


def test_format_report_omits_the_headings_of_empty_blocks(tmp_path):
    # A month owned outright must print as clean counts, not as a stack of
    # empty headings.
    conn = _conn(tmp_path)
    hub = _hub()
    for name in ("widgetquest2_choice", "starfallrallyturbo_choice",
                 "lanternlockpick_choice"):
        del hub["contentChoiceOptions"]["contentChoiceData"]["game_data"][name]
    try:
        out = choice_preview.format_report(choice_preview.preview(conn, hub))
    finally:
        conn.close()
    assert "new 0" in out
    assert "counted as neither owned nor new" not in out
    assert "never been imported" not in out


def test_preview_survives_a_hub_that_is_not_the_expected_shape(tmp_path):
    # The blob is third-party content. A garbage payload must report a
    # month selling nothing, not raise out of a viewer route.
    conn = db.connect(tmp_path / "empty.db")
    try:
        report = choice_preview.preview(conn, {"contentChoiceOptions": "nope"})
    finally:
        conn.close()
    assert report["total"] == 0
    assert report["name"] == "Humble Choice"


# --- Fetching -----------------------------------------------------------

def _client(text, logged_in=True):
    """A stub HumbleClient whose one page carries `text`."""
    client = Mock()
    client.logged_in.return_value = logged_in
    client.get_page.return_value = text
    return client


def _page():
    return (FIXTURES / "choice_page.html").read_text(encoding="utf-8")


def test_fetch_choice_parses_the_embedded_hub_blob():
    hub = choice_preview.fetch_choice(_client(_page()))
    assert hub["contentChoiceOptions"]["title"] == "January 2031"
    assert hub["baseSubscriptionPrice|money"]["amount"] == 11.99


def test_fetch_choice_returns_the_whole_hub_not_just_the_month():
    # The price sits at the TOP level, outside contentChoiceOptions.
    # Returning the narrower dict would put it out of preview's reach.
    hub = choice_preview.fetch_choice(_client(_page()))
    assert "baseSubscriptionPrice|money" in hub


def test_fetch_choice_refuses_a_stale_session_before_fetching_anything():
    # A signed-out /membership still answers 200 with a marketing shell,
    # so a missing blob is ambiguous between "not logged in" and "no offer
    # this month". logged_in() disambiguates, and the caller needs the
    # difference: one is fixed by logging in, the other is not.
    client = _client(_page(), logged_in=False)
    with pytest.raises(humble_api.NotLoggedIn):
        choice_preview.fetch_choice(client)
    client.get_page.assert_not_called()


def test_fetch_choice_rejects_a_page_with_no_hub_blob():
    with pytest.raises(ValueError, match="no Humble Choice data"):
        choice_preview.fetch_choice(
            _client("<html><body>Nothing here</body></html>"))


def test_fetch_choice_rejects_a_blob_with_no_month_on_offer():
    with pytest.raises(ValueError, match="no Humble Choice month"):
        choice_preview.fetch_choice(_client(
            '<script id="webpack-subscriber-hub-data" '
            'type="application/json">{"contentChoiceOptions": {}}</script>'))


def test_the_fetched_page_feeds_preview_unchanged(tmp_path):
    # The seam's whole point: what fetch_choice returns is what preview
    # consumes, with nothing in between to drift.
    conn = _conn(tmp_path)
    try:
        report = choice_preview.preview(
            conn, choice_preview.fetch_choice(_client(_page())))
    finally:
        conn.close()
    assert report["name"] == "Humble Choice: January 2031"
    assert (report["total"], report["owned"]) == (1, 1)


def test_a_possible_carries_its_word(tmp_path):
    # #93: the same word the bundle panel uses, from the same line.
    from humble_catalog import bundle_preview
    possible = _report(tmp_path)["possible_items"]
    assert possible and all(
        p["strength"] == bundle_preview.strength(p["score"]) for p in possible)
