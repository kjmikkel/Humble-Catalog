"""Behavioural tests for the viewer's JavaScript.

These run the real functions from app.js (see js_harness.py). They exist
because the text assertions in test_webapp.py cannot catch a renderer
that throws -- which is how the whole page once went blank.
"""
import json
import re
from pathlib import Path

from humble_catalog import export, stats
from tests.js_harness import eval_js, eval_js_error


def _item(**overrides):
    """A catalog item as /api/items serves it, with fields overridable."""
    item = {
        "id": 1, "name": "The Quiet Harbor: A Novel", "type": "ebook",
        "publisher": "Example Press", "cover_path": None, "my_rating": 4,
        "genre": ["Fantasy"], "series": None, "series_number": None,
        "authors": ["Sam Coder"], "narrator": [], "illustrator": [],
        "external_rating": None, "rating_source": None, "status": "matched",
        "source_url": None, "edited": False, "re_enriched": False,
        "override": False, "bundles": [], "formats": [],
        "user_tags": [], "user_comment": None, "read_status": "unread",
    }
    item.update(overrides)
    return item


def test_tag_badges_survives_a_missing_array():
    # an older server, or any partial payload, omits the field entirely
    assert eval_js_error("app.tagBadges(undefined)") is None
    assert eval_js("app.tagBadges(undefined)") == ""
    assert eval_js("app.tagBadges(null)") == ""


def test_person_survives_a_missing_name_field():
    # same shape of bug as tagBadges, one function along: person() reads
    # .length off narrator before anything has checked it exists
    item = json.dumps(_item(narrator=None, illustrator=None))
    assert eval_js_error(f"app.person({item})") is None
    assert eval_js(f"app.person({item})") == []


def test_person_still_prefers_narrator_then_illustrator():
    narrated = json.dumps(_item(narrator=["Sam Reader"], illustrator=["Ann Art"]))
    drawn = json.dumps(_item(narrator=[], illustrator=["Ann Art"]))
    assert eval_js(f"app.person({narrated})") == ["Sam Reader"]
    assert eval_js(f"app.person({drawn})") == ["Ann Art"]


def test_load_renders_every_panel_even_when_one_renderer_throws():
    # bundles is deliberately absent, so render() throws deep inside the
    # row template. The review, duplicates and genre panels are unrelated
    # to that failure and must still be rendered.
    broken = json.dumps([_item(bundles=None)])
    result = eval_js(
        """(async () => {
             dom.reset();
             app.setFetch((url) => Promise.resolve({json: () => Promise.resolve(
               url === "/api/items"      ? {items: %s} :
               url === "/api/review"     ? {items: []} :
               url === "/api/duplicates" ? {groups: []} :
               url === "/api/stats"      ? {total: 1, sections: []} : {})}));
             let threw = null;
             try { await app.load(); } catch (e) { threw = e.message; }
             return {threw, wrote: Object.keys(dom.writes).sort()};
           })()""" % broken)
    # load() itself must not propagate the failure...
    assert result["threw"] is None
    # ...and the panels a broken row cannot affect must still be written
    assert "#dupes-panel" in result["wrote"]
    assert "#stats-panel" in result["wrote"]


def test_load_survives_a_duplicates_payload_without_groups():
    # loadDupes assigned the payload field straight into dupeGroups, so a
    # response without `groups` replaced the safe [] with undefined. The
    # throw inside renderDupes() is contained by load()'s loop -- but the
    # badge arithmetic after the loop is not, and it reads dupeGroups
    # too, so load() threw anyway from wherever it had been called.
    # loadKeys already had the answer: `data.rows || []`.
    result = eval_js(
        """(async () => {
             app.setFetch((url) => Promise.resolve({json: () => Promise.resolve(
               url === "/api/items"      ? {items: []} :
               url === "/api/review"     ? {items: []} :
               url === "/api/duplicates" ? {} :
               url === "/api/stats"      ? {total: 0, sections: []} : {})}));
             let threw = null;
             try { await app.load(); } catch (e) { threw = e.message; }
             return {threw, maintenance: app.getPending().maintenance};
           })()""")
    assert result["threw"] is None
    # and the badge is a number rather than NaN or a crash
    assert result["maintenance"] == 0


def test_review_panel_collapses_with_a_count_summary():
    # The panel body must be a <details> so it collapses, and the summary
    # must carry the count so a collapsed panel still signals pending work.
    review = json.dumps([
        {"id": 1, "name": "The Quiet Harbor: A Novel", "type": "ebook",
         "status": "low_confidence", "cover_path": None, "candidates": []}])
    html = eval_js(
        """(async () => {
             dom.reset();
             app.setFetch((url) => Promise.resolve({json: () => Promise.resolve(
               url === "/api/review" ? {items: %s} : {items: []})}));
             await app.loadReview();
             return dom.writes["#review-panel"];
           })()""" % review)
    assert "<details" in html
    assert "<summary" in html
    assert "1 item" in html


def _matches(comment, query, **extra):
    """Does an item with this note pass the filters when Notes is set?"""
    item = json.dumps(_item(user_comment=comment, **extra))
    return eval_js(
        """(() => {
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.chipFilters.user_comment.text = %s;
             return app.passesChipFilters(%s);
           })()""" % (json.dumps(query), item))


def test_notes_filter_matches_a_substring_of_the_note():
    assert _matches("Gift from Sam.", "gift") is True
    assert _matches("Gift from Sam.", "borrowed") is False


def test_notes_filter_ignores_the_note_s_case():
    # The matcher lowercases the note but not the query: both places that
    # write f.text lowercase it first, so by the time it arrives here it is
    # already lowercase. Passing "REREAD" would test a state the UI cannot
    # produce, so the case difference belongs on the note side.
    assert _matches("REREAD Before The Sequel.", "reread") is True
    assert _matches("Reread before the sequel.", "sequel") is True


def test_notes_filter_never_matches_an_item_without_a_note():
    assert _matches(None, "gift") is False
    assert _matches("", "gift") is False


def test_notes_filter_empty_query_matches_everything():
    # including items that have no note at all
    assert _matches(None, "") is True
    assert _matches("Gift from Sam.", "") is True


def test_notes_filter_ands_with_a_user_tag_chip():
    item = json.dumps(_item(user_comment="Gift from Sam.",
                            user_tags=["to reread"]))
    result = eval_js(
        """(() => {
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.chipFilters.user_comment.text = "gift";
             const item = %s;
             const before = app.passesChipFilters(item);
             app.chipFilters.user_tags.chips = ["lent out"];
             return {before, afterNonMatchingChip: app.passesChipFilters(item)};
           })()""" % item)
    assert result["before"] is True
    # a non-matching tag chip must exclude the row: fields AND together
    assert result["afterNonMatchingChip"] is False


def _sorted_names(catalog, key, asc=True):
    """Names in the order visible() yields for the given sort."""
    return eval_js(
        """(() => {
             app.setItems(%s);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.setSort(%s, %s);
             return app.visible().map(i => i.name);
           })()""" % (json.dumps(catalog), json.dumps(key),
                      "true" if asc else "false"))


def test_sort_by_bundle_uses_the_bundle_name_not_the_object():
    # item.bundle does not exist; sorting must derive the name from bundles[].
    catalog = [
        {**_item(id=1, name="Beta"), "bundles": [{"name": "Zephyr Bundle", "url": ""}]},
        {**_item(id=2, name="Alpha"), "bundles": [{"name": "Alpine Bundle", "url": ""}]},
    ]
    assert _sorted_names(catalog, "bundle", asc=True) == ["Alpha", "Beta"]
    assert _sorted_names(catalog, "bundle", asc=False) == ["Beta", "Alpha"]


def test_status_sort_follows_the_reading_lifecycle_not_the_alphabet():
    # Alphabetical would be dnf < read < reading < unread < want_to_read;
    # lifecycle order is want_to_read < unread < reading < read < dnf.
    catalog = [
        _item(id=1, name="All Systems Red", read_status="dnf"),
        _item(id=2, name="Unrelated Book", read_status="want_to_read"),
        _item(id=3, name="The Quiet Harbor: A Novel", read_status="reading"),
        _item(id=4, name="Cafe of Broken Clocks", read_status="unread"),
        _item(id=5, name="Wings of Autumn Dusk (Book 1)", read_status="read"),
    ]
    assert _sorted_names(catalog, "read_status", asc=True) == [
        "Unrelated Book",                 # want_to_read
        "Cafe of Broken Clocks",          # unread
        "The Quiet Harbor: A Novel",      # reading
        "Wings of Autumn Dusk (Book 1)",  # read
        "All Systems Red",                # dnf
    ]


def test_sort_by_narrator_follows_the_column_including_illustrator():
    # The column shows narrator‖illustrator; a comic with only an illustrator
    # must still sort under that name, not fall through to empty.
    catalog = [
        {**_item(id=1, name="Narrated"), "narrator": ["Sam Reader"], "illustrator": []},
        {**_item(id=2, name="Drawn", type="comic"), "narrator": [], "illustrator": ["Ann Art"]},
    ]
    # "Ann Art" < "Sam Reader", so the illustrator-only comic sorts first.
    assert _sorted_names(catalog, "narrator", asc=True) == ["Drawn", "Narrated"]


def _bulk_state(n_items, filter_text):
    """shownRows() with n_items in the catalog and an optional note filter."""
    catalog = json.dumps([
        _item(id=i, name=f"Item {i}", user_comment="keep" if i == 1 else None)
        for i in range(1, n_items + 1)])
    return eval_js(
        """(() => {
             app.setItems(%s);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.chipFilters.user_comment.text = %s;
             return app.shownRows();
           })()""" % (catalog, json.dumps(filter_text)))


def test_bulk_target_is_everything_when_unfiltered():
    state = _bulk_state(3, "")
    assert state["count"] == 3
    assert state["ids"] == [1, 2, 3]
    # not narrowed: removal must stay unavailable
    assert state["filtered"] is False


def test_bulk_target_follows_the_filter():
    state = _bulk_state(3, "keep")
    assert state["count"] == 1
    assert state["ids"] == [1]
    assert state["filtered"] is True


def test_bulk_target_is_empty_when_nothing_matches():
    state = _bulk_state(3, "nothing matches this")
    assert state["count"] == 0
    assert state["ids"] == []
    assert state["filtered"] is True


def test_search_now_finds_a_title_with_the_words_in_the_wrong_order():
    items = json.dumps([_item(id=1, name="The Quiet Harbor: A Novel")])
    found = eval_js(
        f"""(() => {{
              app.setItems({items});
              app.setSearch("harbor quiet");
              return app.visible().map(i => i.id);
            }})()""")
    assert found == [1]


def test_search_still_rejects_an_unrelated_query():
    items = json.dumps([_item(id=1, name="The Quiet Harbor: A Novel")])
    found = eval_js(
        f"""(() => {{
              app.setItems({items});
              app.setSearch("axebearer");
              return app.visible().map(i => i.id);
            }})()""")
    assert found == []


def test_an_empty_search_records_no_match_spans():
    items = json.dumps([_item(id=1, name="The Quiet Harbor: A Novel")])
    spans = eval_js(
        f"""(() => {{
              app.setItems({items});
              app.setSearch("");
              app.visible();
              return app.getMatchSpans().size;
            }})()""")
    assert spans == 0


def test_search_does_not_reach_into_notes_or_other_fields():
    # v1.12 narrowed the box to names; fuzzy matching must not widen it.
    # The comment is a verbatim match for the query and the name is not.
    items = json.dumps([_item(id=1, name="The Quiet Harbor: A Novel",
                              user_comment="lent to Sam Reader")])
    found = eval_js(
        f"""(() => {{
              app.setItems({items});
              app.setSearch("lent to Sam Reader");
              return app.visible().map(i => i.id);
            }})()""")
    assert found == []


def test_relevance_puts_the_exact_match_above_the_fuzzy_one():
    # sorted by name, "A Quiet Life in Harbors" would come first; by
    # relevance the verbatim match must win
    items = json.dumps([
        _item(id=1, name="A Quiet Life in Harbors"),
        _item(id=2, name="The Quiet Harbor: A Novel"),
    ])
    order = eval_js(
        f"""(() => {{
              app.setItems({items});
              app.setSort("name", true);
              app.setRelevance(true);
              app.setSearch("quiet harbor");
              return app.visible().map(i => i.id);
            }})()""")
    assert order == [2, 1]


def test_a_column_sort_overrides_relevance():
    items = json.dumps([
        _item(id=1, name="A Quiet Life in Harbors"),
        _item(id=2, name="The Quiet Harbor: A Novel"),
    ])
    order = eval_js(
        f"""(() => {{
              app.setItems({items});
              app.setSort("name", true);
              app.setRelevance(false);
              app.setSearch("quiet harbor");
              return app.visible().map(i => i.id);
            }})()""")
    assert order == [1, 2]


def test_an_empty_query_leaves_the_column_sort_alone():
    items = json.dumps([
        _item(id=2, name="The Quiet Harbor: A Novel"),
        _item(id=1, name="A Quiet Life in Harbors"),
    ])
    order = eval_js(
        f"""(() => {{
              app.setItems({items});
              app.setSort("name", true);
              app.setRelevance(true);
              app.setSearch("");
              return app.visible().map(i => i.id);
            }})()""")
    assert order == [1, 2]


def test_highlight_wraps_only_the_matched_range():
    assert eval_js('app.highlight("The Quiet Harbor", [[4, 9]])') \
        == "The <mark>Quiet</mark> Harbor"


def test_highlight_without_spans_is_plain_escaping():
    assert eval_js('app.highlight("Tom & Jerry <b>", [])') \
        == eval_js('app.esc("Tom & Jerry <b>")')
    assert eval_js('app.highlight("Tom & Jerry <b>", null)') \
        == eval_js('app.esc("Tom & Jerry <b>")')


def test_highlight_escapes_around_and_inside_a_mark():
    # the tempting implementation escapes first and matches second, which
    # displaces every span past an "&" and can split an entity in half
    assert eval_js('app.highlight("A & B <i>", [[4, 5]])') \
        == "A &amp; <mark>B</mark> &lt;i&gt;"


def test_highlight_ignores_a_span_that_overlaps_the_previous_one():
    assert eval_js('app.highlight("abcdef", [[0, 3], [1, 4]])') \
        == "<mark>abc</mark>def"


def _flagged(catalog, flag):
    """The ids visible() yields under the given #f-flag value."""
    return eval_js(
        """(() => {
             app.setItems(%s);
             app.setFlag(%s);
             return app.visible().map(i => i.id);
           })()""" % (json.dumps(catalog), json.dumps(flag)))


def test_no_flag_shows_annotated_and_un_annotated_items_alike():
    # the baseline the two flags narrow: neither reorders or drops rows
    catalog = [_item(id=1, name="The Quiet Harbor: A Novel",
                     user_comment="lent to Sam Reader", user_tags=["lent out"]),
               _item(id=2, name="Unrelated Book")]
    assert _flagged(catalog, "") == [1, 2]


def test_has_notes_keeps_only_the_commented_item():
    catalog = [_item(id=1, name="The Quiet Harbor: A Novel",
                     user_comment="lent to Sam Reader"),
               _item(id=2, name="Unrelated Book", user_comment=None)]
    assert _flagged(catalog, "notes") == [1]


def test_a_whitespace_only_comment_is_not_a_note():
    # saving an empty box can leave "" or "   " behind; neither is a note
    catalog = [_item(id=1, name="The Quiet Harbor: A Novel", user_comment="   "),
               _item(id=2, name="Unrelated Book", user_comment="")]
    assert _flagged(catalog, "notes") == []


def test_has_my_tags_keeps_only_the_tagged_item():
    catalog = [_item(id=1, name="The Quiet Harbor: A Novel", user_tags=["lent out"]),
               _item(id=2, name="Unrelated Book", user_tags=[])]
    assert _flagged(catalog, "mytags") == [1]


def test_no_cover_flag_keeps_only_the_coverless_item():
    catalog = [_item(id=1, cover_path=None),
               _item(id=2, cover_path="covers/2.jpg")]
    assert _flagged(catalog, "nocover") == [1]


def test_no_cover_flag_treats_an_empty_string_as_missing():
    catalog = [_item(id=1, cover_path=""),
               _item(id=2, cover_path="covers/2.jpg")]
    assert _flagged(catalog, "nocover") == [1]


def test_no_source_url_flag_keeps_only_the_linkless_item():
    catalog = [_item(id=1, source_url=None),
               _item(id=2, source_url="http://example.test/2")]
    assert _flagged(catalog, "nourl") == [1]


def test_the_annotation_flags_survive_a_missing_field():
    # same shape of bug as tagBadges: an older server omits the field, and
    # reading .length or .trim() off undefined blanks the whole page
    catalog = [_item(id=1, name="Unrelated Book")]
    del catalog[0]["user_tags"]
    del catalog[0]["user_comment"]
    assert _flagged(catalog, "notes") == []
    assert _flagged(catalog, "mytags") == []


def _rendered(item):
    """The table body app.js renders for a single item."""
    return eval_js(
        """(() => {
             dom.reset();
             app.setItems([%s]);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.setFlag("");
             app.render();
             return dom.writes["#catalog tbody"];
           })()""" % json.dumps(item))


def test_override_filter_keeps_only_queued_rows():
    queued = json.dumps(_item(id=1, edited=True, override=True))
    plain = json.dumps(_item(id=2, edited=True, override=False))
    assert eval_js(
        """(() => {
             app.setItems([%s, %s]);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.setFlag("override");
             return app.visible().map(i => i.id);
           })()""" % (queued, plain)) == [1]


def test_queued_row_renders_its_badge():
    assert "re-enrich queued" in _rendered(_item(edited=True, override=True))


def test_a_table_tag_carries_its_full_name_for_when_it_is_cut():
    # The Library's columns are fixed-width now (#46), so a long bundle or
    # author name is cut with an ellipsis; the title is where the rest of
    # it is read.
    html = _rendered(_item(
        authors=["Sam Coder"],
        bundles=[{"name": "Example Press Omnibus Bundle",
                  "url": "https://example.invalid/b1"}]))
    assert '<span class="tag" title="Sam Coder">Sam Coder</span>' in html
    assert 'title="Example Press Omnibus Bundle"' in html


def test_a_bundle_cell_starts_at_the_part_that_names_the_bundle():
    # At a fixed width the ellipsis cut every bundle to "Humble...", the
    # one word they all share (#46); dropping that still left "Book Bu...",
    # the kind of bundle rather than which one (#76). The cell starts after
    # both; the title and the link keep the full name.
    html = _rendered(_item(bundles=[{
        "name": "Humble Book Bundle: Example Harbor Tales",
        "url": "https://example.invalid/b2"}]))
    assert ('title="Humble Book Bundle: Example Harbor Tales">'
            'Example Harbor Tales</a>') in html


def test_bundle_label_drops_only_what_every_bundle_shares():
    label = lambda name: eval_js("app.bundleLabel(%s)" % json.dumps(name))
    assert label("Humble Audiobook Bundle: Epic Tales 2020") == \
        "Epic Tales 2020"
    # No kind prefix: only the shared word goes.
    assert label("Humble Comics Samples") == "Comics Samples"
    # A colon that does not follow "Bundle" is part of the name.
    assert label("Humble Choice: March") == "Choice: March"
    # Nothing left after a prefix: the name is kept rather than blanked.
    assert label("Humble") == "Humble"
    assert label("Humble Book Bundle:") == "Humble Book Bundle:"
    assert label("Example Press Omnibus") == "Example Press Omnibus"


def test_re_enriched_row_renders_a_revert_button_not_an_edited_badge():
    html = _rendered(_item(edited=False, re_enriched=True))
    assert "re-enriched" in html and "revert" in html
    assert "badge edited" not in html


def _name_cell_buttons(html):
    """{class: aria-label} for each icon-only control in the name cell."""
    found = re.findall(
        r'<(?:button|a) class="(src-link|redo|edit|revert|override)"'
        r'[^>]*?aria-label="([^"]*)"', html, re.S)
    return dict(found)


def test_every_name_cell_glyph_has_an_accessible_name():
    # Five controls that differ only by the shape of an arrow, and a title
    # was all each one had: a hover to read, and the weakest accessible
    # name there is (#50). Each needs an aria-label naming what it does
    # and which row it does it to.
    html = _rendered(_item(source_url="https://example.com/b",
                           edited=True))
    html += _rendered(_item(status="matched"))
    labels = _name_cell_buttons(html)
    assert set(labels) == {"src-link", "redo", "edit", "revert", "override"}
    for cls, label in labels.items():
        assert "The Quiet Harbor" in label, (cls, label)


def test_the_re_enriched_revert_is_labelled_too():
    labels = _name_cell_buttons(_rendered(_item(re_enriched=True)))
    assert "your edited values" in labels["revert"]


def _export_button(n_items, filter_text):
    """#export's label and disabled state after renderExportButton()."""
    catalog = json.dumps([
        _item(id=i, name=f"Item {i}", user_comment="keep" if i == 1 else None)
        for i in range(1, n_items + 1)])
    return eval_js(
        """(() => {
             app.setItems(%s);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.chipFilters.user_comment.text = %s;
             app.renderExportButton();
             return {label: dom.writes["#export:text"],
                     disabled: document.querySelector("#export").disabled};
           })()""" % (catalog, json.dumps(filter_text)))


def test_export_button_says_download_all_when_unfiltered():
    # The format moved to the select, so the label states only what rows.
    # Unfiltered IS the whole catalog, which is what "all" reports.
    state = _export_button(3, "")
    assert state["label"] == "Download all"
    assert state["disabled"] is False


def test_export_button_shows_the_row_count_when_filtered():
    # the label doubles as the blast-radius readout, like the bulk bar
    state = _export_button(3, "keep")
    assert state["label"] == "Download 1 shown"
    assert state["disabled"] is False


def test_export_button_is_disabled_with_nothing_to_export():
    # a header-only file would look like a bug
    state = _export_button(3, "nothing matches this")
    assert state["disabled"] is True


def test_download_export_posts_visible_ids_in_screen_order():
    # Relevance ordering is part of what the viewer shows, so it must be
    # what gets posted -- not the catalog's title order.
    catalog = json.dumps([
        _item(id=1, name="A Quiet Life in Harbors"),
        _item(id=2, name="The Quiet Harbor: A Novel"),
        _item(id=3, name="Unrelated Book"),
    ])
    sent = eval_js(
        """(async () => {
             app.setItems(%s);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.setSearch("quiet harbor");
             app.setRelevance(true);
             let body = null;
             app.setFetch((url, opts) => {
               body = JSON.parse(opts.body);
               return Promise.resolve({ok: true, blob: () => ({})});
             });
             await app.downloadExport();
             return {body, order: app.visible().map(i => i.id)};
           })()""" % catalog)
    # the exact ranking is fuzzy.js's business; that the two agree is ours
    assert sent["body"]["ids"] == sent["order"]
    # and the closer title outranks the looser one, so this is a real order
    assert sent["body"]["ids"][0] == 2


def test_download_export_sends_nothing_when_no_rows_are_visible():
    called = eval_js(
        """(async () => {
             app.setItems([]);
             let calls = 0;
             app.setFetch(() => { calls += 1;
               return Promise.resolve({ok: true, blob: () => ({})}); });
             await app.downloadExport();
             return calls;
           })()""")
    assert called == 0


def _download_target(fmt, filter_text=""):
    """The URL posted and the filename set, for a given format select."""
    catalog = json.dumps([
        _item(id=i, name=f"Item {i}", user_comment="keep" if i == 1 else None)
        for i in range(1, 4)])
    return eval_js(
        """(async () => {
             app.setItems(%s);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.chipFilters.user_comment.text = %s;
             app.setExportFormat(%s);
             let url = null, anchor = null;
             const create = document.createElement;
             document.createElement = (t) => (anchor = create(t));
             app.setFetch((u) => { url = u;
               return Promise.resolve({ok: true, blob: () => ({})}); });
             await app.downloadExport();
             document.createElement = create;
             return {url, name: anchor.download};
           })()""" % (catalog, json.dumps(filter_text), json.dumps(fmt)))


def test_the_select_picks_the_route_and_the_extension():
    sent = _download_target("xlsx")
    assert sent["url"] == "/api/export.xlsx"
    assert sent["name"] == "catalog.xlsx"


def test_csv_stays_the_other_option():
    sent = _download_target("csv")
    assert sent["url"] == "/api/export.csv"
    assert sent["name"] == "catalog.csv"


def test_a_filtered_export_gets_its_own_filename_in_either_format():
    # A filtered export is a different artifact and must not silently
    # overwrite the full one in the downloads folder.
    assert _download_target("xlsx", "keep")["name"] == "catalog-filtered.xlsx"
    assert _download_target("csv", "keep")["name"] == "catalog-filtered.csv"


def test_export_columns_start_as_everything():
    assert eval_js("app.getExportColumns()") == list(export.COLUMNS)


def test_toggling_a_column_removes_it_from_the_payload():
    sent = eval_js(
        """(async () => {
             app.setItems([%s]);
             let body = null;
             app.setFetch((url, opts) => {
               body = JSON.parse(opts.body);
               return Promise.resolve({ok: true, blob: () => ({})});
             });
             app.toggleColumn("publisher", false);
             await app.downloadExport();
             return body;
           })()""" % json.dumps(_item(id=1, name="A Quiet Life in Harbors")))
    assert "publisher" not in sent["columns"]
    assert "title" in sent["columns"]


def test_a_column_only_narrowing_still_gets_the_filtered_filename():
    # The filter-aware spec pinned `filtered` to "fewer rows"; a partial
    # export must not silently overwrite catalog.csv whichever axis
    # narrowed it.
    name = eval_js(
        """(async () => {
             app.setItems([%s]);
             app.setFetch(() => Promise.resolve({ok: true, blob: () => ({})}));
             app.toggleColumn("publisher", false);
             const create = document.createElement;
             let anchor = null;
             document.createElement = () => (anchor = create());
             await app.downloadExport();
             document.createElement = create;
             return anchor.download;
           })()""" % json.dumps(_item(id=1, name="A Quiet Life in Harbors")))
    assert name == "catalog-filtered.csv"


def test_zero_columns_disables_the_export_button():
    disabled = eval_js(
        """(async () => {
             app.setItems([%s]);
             app.setExportColumns([]);
             app.renderExportButton();
             return document.querySelector("#export").disabled;
           })()""" % json.dumps(_item(id=1, name="A Quiet Life in Harbors")))
    assert disabled is True


def test_a_stored_selection_is_restored():
    cols = eval_js(
        """(async () => {
             app.setStored("hc-export-columns",
                           JSON.stringify(["title", "authors"]));
             app.loadColumnSelection();
             return app.getExportColumns();
           })()""")
    assert cols == ["title", "authors"]


def test_a_stored_name_that_no_longer_exists_is_dropped():
    cols = eval_js(
        """(async () => {
             app.setStored("hc-export-columns",
                           JSON.stringify(["title", "gone_column"]));
             app.loadColumnSelection();
             return app.getExportColumns();
           })()""")
    assert cols == ["title"]


def test_unparseable_stored_state_means_every_column():
    cols = eval_js(
        """(async () => {
             app.setStored("hc-export-columns", "{not json");
             app.loadColumnSelection();
             return app.getExportColumns();
           })()""")
    assert cols == list(export.COLUMNS)


def test_app_js_column_list_matches_the_exporter():
    # COLUMNS now exists twice, once per language. Duplicated constants
    # across a language boundary are fine; unpinned ones are not.
    from tests.js_harness import VIEWER_JS
    src = "\n".join(p.read_text(encoding="utf-8") for p in VIEWER_JS)
    listed = re.search(r"const EXPORT_COLUMNS = \[(.*?)\];", src, re.S).group(1)
    assert re.findall(r'"([a-z_]+)"', listed) == list(export.COLUMNS)


def test_the_picker_renders_one_checkbox_per_column():
    html = eval_js(
        """(async () => {
             app.renderColumnPicker();
             return dom.writes["#column-picker-body"];
           })()""")
    for name in export.COLUMNS:
        assert f'data-col="{name}"' in html
    assert html.count("checkbox") == len(export.COLUMNS)


def test_the_summary_counts_the_selection():
    text = eval_js(
        """(async () => {
             app.setExportColumns(%s);
             app.renderColumnPicker();
             return dom.writes["#column-picker-summary:text"];
           })()""" % json.dumps(list(export.COLUMNS)[:3]))
    assert text == "Columns (3/%d)" % len(export.COLUMNS)


def test_an_unselected_column_renders_unchecked():
    html = eval_js(
        """(async () => {
             app.toggleColumn("publisher", false);
             app.renderColumnPicker();
             return dom.writes["#column-picker-body"];
           })()""")
    checked = [line for line in html.split("<label") if "publisher" in line]
    assert checked and "checked" not in checked[0]


def test_toggling_does_not_rebuild_the_checkbox_list():
    # Rebuilding detaches the checkbox that was just clicked, and the
    # outside-click handler then measures contains() against a node no
    # longer in the document and closes the panel mid-click. The user's
    # own click already put the box in the right state, so the only thing
    # that needs redrawing is the count.
    rebuilt = eval_js(
        """(async () => {
             app.renderColumnPicker();
             dom.reset();
             app.toggleColumn("publisher", false);
             return {body: dom.writes["#column-picker-body"] ?? null,
                     summary: dom.writes["#column-picker-summary:text"]};
           })()""")
    assert rebuilt["body"] is None       # the list is left alone
    # one column toggled off from the full set: the count is redrawn
    assert rebuilt["summary"].startswith(
        "Columns (%d/" % (len(export.COLUMNS) - 1))


def test_status_select_marks_the_current_status_selected():
    item = json.dumps(_item(id=7, read_status="reading"))
    html = eval_js(f"app.statusSelect({item})")
    assert 'value="reading" selected' in html
    assert "read-status-select" in html
    assert "rs-reading" in html
    for key in ("want_to_read", "unread", "reading", "read", "dnf"):
        assert f'value="{key}"' in html


def test_status_select_defaults_a_missing_status_to_unread():
    item = json.dumps(_item(id=8))
    html = eval_js(
        "(() => { const i = %s; delete i.read_status; return app.statusSelect(i); })()"
        % item)
    assert 'value="unread" selected' in html


def _status_filtered(catalog, statuses):
    """The ids visible() yields with the given status chips ticked."""
    return eval_js(
        """(() => {
             app.setItems(%s);
             app.setStatusFilter(%s);
             return app.visible().map(i => i.id);
           })()""" % (json.dumps(catalog), json.dumps(statuses)))


def test_no_status_chips_shows_every_item():
    catalog = [_item(id=1, read_status="reading"),
               _item(id=2, read_status="unread")]
    assert _status_filtered(catalog, []) == [1, 2]


def test_status_filter_keeps_any_of_the_ticked_states():
    catalog = [_item(id=1, name="All Systems Red", read_status="reading"),
               _item(id=2, name="Unrelated Book", read_status="want_to_read"),
               _item(id=3, name="The Quiet Harbor: A Novel", read_status="read")]
    assert _status_filtered(catalog, ["reading", "want_to_read"]) == [1, 2]


def test_status_filter_treats_a_missing_status_as_unread():
    del_missing = eval_js(
        """(() => {
             const i = %s; delete i.read_status;
             app.setItems([i]); app.setStatusFilter(["unread"]);
             return app.visible().map(x => x.id);
           })()""" % json.dumps(_item(id=1, name="All Systems Red")))
    assert del_missing == [1]


def _rated(catalog, rating):
    """The ids visible() yields under the given #f-rating value."""
    return eval_js(
        """(() => {
             app.setItems(%s);
             app.setRating(%s);
             return app.visible().map(i => i.id);
           })()""" % (json.dumps(catalog), json.dumps(rating)))


def test_rating_filter_keeps_only_that_rating():
    catalog = [_item(id=1, my_rating=5), _item(id=2, my_rating=3),
               _item(id=3, my_rating=None)]
    assert _rated(catalog, "5") == [1]


def test_empty_rating_filter_keeps_everything():
    catalog = [_item(id=1, my_rating=5), _item(id=2, my_rating=None)]
    assert _rated(catalog, "") == [1, 2]


def test_matched_flag_keeps_only_matched_items():
    catalog = [_item(id=1, status="matched"), _item(id=2, status="pending")]
    assert _flagged(catalog, "matched") == [1]


def test_pending_flag_keeps_only_pending_items():
    catalog = [_item(id=1, status="matched"), _item(id=2, status="pending")]
    assert _flagged(catalog, "pending") == [2]


def test_each_enrichment_state_has_a_flag_of_its_own():
    # caught in the browser: the panel offered a row reading "Unmatched 4"
    # that jumped to #f-flag=review, which spans low_confidence too and so
    # showed 8. A row's count must be what the jump actually yields.
    catalog = [_item(id=1, status="low_confidence"),
               _item(id=2, status="unmatched")]
    assert _flagged(catalog, "low_confidence") == [1]
    assert _flagged(catalog, "unmatched") == [2]
    # the union flag stays: "what needs my attention" is its own question
    assert _flagged(catalog, "review") == [1, 2]


def _stats_payload(sections, total=3):
    return {"total": total, "sections": sections}


def _section(key, label, rows):
    return {"key": key, "label": label,
            "rows": [{"label": l, "count": n} for l, n in rows]}


def _render_stats(payload):
    """The #stats-panel HTML for a given report payload.

    Sets the data and draws it, rather than driving refreshStats: these
    tests are about the rendering, and since #43 the numbers are counted
    in the browser rather than fetched, which is not their subject.
    """
    return eval_js(
        """(() => {
             app.setStatsData(%s);
             app.renderStats();
             return dom.writes["#stats-panel"];
           })()""" % json.dumps(payload))


def test_stats_panel_renders_every_section_with_its_label():
    html = _render_stats(_stats_payload([
        _section("type", "By type", [("E-books", 2)]),
        _section("rating", "Ratings", [("★5", 1)]),
        _section("status", "Reading status", [("Unread", 3)]),
        _section("enrichment", "Enrichment", [("Matched", 2)]),
        _section("gaps", "Gaps", [("No cover", 1)]),
        _section("genre", "Genres", [("Fantasy", 2)]),
    ]))
    assert "<details" in html            # collapsible, like the other panels
    for label in ("By type", "Ratings", "Reading status",
                  "Enrichment", "Gaps", "Genres"):
        assert label in html
    assert "E-books" in html and "Fantasy" in html


def test_stats_rows_carry_their_section_key_and_value():
    html = _render_stats(_stats_payload([
        _section("gaps", "Gaps", [("No cover", 4)]),
    ]))
    # the jump control names the section, so the click handler knows which
    # filter to apply, and the row, so it knows which value
    assert 'data-section="gaps"' in html
    assert 'data-row="No cover"' in html


def test_a_zero_row_is_not_clickable():
    html = _render_stats(_stats_payload([
        _section("gaps", "Gaps", [("No cover", 0)]),
    ]))
    assert "stat-zero" in html
    assert 'data-section="gaps"' not in html


def test_genre_section_shows_fifteen_rows_until_show_all():
    rows = [(f"Genre {i:02d}", 20 - i) for i in range(20)]
    payload = _stats_payload([_section("genre", "Genres", rows)])

    collapsed = _render_stats(payload)
    assert "Genre 14" in collapsed
    assert "Genre 15" not in collapsed
    assert "Show all 20" in collapsed

    expanded = eval_js(
        """(() => {
             app.setStatsData(%s);
             app.setGenresShowAll(true);
             app.renderStats();
             return dom.writes["#stats-panel"];
           })()""" % json.dumps(payload))
    assert "Genre 19" in expanded


def test_edit_tags_toggle_reveals_the_rename_controls():
    payload = _stats_payload([_section("genre", "Genres", [("Fantasy", 2)])])
    plain = _render_stats(payload)
    assert "genre-rename" not in plain      # read-only by default

    editing = eval_js(
        """(() => {
             app.setStatsData(%s);
             app.setTagEditMode(true);
             app.renderStats();
             return dom.writes["#stats-panel"];
           })()""" % json.dumps(payload))
    assert "genre-rename" in editing
    assert "genre-delete" in editing


def _stats_panel(read_only, tag_edit_mode):
    payload = _stats_payload([_section("genre", "Genres", [("Fantasy", 2)])])
    return eval_js(
        """(() => {
             app.setReadOnly(%s);
             app.setStatsData(%s);
             app.setTagEditMode(%s);
             app.renderStats();
             return dom.writes["#stats-panel"];
           })()""" % ("true" if read_only else "false", json.dumps(payload),
                      "true" if tag_edit_mode else "false"))


def test_read_only_stats_have_no_tag_editing_controls():
    # The LAN app has no tag routes, so the controls would only fail.
    # Even with edit mode left on, nothing to rename or delete is drawn.
    for edit_mode in (False, True):
        html = _stats_panel(True, edit_mode)
        assert "Fantasy" in html
        for marker in ("stat-edit-tags", "genre-rename", "genre-delete"):
            assert marker not in html, (edit_mode, marker)
    assert "stat-edit-tags" in _stats_panel(False, False)
    assert "genre-rename" in _stats_panel(False, True)


def test_render_stats_before_any_fetch_draws_nothing():
    # renderStats is re-run on a toggle, so it must cope with no data yet
    # rather than throwing and blanking the panel
    assert eval_js_error("app.renderStats()") is None


_BUNDLE_REPORT = {
    "name": "Humble Book Bundle: The World of Examplia",
    "url": "https://www.humblebundle.com/books/the-world-of-examplia-books",
    "currency": "EUR",
    "tiers": [
        {"price": 21.9, "total": 6, "owned": 2, "new": 4,
         "adds": ["Moonfall Vol. 1-3", "The Hollow Crypt", "Unrelated Book"]},
        {"price": 13.13, "total": 3, "owned": 2, "new": 1,
         "adds": ["Shadow Hound Vol. 1-6"]},
        {"price": 5.47, "total": 1, "owned": 1, "new": 0, "adds": []},
    ],
    "overlaps": [
        {"offered": "Shadow Hound Vol. 1-6", "item_id": 2,
         "item_name": "Shadow Hound Vol 1", "score": 0.92},
    ],
}


def _render_bundle(report):
    """The #bundle-panel HTML for a given /api/bundle-preview body."""
    return eval_js(
        """(async () => {
             app.setFetch(() => Promise.resolve(
               {ok: true, json: () => Promise.resolve(%s)}));
             await app.previewBundle("https://www.humblebundle.com/books/x");
             return dom.writes["#bundle-panel"];
           })()""" % json.dumps(report))


def test_bundle_panel_renders_a_row_per_tier_highest_first():
    html = _render_bundle(_BUNDLE_REPORT)
    assert html.index("21.90") < html.index("13.13") < html.index("5.47")
    assert "Humble Book Bundle: The World of Examplia" in html


def test_bundle_panel_shows_owned_and_new_counts():
    html = _render_bundle(_BUNDLE_REPORT)
    assert ">2<" in html and ">4<" in html


def test_bundle_panel_never_shows_a_price_per_new_item():
    html = _render_bundle(_BUNDLE_REPORT)
    assert "/new" not in html and "per item" not in html


def test_bundle_panel_links_each_overlap_to_the_owned_row():
    # The one thing the CLI cannot offer: "you may own part of this"
    # becomes one click to WHICH part.
    html = _render_bundle(_BUNDLE_REPORT)
    assert 'data-item="2"' in html
    assert "Shadow Hound Vol 1" in html
    assert "Shadow Hound Vol. 1-6" in html


def test_bundle_panel_omits_the_overlap_block_when_there_is_none():
    report = dict(_BUNDLE_REPORT, overlaps=[])
    assert "Possibly already owned" not in _render_bundle(report)


_KEYED_REPORT = {
    "name": "Humble Game Bundle: Story Sampler",
    "url": "https://www.humblebundle.com/games/story-sampler",
    "currency": "EUR",
    "tiers": [
        {"price": 7.5, "total": 2, "owned": 2, "new": 0, "adds": [],
         "keyed": 1, "keyed_items": [
             {"offered": "Cinder Vale", "owned_title": "Cinder Vale",
              "score": 1.0, "key_type": "steam",
              "bundle": "Humble Game Bundle: Key Vault"}]},
    ],
    "overlaps": [],
}


def test_bundle_panel_lists_a_game_owned_only_via_a_key():
    # Counted in `owned` on the row above, named here: the panel must not
    # let an unactivated key pass as a library match.
    html = _render_bundle(_KEYED_REPORT)
    assert "Cinder Vale" in html
    assert "owned via a Humble key (not in any imported library)" in html
    assert "steam" in html
    assert "Humble Game Bundle: Key Vault" in html


def test_bundle_panel_omits_the_keyed_block_when_nothing_is_keyed():
    assert "Humble key" not in _render_bundle(_BUNDLE_REPORT)


def test_bundle_panel_survives_a_tier_with_no_keyed_field():
    # _BUNDLE_REPORT carries no keyed_items at all, which is exactly what a
    # response from an older server looks like. Throwing here would blank
    # the whole panel, the failure mode js_harness exists to catch.
    assert eval_js_error(
        """(async () => {
             app.setFetch(() => Promise.resolve(
               {ok: true, json: () => Promise.resolve(%s)}));
             await app.previewBundle("https://www.humblebundle.com/books/x");
           })()""" % json.dumps(_BUNDLE_REPORT)) is None


def test_bundle_panel_shows_the_error_from_a_rejected_url():
    html = eval_js(
        """(async () => {
             app.setFetch(() => Promise.resolve(
               {ok: false, json: () => Promise.resolve(
                 {error: "not a HumbleBundle URL: example.test"})}));
             await app.previewBundle("https://example.test/x");
             return dom.writes["#bundle-panel"];
           })()""")
    assert "not a HumbleBundle URL" in html


def test_render_bundle_preview_before_any_fetch_draws_nothing():
    # renderBundlePreview re-runs on every toggle, so it has to cope with
    # not having fetched yet rather than throwing and blanking the panel.
    assert eval_js_error("(async () => app.renderBundlePreview())()") is None


def test_bundle_panel_says_item_not_items_for_a_single_item_tier():
    html = _render_bundle(_BUNDLE_REPORT)
    assert "1 item<" in html
    assert "1 items" not in html


def test_bundle_panel_lists_what_each_tier_adds():
    html = _render_bundle(_BUNDLE_REPORT)
    assert "adds 3 new" in html
    assert "Moonfall Vol. 1-3" in html
    assert "The Hollow Crypt" in html
    assert "adds 1 new" in html
    assert "Shadow Hound Vol. 1-6" in html


def test_bundle_panel_emits_no_adds_row_for_a_tier_that_adds_nothing():
    html = _render_bundle(_BUNDLE_REPORT)
    assert html.count('class="bundle-adds"') == 2


def test_bundle_panel_keeps_the_whole_tier_table_above_every_list():
    # The comparison is what must not scroll. Interleaving the lists
    # between the rows put eight titles between the first two prices and
    # pushed the cheapest tier off the panel entirely.
    html = _render_bundle(_BUNDLE_REPORT)
    assert html.index("5.47") < html.index("adds 3 new")
    assert html.index("21.90") < html.index("13.13") < html.index("5.47")


def test_bundle_panel_heads_each_list_with_its_own_price():
    # A list is no longer adjacent to its row, so it has to say which tier
    # it belongs to.
    html = _render_bundle(_BUNDLE_REPORT)
    assert "€21.90 adds 3 new" in html
    assert "€13.13 adds 1 new" in html


def test_bundle_panel_escapes_titles_from_the_bundle_page():
    # Names come off a remote page; the panel is built with innerHTML.
    report = dict(_BUNDLE_REPORT, tiers=[
        {"price": 1.0, "total": 1, "owned": 0, "new": 1,
         "adds": ["<img src=x onerror=alert(1)>"]}])
    html = _render_bundle(report)
    assert "<img src=x" not in html
    assert "&lt;img" in html


def test_harness_loads_every_viewer_script():
    # the harness used to take one path; the split needs it to take the
    # list, in load order, or a moved function becomes an undefined name.
    # Deliberately not a list of filenames: that pins the file layout,
    # which is the very thing VIEWER_JS exists to stop the tests caring
    # about. app.js leading is the one ordering fact worth asserting here
    # -- it holds the helpers every later script calls.
    from tests.js_harness import VIEWER_JS
    assert VIEWER_JS[0].name == "app.js"
    assert all(p.exists() for p in VIEWER_JS)
    assert eval_js("typeof app.esc") == "function"


def test_hash_selects_exactly_one_section():
    shown = eval_js("""(() => {
      app.showSection("maintenance");
      return app.SECTIONS.map((s) => [s.id, !!document.querySelector(
        `#section-${s.id}`).hidden]);
    })()""")
    assert shown == [["library", True], ["maintenance", False],
                     ["keys", True], ["bundles", True], ["tasks", True]]


def test_unknown_hash_falls_back_to_library():
    # a stale bookmark, or a hand-typed hash, must not leave a blank page
    hidden = eval_js("""(() => {
      app.showSection("nonsense");
      return document.querySelector("#section-library").hidden;
    })()""")
    assert hidden is False


def test_current_section_reads_the_hash_and_rejects_junk():
    assert eval_js('(() => { location.hash = "#/bundles";'
                   ' return app.currentSection(); })()') == "bundles"
    assert eval_js('(() => { location.hash = "#/nope";'
                   ' return app.currentSection(); })()') == "library"
    assert eval_js('(() => { location.hash = "";'
                   ' return app.currentSection(); })()') == "library"


def test_badge_shows_a_count_and_vanishes_at_zero():
    # The harness's textContent getter always returns "", so the write is
    # asserted through dom.writes rather than read back off the element.
    written = eval_js("""(() => {
      dom.reset();
      app.setPending({maintenance: 12});
      app.renderBadges();
      const shown = dom.writes["#tab-maintenance .badge-count:text"];
      app.setPending({maintenance: 0});
      app.renderBadges();
      return [shown, dom.writes["#tab-maintenance .badge-count:text"]];
    })()""")
    assert written == ["12", ""]


def test_an_optional_backlog_never_badges_the_library_tab():
    # Unrated items never reach zero, and a badge that is always lit is
    # one the eye stops reading -- which would cost the Maintenance badge
    # beside it its meaning too.
    written = eval_js("""(() => {
      dom.reset();
      app.setPending({library: 900, maintenance: 3});
      app.renderBadges();
      return [dom.writes["#tab-library .badge-count:text"],
              dom.writes["#tab-maintenance .badge-count:text"]];
    })()""")
    assert written == ["", "3"]


def test_sidebar_collapse_persists():
    stored = eval_js("""(() => {
      app.toggleSidebar();
      return [globalThis.localStorage.getItem("hc-sidebar"),
              app.sidebarCollapsed()];
    })()""")
    assert stored == ["1", True]


# A phone-width screen, as matchMedia reports it: every query the viewer
# asks about (the 900 px sidebar and the 600 px cards) matches.
_PHONE = "globalThis.matchMedia = () => ({matches: true, addEventListener() {}});"


def test_on_a_phone_the_filters_button_opens_the_filters():
    # Below 900 px style.css hides the filters unless #library-layout is
    # .expanded, and the button used to toggle only .collapsed -- so on a
    # phone every click left them hidden while aria-expanded said "true".
    result = eval_js("""(() => {
      %s
      const layout = document.querySelector("#library-layout");
      const btn = document.querySelector("#sidebar-toggle");
      const state = () => [layout.classList.contains("expanded"),
                           btn.getAttribute("aria-expanded")];
      app.applySidebar();
      const closed = state();
      app.toggleSidebar();
      const opened = state();
      app.toggleSidebar();
      return {closed, opened, reclosed: state(),
              stored: globalThis.localStorage.getItem("hc-sidebar")};
    })()""" % _PHONE)
    assert result["closed"] == [False, "false"]     # starts hidden on a phone
    assert result["opened"] == [True, "true"]
    assert result["reclosed"] == [False, "false"]
    # Opening them on a phone is for this page only; the saved desktop
    # choice is untouched.
    assert result["stored"] is None


def test_a_desktop_collapse_does_not_trap_the_phone_filters():
    # .collapsed hides the filters outright, so a collapse saved on the PC
    # must not be applied on a phone, or the button could never open them.
    result = eval_js("""(() => {
      app.setStored("hc-sidebar", "1");
      %s
      const layout = document.querySelector("#library-layout");
      app.applySidebar();
      const collapsed = layout.classList.contains("collapsed");
      app.toggleSidebar();
      return [collapsed, layout.classList.contains("expanded")];
    })()""" % _PHONE)
    assert result == [False, True]


def test_active_filters_are_summarised_outside_the_sidebar():
    # The summary is what makes collapsing safe, so it must name every
    # kind of filter, not only the chips.
    html = eval_js("""(() => {
      dom.reset();
      for (const f of Object.values(app.chipFilters)) { f.chips = []; f.text = ""; }
      app.setItems([]);
      app.chipFilters.genre.chips = ["Fantasy"];
      app.chipFilters.user_comment.text = "gift";
      app.setStatusFilter(["reading"]);
      app.setFlag("nocover");
      app.render();
      return dom.writes["#filter-chips"];
    })()""")
    assert "genre: Fantasy" in html
    assert 'user_comment: &quot;gift&quot;' in html
    assert "Status: Reading" in html
    assert "Flag:" in html


def test_active_filter_remove_buttons_avoid_the_tag_x_class():
    # tag-x is tested after chip-x in the click chain; an element with
    # tag-x but no chip-x splices the row-edit buffer instead of clearing
    # a filter. The summary's buttons must not carry it.
    html = eval_js("""(() => {
      dom.reset();
      for (const f of Object.values(app.chipFilters)) { f.chips = []; f.text = ""; }
      app.setItems([]);
      app.chipFilters.genre.chips = ["Fantasy"];
      app.render();
      return dom.writes["#filter-chips"];
    })()""")
    assert "active-x" in html
    assert "tag-x" not in html


_KEY_PAYLOAD = """{
  total: 5, reported: 4, expiring: 1, stale_hides: 0, missing_keys: [],
  counts: {matched: 1, unredeemed: 2, uncertain: 1, uncheckable: 1},
  libraries: {steam: {count: 2, imported_at: "2026-07-25T00:00:00"}},
  rows: [
    {product: "Amber Hollow", machine_name: "amberhollow_ex", gamekey: "kv789",
     store: "steam", key_type_label: "Steam",
     bundle: "Humble Game Bundle: Expiring Keys",
     bundle_url: "https://example.invalid/kv789",
     purchased_at: "2024-01-02T00:00:00", expires: "2099-08-11T00:00:00+00:00",
     expired: false, days_left: 12, revealed: true, state: "unredeemed",
     hidden_at: null, near_match: null},
    {product: "Starfall Rally Turbo", machine_name: "srt_ex", gamekey: "kv789",
     store: "steam", key_type_label: "Steam",
     bundle: "Humble Game Bundle: Key Vault",
     bundle_url: "https://example.invalid/kv789", purchased_at: null,
     expires: null, expired: false, days_left: null, revealed: false,
     state: "uncertain", hidden_at: null,
     near_match: {owned_title: "Starfall Rally", score: 0.86}},
    {product: "Verdant Reach", machine_name: "verdantreach_ex", gamekey: "kv789",
     store: "uplay", key_type_label: "Uplay",
     bundle: "Humble Game Bundle: Key Vault", bundle_url: null,
     purchased_at: null,
     expires: null, expired: false, days_left: null, revealed: false,
     state: "uncheckable", hidden_at: null, near_match: null},
    {product: "Cinder Vale", machine_name: "cindervale_ex", gamekey: "kv789",
     store: "steam", key_type_label: "Steam",
     bundle: "Humble Game Bundle: Key Vault",
     bundle_url: "https://example.invalid/kv789", purchased_at: null,
     expires: null, expired: false, days_left: null, revealed: true,
     state: "unredeemed", hidden_at: "2026-07-31T00:00:00+00:00",
     near_match: null}
  ]
}"""


def _with_keys(expression):
    """Run `expression` after loadKeys() has consumed the payload above."""
    # The payload is parenthesised: `async () => {...}` reads the object
    # literal as a function body and yields undefined, not a syntax error
    # you would notice from the assertion.
    return eval_js("""(async () => {
      app.setFetch(async () => ({json: async () => (%s)}));
      await app.loadKeys();
      return (%s);
    })()""" % (_KEY_PAYLOAD, expression))


def test_the_keys_panel_lists_the_reported_rows():
    html = _with_keys('(app.renderKeys(), dom.writes["#keys-panel"])')
    assert "Amber Hollow" in html
    assert "Humble Game Bundle: Expiring Keys" in html


def test_an_uncertain_row_shows_what_it_nearly_matched():
    html = _with_keys('(app.renderKeys(), dom.writes["#keys-panel"])')
    assert "Starfall Rally" in html


def test_uncheckable_rows_are_hidden_by_default():
    # The default view is the falsifiable one: a store with no importer
    # cannot be checked, so its keys are not evidence of anything.
    shown = _with_keys('app.shownKeys().map((r) => r.product)')
    assert shown == ["Amber Hollow", "Starfall Rally Turbo"]


def test_a_state_chip_toggles_its_rows():
    shown = _with_keys("""(() => {
      app.setKeyStates(["uncheckable"]);
      return app.shownKeys().map((r) => r.product);
    })()""")
    assert shown == ["Verdant Reach"]


def test_the_keys_badge_counts_expiring_rows_not_unredeemed_ones():
    # Hundreds of unredeemed keys would light the tab permanently, which is
    # the policy shell.js already settled against for Library. Expiring
    # keys are a queue; unredeemed ones are a standing fact.
    written = _with_keys("""(() => {
      dom.reset();
      app.setPending({keys: app.keysExpiring()});
      app.renderBadges();
      return dom.writes["#tab-keys .badge-count:text"];
    })()""")
    assert written == "1"


def test_the_keys_section_markup_exists():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert '<div id="keys-panel"></div>' in html
    assert '<script src="/static/keys.js"></script>' in html


def test_the_bundle_column_links_to_the_bundle():
    # Same markup as the Library table's bundle tags, so a bundle name
    # behaves the same wherever it appears.
    html = _with_keys('(app.renderKeys(), dom.writes["#keys-panel"])')
    assert ('<a class="tag tag-link" href="https://example.invalid/kv789"'
            in html)
    assert 'rel="noopener"' in html


def test_a_bundle_with_no_url_renders_as_plain_text():
    # A row whose bundle carries no url must still show its name rather
    # than an <a> pointing at nothing.
    html = _with_keys("""(() => {
      app.setKeyStates(["uncheckable"]);
      app.renderKeys();
      return dom.writes["#keys-panel"];
    })()""")
    assert "Humble Game Bundle: Key Vault" in html
    assert 'href="null"' not in html


def test_the_key_table_gets_its_own_scrollport():
    # A sticky header needs a scroller of its own to stick within, and 722
    # rows must scroll inside the section rather than growing the page.
    html = _with_keys('(app.renderKeys(), dom.writes["#keys-panel"])')
    assert '<div id="key-table-wrap">' in html


def test_a_hidden_row_is_not_shown_by_default():
    # Being off by default is the entire point of hiding.
    shown = _with_keys('app.shownKeys().map((r) => r.product)')
    assert shown == ["Amber Hollow", "Starfall Rally Turbo"]


def test_the_hidden_chip_shows_the_hidden_rows():
    shown = _with_keys("""(() => {
      app.setKeyStates(["hidden"]);
      return app.shownKeys().map((r) => r.product);
    })()""")
    assert shown == ["Cinder Vale"]


def test_a_hidden_row_keeps_its_underlying_state_in_the_table():
    # Only chip membership changes. Nothing about WHY the row was reported
    # is lost from the display -- the State column still says it.
    html = _with_keys("""(() => {
      app.setKeyStates(["hidden"]);
      app.renderKeys();
      return dom.writes["#keys-panel"];
    })()""")
    assert "Cinder Vale" in html
    assert "Not in a library" in html


def test_every_chip_count_equals_the_rows_it_delivers():
    # The statistics panel shipped a row reading "Unmatched 4" that jumped
    # to 8 rows. Counting by displayState makes the four chips partition
    # the reported rows, so this holds by construction rather than by
    # anyone remembering the rule.
    pairs = _with_keys("""(() => {
      const counts = app.keyChipCounts();
      const out = {};
      for (const s of Object.keys(counts)) {
        app.setKeyStates([s]);
        out[s] = [counts[s], app.shownKeys().length];
      }
      return out;
    })()""")
    assert pairs, "no chips counted"
    for state, (promised, delivered) in pairs.items():
        assert promised == delivered, state


def test_the_chip_counts_partition_every_reported_row():
    total = _with_keys("""(() => {
      const counts = app.keyChipCounts();
      app.setKeyStates(app.KEY_STATES.map((s) => s.state));
      return [Object.values(counts).reduce((a, b) => a + b, 0),
              app.shownKeys().length];
    })()""")
    assert total[0] == total[1] == 4


def test_the_keys_badge_ignores_hidden_rows():
    # A hide that silences the row but leaves the badge lit has not
    # stopped the row reappearing.
    written = _with_keys("""(() => {
      dom.reset();
      app.setPending({keys: app.keysExpiring()});
      app.renderBadges();
      return dom.writes["#tab-keys .badge-count:text"];
    })()""")
    assert written == "1"


def test_the_table_offers_hide_and_unhide():
    html = _with_keys("""(() => {
      app.setKeyStates(["unredeemed", "uncertain", "uncheckable", "hidden"]);
      app.renderKeys();
      return dom.writes["#keys-panel"];
    })()""")
    assert "key-hide" in html
    assert ">hide</button>" in html
    assert ">unhide</button>" in html
    assert "2026-07-31" in html


# A bulk write is followed by load(), which drives every panel loader.
# Answering them all matters: loadDupes() reading the wrong shape leaves
# dupeGroups undefined, and load()'s badge arithmetic afterwards is NOT
# inside its try/catch, so the whole call throws somewhere unrelated to
# what the test is asking about.
_STUB_FETCH = """
             app.setFetch((url, opts) => {
               if (url === "/api/user-tags/bulk") {
                 posted = JSON.parse(opts.body);
                 return Promise.resolve(
                   {ok: true, json: () => Promise.resolve({ids: %s})});
               }
               return Promise.resolve({ok: true, json: () => Promise.resolve(
                 url === "/api/items"      ? {items: []} :
                 url === "/api/review"     ? {items: []} :
                 url === "/api/duplicates" ? {groups: []} :
                 url === "/api/stats"      ? {total: 0, sections: []} : {})});
             });
"""


def _run_bulk(action, changed_ids, tag="lent out", n_items=2):
    """Drive runBulk to completion and report the state it leaves.

    Two calls because armOrFire arms on the first click and fires on the
    second; the fired promise is what makes the second call awaitable.
    """
    catalog = json.dumps([_item(id=i, name=f"Item {i}")
                          for i in range(1, n_items + 1)])
    return eval_js(
        """(async () => {
             let posted = null;
             app.setItems(%s);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.setLastTagOp(null);
             document.querySelector("#bulk-tag").value = %s;
             %s
             const btn = document.querySelector("#bulk-add");
             await app.runBulk(btn, %s);
             await app.runBulk(btn, %s);
             return app.getLastTagOp();
           })()""" % (catalog, json.dumps(tag),
                      _STUB_FETCH % json.dumps(changed_ids),
                      json.dumps(action), json.dumps(action)))


def test_a_bulk_add_leaves_an_undo_that_removes():
    # the slot stores the INVERSE verb, ready to post
    op = _run_bulk("add", [1, 2])
    assert op == {"ids": [1, 2], "tag": "lent out", "action": "remove"}


def test_a_bulk_remove_leaves_an_undo_that_adds():
    op = _run_bulk("remove", [1])
    assert op == {"ids": [1], "tag": "lent out", "action": "add"}


def test_an_operation_that_changed_nothing_leaves_no_undo():
    # every row already had the tag: there is nothing to offer to undo,
    # and the route rejects an empty id list anyway
    assert _run_bulk("add", []) is None


def test_a_later_operation_replaces_the_undo():
    op = eval_js(
        """(async () => {
             let posted = null;
             app.setLastTagOp({ids: [9], tag: "to reread", action: "add"});
             app.setItems([%s]);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             document.querySelector("#bulk-tag").value = "lent out";
             %s
             const btn = document.querySelector("#bulk-add");
             await app.runBulk(btn, "add");
             await app.runBulk(btn, "add");
             return app.getLastTagOp();
           })()""" % (json.dumps(_item(id=1, name="Item 1")),
                      _STUB_FETCH % "[1]"))
    assert op == {"ids": [1], "tag": "lent out", "action": "remove"}


def test_undo_posts_the_inverse_and_clears_the_slot():
    sent = eval_js(
        """(async () => {
             let posted = null;
             app.setItems([]);
             app.setLastTagOp({ids: [1, 2], tag: "lent out", action: "add"});
             %s
             await app.undoBulk();
             return {posted, after: app.getLastTagOp()};
           })()""" % (_STUB_FETCH % "[1, 2]"))
    assert sent["posted"] == {"ids": [1, 2], "tag": "lent out", "action": "add"}
    # single level: no redo, and no second undo of the same operation
    assert sent["after"] is None


def test_the_undo_button_names_the_tag_and_the_count():
    labels = eval_js(
        """(() => {
             app.setItems([]);
             const out = {};
             app.setLastTagOp({ids: [1, 2], tag: "lent out", action: "add"});
             app.renderBulkBar();
             out.afterRemove = dom.writes["#bulk-undo:text"];
             app.setLastTagOp({ids: [1], tag: "to reread", action: "remove"});
             app.renderBulkBar();
             out.afterAdd = dom.writes["#bulk-undo:text"];
             out.hiddenWithSlot = document.querySelector("#bulk-undo").hidden;
             app.setLastTagOp(null);
             app.renderBulkBar();
             out.hiddenWithoutSlot = document.querySelector("#bulk-undo").hidden;
             return out;
           })()""")
    assert labels["afterRemove"] == 'Undo: restore "lent out" to 2 items'
    assert labels["afterAdd"] == 'Undo: remove "to reread" from 1 items'
    assert labels["hiddenWithSlot"] is False
    assert labels["hiddenWithoutSlot"] is True


def test_the_result_message_survives_the_button_redraw():
    # renderBulkBar() writes #bulk-note unconditionally, so calling it
    # after the result message wipes it -- the note read "Narrow the view
    # to remove." straight after a successful add. Invisible to the DOM
    # stub until something asserted on the ordering; caught in a browser.
    note = eval_js(
        """(async () => {
             let posted = null;
             app.setItems([%s]);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             app.setLastTagOp(null);
             document.querySelector("#bulk-tag").value = "lent out";
             %s
             const btn = document.querySelector("#bulk-add");
             await app.runBulk(btn, "add");
             await app.runBulk(btn, "add");
             return dom.writes["#bulk-note:text"];
           })()""" % (json.dumps(_item(id=1, name="Item 1")),
                      _STUB_FETCH % "[1]"))
    assert note == "Added to 1 of 1 items."


def test_the_undo_result_message_survives_the_button_redraw():
    note = eval_js(
        """(async () => {
             let posted = null;
             app.setItems([]);
             app.setLastTagOp({ids: [1, 2], tag: "lent out", action: "add"});
             %s
             await app.undoBulk();
             return dom.writes["#bulk-note:text"];
           })()""" % (_STUB_FETCH % "[1, 2]"))
    assert note == 'Restored "lent out" on 2 of 2 items.'


def test_undo_is_offered_while_remove_is_gated_off():
    # The gate exists so "remove from all N" is never one click. Undo acts
    # on a recorded id list, not on the current view, so it is available
    # precisely when Remove is not -- which is the whole point after an
    # unfiltered bulk add.
    state = eval_js(
        """(() => {
             app.setItems(%s);
             for (const f of Object.values(app.chipFilters)) {
               f.chips = []; f.text = "";
             }
             document.querySelector("#bulk-tag").value = "lent out";
             app.setLastTagOp({ids: [1], tag: "lent out", action: "remove"});
             app.renderBulkBar();
             return {
               removeDisabled: document.querySelector("#bulk-remove").disabled,
               undoHidden: document.querySelector("#bulk-undo").hidden,
               filtered: app.shownRows().filtered,
             };
           })()""" % json.dumps([_item(id=1, name="Item 1")]))
    assert state["filtered"] is False
    assert state["removeDisabled"] is True
    assert state["undoHidden"] is False


_SERIES_REPORT = dict(_BUNDLE_REPORT, overlaps=[], series=[
    {"offered": "Shadow Hound Vol. 1-6", "series_name": "Shadow Hound",
     "kind": "collection", "offered_volume": None, "span": [1, 6],
     "owned": [1], "owned_display": "Vol. 1", "already_owned": False},
])


def test_bundle_panel_renders_a_series_section():
    html = _render_bundle(_SERIES_REPORT)
    assert "Series you already hold (1)" in html
    assert "you own 1 of 6" in html
    assert 'data-series="Shadow Hound"' in html


def test_bundle_panel_omits_the_series_block_when_there_is_none():
    assert "Series you already hold" not in _render_bundle(
        dict(_BUNDLE_REPORT, series=[]))


def test_bundle_panel_survives_a_payload_carrying_no_series_field():
    # The `|| []` guard, same as keyed_items: an older server sends no
    # series key at all, and a renderer that throws blanks the page.
    assert "The World of Examplia" in _render_bundle(_BUNDLE_REPORT)


def test_bundle_panel_shouts_a_re_buy():
    html = _render_bundle(dict(_BUNDLE_REPORT, overlaps=[], series=[
        {"offered": "Shadow Hound Vol. 1", "series_name": "Shadow Hound",
         "kind": "volume", "offered_volume": 1, "span": None,
         "owned": [1], "owned_display": "Vol. 1", "already_owned": True}]))
    assert "ALREADY OWNED" in html


def test_a_collection_with_no_span_states_no_denominator_in_the_panel():
    html = _render_bundle(dict(_BUNDLE_REPORT, overlaps=[], series=[
        {"offered": "Shadow Hound Omnibus", "series_name": "Shadow Hound",
         "kind": "collection", "offered_volume": None, "span": None,
         "owned": [1, 2], "owned_display": "Vol. 1-2", "already_owned": False}]))
    assert "you own 2 volumes (Vol. 1-2)" in html
    assert " of " not in html.split("Series you already hold")[1]


# --- The Humble Choice panel --------------------------------------------

_CHOICE_REPORT = {
    "name": "Humble Choice: January 2031", "price": 11.99, "currency": "EUR",
    "total": 4, "owned": 2, "possible": 1, "new": 1,
    "owned_items": ["Cinder Vale", "Neon Drifter"],
    "new_items": ["Lantern & Lockpick"],
    "possible_items": [{"offered": "Starfall Rally Turbo",
                        "owned_title": "Starfall Rally", "score": 0.86}],
    "keyed": 1,
    "keyed_items": [{"offered": "Cinder Vale", "owned_title": "Cinder Vale",
                     "score": 1.0, "key_type": "steam",
                     "bundle": "Humble Game Bundle: Key Vault"}],
    "extras": ["Sample Ambience Pack"], "claimed": False,
    "libraries": {"steam": {"count": 3, "imported_at": "2026-08-01T10:00:00",
                            "source": "test", "source_timestamp": None}},
    "unimported_stores": ["gog"],
}


def _render_choice(report):
    return eval_js(
        """(async () => {
             app.setFetch(() => Promise.resolve(
               {ok: true, json: () => Promise.resolve(%s)}));
             await app.previewChoice();
             return dom.writes["#choice-panel"];
           })()""" % json.dumps(report))


def test_choice_panel_shows_the_month_and_the_three_counts():
    html = _render_choice(_CHOICE_REPORT)
    assert "Humble Choice: January 2031" in html
    assert "owned <b>2</b>" in html
    assert "new <b>1</b>" in html


def test_choice_panel_always_warns_that_matching_is_approximate():
    # A coloured count in a browser reads as more authoritative than the
    # same number in a terminal, so the caveat matters more here.
    assert "APPROXIMATE" in _render_choice(_CHOICE_REPORT)


def test_choice_panel_names_the_key_a_count_is_trusting():
    html = _render_choice(_CHOICE_REPORT)
    assert "owned via a Humble key" in html
    assert "Humble Game Bundle: Key Vault" in html


def test_choice_panel_labels_a_possible_as_counted_as_neither():
    html = _render_choice(_CHOICE_REPORT)
    assert "counted as neither owned nor new" in html
    assert "Starfall Rally Turbo" in html


def test_choice_panel_warns_about_a_store_with_no_import():
    assert "never been imported" in _render_choice(_CHOICE_REPORT)


def test_choice_panel_omits_empty_sections():
    report = dict(_CHOICE_REPORT, keyed=0, keyed_items=[], possible=0,
                  possible_items=[], extras=[], unimported_stores=[])
    html = _render_choice(report)
    assert "owned via" not in html
    assert "counted as neither" not in html
    assert "never been imported" not in html


def test_choice_panel_shows_the_error_from_a_stale_session():
    html = eval_js(
        """(async () => {
             app.setFetch(() => Promise.resolve(
               {ok: false, json: () => Promise.resolve(
                 {error: "Humble session expired -- run login, then try again."})}));
             await app.previewChoice();
             return dom.writes["#choice-panel"];
           })()""")
    assert "session expired" in html


def test_render_choice_preview_before_any_fetch_draws_nothing():
    assert eval_js_error("(async () => app.renderChoicePreview())()") is None


def test_task_cards_cover_every_command_in_both_whitelists():
    from humble_catalog import handoff, jobs
    cards = eval_js("app.TASK_CARDS")
    in_page = {c["command"] for c in cards if not c.get("handoff")}
    handed = {c["command"] for c in cards if c.get("handoff")}
    # Each card posts to the endpoint whose whitelist owns its command. A
    # card on the wrong side would answer 400, which is a dead button.
    assert in_page == set(jobs.COMMANDS)
    assert handed == set(handoff.COMMANDS)


def test_tasks_gets_no_badge_even_with_a_job_running():
    # A badge means a queue you can empty, never an optional backlog, and
    # "you could run a harvest" is the definition of an optional backlog.
    assert eval_js("(app.setPending({tasks: 5}), app.badgeCount('tasks'))") == 0


def test_render_tasks_groups_every_card_and_escapes_its_text():
    html = eval_js("(app.renderTasks(), dom.writes['#task-cards'])")
    for card in eval_js("app.TASK_CARDS"):
        assert card["label"] in html or "&" in card["label"]
    # Every group heading a card claims is actually rendered, so a typo in
    # a card's group cannot silently drop it off the page.
    for group in eval_js("app.TASK_CARDS.map((c) => c.group)"):
        assert f"<h3>{group}</h3>" in html
    # The options ride in an attribute, so a quote in the JSON would end
    # the attribute early and put the rest in the markup.
    assert "'{&quot;ignore_quota&quot;:true}'" in html


def test_tasks_is_a_section_the_shell_knows_about():
    assert "tasks" in eval_js("app.SECTIONS.map((s) => s.id)")
    assert eval_js("(location.hash = '#/tasks', app.currentSection())") == "tasks"


def test_job_panel_shows_progress_and_the_log():
    html = eval_js("""renderJobPanel({
      running: {command: "harvest", started_at: "2026-08-04T00:00:00+00:00"},
      progress: [{command: "harvest", phase: "Source", done: 5, total: 9,
                  current: "hardcover"}],
      log: ["harvest  hardcover 5/9"], last: null})""")
    assert "harvest" in html and "5" in html and "9" in html
    assert "hardcover 5/9" in html
    assert "job-cancel" in html          # a long run has to be stoppable


def test_job_panel_reports_a_cancelled_job_as_cancelled_not_failed():
    html = eval_js("""renderJobPanel({
      running: null, progress: [], log: [],
      last: {command: "harvest", state: "cancelled", exit_code: 2,
             finished_at: "2026-08-04T00:01:00+00:00"}})""")
    assert "cancelled" in html.lower()
    assert "fail" not in html.lower()


def test_job_panel_translates_an_expired_session():
    # The one failure the page must turn into an action rather than show
    # raw: the fix is a terminal command, and the page can only say so.
    html = eval_js("""renderJobPanel({
      running: null, progress: [],
      log: ["HumbleBundle session expired -- run "
            + "'python -m humble_catalog login', then try again."],
      last: {command: "extract", state: "failed", exit_code: 1,
             finished_at: "2026-08-04T00:01:00+00:00"}})""")
    assert "session" in html.lower()
    assert "humble_catalog login" in html


def test_job_panel_hides_itself_when_nothing_has_ever_run():
    hidden = eval_js("""(renderJobPanel({running: null, progress: [], log: [],
                                         last: null}),
                         document.querySelector("#job-panel").hidden)""")
    assert hidden is True


def test_job_panel_escapes_the_log():
    # The log is the child's stdout, and it names owned titles verbatim.
    html = eval_js("""renderJobPanel({
      running: null, progress: [],
      log: ["Row 1/2: <script>alert(1)</script>"],
      last: null})""")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_job_panel_survives_a_running_job_with_no_progress_row_yet():
    # run_status is written by the CHILD, so there is a window after the
    # spawn where the job is running and no row exists. Throwing here
    # would blank the panel for the first few seconds of every job.
    assert eval_js_error("""renderJobPanel({
      running: {command: "check", started_at: "t"},
      progress: [], log: [], last: null})""") is None


# --- Read-only mode (the LAN viewer) ------------------------------------

def _render_row(read_only, **overrides):
    item = json.dumps(_item(
        status="matched", edited=True, source_url="https://example.com/b",
        bundles=[{"name": "Bundle One", "url": "https://www.humblebundle.com/downloads?key=k1",
                  "purchased_at": "2020-01-01"}], **overrides))
    return eval_js(
        """(() => { app.setReadOnly(%s); app.setItems([%s]); dom.reset();
                    app.render(); return dom.writes["#catalog tbody"]; })()"""
        % ("true" if read_only else "false", item))


def test_read_only_rows_have_no_editing_controls():
    html = _render_row(True)
    assert "<select" not in html
    # data-n marks the clickable star widget; read-only stars are plain
    # text (class "star-text"), so matching on a class prefix would not do.
    for marker in ('class="edit"', 'class="redo"', 'class="revert"',
                   'class="override"', 'data-n="'):
        assert marker not in html, marker
    assert "★★★★" in html                      # the rating, as text
    assert "downloads?key=k1" in html          # the download link stays
    assert "Unread" in html                    # status as text


def test_the_full_viewer_still_renders_its_controls():
    html = _render_row(False)
    assert "<select" in html and 'class="edit"' in html


def test_read_only_mode_hides_the_write_sections():
    result = eval_js("""(() => {
        app.applyMode(true);
        return ["library", "maintenance", "keys", "bundles", "tasks"]
          .map((id) => document.querySelector("#tab-" + id).hidden);
      })()""")
    assert result == [False, True, False, True, True]


def test_a_bookmark_to_a_hidden_section_lands_on_library():
    assert eval_js("""(() => { app.applyMode(true);
        location.hash = "#/tasks"; return app.currentSection(); })()""") == "library"


def test_read_only_load_does_not_ask_for_write_only_data():
    urls = eval_js("""(async () => {
        const seen = [];
        app.setReadOnly(true);
        app.setFetch((url) => { seen.push(url); return Promise.resolve({
          json: () => Promise.resolve(
            url === "/api/items" ? {items: []} :
            url === "/api/stats" ? {total: 0, sections: []} :
            url === "/api/keys"  ? {rows: []} : {})}); });
        await app.load();
        return seen;
      })()""")
    assert "/api/review" not in urls and "/api/duplicates" not in urls
    assert "/api/jobs" not in urls


def test_polling_starts_only_once_the_mode_is_known():
    # Before boot() has read /api/status, READ_ONLY is still false, so a
    # poll started alongside boot() asked the LAN app for /api/jobs.
    result = eval_js("""(async () => {
        const seen = [], intervals = [];
        globalThis.setInterval = (fn, ms) => { intervals.push(ms); return 1; };
        app.setFetch((url) => { seen.push(url); return Promise.resolve({
          json: () => Promise.resolve(
            url === "/api/status" ? {read_only: true, runs: []} :
            url === "/api/items" ? {items: []} :
            url === "/api/stats" ? {total: 0, sections: []} :
            url === "/api/keys"  ? {rows: []} : {})}); });
        await app.start();
        return {seen, intervals, readOnly: app.getReadOnly()};
      })()""")
    assert result["readOnly"] is True
    assert result["seen"][0] == "/api/status"
    assert "/api/jobs" not in result["seen"]
    assert result["intervals"] == [5000]


def test_read_only_keys_have_no_hide_button():
    # _with_keys (defined earlier in this file) loads the standard key
    # payload; the panel is rendered again once read-only mode is on.
    html = _with_keys(
        '(app.setReadOnly(true), app.renderKeys(), dom.writes["#keys-panel"])')
    assert "Amber Hollow" in html              # the rows still render
    assert "key-hide" not in html


def test_cards_carry_the_title_series_and_download_link():
    item = json.dumps(_item(
        name="The Quiet Harbor: A Novel", series="Harbor Tales", series_number=2,
        my_rating=4, formats=["epub", "pdf"],
        bundles=[{"name": "Bundle One", "url": "https://www.humblebundle.com/downloads?key=k1",
                  "purchased_at": "2020-01-01"}]))
    html = eval_js(f"app.renderCards([{item}])")
    assert html.count("</article>") == 1
    assert "The Quiet Harbor: A Novel" in html
    assert "Harbor Tales #2" in html
    assert 'class="card-link" href="https://www.humblebundle.com/downloads?key=k1"' in html
    assert "★★★★" in html and "epub, pdf" in html


def test_a_card_without_a_cover_draws_no_cover_box():
    # An empty placeholder reserved a blank column on every coverless card;
    # with the cover floated, no cover should mean full-width text.
    html = eval_js(f"app.renderCards([{json.dumps(_item(cover_path=None))}])")
    assert "card-cover" not in html
    with_cover = eval_js(
        f"app.renderCards([{json.dumps(_item(cover_path='covers/1.jpg'))}])")
    assert '<img class="card-cover" src="/covers/1.jpg"' in with_cover


def test_cards_survive_missing_fields():
    # Same tolerance tagBadges and person have: an older server or a partial
    # payload must not blank the page.
    item = json.dumps(_item(bundles=None, authors=None, user_tags=None,
                            formats=None, read_status=None))
    assert eval_js(f"app.renderCards([{item}])").count("</article>") == 1


def test_a_narrow_screen_renders_cards_instead_of_the_table():
    result = eval_js("""(() => {
        globalThis.matchMedia = () => ({matches: true, addEventListener() {}});
        app.setItems([%s]); dom.reset(); app.render();
        return {cards: dom.writes["#card-list"] || "",
                table: dom.writes["#catalog tbody"] || "",
                tableHidden: document.querySelector("#table-wrap").hidden,
                cardsHidden: document.querySelector("#card-list").hidden};
      })()""" % json.dumps(_item()))
    assert "</article>" in result["cards"]
    assert result["table"] == ""
    assert result["tableHidden"] is True and result["cardsHidden"] is False


def test_a_wide_screen_keeps_the_table():
    result = eval_js("""(() => {
        app.setItems([%s]); dom.reset(); app.render();
        return {table: dom.writes["#catalog tbody"] || "",
                cardsHidden: document.querySelector("#card-list").hidden};
      })()""" % json.dumps(_item()))
    assert "<tr>" in result["table"] and result["cardsHidden"] is True


def test_handoff_cards_say_they_use_the_terminal():
    html = eval_js("(app.renderTasks(), dom.writes['#task-cards'])")
    assert html.count("uses the terminal") == 3
    assert 'data-handoff="1"' in html
    assert "<h3>Danger</h3>" in html


def test_reset_sits_alone_in_the_danger_group():
    cards = eval_js("app.TASK_CARDS.filter((c) => c.group === 'Danger')")
    assert [c["command"] for c in cards] == ["reset"]


def test_restore_body_carries_the_chosen_snapshot_and_covers():
    body = eval_js("""(() => {
        document.querySelector("#restore-snapshot").value =
          "catalog-20260101-120000.db";
        document.querySelector("#restore-covers").checked = true;
        return handoffBody("restore", {});
      })()""")
    assert body == {"command": "restore", "options": {"covers": True},
                    "snapshot": "catalog-20260101-120000.db"}


def test_a_plain_handoff_body_has_no_snapshot():
    assert eval_js('handoffBody("reset", {})') == {
        "command": "reset", "options": {}}


def test_start_handoff_shows_the_takeover_and_reconnects():
    result = eval_js("""(async () => {
        const posted = [];
        let reloaded = false;
        location.reload = () => { reloaded = true; };
        let polls = 0;
        app.setFetch((url, init) => {
          if (init && init.method === "POST") {
            posted.push([url, JSON.parse(init.body)]);
            return Promise.resolve({ok: true, status: 200,
              json: () => Promise.resolve({command: "reset", generation: 4})});
          }
          polls += 1;
          // down, still the old server, then back with a new generation
          if (polls === 1) return Promise.reject(new TypeError("refused"));
          const generation = polls === 2 ? 4 : 5;
          return Promise.resolve({ok: true,
            json: () => Promise.resolve({handoff: {generation}})});
        });
        const how = await startHandoff("reset", {}, () => Promise.resolve());
        return {how, posted, polls, reloaded,
                screen: dom.writes["#handoff-screen"],
                hidden: document.querySelector("#handoff-screen").hidden};
      })()""")
    assert result["how"] == "handed"
    assert result["posted"] == [["/api/jobs/handoff",
                                 {"command": "reset", "options": {}}]]
    assert result["polls"] == 3 and result["reloaded"] is True
    assert "RESET" in result["screen"] and result["hidden"] is False


def test_a_refused_handoff_stays_on_the_page():
    result = eval_js("""(async () => {
        app.setFetch(() => Promise.resolve({ok: false, status: 409,
          json: () => Promise.resolve({error: "harvest is running"})}));
        const how = await startHandoff("reset", {}, () => Promise.resolve());
        return {how, msg: dom.writes["#task-message:text"],
                screen: dom.writes["#handoff-screen"] || ""};
      })()""")
    assert result["how"] == "error"
    assert "harvest is running" in result["msg"]
    # A refusal must not tell the user to go and type RESET somewhere.
    assert "RESET" not in result["screen"]


def test_every_handoff_command_has_takeover_text():
    from humble_catalog import handoff
    text = eval_js("app.TAKEOVER_TEXT")
    assert set(text) == set(handoff.COMMANDS)
    assert "RESET" in text["reset"] and "RESTORE" in text["restore"]


def test_takeover_says_the_page_comes_back_by_itself():
    html = eval_js('renderTakeover("login")')
    assert "reconnect" in html.lower()


def test_render_backups_escapes_and_marks_covers():
    html = eval_js("""renderBackups([
        {name: "catalog-20260301-090000.db", size: 2000000,
         modified: "2026-03-01 09:00", covers: true},
        {name: "catalog-<x>.db", size: 1, modified: "m", covers: false}])""")
    assert "catalog-20260301-090000.db" in html and "covers" in html
    assert "<x>" not in html


def test_render_backups_with_none_disables_restore():
    html = eval_js("renderBackups([])")
    assert "No snapshots" in html
    assert eval_js("""(renderBackups([]),
        document.querySelector("#restore-go").disabled)""") is True


def test_the_first_poll_loads_the_snapshot_list_even_with_no_job_history():
    seen = eval_js("""(async () => {
        const seen = [];
        app.setFetch((url) => { seen.push(url); return Promise.resolve({
          json: () => Promise.resolve(url === "/api/backups"
            ? {backups: []}
            : {running: null, progress: [], log: [], last: null})}); });
        await pollJobs();
        await pollJobs();
        return seen;
      })()""")
    # Once on the first poll, not again until a job finishes.
    assert seen.count("/api/backups") == 1


def test_an_expired_session_offers_a_log_in_handoff():
    html = eval_js("""renderJobPanel({
      running: null, progress: [],
      log: ["HumbleBundle session expired -- run "
            + "'python -m humble_catalog login', then try again."],
      last: {command: "extract", state: "failed", exit_code: 1,
             finished_at: "2026-08-04T00:01:00+00:00"}})""")
    assert 'data-command="login"' in html and 'data-handoff="1"' in html


def test_job_panel_reports_the_last_handoff():
    html = eval_js("""renderJobPanel({running: null, progress: [], log: [],
      last: null, handoff: {available: true, generation: 1, pending: null,
        last: {command: "reset", exit_code: 0,
               finished_at: "2026-09-19T00:00:00+00:00"}}})""")
    assert "reset" in html and "terminal" in html.lower()


def test_a_fired_button_gets_its_label_back():
    # Only the unarmed timeout restored the label, so a button that FIRED
    # read "Click again to confirm" for good -- on a refused reset, that is
    # a Danger button inviting a click that has already happened.
    result = eval_js("""(() => {
        const el = {dataset: {}, textContent: "Run", isConnected: true,
                    classList: {add() {}, remove() {}},
                    getAttribute() { return null; }};
        armOrFire(el, () => null);
        const armed = el.textContent;
        armOrFire(el, () => null);
        return [armed, el.textContent, Boolean(el.dataset.armed)];
      })()""")
    assert result == ["Click again to confirm", "Run", False]


def _labelled_button():
    """A stand-in button with an aria-label, as the name-cell glyphs have."""
    return """{dataset: {}, textContent: "↩", isConnected: true,
               classList: {add() {}, remove() {}},
               attrs: {"aria-label": "Revert Book"},
               getAttribute(k) { return this.attrs[k] ?? null; },
               setAttribute(k, v) { this.attrs[k] = v; }}"""


def test_an_armed_glyph_announces_the_confirm_prompt():
    # An aria-label outranks the text, so swapping only textContent left a
    # reader hearing "Revert Book" on a button that now wants a second
    # click. The prompt has to reach the label as well (#50).
    result = eval_js("""(() => {
        const el = %s;
        armOrFire(el, () => null);
        const armed = el.attrs["aria-label"];
        armOrFire(el, () => null);
        return [armed, el.attrs["aria-label"]];
      })()""" % _labelled_button())
    assert result == ["Click again to confirm", "Revert Book"]


def test_an_armed_glyph_gets_its_label_back_on_timeout():
    result = eval_js("""(() => {
        const timers = [];
        const realTimeout = globalThis.setTimeout;
        globalThis.setTimeout = (fn) => timers.push(fn);
        const el = %s;
        armOrFire(el, () => null);
        globalThis.setTimeout = realTimeout;
        timers.forEach(fn => fn());
        return [el.textContent, el.attrs["aria-label"]];
      })()""" % _labelled_button())
    assert result == ["↩", "Revert Book"]


# --- Job log: follow, and hold still when not following (#36) -----------

def test_log_shift_counts_the_lines_that_fell_off_the_top():
    # The page shows the last 200 lines, so old lines drop off as new ones
    # arrive. Holding the view still means knowing how many.
    assert eval_js("logShift(['a','b','c'], ['a','b','c'])") == 0
    assert eval_js("logShift(['a','b'], ['a','b','c'])") == 0      # appended
    assert eval_js("logShift(['a','b','c'], ['c','d'])") == 2      # slid by 2
    assert eval_js("logShift([], ['a'])") == 0
    assert eval_js("logShift(['a','b'], ['x','y'])") == 2          # no overlap

_FAKE_PRE = """
  const pre = {
    lines: [], top: 0, clientHeight: 100, lineHeight: 10,
    get scrollHeight() { return this.lines.length * this.lineHeight; },
    get scrollTop() { return this.top; },
    set scrollTop(v) {
      this.top = Math.max(0, Math.min(v, Math.max(0, this.scrollHeight - this.clientHeight)));
    },
    get textContent() { return this.lines.join("\\n"); },
    set textContent(v) { this.lines = v === "" ? [] : v.split("\\n"); },
  };
"""

def test_following_keeps_the_log_at_the_bottom():
    top = eval_js("""(() => {
      %s
      const lines = Array.from({length: 30}, (_, i) => "line " + i);
      applyLog(pre, lines, {follow: true, prev: []});
      const first = pre.scrollTop;
      applyLog(pre, lines.concat(["line 30"]), {follow: true, prev: lines});
      return [first, pre.scrollTop, pre.scrollHeight - pre.clientHeight];
    })()""" % _FAKE_PRE)
    assert top[0] == 200                 # 30 lines * 10 - 100 viewport
    assert top[1] == top[2] == 210       # still pinned after a new line


def test_not_following_holds_the_same_lines_in_view_as_the_window_slides():
    # Keeping scrollTop alone is not enough: three lines leaving the top
    # shift everything up by their height, and the text slides under you.
    result = eval_js("""(() => {
      %s
      const prev = Array.from({length: 40}, (_, i) => "line " + i);
      applyLog(pre, prev, {follow: true, prev: []});
      pre.scrollTop = 150;               // the user scrolled up to read
      const next = prev.slice(3).concat(["line 40", "line 41", "line 42"]);
      applyLog(pre, next, {follow: false, prev});
      return pre.scrollTop;
    })()""" % _FAKE_PRE)
    assert result == 120                 # 150 - 3 dropped lines * 10


def test_not_following_leaves_the_position_alone_when_only_appending():
    result = eval_js("""(() => {
      %s
      const prev = Array.from({length: 40}, (_, i) => "line " + i);
      applyLog(pre, prev, {follow: true, prev: []});
      pre.scrollTop = 150;
      applyLog(pre, prev.concat(["new"]), {follow: false, prev});
      return pre.scrollTop;
    })()""" % _FAKE_PRE)
    assert result == 150


def test_the_panel_offers_follow_output_ticked():
    html = eval_js("""renderJobPanel({
      running: {command: "enrich", started_at: "t"},
      progress: [{command: "enrich", phase: "Item", done: 1, total: 9,
                  current: "x"}],
      log: ["Item 1/9"], last: null})""")
    assert 'id="job-follow"' in html
    assert "checked" in html            # on by default, every page load
    assert "Follow output" in html


def test_a_poll_during_a_run_updates_the_panel_instead_of_rebuilding_it():
    # The rebuild is what threw away the scroll position, the focused
    # Cancel button and any selected text.
    result = eval_js("""(() => {
      const state = (log, done) => ({
        running: {command: "enrich", started_at: "t"},
        progress: [{command: "enrich", phase: "Item", done, total: 9,
                    current: "item " + done}],
        log, last: null});
      renderJobPanel(state(["Item 1/9"], 1));
      const panel = document.querySelector("#job-panel");
      panel.innerHTML = "SENTINEL";
      renderJobPanel(state(["Item 1/9", "Item 2/9"], 2));
      return [panel.innerHTML, dom.writes["#job-log:text"] || ""];
    })()""")
    assert result[0] == "SENTINEL"           # no rebuild
    assert "Item 2/9" in result[1]           # the log still updated


def test_a_job_finishing_does_rebuild_the_panel():
    # The panel's shape changes then -- the bar and Cancel go, a verdict
    # arrives -- so it must be rebuilt rather than patched.
    result = eval_js("""(() => {
      renderJobPanel({running: {command: "enrich", started_at: "t"},
                      progress: [], log: ["Item 1/9"], last: null});
      const panel = document.querySelector("#job-panel");
      panel.innerHTML = "SENTINEL";
      renderJobPanel({running: null, progress: [], log: ["Item 9/9"],
        last: {command: "enrich", state: "done", exit_code: 0,
               finished_at: "t2"}});
      return panel.innerHTML;
    })()""")
    assert result != "SENTINEL"
    assert "finished" in result


def test_a_table_filtered_to_nothing_says_why_it_is_empty():
    # Searching for something that matches nothing left the header row and
    # several hundred pixels of blank space -- indistinguishable from a
    # failed load, and with nothing on screen naming the filters as the
    # reason.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    html = eval_js(
        f"""(() => {{
              dom.reset();
              app.setItems({items});
              app.setSearch("zzzqqq");
              app.render();
              return dom.writes["#catalog tbody"];
            }})()""")
    assert "No items match" in html


def test_an_empty_catalog_does_not_blame_the_filters():
    # Same blank table, opposite cause: nothing has been fetched yet. The
    # line has to say which of the two it is, or it sends the reader to
    # clear filters that are not set.
    html = eval_js(
        """(() => {
             dom.reset();
             app.setItems([]);
             app.setSearch("");
             app.render();
             return dom.writes["#catalog tbody"];
           })()""")
    assert "No items match" not in html
    assert "Tasks" in html


def test_the_empty_catalog_line_does_not_send_the_lan_viewer_to_tasks():
    # The LAN viewer has no Tasks section at all -- READ_ONLY_SECTIONS is
    # library and keys -- so naming it there is an instruction the reader
    # cannot follow.
    html = eval_js(
        """(() => {
             dom.reset();
             app.setReadOnly(true);
             app.setItems([]);
             app.setSearch("");
             app.render();
             app.setReadOnly(false);
             return dom.writes["#catalog tbody"];
           })()""")
    assert "Tasks" not in html


def test_clear_all_is_offered_only_while_a_filter_is_active():
    # A permanent control with nothing to clear is noise, and the strip it
    # belongs to is itself only there when something is filtering.
    off, on = eval_js(
        """(() => {
             app.setItems([]);
             app.setSearch("");
             app.renderActiveFilters();
             const off = dom.writes["#filter-chips"];
             app.setSearch("quiet");
             app.renderActiveFilters();
             return [off, dom.writes["#filter-chips"]];
           })()""")
    assert "clear-all" not in off
    assert "clear-all" in on
    # "Clear all" alone does not say all WHAT, sitting in a toolbar beside
    # a column picker and an export button
    assert "Clear all filters" in on


def test_clear_all_clears_every_kind_of_filter_at_once():
    # Search, three selects, the status set and both halves of a chip
    # filter. Clearing them one chip at a time was four or more clicks.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors",
                              genre=["Fantasy"])])
    state = eval_js(
        f"""(() => {{
              app.setItems({items});
              app.setSearch("quiet");
              app.setFlag("unrated");
              app.setRating("4");
              app.setStatusFilter(["read"]);
              app.chipFilters.genre.chips = ["Fantasy"];
              app.chipFilters.genre.text = "fan";
              document.querySelector("#f-type").value = "ebook";
              app.clearAllFilters();
              return {{
                search: document.querySelector("#search").value,
                type: document.querySelector("#f-type").value,
                rating: document.querySelector("#f-rating").value,
                flag: document.querySelector("#f-flag").value,
                chips: app.chipFilters.genre.chips,
                text: app.chipFilters.genre.text,
                shown: app.visible().map(i => i.id),
              }};
            }})()""")
    # the item is unread and unrated, so it reappears only if the status
    # set and every select really were emptied
    assert state == {"search": "", "type": "", "rating": "", "flag": "",
                     "chips": [], "text": "", "shown": [1]}


def test_spreadsheet_picker_is_inside_its_import_card():
    html = eval_js("(app.renderTasks(), dom.writes['#task-cards'])")
    # Slice the actual generated card, not the unrelated static Tasks shell.
    start = html.rfind('<div class="task-card">', 0, html.index('Import a spreadsheet'))
    end = html.index('<div class="task-card">', html.index('Import a spreadsheet'))
    card = html[start:end]
    assert html.count('id="sheet-file"') == 1
    assert 'for="sheet-file">Choose spreadsheet' in card
    assert 'id="sheet-file" type="file" accept=".xlsx"' in card
    assert 'aria-describedby="sheet-filename"' in card
    assert 'id="sheet-filename" role="status">No file selected' in card
    assert 'data-command="import_sheets"' in card
    assert 'Choosing a file below starts the import' in card


def test_a_catalog_that_cannot_be_read_says_so_rather_than_going_blank():
    # load() read /api/items outside its own guard, so a server that had
    # stopped left the page on the loading line for ever, with the reason
    # in the console and nothing on screen.
    result = eval_js(
        """(async () => {
             dom.reset();
             app.setItems([]);
             app.setFetch(() => Promise.reject(new Error("connection refused")));
             let threw = null;
             try { await app.load(); } catch (e) { threw = e.message; }
             return {threw, tbody: dom.writes["#catalog tbody"]};
           })()""")
    assert result["threw"] is None
    assert "Could not read the catalog" in result["tbody"]


def test_a_failed_load_does_not_tell_the_reader_to_go_and_fetch_bundles():
    # The empty-catalog line is the wrong advice here: the rows are
    # unknown, not absent.
    tbody = eval_js(
        """(async () => {
             dom.reset();
             app.setItems([]);
             app.setFetch(() => Promise.reject(new Error("connection refused")));
             await app.load();
             return dom.writes["#catalog tbody"];
           })()""")
    assert "No items in the catalog yet" not in tbody


def test_a_later_successful_load_clears_the_failure_line():
    # Otherwise the first failure sticks for the life of the page, and the
    # Tasks tab's own reload would look like it had done nothing.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    tbody = eval_js(
        f"""(async () => {{
              app.setItems([]);
              app.setFetch(() => Promise.reject(new Error("refused")));
              await app.load();
              dom.reset();
              app.setFetch((url) => Promise.resolve({{json: () => Promise.resolve(
                url === "/api/items"      ? {{items: {items}}} :
                url === "/api/review"     ? {{items: []}} :
                url === "/api/duplicates" ? {{groups: []}} :
                url === "/api/stats"      ? {{total: 1, sections: []}} : {{}})}}));
              await app.load();
              return dom.writes["#catalog tbody"];
            }})()""")
    assert "Could not read the catalog" not in tbody
    assert "A Quiet Life in Harbors" in tbody


def test_clearing_every_filter_returns_focus_to_the_search_box():
    # The button deletes itself as it fires -- the strip it lives in is
    # re-rendered from a now-empty filter set -- so focus fell back to
    # <body> and a keyboard user was dropped at the top of the page. With
    # a focus ring now drawn (#38) it reads as focus simply vanishing.
    focused = eval_js(
        """(() => {
             dom.reset();
             app.setItems([]);
             app.setSearch("quiet");
             app.clearAllFilters();
             return dom.focused;
           })()""")
    assert "#search" in focused


def test_an_empty_table_announces_itself():
    # The line is drawn where the rows would be, which a sighted reader
    # sees immediately and a screen-reader user is never told about: the
    # table simply stops having rows. The announcement goes through a live
    # region that is present from first paint, because a region inserted
    # at the same moment as its text is not reliably spoken.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    said = eval_js(
        f"""(() => {{
              dom.reset();
              app.setItems({items});
              app.setSearch("zzzqqq");
              app.render();
              return dom.writes["#table-status:text"];
            }})()""")
    assert "No items match these filters." == said


def test_the_announcement_is_dropped_once_rows_come_back():
    # A live region still holding the old sentence re-announces it on the
    # next unrelated change, so the all-clear has to be written too.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    said = eval_js(
        f"""(() => {{
              dom.reset();
              app.setItems({items});
              app.setSearch("");
              app.render();
              return dom.writes["#table-status:text"];
            }})()""")
    assert said == ""


def _driven(items_json, body):
    """Run `body` against a loaded catalog with a stubbed fetch.

    isNarrow() reads matchMedia, which the sandbox does not have, so a
    test wanting the card or sheet path calls into it by hand. Posts are
    captured rather than sent.
    """
    return eval_js(
        f"""(async () => {{
              dom.reset();
              globalThis.posts = [];
              app.setFetch((url, opts) => {{
                // Writes only. Every write here also refreshes the stats
                // panel, and a plain GET is not what these tests are about.
                if (opts) posts.push({{url, body: JSON.parse(opts.body)}});
                return Promise.resolve({{ok: true, json: () => Promise.resolve({{}})}});
              }});
              app.setItems({items_json});
              {body}
            }})()""")


def test_a_phone_card_is_a_button_that_opens_the_editor():
    # The cards were display-only -- "editing needs the table's width" --
    # so a phone could not set the two fields a phone is actually for.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    html = _driven(items, "return app.renderCards(app.getItems());")
    assert 'role="button"' in html
    assert 'data-open="1"' in html


def test_the_lan_viewers_cards_stay_display_only():
    # serve --lan has no write routes at all -- they are absent, not
    # refused -- so a control that posts must never be drawn there.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    html = eval_js(
        f"""(() => {{
              app.setReadOnly(true);
              app.setItems({items});
              const html = app.renderCards(app.getItems());
              app.setReadOnly(false);
              return html;
            }})()""")
    assert 'role="button"' not in html
    assert "data-open" not in html


def test_the_sheet_offers_every_status_by_its_short_name():
    # "Want to read" wraps the five-button row at 375 px; "Want" does not.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    html = _driven(items, "return app.sheetFor(app.getItems()[0]);")
    for label in ("Want", "Unread", "Reading", "Read", "DNF"):
        assert f">{label}<" in html, label


def test_choosing_a_status_in_the_sheet_posts_it_and_keeps_the_item():
    items = json.dumps([_item(id=1, read_status="unread")])
    out = _driven(items, """
      await app.setSheetStatus(1, "read");
      return {posts, status: app.getItems()[0].read_status};""")
    assert out["posts"] == [{"url": "/api/items/1/read-status",
                             "body": {"status": "read"}}]
    assert out["status"] == "read"


def test_rating_from_the_sheet_posts_the_star_that_was_tapped():
    items = json.dumps([_item(id=1, my_rating=None)])
    out = _driven(items, """
      await app.setSheetRating(1, 4);
      return {posts, rating: app.getItems()[0].my_rating};""")
    assert out["posts"] == [{"url": "/api/items/1/rating", "body": {"rating": 4}}]
    assert out["rating"] == 4


def test_clearing_the_rating_from_the_sheet_posts_null():
    # Re-tapping the current star clears it on the table too, but nothing
    # says so; the sheet has room for a control that does.
    items = json.dumps([_item(id=1, my_rating=4)])
    out = _driven(items, """
      await app.setSheetRating(1, 0);
      return {posts, rating: app.getItems()[0].my_rating};""")
    assert out["posts"] == [{"url": "/api/items/1/rating", "body": {"rating": None}}]
    assert out["rating"] is None


def test_opening_the_sheet_does_not_scroll_the_list():
    # The sheet is parked below the frame until it animates up, so a plain
    # focus() makes the browser scroll to bring the control into view --
    # and what visibly moves is the list behind it.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    calls = _driven(items, "app.openSheet(1); return dom.focusCalls;")
    assert calls, "nothing was focused when the sheet opened"
    assert all(c["preventScroll"] for c in calls), calls


def test_closing_the_sheet_does_not_scroll_the_list_either():
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    calls = _driven(items, """
      app.openSheet(1);
      dom.reset();
      app.closeSheet();
      return dom.focusCalls;""")
    assert calls, "focus was not returned when the sheet closed"
    assert all(c["preventScroll"] for c in calls), calls


def test_the_sheet_reveals_itself_even_when_frames_never_come():
    # Found in the browser: requestAnimationFrame does not fire in a
    # hidden or throttled tab, so a reveal deferred to the next frame
    # never happened -- and the sheet sat parked below the viewport while
    # focused and taking taps. The animation is decoration; being visible
    # is not, so the class goes on synchronously.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    opened = eval_js(
        f"""(() => {{
              // A frame callback that is registered and never called, which
              // is exactly what a backgrounded tab does.
              globalThis.requestAnimationFrame = () => 0;
              app.setItems({items});
              app.openSheet(1);
              return document.querySelector("#edit-sheet")
                       .classList.contains("open");
            }})()""")
    assert opened is True


def test_the_sheet_refuses_to_open_on_the_lan_viewer():
    # Defence in depth rather than a driven test: the cards there carry no
    # opener at all (above). This pins the second half of the LAN viewer's
    # safety story -- the controls are never drawn AND never reachable --
    # so removing the guard cannot pass unnoticed.
    items = json.dumps([_item(id=1, name="A Quiet Life in Harbors")])
    opened = eval_js(
        f"""(() => {{
              app.setReadOnly(true);
              app.setItems({items});
              app.openSheet(1);
              const open = app.getOpenSheetId();
              app.setReadOnly(false);
              return open;
            }})()""")
    assert opened is None


# -- Star titles (#61) -------------------------------------------------
# Clicking the star that matches the current rating clears it, and that
# was the only way to un-rate from the table. Each star now carries a
# title naming the action its own click performs, so the clear appears on
# the control that does it rather than in the source.

def _star_titles(my_rating):
    """The title of each of the five table stars, at `my_rating`."""
    return eval_js(
        '(() => { const html = app.stars({id: 1, my_rating: %s});'
        '  return [...html.matchAll(/title="([^"]*)"/g)].map(m => m[1]);'
        ' })()' % ("null" if my_rating is None else my_rating))


def test_the_star_matching_the_current_rating_is_titled_to_clear():
    assert _star_titles(3)[2] == "Clear rating"


def test_the_other_stars_are_titled_with_the_rating_they_set():
    titles = _star_titles(3)
    assert titles[1] == "Rate 2 stars" and titles[3] == "Rate 4 stars"


def test_an_unrated_row_offers_no_clear():
    assert _star_titles(None) == ["Rate 1 star", "Rate 2 stars",
                                  "Rate 3 stars", "Rate 4 stars",
                                  "Rate 5 stars"]


def test_the_read_only_rating_carries_no_title():
    # The LAN viewer has no click handler, so a title promising a click
    # would lie. It renders plain text and must stay that way.
    html = _render_row(True)
    assert "Clear rating" not in html and "Rate " not in html


# -- Keyboard-operable rating (#39) ------------------------------------
# The stars were <span>s with no tabindex, role or key handler, so the
# most-repeated action in the app was unavailable without a mouse. They
# are now one radiogroup per row: a single tab stop rather than five, so
# Tab still crosses a large table in a usable number of presses, with the
# arrows moving within the group.

def _star_attrs(my_rating, attr):
    """`attr` of each of the five table stars, at `my_rating`."""
    return eval_js(
        '(() => { const html = app.stars({id: 1, my_rating: %s});'
        '  return [...html.matchAll(/<span class="star[^>]*>/g)]'
        '    .map(m => (m[0].match(/ %s="([^"]*)"/) || [])[1] ?? null);'
        ' })()' % ("null" if my_rating is None else my_rating, attr))


def test_the_five_stars_are_wrapped_in_one_radiogroup():
    html = eval_js('app.stars({id: 7, my_rating: 3})')
    assert 'role="radiogroup"' in html and 'data-id="7"' in html


def test_exactly_one_star_is_tabbable():
    # The point of the radiogroup: a row costs one tab stop, not five.
    assert _star_attrs(3, "tabindex").count("0") == 1


def test_the_tab_stop_sits_on_the_current_rating():
    assert _star_attrs(3, "tabindex") == ["-1", "-1", "0", "-1", "-1"]


def test_an_unrated_row_puts_the_tab_stop_on_the_first_star():
    # With nothing checked there is no rating to return to, so the group
    # is entered at the low end and arrowed up from there.
    assert _star_attrs(None, "tabindex") == ["0", "-1", "-1", "-1", "-1"]


def test_only_the_exact_rating_is_checked():
    # The fill is cumulative -- three stars are lit at a rating of three --
    # but selection is not: a reader must hear "3 stars, selected" once,
    # not three separate selected radios.
    assert _star_attrs(3, "aria-checked") == ["false", "false", "true",
                                              "false", "false"]


def test_an_unrated_row_checks_nothing():
    assert _star_attrs(None, "aria-checked") == ["false"] * 5


def test_each_star_is_labelled_with_the_action_its_key_performs():
    # The same wording #61 put in the title, now as the accessible name:
    # a title is not announced reliably, and a radio needs a real label.
    labels = _star_attrs(3, "aria-label")
    assert labels[2] == "Clear rating" and labels[3] == "Rate 4 stars"


def test_the_read_only_rating_is_not_focusable():
    # The LAN viewer has no handlers, so a tab stop would be a promise
    # nothing keeps.
    html = _render_row(True)
    assert "radiogroup" not in html and "tabindex" not in html


# The key mapping is a pure function rather than logic inside the keydown
# listener, because the harness stubs addEventListener to a no-op: a rule
# written inside a listener cannot be tested here at all. It answers with
# the star to focus and the rating to store, or null when the key is not
# the group's to handle -- so the listener knows when to leave the event
# alone rather than swallowing Tab.

def _for_key(key, focused, current):
    return eval_js('app.ratingForKey("%s", %s, %s)'
                   % (key, focused, "null" if current is None else current))


def test_arrowing_right_moves_up_one_star_and_selects_it():
    # Selection follows focus, as it does in any radiogroup: arriving at a
    # star IS choosing it, with no second keypress to confirm.
    assert _for_key("ArrowRight", 2, 2) == {"focus": 3, "rating": 3}


def test_arrowing_left_moves_down_one_star():
    assert _for_key("ArrowLeft", 3, 3) == {"focus": 2, "rating": 2}


def test_up_and_down_mirror_right_and_left():
    assert _for_key("ArrowUp", 2, 2) == _for_key("ArrowRight", 2, 2)
    assert _for_key("ArrowDown", 2, 2) == _for_key("ArrowLeft", 2, 2)


def test_arrowing_past_the_last_star_stays_on_it():
    # Clamped rather than wrapped: wrapping turns one keypress at the top
    # into a five-star mis-rating, and this posts on every move.
    assert _for_key("ArrowRight", 5, 5) == {"focus": 5, "rating": 5}


def test_home_and_end_jump_to_the_ends():
    assert _for_key("Home", 3, 3) == {"focus": 1, "rating": 1}
    assert _for_key("End", 3, 3) == {"focus": 5, "rating": 5}


def test_activating_the_current_rating_clears_it():
    # The keyboard reading of the click that clears, so the "Clear rating"
    # label names something a keyboard user can actually do.
    assert _for_key("Enter", 3, 3) == {"focus": 3, "rating": None}


def test_activating_a_different_star_sets_it():
    assert _for_key(" ", 4, 3) == {"focus": 4, "rating": 4}


def test_a_key_the_group_does_not_own_is_left_alone():
    # Tab must still leave the group, so the listener needs to know the
    # difference between "handled" and "not mine".
    assert _for_key("Tab", 3, 3) is None
    assert _for_key("a", 3, 3) is None


def test_arrowing_down_from_an_unrated_row_rates_it_one_star():
    # Consequence of clamping, and the one place the pattern reads oddly:
    # focus starts on star 1 with nothing selected, so a LEFT arrow raises
    # the rating from none to one. Pinned deliberately -- the alternative
    # was letting it clear, which is not what a radiogroup does. Enter on
    # the current star remains the way to un-rate.
    assert _for_key("ArrowLeft", 1, None) == {"focus": 1, "rating": 1}


# render() rebuilds the table's innerHTML, so the star that had focus is
# destroyed by the very keypress that used it. The mouse never noticed;
# a keyboard user would find the second arrow key going nowhere, because
# focus had fallen back to the body. So the write restores it, the way
# closeSheet() already restores focus to the card it came from.

def _rating_run(items_json, body):
    return _driven(items_json, "dom.reset();\n" + body)


def test_rating_posts_the_new_value_and_updates_the_row():
    items = json.dumps([_item(id=1, my_rating=2)])
    out = _rating_run(items, """
      await app.applyRating(1, 3, 3);
      return {posts, rating: app.getItems()[0].my_rating};""")
    assert out["posts"][0] == {"url": "/api/items/1/rating", "body": {"rating": 3}}
    assert out["rating"] == 3


def test_rating_returns_focus_to_the_star_that_was_used():
    items = json.dumps([_item(id=1, my_rating=2)])
    out = _rating_run(items, """
      await app.applyRating(1, 3, 3);
      return dom.focused;""")
    assert any('.star[data-n="3"]' in sel and '[data-id="1"]' in sel
               for sel in out), out


def test_returning_focus_does_not_scroll_the_table():
    # Same reason the sheet passes preventScroll: the row is already where
    # the user is looking, and a scroll would move the page under them.
    items = json.dumps([_item(id=1, my_rating=2)])
    calls = _rating_run(items, """
      await app.applyRating(1, 3, 3);
      return dom.focusCalls;""")
    assert calls and all(c["preventScroll"] for c in calls), calls


def test_clearing_keeps_focus_on_the_star_that_cleared_it():
    # The star is still there after a clear -- unlit, and now labelled
    # "Rate 3 stars" -- so focus has somewhere to land.
    items = json.dumps([_item(id=1, my_rating=3)])
    out = _rating_run(items, """
      await app.applyRating(1, 3, null);
      return {posts, rating: app.getItems()[0].my_rating, focused: dom.focused};""")
    assert out["posts"][0]["body"] == {"rating": None}
    assert out["rating"] is None
    assert any('.star[data-n="3"]' in sel for sel in out["focused"])


# -- Sort headers announce the sort (#39) ------------------------------
# The active sort was conveyed by the .sort-ind glyph alone, which is
# invisible to a reader. aria-sort is the attribute made for it. As with
# the key mapping, the value is a pure function: renderSortIndicators()
# walks querySelectorAll, which the harness returns empty, so a rule
# written inside it could not be tested.

def _aria_sort(column, key="name", asc=True, search=""):
    return eval_js(
        '(() => { app.setSort("%s", %s); app.setSearch("%s");'
        '  app.setRelevance(%s); return app.ariaSortFor("%s"); })()'
        % (key, "true" if asc else "false", search,
           "true" if search else "false", column))


def test_the_sorted_column_announces_its_direction():
    assert _aria_sort("name", key="name", asc=True) == "ascending"
    assert _aria_sort("name", key="name", asc=False) == "descending"


def test_the_other_columns_announce_no_sort():
    # "none" rather than omitting the attribute: on a table that IS
    # sorted, silence on the other headers reads as "not sortable".
    assert _aria_sort("bundle", key="name", asc=True) == "none"


def test_relevance_ordering_claims_no_column():
    # The same reason the arrow is already suppressed here: the table is
    # ordered by relevance, so naming a sorted column would be a lie.
    assert _aria_sort("name", key="name", asc=True,
                      search="harbors") == "none"


# Arrow keys repeat when held, which is how a rating gets moved several
# stars at once. A write that reaches the model only after the response
# leaves the focused star reporting a stale rating for the length of a
# round trip, and the repeat recomputes from it -- pressing Right twice
# quickly moved one star, not two. So the model and the focus move first
# and the request follows. post() never inspects the response, so nothing
# was being guarded by the old order.

def _in_flight(items_json, body):
    """Run `body` with a fetch that hangs until `release()` is called."""
    return _driven(items_json, """
      let release;
      app.setFetch(() => new Promise(r => {
        release = () => r({ok: true, json: () => Promise.resolve({})});
      }));
    """ + body)


def test_the_rating_lands_before_the_request_is_answered():
    items = json.dumps([_item(id=1, my_rating=2)])
    out = _in_flight(items, """
      const p = app.applyRating(1, 3, 3);
      const duringFlight = app.getItems()[0].my_rating;
      release(); await p;
      return {duringFlight, settled: app.getItems()[0].my_rating};""")
    assert out["duringFlight"] == 3, "the row still reported the old rating"
    assert out["settled"] == 3


def test_focus_returns_before_the_request_is_answered():
    # The repeat arrives during the flight, so the star has to be back
    # under focus by then or the keypress lands on nothing.
    items = json.dumps([_item(id=1, my_rating=2)])
    out = _in_flight(items, """
      dom.reset();
      const p = app.applyRating(1, 3, 3);
      const duringFlight = [...dom.focused];
      release(); await p;
      return duringFlight;""")
    assert any('.star[data-n="3"]' in sel for sel in out), out


def test_a_write_that_never_arrives_puts_the_rating_back():
    # Optimism is only honest if it is undone when the write fails: the
    # row must not keep showing a rating the server never took.
    items = json.dumps([_item(id=1, my_rating=2)])
    out = _driven(items, """
      app.setFetch(() => Promise.reject(new Error("offline")));
      await app.applyRating(1, 4, 4);
      return app.getItems()[0].my_rating;""")
    assert out == 2


def test_empty_keys_explains_setup_without_read_only_task_links():
    for read_only in (False, True):
        html = eval_js("""(async () => {
          app.setReadOnly(%s);
          app.setFetch(async () => ({json: async () =>
            ({total: 0, rows: [], libraries: {}})}));
          await app.loadKeys();
          return dom.writes["#keys-panel"];
        })()""" % json.dumps(read_only))
        assert "No Humble keys have been fetched yet" in html
        assert 'id="key-table-wrap" hidden' in html
        assert ('href="#/tasks"' in html) is not read_only
        assert ("catalog owner" in html) is read_only


def test_keys_filtered_empty_does_not_claim_there_are_no_keys():
    html = _with_keys('''(app.setKeyStates([]), app.renderKeys(),
                         dom.writes["#keys-panel"])''')
    assert "No keys match these filters" in html
    assert "No Humble keys have been fetched" not in html
    assert 'id="key-table-wrap" hidden' in html


def test_keys_all_matched_does_not_ask_for_a_new_import():
    html = eval_js("""(async () => {
      app.setFetch(async () => ({json: async () => ({total: 2,
        counts: {matched: 2}, rows: [],
        libraries: {steam: {count: 2, imported_at: "2026-01-01"}}})}));
      await app.loadKeys();
      return dom.writes["#keys-panel"];
    })()""")
    assert "All reported keys match an imported game library" in html
    assert 'href="#/tasks"' not in html


def test_maintenance_all_clear_is_replaced_when_review_work_arrives():
    result = eval_js("""(async () => {
      const review = [];
      app.setFetch(async (url) => ({json: async () =>
        url === "/api/review" ? {items: review} :
        url === "/api/duplicates" ? {groups: []} :
        url === "/api/stats" ? {total: 0, sections: []} : {items: []}}));
      await app.load();
      const empty = [dom.writes["#review-panel"], dom.writes["#dupes-panel"]];
      review.push({id: 1, name: "The Quiet Harbor: A Novel",
                   status: "review", type: "ebook", candidates: []});
      await app.loadReview();
      return {empty, populated: dom.writes["#review-panel"]};
    })()""")
    assert "All clear" in result["empty"][0]
    assert "No suggested duplicate groups" in result["empty"][1]
    assert "1 item needs review" in result["populated"]
    assert "All clear" not in result["populated"]


# -- The panel counts the rows the table shows (#43) -------------------
# The counting used to live only in stats.py and arrive over /api/stats,
# which is why the panel could only ever describe the whole catalog. It
# now runs in the browser over the filtered rows, so there ARE two
# implementations -- and this is what stops them drifting: one fixture,
# both implementations, asserted equal field for field. It is the same
# invariant the probe battery pins for the route, moved to the pair that
# can now disagree.

def _py_report(items):
    """stats.report reshaped into the JSON shape the viewer renders."""
    sections, total = stats.report(items)
    return {"total": total,
            "sections": [{"key": key, "label": label,
                          "rows": [{"label": rl, "count": c} for rl, c in rows]}
                         for key, label, rows in sections]}


def _js_report(items):
    return eval_js("app.statsReport(%s)" % json.dumps(items))


def test_the_browser_counts_agree_with_stats_py():
    items = [_item(id=1), _item(id=2, type="audiobook", my_rating=None),
             _item(id=3, type="comic", read_status="read", status="pending"),
             _item(id=4, type="music", my_rating=5, genre=["Fantasy", "Epic"])]
    assert _js_report(items) == _py_report(items)


def test_they_agree_on_a_value_outside_the_vocabulary():
    # stats.py counts it nowhere rather than inventing a row, so a section
    # need not sum to the total. The browser must be as silent about it.
    items = [_item(id=1, type="sheet music"), _item(id=2, status="invented")]
    assert _js_report(items) == _py_report(items)


def test_they_agree_when_read_status_is_missing_entirely():
    # A partial payload from an older server: stats.py defaults it to
    # "unread" via _tally's `default`, and nothing else does.
    items = [_item(id=1)]
    del items[0]["read_status"]
    assert _js_report(items) == _py_report(items)


def test_they_agree_on_the_gaps():
    items = [_item(id=1, my_rating=None, cover_path=None, source_url=None),
             _item(id=2, my_rating=3, cover_path="covers/a.jpg",
                   source_url="https://example.invalid/a")]
    assert _js_report(items) == _py_report(items)


def test_they_agree_on_a_genre_tie():
    # Genres sort by count descending, ties broken alphabetically, so the
    # order is total. A JS sort that left ties in insertion order would
    # pass every count assertion and fail this one.
    items = [_item(id=1, genre=["Westerns"]), _item(id=2, genre=["Epic"]),
             _item(id=3, genre=["Fantasy", "Epic"])]
    assert _js_report(items) == _py_report(items)


def test_they_agree_on_an_empty_catalog():
    assert _js_report([]) == _py_report([])


def _panel_after(items_json, setup=""):
    """The #stats-panel HTML after `setup` and a render."""
    return eval_js("""(async () => {
             dom.reset();
             app.setFetch(() => Promise.resolve(
               {ok: true, json: () => Promise.resolve({})}));
             app.setItems(%s);
             %s
             app.render();
             return dom.writes["#stats-panel"];
           })()""" % (items_json, setup))


_MIXED = json.dumps([
    _item(id=1, type="ebook", genre=["Fantasy"]),
    _item(id=2, type="ebook", genre=["Fantasy"]),
    _item(id=3, type="ebook", genre=["Westerns"]),
    _item(id=4, type="comic", genre=["Fantasy"]),
])


def test_the_panel_counts_only_the_rows_the_table_is_showing():
    # Filtered to Fantasy: two of the three e-books and the comic. The
    # panel used to answer for the whole catalog and say three e-books.
    html = _panel_after(_MIXED, 'app.chipFilters.genre.chips = ["Fantasy"];')
    block = html[html.index("stat-type"):html.index("stat-rating")]
    assert ">2<" in block, block
    assert ">3<" not in block, block


def test_the_panel_total_agrees_with_the_toolbar():
    # The complaint that opened #43: a panel reading "N items -- overview"
    # beside a toolbar reading "3 / 4 items".
    html = _panel_after(_MIXED, 'app.chipFilters.genre.chips = ["Fantasy"];')
    assert "3 items" in html, html[:200]


def test_clearing_the_filter_puts_the_whole_catalog_back():
    html = _panel_after(_MIXED)
    assert "4 items" in html, html[:200]


def test_a_filter_matching_nothing_hides_the_panel():
    # Reached through a filter now, but the same rule the empty catalog
    # already had: with no rows there is nothing to summarise, and the
    # table's own empty state is what says so. What must NOT happen is the
    # panel keeping the counts from before the filter.
    out = eval_js("""(() => {
             dom.reset();
             app.setItems(%s);
             app.chipFilters.genre.chips = ["Nothing"];
             app.render();
             return {written: dom.writes["#stats-panel"] ?? null,
                     total: app.getStatsData().total};
           })()""" % _MIXED)
    assert out["total"] == 0
    assert out["written"] is None, out["written"]


def test_a_single_row_is_summarised_in_the_singular():
    # "1 items" was unreachable while the panel counted the whole catalog
    # and became ordinary once it counts a filtered slice.
    html = _panel_after(json.dumps([_item(id=1)]))
    assert "1 item —" in html, html[:120]
    assert "1 items" not in html


def test_manual_merge_picker_is_reachable_with_no_suggested_duplicates():
    # The picker lived only inside a panel that was hidden whenever
    # /api/duplicates returned no groups. Picking a pair is the only thing
    # that set manualPair.shown, so the first pick could never happen: the
    # case the detector misses was exactly the case with no way to merge.
    result = eval_js("""(async () => {
      app.setFetch(async (url) => ({json: async () =>
        url === "/api/duplicates" ? {groups: []} :
        url === "/api/review" ? {items: []} :
        url === "/api/stats" ? {total: 0, sections: []} : {items: []}}));
      await app.load();
      const panel = document.querySelector("#dupes-panel");
      return {hidden: panel.hidden, html: dom.writes["#dupes-panel"]};
    })()""")
    assert result["hidden"] is False
    assert 'id="dupe-a"' in result["html"]
    assert 'id="dupe-b"' in result["html"]


def test_empty_duplicates_summary_says_so_and_points_to_the_picker():
    # The summary is all a collapsed panel shows. "0 possible duplicate
    # groups" gave no reason to open it, and the manual picker is inside.
    # No warning sign either: nothing suggested is the good outcome.
    html = eval_js("""(async () => {
      app.setFetch(async (url) => ({json: async () =>
        url === "/api/duplicates" ? {groups: []} :
        url === "/api/review" ? {items: []} :
        url === "/api/stats" ? {total: 0, sections: []} : {items: []}}));
      await app.load();
      return dom.writes["#dupes-panel"];
    })()""")
    summary = html.split("<summary>")[1].split("</summary>")[0]
    assert "No suggested duplicate groups" in summary
    assert "by hand" in summary
    assert "&#9888;" not in summary


def test_duplicates_panel_drops_its_warning_look_only_when_nothing_is_suggested():
    # The panel is amber because suggested duplicates need the owner's
    # attention. Always showing it (#71) made the amber say "warning" when
    # there is nothing to act on, so the empty state gets a neutral class
    # -- and loses it again once a group arrives.
    result = eval_js("""(async () => {
      let groups = [];
      app.setFetch(async (url) => ({json: async () =>
        url === "/api/duplicates" ? {groups} :
        url === "/api/review" ? {items: []} :
        url === "/api/stats" ? {total: 0, sections: []} : {items: []}}));
      const panel = document.querySelector("#dupes-panel");
      await app.load();
      const empty = panel.classList.contains("dupes-none");
      groups = [[
        {id: 1, name: "Amber Hollow", type: "ebook", bundles: []},
        {id: 2, name: "Amber Hollow", type: "ebook", bundles: []}]];
      await app.load();
      return {empty, populated: panel.classList.contains("dupes-none")};
    })()""")
    assert result == {"empty": True, "populated": False}


def test_bundle_guidance_disappears_after_either_preview():
    for method, report in (("previewBundle", _BUNDLE_REPORT),
                           ("previewChoice", _CHOICE_REPORT)):
        result = eval_js("""(async () => {
          app.renderBundlePreview();
          app.renderChoicePreview();
          const hint = document.querySelector("#bundle-empty");
          const before = !!hint.hidden;
          app.setFetch(async () => ({ok: true, json: async () => (%s)}));
          await app.%s("https://example.test/bundle");
          app.renderBundlePreview();
          app.renderChoicePreview();
          return {before, after: !!hint.hidden};
        })()""" % (json.dumps(report), method))
        assert result == {"before": False, "after": True}


def test_keys_text_filter_matches_title_and_store_without_changing_library_search():
    result = _with_keys('''(() => {
      app.setSearch("a separate library query");
      const search = document.querySelector("#keys-search");
      search.value = "  AMBER  ";
      const title = app.shownKeys().map(r => r.product);
      search.value = "steam";
      const store = app.shownKeys().map(r => r.store);
      app.setKeyStates([]);
      const none = app.shownKeys().length;
      app.setKeyStates(["unredeemed", "uncertain"]);
      search.value = "does-not-exist";
      const missing = app.shownKeys().length;
      search.value = "";
      return {title, store, none, missing, reset: app.shownKeys().length,
              library: document.querySelector("#search").value};
    })()''')
    assert result["title"] == ["Amber Hollow"]
    assert result["store"] and set(result["store"]) == {"steam"}
    assert result["none"] == result["missing"] == 0
    assert result["reset"] == 2
    assert result["library"] == "a separate library query"


def test_library_search_is_hidden_outside_library_and_restored_on_return():
    result = eval_js('''(() => {
      app.setSearch("retained query");
      const hidden = ["keys", "bundles", "maintenance", "tasks", "library"].map(id => {
        app.showSection(id);
        return document.querySelector("#search-row").hidden;
      });
      return {hidden, query: document.querySelector("#search").value};
    })()''')
    assert result == {"hidden": [True, True, True, True, False], "query": "retained query"}
