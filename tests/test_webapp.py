import io
import json
import re
import ssl as _ssl
import sys
import tempfile
from pathlib import Path
import pytest
import requests
from unittest.mock import Mock
from openpyxl import load_workbook
from humble_catalog import db, export, stats
from humble_catalog import handoff as handoffmod, lan as lanmod, webapp as webmod
from humble_catalog.webapp import create_app, create_lan_app


def _viewer_js():
    """Every viewer script concatenated, in load order.

    These assertions pin that the viewer does something, not that one
    file does. Reading app.js alone made them break when a function moved
    between scripts, which is a fact about the file layout and not about
    the behaviour they were written to protect.
    """
    from tests.js_harness import VIEWER_JS
    return "\n".join(p.read_text(encoding="utf-8") for p in VIEWER_JS)


def test_index_offers_android_type_filter():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert '<option value="android">Android apps</option>' in html

def test_index_has_autocomplete_filters():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert '<input id="f-genre"' in html      # selects replaced by
    assert '<input id="f-bundle"' in html     # autocomplete inputs
    # Open-ended, like the two above: the claim is that these stay
    # SELECTS, not that they carry no attributes. Pinning the closing
    # bracket made the assertion depend on f-type having none, and J1
    # gave both of them an aria-label.
    assert '<select id="f-type"' in html      # small closed lists stay selects
    assert '<select id="f-flag"' in html

def test_index_offers_the_annotation_flags():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    # the values are what app.js switches on; the labels are what is read
    assert '<option value="notes">Has notes</option>' in html
    assert '<option value="mytags">Has my tags</option>' in html

def test_index_has_person_filters():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    # authors and narrator are array fields, so they get chip filters
    # like genre/bundle rather than living only in the search haystack
    assert '<input id="f-authors"' in html
    assert '<input id="f-narrator"' in html
    assert '<input id="f-publisher"' in html

def test_index_marks_narrator_and_bundle_sortable():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-sort="narrator"' in html
    assert 'data-sort="bundle"' in html
    assert 'data-sort="read_status"' in html
    # every sortable header carries an indicator slot (Status added an 11th)
    assert html.count('class="sort-ind"') == 11

def test_only_the_table_scrolls_sideways():
    static = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
              / "static")
    html = (static / "index.html").read_text(encoding="utf-8")
    css = (static / "style.css").read_text(encoding="utf-8")
    # the 13 columns outrun the viewport, so something has to scroll. A
    # scroller around <main> was tried and dragged the panels sideways
    # with the table, which reads as the whole page scrolling; the
    # scroller has to wrap the table alone.
    assert '<div id="table-wrap">' in html
    assert "#table-wrap { flex: 1; min-height: 0; overflow: auto; }" in css
    assert "body { margin: 0" in css and "overflow: hidden;" in css
    # #table-wrap scrolls vertically too, so the sticky <thead> has a
    # scrollport of its own to stick within
    assert "#catalog thead th { position: sticky; top: 0;" in css
    # panels sit outside that scroller, so they need a cap of their own or
    # an expanded one squeezes the table region to nothing
    # the cap is gone with the stacking that needed it: a section owns the
    # viewport, so no panel can squeeze the table region any more
    assert "max-height: 50%" not in css
    assert 'section[id^="section-"]' in css

def test_the_card_list_is_its_own_scroller():
    # body is overflow: hidden, so the only vertical scroll in the Library
    # is the scroller the content sits in. On a narrow screen render() hides
    # #table-wrap and shows #card-list in its place, so the card list has to
    # take that role too -- without it the cards were clipped at the bottom
    # of the screen and could not be scrolled at all.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    rule = css[css.index("#card-list:not([hidden]) {"):]
    rule = rule[:rule.index("}")]
    for decl in ("flex: 1", "min-height: 0", "overflow-y: auto",
                 # a grid in a fixed-height scroller stretches its rows to
                 # fill it: one search result became a card 448 px tall
                 "align-content: start"):
        assert decl in rule, decl


def _css_rule(css, selector):
    body = css[css.index(selector + " {"):]
    return body[:body.index("}")]


def test_a_card_cover_keeps_its_proportions_and_text_flows_around_it():
    # The card was a flexbox, and a flex item stretches to the row's height:
    # the cover, given only a width, was pulled to the card's full height
    # and distorted. It floats now, at its own proportions, with the text
    # wrapping round it -- which needs the card to contain the float and
    # the text block NOT to be a flex or formatting-context box, or the
    # text would sit beside the cover in a column instead of flowing.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    card = _css_rule(css, ".card")
    cover = _css_rule(css, ".card-cover")
    assert "display: flow-root" in card and "flex" not in card
    for decl in ("float: left", "height: auto"):
        assert decl in cover, decl
    # The link row too: a flex row cannot wrap round a float, so the whole
    # row was pushed beside a tall cover and its links squeezed into a
    # narrow column. As a plain block, each link wraps like a word.
    assert "flex" not in _css_rule(css, ".card-links")
    # .card-body needs no rule of its own; if one returns, it must not
    # turn the text into a column beside the cover.
    if ".card-body {" in css:
        body = _css_rule(css, ".card-body")
        assert "flex" not in body and "overflow" not in body


def _library_column_widths(css):
    """{column: width in rem} from the Library table's column rules."""
    return {sort or cls: float(value) for sort, cls, value in re.findall(
        r'#catalog th(?:\[data-sort="(\w+)"\]|\.col-(\w+))'
        r' \{ width: ([\d.]+)rem; \}', css)}


def test_the_library_table_gives_name_the_widest_column():
    # Automatic layout sized columns by their content's unbreakable width,
    # which ran backwards: a bundle name is a nowrap .tag, so Bundle took a
    # wide column and overflowed anyway, while Name -- the column people
    # scan -- wrapped to three or four lines (#46). A fixed layout with an
    # explicit width per column puts the share where it is read.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    assert "table-layout: fixed" in _css_rule(css, "#catalog")
    widths = _library_column_widths(css)
    # Every one of the 14 headers has a width, or fixed layout splits the
    # remainder evenly among the unsized ones and the shares mean nothing.
    assert len(widths) == 14, sorted(widths)
    assert max(widths, key=widths.get) == "name"
    assert widths["bundle"] < widths["name"]
    # At 1440 px, with the filter sidebar open, the table's scroller is
    # 1137 px wide (measured on the demo catalog), about 71rem. The issue
    # was that it still scrolled sideways there.
    assert sum(widths.values()) <= 70, sum(widths.values())


def test_every_library_header_has_a_column_hook():
    # The width rules select on data-sort or a col- class, so a header
    # with neither would be unsized.
    html = _index_html()
    head = html[html.index('<table id="catalog">'):html.index("</thead>")]
    for th in re.findall(r"<th(?:\s[^>]*)?>", head):
        assert "data-sort=" in th or 'class="col-' in th, th


def test_a_truncated_tag_in_the_table_stays_inside_its_cell():
    # A fixed column no longer grows to fit a nowrap tag, so a long bundle
    # or author name must be cut with an ellipsis rather than painted over
    # the next column. The full name is in the tag's title.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    rule = _css_rule(css, "#catalog td .tag")
    for decl in ("max-width: 100%", "overflow: hidden",
                 "text-overflow: ellipsis"):
        assert decl in rule, decl


def test_a_bundle_tag_wraps_to_two_lines_rather_than_one():
    # One line of an 88 px column showed a few letters of any bundle name
    # (#76). Unclamped, a name ran to five lines and doubled the row; two
    # lines fit the height every row already has for its cover and status.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    rule = _css_rule(css, "#catalog td .tag-link")
    for decl in ("white-space: normal", "-webkit-line-clamp: 2",
                 "line-clamp: 2", "display: -webkit-box"):
        assert decl in rule, decl


def test_the_tasks_section_is_its_own_scroller():
    # body is overflow: hidden and every section brings its own scroller.
    # Tasks had none, which went unseen while its cards fitted the window;
    # the handoff cards pushed the Danger group below the fold with no way
    # to scroll to it.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    assert "overflow-y: auto" in _css_rule(css, "#section-tasks")


def test_task_cards_share_a_line_from_1080_px():
    # At 1920 px a card was 1873 px wide around at most 662 px of text,
    # with its Run button 1672 px from its label (#34). From 1080 px up
    # each group lays its cards out in columns; below that, one per line.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    wide = css[css.index("@media (min-width: 1080px) {"):]
    wide = wide[:wide.index("\n}")]
    group = _css_rule(wide, ".task-group")
    assert "display: grid" in group
    assert "repeat(auto-fill, minmax(" in group
    # the heading is a row of its own, not the first cell
    assert "grid-column: 1 / -1" in _css_rule(wide, ".task-group h3")
    # outside the query the groups stay plain blocks
    assert "grid" not in _css_rule(css, ".task-group")


def test_app_wires_every_registered_chip_filter():
    js = _viewer_js()
    for field in ("genre", "series", "authors", "narrator", "publisher",
                  "bundle"):
        assert f"{field}:" in js
    # wiring loops over the registry, so an entry cannot end up as a
    # silently dead control the way a hand-written call list allowed
    assert "for (const field of Object.keys(chipFilters)) wireChipFilter(field);" in js

def test_narrator_filter_spans_illustrator():
    js = _viewer_js()
    # the Narrator/Artist column shows narrator || illustrator, so a
    # narrator-only filter would silently miss every comic illustrator
    assert "[...i.narrator, ...i.illustrator]" in js

def test_search_matches_name_only():
    static = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
              / "static")
    js = _viewer_js()
    # every other field the old haystack spanned now has its own filter.
    # Matching became fuzzy (fuzzy.js), but the haystack is still the
    # name and nothing else.
    assert "Fuzzy.score(q, i.name" in js
    assert "...i.bundles.map(b => b.name)].join" not in js
    html = (static / "index.html").read_text(encoding="utf-8")
    # the word "Search" is a standalone label, not placeholder text
    assert '<label id="search-label" for="search">Search</label>' in html
    assert 'placeholder="Name..."' in html

def test_series_filter_suppresses_all_any_toggle():
    static = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
              / "static")
    html = (static / "index.html").read_text(encoding="utf-8")
    assert '<input id="f-series"' in html
    js = _viewer_js()
    # series is one-per-item, so "all" with 2+ chips is unsatisfiable:
    # the flag hides a toggle that could only ever empty the table
    assert "scalar: true" in js
    assert "!f.scalar" in js

def test_autocomplete_opens_only_on_typing_or_arrows():
    ac = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
          / "static" / "autocomplete.js").read_text(encoding="utf-8")
    # opening on focus made the list flash up whenever a field was
    # clicked; the arrows summon it deliberately instead
    assert 'addEventListener("focus"' not in ac
    assert "if (!owned()) show();" in ac

def test_autocomplete_list_belongs_to_one_input():
    ac = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
          / "static" / "autocomplete.js").read_text(encoding="utf-8")
    # one list is shared across every attached input, so each handler
    # must check the open one is its own: otherwise a blur timer closes
    # a list another input just opened, and arrow keys drive a list
    # whose values belong to a different field
    assert "openOwner" in ac
    assert "const owned = () => openList && openOwner === input;" in ac
    assert "if (owned()) close();" in ac

def test_autocomplete_popup_is_not_a_tab_stop():
    ac = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
          / "static" / "autocomplete.js").read_text(encoding="utf-8")
    # the list scrolls and has no focusable children, so Chrome would
    # otherwise hand it a tab stop of its own as a "focusable scroller",
    # stealing the Tab that should reach the next filter field
    assert 'openList.tabIndex = -1;' in ac

def test_autocomplete_anchors_popup_to_the_input():
    ac = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
          / "static" / "autocomplete.js").read_text(encoding="utf-8")
    # .ac-wrap also holds chips, which wrap onto extra lines; without an
    # explicit anchor the list renders at its static position and drifts
    assert "openOwner.getBoundingClientRect()" in ac
    assert "openList.style.top" in ac and "openList.style.left" in ac
    # the list hangs off <body> so <main>'s overflow cannot clip it, which
    # means nothing moves it with its anchor unless we do it ourselves
    assert "document.body.appendChild(openList)" in ac
    assert 'window.addEventListener("scroll", reposition, true)' in ac
    assert 'window.addEventListener("resize", reposition)' in ac
    # an in-cell list outlives the row rebuild that used to remove it
    assert "if (!openOwner.isConnected) { close(); return; }" in ac
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    # the list may grow rightwards past the field's own width
    assert "width: max-content" in css
    # viewport coordinates only work against a fixed element
    assert ".ac-list { position: fixed;" in css

def test_buttons_are_themed_by_a_base_rule():
    # Three buttons had been hand-fixed with the same recipe and a comment
    # saying an unstyled <button> "keeps the browser's grey default, which
    # glares in dark mode". Thirteen more had never opted in, because
    # opting in was the rule. A base rule makes theming the default and
    # leaves opting OUT to the link-style buttons, which are all
    # class- or id-selected and so outrank it.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    rule = css[css.index("\nbutton {"):]
    rule = rule[:rule.index("}")]
    # custom properties, never a literal colour, or one theme breaks
    assert "var(--surface)" in rule and "var(--fg)" in rule
    assert "#" not in rule

def test_the_empty_state_line_does_not_read_as_a_data_row():
    # It stands where the rows would be, so without a treatment of its own
    # it reads as an item called "No items match these filters" -- the one
    # reading that is worse than the blank table it replaced.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    for selector in (".table-empty td", ".list-empty"):
        rule = _css_rule(css, selector)
        assert "var(--muted)" in rule, selector
        assert "text-align: center" in rule, selector


def test_the_table_says_it_is_loading_before_any_script_runs():
    # /api/items is awaited before anything is drawn, so the table was
    # blank for the whole round trip -- and identical to an empty catalog
    # and to a server that never answered. The first state ships in the
    # markup, so it is on screen at first paint rather than after the
    # scripts have parsed.
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    body = html[html.index("<tbody>"):html.index("</tbody>")]
    assert "Loading" in body


def test_focus_is_visible_on_every_control():
    # There was no :focus-visible rule at all, so a keyboard user tabbing
    # through the filter fields, the status chips, the active-filter
    # strip or a Tasks card had nothing on screen saying where they were.
    # The base button rule above is exactly why the browser's own ring
    # cannot be relied on here: every button carries a custom background,
    # and the default ring is drawn to sit on the default button.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    rule = _css_rule(css, ":focus-visible")
    assert "outline:" in rule
    # custom properties, never a literal colour, or one theme loses the
    # ring against its own ground -- the same rule the button base obeys
    assert "var(--" in rule and "#" not in rule
    # offset, so the ring clears a control's own border instead of
    # tracing it and reading as a thicker border
    assert "outline-offset:" in rule


def test_nothing_suppresses_the_focus_outline():
    # A single `outline: none` anywhere puts one control back in the dark,
    # and it is the conventional way to "fix" a ring someone dislikes.
    # Declarations only: the rule's own comment says not to write
    # `outline: none`, and a raw substring scan reads that as the offence.
    css = re.sub(r"/\*.*?\*/", "", (Path(__file__).parent.parent
                 / "humble_catalog" / "webapp" / "static" / "style.css")
                 .read_text(encoding="utf-8"), flags=re.S)
    assert "outline: none" not in css
    assert "outline: 0" not in css


def test_search_box_has_title_typeahead():
    static = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
              / "static")
    html = (static / "index.html").read_text(encoding="utf-8")
    # the dropdown positions against a .ac-wrap, so #search must sit
    # inside one; the wrapper takes over the flex sizing
    assert 'id="search-wrap"' in html
    css = (static / "style.css").read_text(encoding="utf-8")
    assert "#search-wrap" in css
    js = _viewer_js()
    # one stray keystroke should not open a list drawn from every title
    assert "length < 2" in js
    assert 'Autocomplete.attach(\n  $("#search")' in js

def _seed(dbp):
    conn = db.connect(dbp)
    conn.execute("INSERT INTO bundles VALUES ('k1','Bundle One','http://b1','2020-01-01')")
    cur = conn.execute(
        "INSERT INTO items (machine_name, name, type, publisher) "
        "VALUES ('asr','All Systems Red','ebook','Example Press')")
    item_id = cur.lastrowid
    conn.execute("INSERT INTO item_bundles VALUES (?, 'k1')", (item_id,))
    cands = [{"source": "hardcover", "title": "All Systems Red",
              "authors": ["Martha Wells"], "genre": "SF", "series": None,
              "series_number": None, "rating": 4.3, "narrator": None,
              "illustrator": None, "extra": {}, "confidence": 0.7}]
    conn.execute(
        "INSERT INTO enrichment (item_id, status, candidates) VALUES (?,?,?)",
        (item_id, "low_confidence", json.dumps(cands)))
    conn.commit()
    conn.close()
    return item_id

def test_items_rating_and_review_flow(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    items = client.get("/api/items").get_json()["items"]
    assert items[0]["name"] == "All Systems Red"
    assert items[0]["bundles"][0]["name"] == "Bundle One"

    assert client.post(f"/api/items/{item_id}/rating",
                       json={"rating": 5}).status_code == 200
    assert client.get("/api/items").get_json()["items"][0]["my_rating"] == 5

    review = client.get("/api/review").get_json()["items"]
    assert review and review[0]["candidates"][0]["title"] == "All Systems Red"

    assert client.post(f"/api/items/{item_id}/choose",
                       json={"candidate": 0}).status_code == 200
    item = client.get("/api/items").get_json()["items"][0]
    assert item["status"] == "manually_fixed" and item["genre"] == ["SF"]
    assert client.get("/api/review").get_json()["items"] == []


def test_set_read_status_updates_the_item(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post(f"/api/items/{item_id}/read-status", json={"status": "reading"})
    assert resp.status_code == 200
    conn = db.connect(dbp)
    assert conn.execute("SELECT read_status FROM items WHERE id=?",
                        (item_id,)).fetchone()["read_status"] == "reading"
    conn.close()


def test_set_read_status_rejects_an_unknown_value(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post(f"/api/items/{item_id}/read-status",
                       json={"status": "skimmed"}).status_code == 400


def test_set_read_status_404s_for_a_missing_item(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/items/99999/read-status",
                       json={"status": "read"}).status_code == 404

def test_type_override_and_status(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post(f"/api/items/{item_id}/type",
                       json={"type": "comic"}).status_code == 200
    assert client.get("/api/items").get_json()["items"][0]["type"] == "comic"
    assert client.get("/api/status").get_json() == {"runs": [], "read_only": False}


# The write routes below answer a malformed body or an unknown item the way
# read-status already did. They are grouped because they were one defect:
# each indexed the JSON body directly, or skipped the existence check, so a
# typo answered 500 and a write to a deleted id answered 200 having stored
# nothing. The star widget's own values (1..5, and null to clear) are the
# rating domain, so the boundary cases are 0 and 6, not 0 and 100.

def test_rating_null_clears_the_rating(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post(f"/api/items/{item_id}/rating",
                       json={"rating": 4}).status_code == 200
    # catalog.js sends null when you click the star already showing
    assert client.post(f"/api/items/{item_id}/rating",
                       json={"rating": None}).status_code == 200
    assert client.get("/api/items").get_json()["items"][0]["my_rating"] is None


def test_rating_rejects_values_outside_the_star_domain(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    for bad in (0, 6, "five", True, [5]):
        assert client.post(f"/api/items/{item_id}/rating",
                           json={"rating": bad}).status_code == 400, bad
    # a missing key is a malformed body, not a clear
    assert client.post(f"/api/items/{item_id}/rating", json={}).status_code == 400
    # and nothing was stored by any of them
    assert client.get("/api/items").get_json()["items"][0]["my_rating"] is None


def test_rating_404s_for_a_missing_item(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/items/99999/rating",
                       json={"rating": 3}).status_code == 404


def test_type_rejects_a_malformed_body_and_a_missing_item(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post(f"/api/items/{item_id}/type", json={}).status_code == 400
    assert client.post("/api/items/99999/type",
                       json={"type": "comic"}).status_code == 404


def test_choose_404s_when_the_item_has_no_enrichment_row(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    conn = db.connect(dbp)
    cur = conn.execute("INSERT INTO items (machine_name, name, type) "
                       "VALUES ('ub','Unrelated Book','ebook')")
    bare_id = cur.lastrowid
    conn.commit()
    conn.close()
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post(f"/api/items/{bare_id}/choose",
                       json={"candidate": 0}).status_code == 404


def test_choose_rejects_a_non_integer_index(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    # "0" is compared against len(candidates); it has to be refused before
    # that comparison, not raise TypeError inside it
    assert client.post(f"/api/items/{item_id}/choose",
                       json={"candidate": "0"}).status_code == 400
    assert client.post(f"/api/items/{item_id}/choose", json={}).status_code == 400


def test_reopen_404s_for_a_missing_item(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/items/99999/reopen").status_code == 404

def test_review_sorted_by_confidence_with_covers(tmp_path):
    dbp = tmp_path / "t.db"
    conn = db.connect(dbp)
    conn.execute("INSERT INTO items (machine_name, name, type, cover_path) "
                 "VALUES ('a','Low Conf Book','ebook','covers/1.jpg')")
    conn.execute("INSERT INTO enrichment (item_id, status, candidates) VALUES "
                 "(1,'low_confidence','[{\"source\":\"s\",\"title\":\"A\",\"confidence\":0.62}]')")
    conn.execute("INSERT INTO items (machine_name, name, type) VALUES ('b','High Conf Book','ebook')")
    conn.execute("INSERT INTO enrichment (item_id, status, candidates) VALUES "
                 "(2,'low_confidence','[{\"source\":\"s\",\"title\":\"B1\",\"confidence\":0.4},"
                 "{\"source\":\"s\",\"title\":\"B2\",\"confidence\":0.81}]')")
    conn.commit()
    conn.close()
    client = create_app(db_path=str(dbp)).test_client()
    review = client.get("/api/review").get_json()["items"]
    assert [r["name"] for r in review] == ["High Conf Book", "Low Conf Book"]
    assert review[0]["candidates"][0]["title"] == "B2"  # sorted within item too
    assert review[1]["cover_path"] == "covers/1.jpg"

def test_choose_index_matches_review_order(tmp_path):
    # Candidates stored low-confidence-first; /api/review shows them sorted
    # desc, and the frontend posts an index into that sorted view. Choosing
    # index 0 must apply the highest-confidence candidate, not stored[0].
    dbp = tmp_path / "t.db"
    conn = db.connect(dbp)
    conn.execute("INSERT INTO items (machine_name, name, type) VALUES ('x','X','ebook')")
    cands = [{"source": "s", "title": "Woodworking X", "genre": "Crafts",
              "confidence": 0.55},
             {"source": "s", "title": "Programming X", "genre": "Computing",
              "confidence": 0.84}]
    conn.execute("INSERT INTO enrichment (item_id, status, candidates) "
                 "VALUES (1,'low_confidence',?)", (json.dumps(cands),))
    conn.commit()
    conn.close()
    client = create_app(db_path=str(dbp)).test_client()
    review = client.get("/api/review").get_json()["items"]
    assert review[0]["candidates"][0]["title"] == "Programming X"
    assert client.post("/api/items/1/choose",
                       json={"candidate": 0}).status_code == 200
    item = client.get("/api/items").get_json()["items"][0]
    assert item["genre"] == ["Computing"]

def test_reopen_and_apply_endpoints(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/choose", json={"candidate": 0})
    assert client.get("/api/review").get_json()["items"] == []

    # reopen: back in the queue, data and candidates intact
    assert client.post(f"/api/items/{item_id}/reopen").status_code == 200
    review = client.get("/api/review").get_json()["items"]
    assert review and review[0]["candidates"]

    # apply an arbitrary candidate (as the URL importer will)
    cand = {"source": "comicvine", "title": "Shadow Hound: Origins",
            "genre": "Manga", "url": "https://comicvine.gamespot.com/x/4050-1/",
            "authors": ["Bo Writer"]}
    assert client.post(f"/api/items/{item_id}/apply",
                       json={"candidate": cand}).status_code == 200
    item = client.get("/api/items").get_json()["items"][0]
    assert item["status"] == "manually_fixed"
    assert item["genre"] == ["Manga"]
    assert item["source_url"] == "https://comicvine.gamespot.com/x/4050-1/"
    assert client.post(f"/api/items/{item_id}/apply",
                       json={"candidate": {"title": "no source"}}).status_code == 400

def test_fetch_url_endpoint(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    assert client.post(f"/api/items/{item_id}/fetch_url",
                       json={}).status_code == 400

    from humble_catalog import url_import
    fake = {"source": "drivethrurpg", "title": "Heart", "url": "https://d/x"}
    monkeypatch.setattr(url_import, "resolve", lambda conn, url: fake)
    resp = client.post(f"/api/items/{item_id}/fetch_url",
                       json={"url": "https://www.drivethrurpg.com/en/product/1/x"})
    assert resp.status_code == 200
    assert resp.get_json()["candidate"]["title"] == "Heart"

    def boom(conn, url):
        raise ValueError("unsupported source URL")
    monkeypatch.setattr(url_import, "resolve", boom)
    resp = client.post(f"/api/items/{item_id}/fetch_url",
                       json={"url": "https://example.com/x"})
    assert resp.status_code == 400
    assert "unsupported" in resp.get_json()["error"]

# --- the two routes that take a URL in the body ----------------------------
# Both read `url` through _url_from_body, so neither can answer 500 for a
# body shape the other refuses. Each of these shapes raised an
# AttributeError before H1's sibling fix: a body with no `.get`, a `url`
# with no `.strip`. The envelope makes them Low - the viewer API is
# user-error, reachable only from loopback - but a wrong value is exactly
# the case that earns a clear failure message rather than a stack trace.

BAD_BODIES = [
    ("a JSON array", "[1,2,3]"),
    ("a bare JSON string", '"hello"'),
    ("a JSON number", "5"),
    ("malformed JSON", "{not json"),
]


def _post_raw(client, route, body):
    return client.post(route, data=body, content_type="application/json")


def test_fetch_url_refuses_a_body_that_is_not_an_object(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    for label, body in BAD_BODIES:
        resp = _post_raw(client, f"/api/items/{item_id}/fetch_url", body)
        assert resp.status_code == 400, label
        assert resp.get_json()["error"] == "url required", label


def test_bundle_preview_refuses_a_body_that_is_not_an_object(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    for label, body in BAD_BODIES:
        resp = _post_raw(client, "/api/bundle-preview", body)
        assert resp.status_code == 400, label
        assert resp.get_json()["error"] == "url required", label


def test_both_routes_refuse_a_url_that_is_not_a_string(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    for value in [5, 5.5, True, None, ["https://example.invalid/x"],
                  {"href": "https://example.invalid/x"}]:
        for route in [f"/api/items/{item_id}/fetch_url", "/api/bundle-preview"]:
            resp = client.post(route, json={"url": value})
            assert resp.status_code == 400, (route, value)
            assert resp.get_json()["error"] == "url required", (route, value)


def test_both_routes_still_refuse_a_blank_url(tmp_path):
    # The behaviour that already worked must not have been traded away.
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    for value in ["", "   ", "\t\n"]:
        for route in [f"/api/items/{item_id}/fetch_url", "/api/bundle-preview"]:
            resp = client.post(route, json={"url": value})
            assert resp.status_code == 400, (route, value)


def test_a_refused_body_never_reaches_the_network(tmp_path, monkeypatch):
    # The property that makes this a refusal rather than a slow failure:
    # nothing outbound is attempted for a body that cannot supply a URL.
    from humble_catalog import bundle_preview, url_import
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    def explode(*args, **kwargs):
        raise AssertionError("a refused body reached the network")

    monkeypatch.setattr(url_import, "resolve", explode)
    monkeypatch.setattr(bundle_preview, "fetch_bundle", explode)
    for _label, body in BAD_BODIES:
        assert _post_raw(client, f"/api/items/{item_id}/fetch_url",
                         body).status_code == 400
        assert _post_raw(client, "/api/bundle-preview", body).status_code == 400


def _every_post_route(app, item_id):
    """Every POST rule the app actually registers, as concrete paths.

    Enumerated from `app.url_map` rather than from a hand-kept list, so a
    route added later is covered by the assertions below without anyone
    remembering to add it. That is the point: the defect these pin was a
    whole class, and a list of names would go stale the first time a
    route was added.
    """
    paths = []
    for rule in app.url_map.iter_rules():
        if "POST" not in (rule.methods or set()):
            continue
        path = str(rule).replace("<int:item_id>", str(item_id))
        if "<" in path:                     # no POST rule needs another arg
            continue
        paths.append(path)
    return sorted(paths)


def test_no_post_route_answers_5xx_for_a_body_that_is_not_an_object(tmp_path):
    # The class check. Every POST route is driven with each non-object
    # body; none may answer 5xx, and each must answer a 4xx carrying a
    # JSON error object rather than an HTML error page.
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    app = create_app(db_path=str(dbp))
    client = app.test_client()
    routes = _every_post_route(app, item_id)
    assert len(routes) >= 20, routes        # the enumeration found the routes
    # The routes that legitimately answer 2xx here: each reads NO field
    # from the body, so a body it never looks at cannot make it fail.
    # `/reopen` takes a bare body by documented contract. Every other
    # route reads something and must refuse. `/api/choice-preview` reads
    # no field either, but it still requires an object (issue #20): the
    # route does credentialed network work, and a malformed request must
    # be refused before any of it starts.
    #
    # Membership of this set is a claim about the route, not a waiver: add
    # a path here only when it reads nothing, and never to quiet a failure
    # from a route that does.
    bodiless = set()
    for path in routes:
        for label, body in BAD_BODIES:
            resp = client.post(path, data=body,
                               content_type="application/json")
            assert resp.status_code < 500, (path, label, resp.status_code)
            if path.endswith("/reopen") or path in bodiless:
                continue
            assert 400 <= resp.status_code < 500, (path, label,
                                                   resp.status_code)
            # a JSON error object, not Werkzeug's HTML error page
            assert resp.get_json() is not None, (path, label)


def test_comment_requires_the_key_so_a_bad_body_cannot_clear_it(tmp_path):
    # An absent `comment` used to mean "clear it", so once a malformed
    # body reads as an empty object a client bug would silently erase the
    # note. The key is now required; clearing is still done the
    # documented way, with a blank string.
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/comment", json={"comment": "A note."})

    for body in [{}, [1, 2, 3], "hello"]:
        resp = client.post(f"/api/items/{item_id}/comment", json=body)
        assert resp.status_code == 400, body
    assert client.get("/api/items").get_json()["items"][0]["user_comment"] \
        == "A note."

    resp = client.post(f"/api/items/{item_id}/comment", json={"comment": "  "})
    assert resp.status_code == 200
    assert client.get("/api/items").get_json()["items"][0]["user_comment"] is None


def test_no_post_route_answers_5xx_for_an_absent_body(tmp_path):
    # The neighbouring shape: no body at all, which reaches the same
    # reader and must also become each route's own refusal.
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    app = create_app(db_path=str(dbp))
    client = app.test_client()
    for path in _every_post_route(app, item_id):
        resp = client.post(path)
        assert resp.status_code < 500, (path, resp.status_code)


def test_tag_vocab_routes_refuse_a_non_string_field(tmp_path):
    # I1: `(data.get("x") or "").strip()` answered 500 for a number,
    # because `or ""` is not a type check. `_text_field` is the one place
    # a named text field is read now.
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    routes = [("/api/genres/rename", ["old", "new"]),
              ("/api/genres/delete", ["tag"]),
              ("/api/user-tags/rename", ["old", "new"]),
              ("/api/user-tags/delete", ["tag"])]
    for route, fields in routes:
        for field in fields:
            for value in [5, True, None, ["x"], {"a": 1}]:
                body = {f: "SF" for f in fields}
                body[field] = value
                resp = client.post(route, json=body)
                assert resp.status_code == 400, (route, field, value)
                assert resp.get_json() is not None, (route, field, value)


def test_bulk_user_tags_refuses_a_non_string_tag(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    for value in [5, True, None, ["x"], {"a": 1}]:
        resp = client.post("/api/user-tags/bulk",
                           json={"ids": [item_id], "tag": value,
                                 "action": "add"})
        assert resp.status_code == 400, value


def test_user_tags_refuses_a_non_string_entry_rather_than_coercing(tmp_path):
    # The silent half of I1: db.normalize_tags coerces with str(), which
    # is right for the import paths it also serves, so {"tags": [null]}
    # was stored as a tag literally spelled None. Refused at the boundary
    # instead, leaving that coercion intact for its other callers.
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/user-tags", json={"tags": ["lent out"]})
    for value in [None, 5, True, {"a": 1}]:
        resp = client.post(f"/api/items/{item_id}/user-tags",
                           json={"tags": [value]})
        assert resp.status_code == 400, value
    item = client.get("/api/items").get_json()["items"][0]
    assert item["user_tags"] == ["lent out"]

    # the control: the shape the viewer sends still works
    assert client.post(f"/api/items/{item_id}/user-tags",
                       json={"tags": ["lent out", "boxed"]}).status_code == 200


def test_index_has_the_stats_panel():
    static = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
              / "static")
    html = (static / "index.html").read_text(encoding="utf-8")
    assert '<div id="stats-panel" hidden></div>' in html
    # the two panels it replaced are gone, not merely hidden
    assert "genres-panel" not in html and "gaps-panel" not in html
    # genre management survives inside it, behind the Edit tags toggle
    js = _viewer_js()
    assert "/api/genres/rename" in js and "/api/genres/delete" in js

def _seed_genres_app(tmp_path):
    dbp = tmp_path / "g.db"
    conn = db.connect(dbp)
    for idx, (mn, name) in enumerate(
            [("wad", "Wings of Autumn Dusk"), ("ub", "Unrelated Book")], 1):
        conn.execute("INSERT INTO items (machine_name, name) VALUES (?,?)",
                     (mn, name))
        conn.execute("INSERT INTO enrichment (item_id, genre) VALUES (?,?)",
                     (idx, '["Fantasy"]' if idx == 1 else '["Horror"]'))
    conn.commit()
    conn.close()
    return create_app(db_path=str(dbp)).test_client()

def test_genre_rename_endpoint(tmp_path):
    client = _seed_genres_app(tmp_path)
    resp = client.post("/api/genres/rename",
                       json={"old": "Fantasy", "new": "Epic Fantasy"})
    assert resp.status_code == 200 and resp.get_json() == {"changed": 1}
    genres = [i["genre"] for i in client.get("/api/items").get_json()["items"]]
    assert ["Epic Fantasy"] in genres and ["Fantasy"] not in genres

def test_genre_rename_endpoint_rejects_bad_input(tmp_path):
    client = _seed_genres_app(tmp_path)
    assert client.post("/api/genres/rename",
                       json={"old": "", "new": "X"}).status_code == 400
    assert client.post("/api/genres/rename",
                       json={"old": "Fantasy"}).status_code == 400
    assert client.post("/api/genres/rename",
                       json={"old": "Cooking", "new": "Food"}).status_code == 404

def test_genre_delete_endpoint(tmp_path):
    client = _seed_genres_app(tmp_path)
    resp = client.post("/api/genres/delete", json={"tag": "Horror"})
    assert resp.status_code == 200 and resp.get_json() == {"changed": 1}
    genres = [i["genre"] for i in client.get("/api/items").get_json()["items"]]
    assert [] in genres and ["Horror"] not in genres

def test_genre_delete_endpoint_rejects_bad_input(tmp_path):
    client = _seed_genres_app(tmp_path)
    assert client.post("/api/genres/delete", json={}).status_code == 400
    assert client.post("/api/genres/delete",
                       json={"tag": "Cooking"}).status_code == 404

def test_edit_snapshots_once_and_updates(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/choose", json={"candidate": 0})

    # first edit: snapshot taken, fields updated, status untouched
    assert client.post(f"/api/items/{item_id}/edit", json={"fields": {
        "genre": ["Cyberpunk", "Noir"], "series_number": "2"}}).status_code == 200
    item = client.get("/api/items").get_json()["items"][0]
    assert item["genre"] == ["Cyberpunk", "Noir"] and item["series_number"] == 2.0
    assert item["edited"] is True
    assert item["status"] == "manually_fixed"

    # second edit must NOT re-snapshot (revert target stays the enriched form)
    client.post(f"/api/items/{item_id}/edit",
                json={"fields": {"genre": ["Solarpunk"], "authors": []}})
    item = client.get("/api/items").get_json()["items"][0]
    assert item["genre"] == ["Solarpunk"] and item["authors"] == []

    assert client.post(f"/api/items/{item_id}/revert").status_code == 200
    item = client.get("/api/items").get_json()["items"][0]
    assert item["genre"] == ["SF"]              # back to the enriched values
    assert item["authors"] == ["Martha Wells"]
    assert item["edited"] is False

def test_edit_validation(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post(f"/api/items/{item_id}/edit",
                       json={"fields": {"status": "matched"}})
    assert resp.status_code == 400 and "status" in resp.get_json()["error"]
    assert client.post(f"/api/items/{item_id}/edit", json={"fields": {
        "series_number": "two"}}).status_code == 400
    assert client.post(f"/api/items/{item_id}/edit",
                       json={}).status_code == 400
    assert client.post(f"/api/items/{item_id}/edit", json={"fields": {
        "genre": "not a list"}}).status_code == 400
    assert client.post(f"/api/items/{item_id}/edit", json={"fields": {
        "authors": ["", "  "]}}).status_code == 200  # all-blank list stores NULL

def test_revert_without_edit_is_400(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post(f"/api/items/{item_id}/revert").status_code == 400

def test_apply_candidate_keeps_a_revert_target_for_a_hand_edit(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/edit",
                json={"fields": {"genre": ["Hand Typed"]}})
    assert client.get("/api/items").get_json()["items"][0]["edited"] is True
    # Applying a candidate hands authorship back to enrichment, but the
    # typed values become the new revert target instead of being dropped.
    client.post(f"/api/items/{item_id}/choose", json={"candidate": 0})
    item = client.get("/api/items").get_json()["items"][0]
    assert item["edited"] is False and item["genre"] == ["SF"]
    assert item["re_enriched"] is True
    assert client.post(f"/api/items/{item_id}/revert").status_code == 200
    assert client.get("/api/items").get_json()["items"][0]["genre"] == ["Hand Typed"]

def test_index_serves_html(tmp_path):
    _seed(tmp_path / "t.db")
    client = create_app(db_path=str(tmp_path / "t.db")).test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<table" in resp.data or b"catalog" in resp.data.lower()

def test_export_csv_endpoint(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.get("/api/export.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert resp.headers["Content-Disposition"] == "attachment; filename=catalog.csv"
    body = resp.get_data()
    assert body.startswith(b"\xef\xbb\xbftitle,")  # UTF-8 BOM so Excel detects encoding
    assert b"All Systems Red" in body

# The POST tests below use _seed_pair, defined just after them: the export
# tests stay together rather than splitting around a shared helper.

def test_export_csv_post_uses_the_posted_ids_in_order(tmp_path):
    dbp = tmp_path / "t.db"
    ids = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/export.csv", json={"ids": list(reversed(ids))})
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert resp.headers["Content-Disposition"] == "attachment; filename=catalog.csv"
    body = resp.get_data()
    assert body.startswith(b"\xef\xbb\xbftitle,")  # same BOM as the GET path
    rows = body.decode("utf-8-sig").splitlines()
    assert len(rows) == 3  # header + 2 items
    # the second seeded item's row comes first, because that is what was posted
    first_data_row = rows[1]
    resp_fwd = client.post("/api/export.csv", json={"ids": ids})
    fwd_rows = resp_fwd.get_data().decode("utf-8-sig").splitlines()
    assert fwd_rows[1] != first_data_row

def test_export_csv_post_subset(tmp_path):
    dbp = tmp_path / "t.db"
    ids = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/export.csv", json={"ids": [ids[0]]})
    rows = resp.get_data().decode("utf-8-sig").splitlines()
    assert len(rows) == 2  # header + 1 item

def test_export_csv_post_rejects_a_bad_body(tmp_path):
    dbp = tmp_path / "t.db"
    _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/export.csv", json={}).status_code == 400
    assert client.post("/api/export.csv", json={"ids": "all"}).status_code == 400

def test_export_csv_get_still_returns_the_whole_catalog(tmp_path):
    # GET keeps meaning "everything": bookmarks, curl, and scripts use it
    # even though the viewer now posts.
    dbp = tmp_path / "t.db"
    _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    rows = client.get("/api/export.csv").get_data().decode("utf-8-sig").splitlines()
    assert len(rows) == 3  # header + both items

_XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")

def _xlsx_titles(resp):
    """Data-row titles from an xlsx response, in file order."""
    ws = load_workbook(io.BytesIO(resp.get_data())).active
    col = [c.value for c in ws[1]].index("title")
    return [row[col].value for row in ws.iter_rows(min_row=2)]

def test_export_xlsx_post_uses_the_posted_ids_in_order(tmp_path):
    dbp = tmp_path / "t.db"
    ids = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/export.xlsx", json={"ids": list(reversed(ids))})
    assert resp.status_code == 200
    assert resp.mimetype == _XLSX_MIME
    assert resp.headers["Content-Disposition"] == \
        "attachment; filename=catalog.xlsx"
    forward = _xlsx_titles(client.post("/api/export.xlsx", json={"ids": ids}))
    assert _xlsx_titles(resp) == list(reversed(forward))

def test_export_xlsx_get_returns_the_whole_catalog(tmp_path):
    # GET keeps meaning "everything", same as the CSV route: it is the
    # form a bookmark or a script can use.
    dbp = tmp_path / "t.db"
    _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert len(_xlsx_titles(client.get("/api/export.xlsx"))) == 2

def test_export_xlsx_post_rejects_a_bad_body(tmp_path):
    dbp = tmp_path / "t.db"
    _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/export.xlsx", json={}).status_code == 400
    assert client.post("/api/export.xlsx", json={"ids": "all"}).status_code == 400

def _seed_pair(dbp, type_b="ebook"):
    conn = db.connect(dbp)
    conn.execute("INSERT INTO bundles VALUES ('k1','Bundle One','http://b1',NULL)")
    conn.execute("INSERT INTO bundles VALUES ('k2','Bundle Two','http://b2',NULL)")
    ids = []
    for mn, name, typ, gk in [("m1", "Book 2e", "ebook", "k1"),
                              ("m2", "Book, 2nd Edition", type_b, "k2")]:
        cur = conn.execute(
            "INSERT INTO items (machine_name, name, type) VALUES (?,?,?)",
            (mn, name, typ))
        conn.execute("INSERT INTO enrichment (item_id, genre) VALUES (?,?)",
                     (cur.lastrowid, db.tags_to_json(["Tech"])))
        conn.execute("INSERT INTO item_bundles VALUES (?,?)", (cur.lastrowid, gk))
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids

def test_duplicates_endpoint_groups_and_dismissal(tmp_path):
    dbp = tmp_path / "t.db"
    a, b = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    groups = client.get("/api/duplicates").get_json()["groups"]
    assert len(groups) == 1
    member = groups[0][0]
    assert member["id"] == a and member["genre"] == ["Tech"]
    assert member["bundles"] == ["Bundle One"] and member["edited"] is False
    assert client.post("/api/dismiss_pair",
                       json={"id_a": a, "id_b": b}).status_code == 200
    assert client.get("/api/duplicates").get_json()["groups"] == []

def test_merge_endpoint_and_guards(tmp_path):
    dbp = tmp_path / "t.db"
    a, b = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/merge", json={"keep_id": a, "drop_id": a}).status_code == 400
    assert client.post("/api/merge", json={"keep_id": a, "drop_id": 999}).status_code == 400
    assert client.post("/api/merge", json={"keep_id": a, "drop_id": b}).status_code == 200
    items = client.get("/api/items").get_json()["items"]
    assert len(items) == 1
    assert {bu["name"] for bu in items[0]["bundles"]} == {"Bundle One", "Bundle Two"}

def test_merge_endpoint_rejects_cross_type(tmp_path):
    dbp = tmp_path / "t.db"
    a, b = _seed_pair(dbp, type_b="audiobook")
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/merge", json={"keep_id": a, "drop_id": b})
    assert resp.status_code == 400
    assert "type" in resp.get_json()["error"]

def test_dismiss_pair_guards(tmp_path):
    dbp = tmp_path / "t.db"
    a, _b = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/dismiss_pair", json={"id_a": a, "id_b": a}).status_code == 400
    assert client.post("/api/dismiss_pair", json={"id_a": a, "id_b": 999}).status_code == 400

def test_index_has_duplicates_panel():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert '<div id="dupes-panel" hidden></div>' in html

def test_edit_normalizes_genre_case(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    conn = db.connect(dbp)
    conn.execute("UPDATE enrichment SET genre=? WHERE item_id=?",
                 (db.tags_to_json(["Science Fiction"]), item_id))
    conn.commit()
    conn.close()
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post(f"/api/items/{item_id}/edit", json={"fields": {
        "genre": ["science fiction", "cozy mystery", "Cozy Mystery"],
        "authors": ["lowercase name kept"]}}).status_code == 200
    item = client.get("/api/items").get_json()["items"][0]
    assert item["genre"] == ["Science Fiction", "Cozy Mystery"]
    assert item["authors"] == ["lowercase name kept"]  # people untouched

def test_autocomplete_supports_tag_counts():
    static = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
              / "static")
    ac = (static / "autocomplete.js").read_text(encoding="utf-8")
    # commit value must come from dataset.value, not textContent, so the
    # count span can't leak into the committed tag
    assert "dataset.value" in ac
    assert "textContent" not in ac.split("Enter")[1].split("Escape")[0]
    assert "ac-count" in ac
    assert "countsFn" in ac
    css = (static / "style.css").read_text(encoding="utf-8")
    assert ".ac-count" in css

def test_app_passes_tag_counts_to_autocomplete():
    static = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
              / "static")
    js = _viewer_js()
    assert "tagCounts" in js
    # both the tag editors and the chip filters supply a counts source
    assert js.count("tagCounts(") >= 2   # the two call sites

def test_fetch_url_falls_back_to_link_only(tmp_path, monkeypatch):
    dbp = tmp_path / "w.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    from humble_catalog import url_import
    def unavailable(conn, url):
        raise url_import.MetadataUnavailable("examplegames.com served no og:title")
    monkeypatch.setattr(url_import, "resolve", unavailable)

    resp = client.post(f"/api/items/{item_id}/fetch_url",
                       json={"url": "https://examplegames.com/p/1"})
    assert resp.status_code == 200
    cand = resp.get_json()["candidate"]
    assert cand["link_only"] is True
    assert cand["title"] == "All Systems Red"   # the item's existing name
    assert cand["url"] == "https://examplegames.com/p/1"
    assert cand["source"] == "examplegames.com"
    assert cand["authors"] is None
    assert "og:title" in cand["reason"]

def test_fetch_url_falls_back_on_network_error(tmp_path, monkeypatch):
    dbp = tmp_path / "w2.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    from humble_catalog import url_import
    def boom(conn, url):
        raise requests.ConnectionError("unreachable")
    monkeypatch.setattr(url_import, "resolve", boom)

    resp = client.post(f"/api/items/{item_id}/fetch_url",
                       json={"url": "https://examplegames.com/p/1"})
    assert resp.status_code == 200
    assert resp.get_json()["candidate"]["link_only"] is True

def test_fetch_url_rejects_bad_scheme_without_link_only(tmp_path, monkeypatch):
    dbp = tmp_path / "w3.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    from humble_catalog import url_import
    def reject(conn, url):
        raise ValueError("unsupported URL scheme 'javascript'")
    monkeypatch.setattr(url_import, "resolve", reject)

    resp = client.post(f"/api/items/{item_id}/fetch_url",
                       json={"url": "javascript:alert(1)"})
    assert resp.status_code == 400
    assert "candidate" not in resp.get_json()

def test_app_js_escapes_candidate_source():
    # source used to be a hardcoded literal from _HANDLERS; it is now a
    # hostname from a pasted URL, and urlparse does not validate netloc.
    app_js = _viewer_js()
    assert "(${c.source})" not in app_js
    assert "esc(c.source)" in app_js

def test_app_js_renders_link_only_candidates():
    app_js = _viewer_js()
    assert "link_only" in app_js
    assert "esc(c.reason)" in app_js

def test_bot_wall_403_becomes_link_only_end_to_end(tmp_path, monkeypatch):
    # The real-world case: a storefront answers the scrape with a 403 bot
    # wall. Covered in halves elsewhere (403 raises out of resolve, and a
    # RequestException degrades in the route); this pins the whole path.
    monkeypatch.setattr("time.sleep", lambda s: None)
    dbp = tmp_path / "w4.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    http = Mock()
    resp = Mock(status_code=403)
    resp.headers = {"Content-Type": "text/html"}
    resp.url = "https://examplegames.com/p/1"
    resp.raise_for_status = Mock(
        side_effect=requests.HTTPError("403 Client Error: Forbidden",
                                       response=Mock(status_code=403)))
    http.request.return_value = resp

    from humble_catalog import url_import
    real_resolve = url_import.resolve
    monkeypatch.setattr(url_import, "resolve",
                        lambda conn, url: real_resolve(conn, url, http=http))

    r = client.post(f"/api/items/{item_id}/fetch_url",
                    json={"url": "https://examplegames.com/p/1"})
    assert r.status_code == 200
    cand = r.get_json()["candidate"]
    assert cand["link_only"] is True
    assert cand["title"] == "All Systems Red"
    assert "403" in cand["reason"]
    # A bot wall is not retried: one request, no backoff.
    assert http.request.call_count == 1

def test_revert_leaves_fields_absent_from_an_older_snapshot(tmp_path):
    # pre_edit snapshots written before a field joined EDITABLE_FIELDS do
    # not contain its key. Treating that as NULL would silently wipe live
    # data on revert, so revert must skip keys it does not find.
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    # narrator is used rather than source_url because it is already in
    # EDITABLE_FIELDS: revert writes to it today, so a missing key is
    # genuinely destructive here and the test fails without the fix.
    conn = db.connect(dbp)
    conn.execute(
        "UPDATE enrichment SET series=?, narrator=?, pre_edit=? "
        "WHERE item_id=?",
        ("Edited Series", db.tags_to_json(["Sam Reader"]),
         json.dumps({"series": "Original Series"}), item_id))
    conn.commit()
    conn.close()

    assert client.post(f"/api/items/{item_id}/revert").status_code == 200

    conn = db.connect(dbp)
    row = conn.execute(
        "SELECT series, narrator FROM enrichment WHERE item_id=?",
        (item_id,)).fetchone()
    conn.close()
    assert row["series"] == "Original Series"          # present key: restored
    assert db.tags_from_json(row["narrator"]) == ["Sam Reader"]  # absent: kept

def test_edit_sets_source_url(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post(f"/api/items/{item_id}/edit",
                       json={"fields": {"source_url": "https://examplegames.com/p/1"}})
    assert resp.status_code == 200
    item = client.get("/api/items").get_json()["items"][0]
    assert item["source_url"] == "https://examplegames.com/p/1"

def test_edit_prepends_https_to_bare_source_url(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/edit",
                json={"fields": {"source_url": "examplegames.com/p/1"}})
    item = client.get("/api/items").get_json()["items"][0]
    assert item["source_url"] == "https://examplegames.com/p/1"

def test_edit_rejects_javascript_source_url(tmp_path):
    # The value is rendered into an href, and esc() does not filter schemes.
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post(f"/api/items/{item_id}/edit",
                       json={"fields": {"source_url": "javascript:alert(1)"}})
    assert resp.status_code == 400
    assert "scheme" in resp.get_json()["error"].lower()
    item = client.get("/api/items").get_json()["items"][0]
    assert item["source_url"] is None      # nothing was written

def test_edit_clears_source_url(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/edit",
                json={"fields": {"source_url": "https://examplegames.com/p/1"}})
    client.post(f"/api/items/{item_id}/edit",
                json={"fields": {"source_url": ""}})
    item = client.get("/api/items").get_json()["items"][0]
    assert item["source_url"] is None

def test_app_js_renders_source_link_as_trailing_icon():
    # The whole title used to be the anchor, so selecting or copying a
    # title risked navigating. The link is now a trailing glyph.
    app_js = _viewer_js()
    assert "src-link" in app_js
    assert "&#x2197;" in app_js
    # Built by nameExtras' named() helper, which writes it as both the
    # title and the aria-label -- see test_every_name_cell_glyph_has_an_
    # accessible_name for the rendered attributes.
    assert '"Open source page"' in app_js

def test_app_js_edits_source_url():
    app_js = _viewer_js()
    assert 'data-f="source_url"' in app_js

def test_set_user_tags(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post(f"/api/items/{item_id}/user-tags",
                       json={"tags": ["To Reread"]})
    assert resp.status_code == 200
    item = client.get("/api/items").get_json()["items"][0]
    assert item["user_tags"] == ["To Reread"]

def test_user_writes_do_not_mark_edited(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/user-tags", json={"tags": ["lent out"]})
    client.post(f"/api/items/{item_id}/comment", json={"comment": "A note."})
    item = client.get("/api/items").get_json()["items"][0]
    assert item["edited"] is False          # no snapshot: not a hand edit
    conn = db.connect(dbp)
    assert conn.execute("SELECT pre_edit FROM enrichment WHERE item_id=?",
                        (item_id,)).fetchone()["pre_edit"] is None

def test_set_user_tags_rejects_non_list(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post(f"/api/items/{item_id}/user-tags",
                       json={"tags": "nope"}).status_code == 400

def test_set_user_tags_empty_clears_to_null(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/user-tags", json={"tags": ["lent out"]})
    client.post(f"/api/items/{item_id}/user-tags", json={"tags": []})
    conn = db.connect(dbp)
    assert conn.execute("SELECT user_tags FROM items WHERE id=?",
                        (item_id,)).fetchone()["user_tags"] is None

def test_set_comment_strips_and_clears(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/comment",
                json={"comment": "  Gift from Sam.  "})
    assert client.get("/api/items").get_json()["items"][0]["user_comment"] \
        == "Gift from Sam."
    client.post(f"/api/items/{item_id}/comment", json={"comment": "   "})
    assert client.get("/api/items").get_json()["items"][0]["user_comment"] is None

def test_user_endpoints_404_on_missing_item(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/items/999/user-tags",
                       json={"tags": ["x"]}).status_code == 404
    assert client.post("/api/items/999/comment",
                       json={"comment": "x"}).status_code == 404

def test_rename_user_tag(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/user-tags", json={"tags": ["to reread"]})
    resp = client.post("/api/user-tags/rename",
                       json={"old": "to reread", "new": "reread"})
    assert resp.status_code == 200 and resp.get_json()["changed"] == 1
    assert client.get("/api/items").get_json()["items"][0]["user_tags"] \
        == ["reread"]

def test_rename_user_tag_unknown_404(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/user-tags/rename",
                       json={"old": "nope", "new": "x"}).status_code == 404

def test_rename_user_tag_blank_400(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/user-tags/rename",
                       json={"old": "", "new": "x"}).status_code == 400

def test_delete_user_tag(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/user-tags", json={"tags": ["lent out"]})
    resp = client.post("/api/user-tags/delete", json={"tag": "lent out"})
    assert resp.status_code == 200 and resp.get_json()["changed"] == 1
    assert client.get("/api/items").get_json()["items"][0]["user_tags"] == []

def test_delete_user_tag_unknown_404(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/user-tags/delete",
                       json={"tag": "nope"}).status_code == 404

def test_user_tag_rename_does_not_touch_genre(tmp_path):
    # the two vocabularies are separate pools: renaming a user tag must
    # never reach enrichment.genre, even on a same-spelled tag
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/choose", json={"candidate": 0})
    client.post(f"/api/items/{item_id}/edit", json={"fields": {"genre": ["SF"]}})
    client.post(f"/api/items/{item_id}/user-tags", json={"tags": ["SF"]})
    assert client.post("/api/user-tags/rename",
                       json={"old": "SF", "new": "space"}).get_json()["changed"] == 1
    item = client.get("/api/items").get_json()["items"][0]
    assert item["user_tags"] == ["space"]
    assert item["genre"] == ["SF"]          # genre pool untouched

def test_user_fields_never_reach_the_edit_endpoint():
    js = _viewer_js()
    # user_tags is destructured out before the /edit payload is assembled;
    # sending it would 400, since it is not in EDITABLE_FIELDS
    assert "const {user_tags, ...enrichmentTags} = editingTags;" in js
    assert "Object.assign(fields, enrichmentTags);" in js
    # the note must NOT carry .edit-field, or the selector that builds the
    # /edit payload would sweep it up
    assert 'class="edit-comment"' in js
    assert "edit-field edit-comment" not in js

def test_save_skips_edit_when_only_user_fields_changed():
    js = _viewer_js()
    # every /edit call snapshots the row and marks it hand-edited, so a
    # save that changed only the note or the user tags must not post it
    assert "function shouldPostEnrichmentEdit(item, fields)" in js
    assert "if (shouldPostEnrichmentEdit(items.find(i => i.id === +id), fields)) {" in js

def test_index_has_user_columns():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert ('<th class="col-tags">My tags</th>'
            '<th class="col-notes">Notes</th>') in html

def _index_html():
    return (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")

def test_user_tags_filter_is_registered():
    # one registry entry + one input is the whole contract for a new
    # filterable column; the wiring loops pick it up from there
    assert 'data-field="user_tags"' in _index_html()
    assert '<input id="f-user-tags"' in _index_html()
    assert "user_tags: {accessor: i => i.user_tags," in _viewer_js()

def test_user_tags_filter_pool_is_separate_from_genre():
    js = _viewer_js()
    # genre and user tags are independent pools: a genre "Fantasy" and a
    # personal tag "fantasy" mean different things and must stay
    # separately selectable, so no accessor may union the two
    assert "[...i.genre, ...i.user_tags]" not in js
    assert "[...i.user_tags, ...i.genre]" not in js

def test_tag_badges_tolerates_a_missing_field():
    # render() runs before loadReview/loadDupes/refreshStats, so an
    # exception here blanks the whole page, not just one column. An item
    # served without user_tags (an older API, a partial payload) must not
    # be able to do that.
    js = _viewer_js()
    assert "const tagBadges = (arr) =>\n  (arr || []).map(" in js

def test_notes_filter_is_registered():
    assert 'data-field="user_comment"' in _index_html()
    assert '<input id="f-notes"' in _index_html()
    assert "user_comment: {accessor: i => i.user_comment ? [i.user_comment] : []," in _viewer_js()

def test_notes_filter_has_no_autocomplete():
    # a dropdown suggesting whole note bodies would be useless
    assert "if (!f.textOnly) Autocomplete.attach(" in _viewer_js()

def test_chip_filter_text_is_lowercased_on_input():
    # passesChipFilters lowercases the value but not f.text, so every
    # place that writes f.text has to lowercase it first
    js = _viewer_js()
    assert "f.text = input.value.trim().toLowerCase();" in js
    assert "f.text = value.toLowerCase();" in js

def test_search_box_is_still_names_only():
    # v1.12 narrowed it deliberately; neither the notes filter nor fuzzy
    # matching may widen it. Asserted against the source rather than
    # behaviour only for the negative half -- the positive half moved to
    # test_webapp_js.py, where it runs the real visible().
    js = _viewer_js()
    assert "i.user_comment.toLowerCase().includes(q)" not in js

def test_bulk_add_and_remove(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/user-tags/bulk", json={
        "ids": [item_id], "tag": "to reread", "action": "add"})
    assert resp.status_code == 200 and resp.get_json()["ids"] == [item_id]
    assert client.get("/api/items").get_json()["items"][0]["user_tags"] \
        == ["to reread"]
    # adding again changes nothing
    assert client.post("/api/user-tags/bulk", json={
        "ids": [item_id], "tag": "to reread",
        "action": "add"}).get_json()["ids"] == []
    resp = client.post("/api/user-tags/bulk", json={
        "ids": [item_id], "tag": "to reread", "action": "remove"})
    assert resp.get_json()["ids"] == [item_id]
    assert client.get("/api/items").get_json()["items"][0]["user_tags"] == []

def test_bulk_does_not_mark_rows_edited(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post("/api/user-tags/bulk", json={
        "ids": [item_id], "tag": "lent out", "action": "add"})
    assert client.get("/api/items").get_json()["items"][0]["edited"] is False

def test_bulk_validation(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    bad = [
        {"ids": [], "tag": "x", "action": "add"},              # no ids
        {"ids": "nope", "tag": "x", "action": "add"},          # ids not a list
        {"ids": [item_id], "tag": "  ", "action": "add"},      # blank tag
        {"ids": [item_id], "tag": "x", "action": "replace"},   # bad verb
        {"ids": [item_id], "tag": "x"},                        # no verb
    ]
    for payload in bad:
        assert client.post("/api/user-tags/bulk",
                           json=payload).status_code == 400, payload

def test_bulk_ignores_unknown_ids(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    # a stale page can hold ids that no longer exist; that is not an error
    resp = client.post("/api/user-tags/bulk", json={
        "ids": [item_id, 999], "tag": "to reread", "action": "add"})
    assert resp.status_code == 200 and resp.get_json()["ids"] == [item_id]

def test_undoing_a_bulk_add_leaves_rows_that_already_had_the_tag(tmp_path):
    # The add-side asymmetry. The item starts with the tag, so the bulk
    # add reports no change, and the undo over that empty list must not
    # take the tag away.
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/user-tags", json={"tags": ["lent out"]})
    changed = client.post("/api/user-tags/bulk", json={
        "ids": [item_id], "tag": "lent out", "action": "add"}).get_json()["ids"]
    assert changed == []
    # an undo over no ids is rejected by the route's own validation, which
    # is why the viewer never offers one -- see the JS test
    assert client.post("/api/user-tags/bulk", json={
        "ids": changed, "tag": "lent out",
        "action": "remove"}).status_code == 400
    assert client.get("/api/items").get_json()["items"][0]["user_tags"] \
        == ["lent out"]

def test_bulk_bar_is_present():
    html = _index_html()
    assert '<input id="bulk-tag"' in html
    assert '<button id="bulk-add">' in html
    assert '<button id="bulk-remove">' in html
    assert '<button id="bulk-undo" hidden>' in html

def test_undo_does_not_arm_before_firing():
    # armOrFire is for the destructive direction. Requiring two clicks to
    # recover from a mistake points the friction the wrong way.
    js = _viewer_js()
    body = js[js.index("async function undoBulk()"):]
    assert "armOrFire" not in body[:body.index("\n}")]

def test_bulk_remove_is_gated_on_an_active_filter():
    # user_tags has no pre_edit snapshot, so a bulk remove cannot be undone
    assert "removeBtn.disabled = !tag || count === 0 || !filtered;" in _viewer_js()

def test_bulk_bar_lives_outside_the_table():
    # the table rebuilds via innerHTML; controls inside it would be destroyed
    html = _index_html()
    assert html.index('id="bulk-bar"') < html.index('<table id="catalog">')

def _static_dir():
    return Path(__file__).parent.parent / "humble_catalog" / "webapp" / "static"

def test_index_links_both_favicons():
    html = _index_html()
    # Browsers that understand SVG favicons take the first and ignore the
    # second; the PNG covers the rest. Absolute /static/ paths keep the
    # bare /favicon.ico request path out of it, so no Flask route is
    # needed - static_url_path="/static" already serves both.
    assert ('<link rel="icon" href="/static/favicon.svg" '
            'type="image/svg+xml">') in html
    assert ('<link rel="icon" href="/static/favicon-32.png" '
            'type="image/png" sizes="32x32">') in html
    # both files must actually ship, not just be referenced
    static = _static_dir()
    assert (static / "favicon.svg").read_text(encoding="utf-8").strip()
    assert (static / "favicon-32.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

def test_favicon_follows_the_os_theme():
    svg = (_static_dir() / "favicon.svg").read_text(encoding="utf-8")
    # The tab icon renders outside the page's CSS cascade, so it cannot
    # read style.css or the data-theme attribute the toggle sets. Its own
    # media query is the only mechanism available.
    assert "@media (prefers-color-scheme:dark)" in svg


def test_index_loads_the_fuzzy_scorer_before_the_app():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert '<script src="/static/fuzzy.js"></script>' in html
    # order matters: app.js references Fuzzy at load time
    assert html.index("fuzzy.js") < html.index("app.js")

def test_override_round_trip(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/edit",
                json={"fields": {"series": "Harbor Tales"}})
    assert client.post(f"/api/items/{item_id}/override",
                       json={"override": True}).status_code == 200
    assert client.get("/api/items").get_json()["items"][0]["override"] is True
    assert client.post(f"/api/items/{item_id}/override",
                       json={"override": False}).status_code == 200
    assert client.get("/api/items").get_json()["items"][0]["override"] is False

def test_override_rejected_on_a_row_that_was_never_edited(tmp_path):
    # a machine-enriched row is already eligible for enrichment, so an
    # override on it is meaningless rather than harmless
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post(f"/api/items/{item_id}/override",
                       json={"override": True}).status_code == 400

def test_override_rejects_a_non_boolean(tmp_path):
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/edit",
                json={"fields": {"series": "Harbor Tales"}})
    assert client.post(f"/api/items/{item_id}/override",
                       json={"override": "yes"}).status_code == 400

def test_revert_of_a_re_enriched_row_hands_the_edit_back(tmp_path):
    # authorship flips: this row's snapshot holds the TYPED values, so
    # reverting makes it hand-edited again and drops any queued override
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    client.post(f"/api/items/{item_id}/edit",
                json={"fields": {"genre": ["Hand Typed"]}})
    client.post(f"/api/items/{item_id}/choose", json={"candidate": 0})
    item = client.get("/api/items").get_json()["items"][0]
    assert item["edited"] is False and item["re_enriched"] is True
    client.post(f"/api/items/{item_id}/revert")
    item = client.get("/api/items").get_json()["items"][0]
    assert item["edited"] is True and item["re_enriched"] is False
    assert item["genre"] == ["Hand Typed"] and item["override"] is False

def test_post_export_csv_narrows_the_columns(tmp_path):
    dbp = tmp_path / "t.db"
    ids = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/export.csv",
                       json={"ids": ids, "columns": ["type", "title"]})
    assert resp.status_code == 200
    header = resp.get_data().decode("utf-8-sig").splitlines()[0]
    assert header == "title,type"  # canonical, not requested, order

def test_post_export_drops_unknown_column_names(tmp_path):
    # Silently, unlike the CLI: a stale hc-export-columns in someone's
    # browser can outlive a COLUMNS rename by months, and a 500 there
    # punishes the user for the schema's history.
    dbp = tmp_path / "t.db"
    ids = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/export.csv",
                       json={"ids": ids, "columns": ["title", "not_a_column"]})
    assert resp.status_code == 200
    assert resp.get_data().decode("utf-8-sig").splitlines()[0] == "title"

def test_post_export_empty_or_all_unknown_columns_means_everything(tmp_path):
    dbp = tmp_path / "t.db"
    ids = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    for cols in ([], ["nope"]):
        resp = client.post("/api/export.csv",
                           json={"ids": ids, "columns": cols})
        assert resp.status_code == 200
        header = resp.get_data().decode("utf-8-sig").splitlines()[0]
        assert header.split(",") == list(export.COLUMNS)

def test_post_export_rejects_a_non_list_columns(tmp_path):
    dbp = tmp_path / "t.db"
    ids = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/export.csv",
                       json={"ids": ids, "columns": "title"})
    assert resp.status_code == 400

def test_post_export_xlsx_narrows_the_columns(tmp_path):
    dbp = tmp_path / "t.db"
    ids = _seed_pair(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/export.xlsx",
                       json={"ids": ids, "columns": ["type", "title"]})
    assert resp.status_code == 200
    ws = load_workbook(io.BytesIO(resp.get_data())).active
    assert [c.value for c in ws[1]] == ["title", "type"]

def test_header_stacks_above_the_sticky_table_head():
    # <header> is a static flex item WITH a z-index, so it establishes a
    # stacking context: every z-index inside it -- the column picker's
    # included -- is ordered only within the header, and externally the
    # whole header is one layer. The sticky <th> sits in the root context
    # (its #table-wrap ancestor has z-index auto), so if the header's
    # layer is the lower of the two, the sticky cells paint over anything
    # the header contains and no z-index on the picker can rescue it.
    # Pinned as a relationship, not as literal values, because that is the
    # part that has to stay true.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    def z(selector):
        block = re.search(re.escape(selector) + r"\s*\{[^}]*?z-index:\s*(\d+)",
                          css, re.S)
        assert block, f"no z-index found for {selector}"
        return int(block.group(1))
    assert z("header") > z("#catalog thead th")
    # and the autocomplete list, which hangs off <body> to escape both
    # clipping and this very stacking problem, stays above the header
    assert z(".ac-list") > z("header")

def test_api_stats_returns_every_section_with_counts(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    body = client.get("/api/stats").get_json()
    assert body["total"] == 1
    assert [s["key"] for s in body["sections"]] == [
        "type", "rating", "status", "enrichment", "gaps", "genre"]
    rows = {s["key"]: {r["label"]: r["count"] for r in s["rows"]}
            for s in body["sections"]}
    assert rows["type"]["E-books"] == 1
    assert rows["enrichment"]["Low confidence"] == 1

def test_api_stats_matches_the_report_over_the_same_db(tmp_path):
    # the route must be a reshaping of report(), never a second count
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    conn = db.connect(dbp)
    sections, total = stats.report(db.fetch_items(conn))
    conn.close()

    body = client.get("/api/stats").get_json()
    assert body["total"] == total
    assert body["sections"] == [
        {"key": key, "label": label,
         "rows": [{"label": rl, "count": n} for rl, n in rows]}
        for key, label, rows in sections]

def test_api_stats_of_an_empty_catalog_is_well_formed(tmp_path):
    dbp = tmp_path / "t.db"
    db.connect(str(dbp)).close()
    client = create_app(db_path=str(dbp)).test_client()

    body = client.get("/api/stats").get_json()
    assert body["total"] == 0
    assert len(body["sections"]) == 6

def test_index_offers_the_rating_and_enrichment_filters():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert '<select id="f-rating"' in html    # carries an aria-label too
    assert '<option value="5">★5</option>' in html
    # the enrichment section's four rows each jump to their own state, so
    # a row reading "Unmatched 4" cannot land on review's wider 8
    assert '<option value="matched">Matched</option>' in html
    assert '<option value="low_confidence">Low-confidence match</option>' in html
    assert '<option value="unmatched">Unmatched</option>' in html
    assert '<option value="pending">Pending enrichment</option>' in html
    assert '<option value="review">Needs review</option>' in html   # union stays

def test_stats_controls_are_themed_not_browser_default():
    # Same bug the form controls had: an unstyled <button> keeps the
    # browser's grey default, which glares on the dark panel. Caught in a
    # real browser -- the JS harness has no computed styles.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    assert ".stat-jump, .stat-show-all, .stat-edit-tags, .bundle-jump {" in css
    # must use the theme variable, never a literal, or one palette breaks
    assert "color: var(--accent);" in css


def _bundle_app(tmp_path):
    dbp = tmp_path / "catalog.db"
    conn = db.connect(dbp)
    conn.execute("INSERT INTO items (machine_name, name, type) "
                 "VALUES ('owned_examplepress', 'Unrelated Book', 'ebook')")
    conn.commit()
    conn.close()
    return create_app(db_path=str(dbp)).test_client()


_FAKE_BUNDLE = {
    "basic_data": {"human_name": "Bundle One", "currency": "EUR"},
    "tier_item_data": {"owned_examplepress": {"human_name": "Unrelated Book"},
                       "new_examplepress": {"human_name": "The Hollow Crypt"}},
    "tier_display_data": {"initial": {
        "tier_item_machine_names": ["owned_examplepress", "new_examplepress"]}},
    "tier_pricing_data": {"initial": {
        "price|money": {"currency": "EUR", "amount": 12.0}}},
}


def test_bundle_preview_route_returns_the_report(tmp_path, monkeypatch):
    from humble_catalog import bundle_preview
    monkeypatch.setattr(bundle_preview, "fetch_bundle",
                        lambda url, http=None: _FAKE_BUNDLE)
    client = _bundle_app(tmp_path)
    resp = client.post("/api/bundle-preview", json={
        "url": "https://www.humblebundle.com/books/bundle-one-books"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "Bundle One"
    assert body["currency"] == "EUR"
    assert body["tiers"][0]["owned"] == 1
    assert body["tiers"][0]["new"] == 1


def test_bundle_preview_route_echoes_the_url_it_was_given(tmp_path, monkeypatch):
    from humble_catalog import bundle_preview
    monkeypatch.setattr(bundle_preview, "fetch_bundle",
                        lambda url, http=None: _FAKE_BUNDLE)
    url = "https://www.humblebundle.com/books/bundle-one-books"
    body = _bundle_app(tmp_path).post(
        "/api/bundle-preview", json={"url": url}).get_json()
    assert body["url"] == url


def test_bundle_preview_route_rejects_a_missing_url(tmp_path):
    resp = _bundle_app(tmp_path).post("/api/bundle-preview", json={})
    assert resp.status_code == 400
    assert "url required" in resp.get_json()["error"]


def test_bundle_preview_route_rejects_a_non_humble_url(tmp_path):
    resp = _bundle_app(tmp_path).post(
        "/api/bundle-preview", json={"url": "https://example.test/books/x"})
    assert resp.status_code == 400
    assert "not a HumbleBundle URL" in resp.get_json()["error"]


def test_bundle_preview_route_reports_a_dead_page_as_a_gateway_error(
        tmp_path, monkeypatch):
    from humble_catalog import bundle_preview

    def boom(url, http=None):
        raise requests.HTTPError("404 Client Error")

    monkeypatch.setattr(bundle_preview, "fetch_bundle", boom)
    resp = _bundle_app(tmp_path).post("/api/bundle-preview", json={
        "url": "https://www.humblebundle.com/books/gone"})
    assert resp.status_code == 502
    assert "404" in resp.get_json()["error"]


def test_bundle_preview_route_is_not_reachable_by_get(tmp_path):
    # A bundle URL in a query string would reach access logs and browser
    # history, and which bundles are being eyed is the same class of
    # information as which books are owned.
    resp = _bundle_app(tmp_path).get(
        "/api/bundle-preview?url=https://www.humblebundle.com/books/x")
    assert resp.status_code == 405


def test_index_has_the_bundle_preview_panel_and_input():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert '<div id="bundle-panel"' in html
    assert '<input id="bundle-url"' in html
    assert '<button id="bundle-go"' in html


def test_bundle_panel_scrolls_internally_like_the_other_panels():
    # Without this a 35-item adds list grows the panel without bound. It
    # can no longer push the table off screen -- they are in different
    # sections now, which is why the max-height half of this rule is gone
    # -- but a panel taller than the viewport still has to scroll itself
    # rather than the page. The JS harness has no computed styles, so this
    # is asserted against the stylesheet.
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    assert ("#review-panel, #dupes-panel, #stats-panel, #bundle-panel "
            "{ flex: 0 1 auto;") in css
    assert "overflow: auto; }" in css


# --- Host validation (DNS rebinding defence) -------------------------------

def test_host_is_loopback_accepts_only_loopback_authorities():
    # Unit-level because the missing-Host case cannot be produced through
    # the test client, which always synthesises one.
    from humble_catalog.webapp import host_is_loopback
    assert host_is_loopback("127.0.0.1:8087")
    assert host_is_loopback("localhost:8087")
    assert host_is_loopback("localhost")
    assert host_is_loopback("[::1]:8087")
    assert host_is_loopback("[::1]")
    assert host_is_loopback("LOCALHOST:8087")      # Host is case-insensitive
    assert not host_is_loopback("evil.example.com")
    assert not host_is_loopback("evil.example.com:8087")
    assert not host_is_loopback("127.0.0.1.evil.com")
    assert not host_is_loopback("localhost.evil.com")
    assert not host_is_loopback("192.168.1.10:8087")
    assert not host_is_loopback("")
    assert not host_is_loopback(None)


def test_reads_are_refused_for_a_rebound_hostname(tmp_path):
    # The attack this closes: a page on evil.com whose DNS is re-pointed at
    # 127.0.0.1 becomes same-origin with the viewer, and same-origin policy
    # stops protecting the catalog. The Host header still says evil.com.
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    resp = client.get("/api/items", headers={"Host": "evil.example.com"})
    assert resp.status_code == 403
    assert b"All Systems Red" not in resp.data


def test_writes_are_refused_before_the_body_is_even_parsed(tmp_path):
    # 403 rather than 415/404 proves the check runs ahead of routing, so a
    # foreign host cannot reach a handler by getting the content type right.
    dbp = tmp_path / "t.db"
    item_id = _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    resp = client.post(f"/api/items/{item_id}/rating", json={"rating": 5},
                       headers={"Host": "evil.example.com"})
    assert resp.status_code == 403


def test_loopback_callers_are_unaffected(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    for host in ["127.0.0.1:8087", "localhost:8087", "[::1]:8087"]:
        client = create_app(db_path=str(dbp)).test_client()
        resp = client.get("/api/items", headers={"Host": host})
        assert resp.status_code == 200, host
        assert resp.get_json()["items"][0]["name"] == "All Systems Red"


def test_index_loads_the_viewer_scripts_in_dependency_order():
    from tests.js_harness import VIEWER_JS
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    # Classic scripts run in <script> order and share one global scope,
    # so order is a real dependency, not a formatting choice: app.js's
    # helpers must exist before any section defines a renderer that calls
    # them, and shell.js boots last because load() calls every renderer.
    positions = [html.index(f'/static/{p.name}"') for p in VIEWER_JS]
    assert positions == sorted(positions)
    assert VIEWER_JS[0].name == "app.js"
    assert VIEWER_JS[-1].name == "shell.js"


def test_hidden_sections_are_actually_hidden():
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    # A section carries display:flex, which outranks the UA stylesheet's
    # [hidden] { display: none } and paints every section at once. The JS
    # stays correct throughout -- el.hidden really is true -- so no DOM
    # assertion can catch this; only the explicit guard prevents it.
    assert 'section[id^="section-"][hidden] { display: none; }' in css


def test_filter_chips_live_outside_the_collapsible_sidebar():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    # a collapsed sidebar must never hide a filter that is narrowing the
    # table, so the summary renders in the main column, not the aside
    aside = html[html.index('<aside id="filters"'):html.index("</aside>")]
    assert 'id="filter-chips"' not in aside
    assert 'id="filter-chips"' in html
    # search likewise stays in the header, above the tabs
    assert html.index('id="search-wrap"') < html.index('<nav id="tabs"')


def test_collapsing_the_sidebar_does_not_collapse_the_table():
    css = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
           / "static" / "style.css").read_text(encoding="utf-8")
    # display:none takes the aside out of grid layout, so a collapsed
    # layout declaring two tracks auto-places the table into the FIRST.
    # With a first track of 0 the table went to zero width -- collapsing
    # the filters collapsed the catalog. One track is the fix.
    assert "#library-layout.collapsed { grid-template-columns: 1fr; }" in css
    assert "grid-template-columns: 0 1fr" not in css

def test_api_keys_matches_the_report_over_the_same_db(tmp_path):
    # A reshaping of report(), never a second count -- the /api/stats rule.
    dbp = tmp_path / "t.db"
    conn = db.connect(dbp)
    conn.execute("INSERT INTO bundles (gamekey, name, url, purchased_at) "
                 "VALUES ('kv789', 'Humble Game Bundle: Key Vault', "
                 "'https://example.invalid/kv789', '2024-01-02T00:00:00')")
    conn.execute(
        "INSERT INTO external_keys "
        "(gamekey, machine_name, human_name, key_type, raw) "
        "VALUES ('kv789', 'cindervale_ex', 'Cinder Vale', 'steam', ?)",
        (json.dumps({"human_name": "Cinder Vale", "key_type": "steam",
                     "machine_name": "cindervale_ex"}),))
    conn.commit()
    conn.close()
    client = create_app(db_path=str(dbp)).test_client()

    body = client.get("/api/keys").get_json()
    assert body["total"] == 1
    assert body["counts"]["uncheckable"] == 1     # steam never imported
    assert [r["product"] for r in body["rows"]] == ["Cinder Vale"]

def test_api_keys_of_an_empty_catalog_is_well_formed(tmp_path):
    dbp = tmp_path / "t.db"
    db.connect(str(dbp)).close()
    client = create_app(db_path=str(dbp)).test_client()

    body = client.get("/api/keys").get_json()
    assert body["total"] == 0
    assert body["rows"] == []
    assert set(body["counts"]) == {
        "matched", "unredeemed", "uncertain", "uncheckable"}


def _keyed_db(tmp_path, hidden=()):
    """A catalog with one bundle and one steam key, plus any hides."""
    dbp = tmp_path / "t.db"
    conn = db.connect(dbp)
    conn.execute("INSERT INTO bundles (gamekey, name, url) VALUES "
                 "('kv789', 'Humble Game Bundle: Key Vault', "
                 "'https://example.invalid/kv789')")
    conn.execute("INSERT INTO external_keys "
                 "(gamekey, machine_name, human_name, key_type, raw) "
                 "VALUES ('kv789', 'cindervale_steam', 'Cinder Vale', "
                 "'steam', '{}')")
    for machine in hidden:
        conn.execute(
            "INSERT INTO hidden_keys (gamekey, machine_name, hidden_at) "
            "VALUES ('kv789', ?, '2026-07-31T00:00:00+00:00')", (machine,))
    conn.commit()
    conn.close()
    return dbp


def _hides(dbp):
    conn = db.connect(dbp)
    try:
        return [(r["machine_name"], r["hidden_at"]) for r in
                conn.execute("SELECT machine_name, hidden_at FROM hidden_keys")]
    finally:
        conn.close()


def test_hiding_a_key_records_it(tmp_path):
    dbp = _keyed_db(tmp_path)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/keys/hide", json={
        "gamekey": "kv789", "machine_name": "cindervale_steam"})
    assert resp.status_code == 200
    (machine, hidden_at), = _hides(dbp)
    assert machine == "cindervale_steam"
    # Stamped server-side, so a wrong client clock cannot write a wrong date.
    assert hidden_at.startswith("20")


def test_hiding_twice_keeps_the_first_timestamp(tmp_path):
    # The date answers "when did I decide this"; a second click is not a
    # second decision, so INSERT OR IGNORE rather than OR REPLACE.
    dbp = _keyed_db(tmp_path)
    client = create_app(db_path=str(dbp)).test_client()
    body = {"gamekey": "kv789", "machine_name": "cindervale_steam"}
    client.post("/api/keys/hide", json=body)
    first = _hides(dbp)[0][1]
    client.post("/api/keys/hide", json=body)
    assert _hides(dbp)[0][1] == first


def test_hiding_an_unknown_key_is_rejected(tmp_path):
    dbp = _keyed_db(tmp_path)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/keys/hide", json={
        "gamekey": "kv789", "machine_name": "no_such_steam"})
    assert resp.status_code == 400
    assert _hides(dbp) == []


def test_hiding_needs_both_identifiers(tmp_path):
    dbp = _keyed_db(tmp_path)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/keys/hide", json={}).status_code == 400
    assert client.post("/api/keys/hide",
                       json={"gamekey": "kv789"}).status_code == 400
    assert client.post("/api/keys/hide", json={
        "gamekey": "kv789", "machine_name": ""}).status_code == 400


def test_unhiding_works_on_a_hide_whose_key_is_gone(tmp_path):
    # Deliberately asymmetric with hide. Requiring the key to exist would
    # make exactly the stale hides un-unhideable -- and every hide is
    # stale straight after a reset, which is when they most need removing.
    dbp = _keyed_db(tmp_path, hidden=["ghost_steam"])
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/keys/unhide", json={
        "gamekey": "kv789", "machine_name": "ghost_steam"})
    assert resp.status_code == 200
    assert _hides(dbp) == []


def test_unhiding_something_not_hidden_is_a_no_op(tmp_path):
    dbp = _keyed_db(tmp_path)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/keys/unhide", json={
        "gamekey": "kv789", "machine_name": "never_hidden"})
    assert resp.status_code == 200


def test_a_hidden_key_reaches_the_api_annotated(tmp_path):
    dbp = _keyed_db(tmp_path, hidden=["cindervale_steam"])
    client = create_app(db_path=str(dbp)).test_client()
    rows = client.get("/api/keys").get_json()["rows"]
    assert [r["hidden_at"] for r in rows] == ["2026-07-31T00:00:00+00:00"]


def _seed_editions(dbp):
    """An ebook, its audiobook, and an unrelated row."""
    conn = db.connect(dbp)
    for mn, name, typ in [("e1", "Salt and Sextant", "ebook"),
                          ("a1", "Salt and Sextant Audiobook", "audiobook"),
                          ("u1", "Unrelated Book", "ebook")]:
        cur = conn.execute(
            "INSERT INTO items (machine_name, name, type) VALUES (?,?,?)",
            (mn, name, typ))
        conn.execute("INSERT INTO enrichment (item_id) VALUES (?)",
                     (cur.lastrowid,))
    conn.commit()
    conn.close()


def test_api_items_attaches_edition_siblings(tmp_path):
    dbp = tmp_path / "t.db"
    _seed_editions(dbp)
    client = create_app(db_path=str(dbp)).test_client()

    by_name = {i["name"]: i for i in
               client.get("/api/items").get_json()["items"]}

    ebook = by_name["Salt and Sextant"]
    assert [s["type"] for s in ebook["editions"]] == ["audiobook"]
    assert ebook["editions"][0]["name"] == "Salt and Sextant Audiobook"

    audio = by_name["Salt and Sextant Audiobook"]
    assert [s["type"] for s in audio["editions"]] == ["ebook"]
    assert audio["editions"][0]["id"] == ebook["id"]

    # Absent, not empty, for a row with no sibling -- on a real catalog
    # that is nearly every row of a ~1.3 MiB payload.
    assert "editions" not in by_name["Unrelated Book"]


def test_export_rows_carry_no_edition_field(tmp_path):
    # fetch_items is shared with CSV/XLSX export "so the two
    # serializations cannot drift". An edition link is a derived view,
    # not a stored fact, so it is attached in the route and must not
    # reach the export's row source.
    dbp = tmp_path / "t.db"
    _seed_editions(dbp)
    conn = db.connect(dbp)
    assert all("editions" not in row for row in db.fetch_items(conn))


# --- The Humble Choice route --------------------------------------------

_CHOICE_HUB = {
    "baseSubscriptionPrice|money": {"currency": "EUR", "amount": 11.99},
    "contentChoiceOptions": {
        "title": "January 2031",
        "contentChoiceState": {"initial": {"choices_made": []}},
        "contentChoiceData": {"extras": [], "game_data": {
            "lanternlockpick_choice": {"title": "Lantern & Lockpick",
                                       "delivery_methods": ["steam"]}}}},
}


def test_choice_preview_returns_the_report(tmp_path, monkeypatch):
    from humble_catalog import choice_preview
    dbp = tmp_path / "t.db"
    _seed(dbp)
    monkeypatch.setattr(choice_preview, "fetch_choice",
                        lambda client=None: _CHOICE_HUB)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/choice-preview", json={})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Humble Choice: January 2031"


def test_choice_preview_refuses_a_bad_body_before_fetching(tmp_path,
                                                          monkeypatch):
    # Issue #20: a malformed request reached fetch_choice, which builds a
    # client from saved cookies -- a Playwright launch -- and answered 500
    # wherever no browser is installed. The refusal has to come first.
    from humble_catalog import choice_preview
    calls = []
    monkeypatch.setattr(choice_preview, "fetch_choice",
                        lambda *a, **k: calls.append(1))
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    bad = [dict(json=[1, 2, 3]), dict(json="hello"),
           dict(data="{not json", content_type="application/json"), dict()]
    for kwargs in bad:
        resp = client.post("/api/choice-preview", **kwargs)
        assert resp.status_code == 400, kwargs
        assert resp.get_json()["error"], kwargs
    assert calls == []


def test_choice_preview_answers_409_for_a_stale_session(tmp_path, monkeypatch):
    # 409, not 401: nothing about the viewer's own authorization is wrong,
    # and the fix is a command the owner runs elsewhere. Reusing 401 would
    # invite someone to add a login prompt to the viewer -- and
    # manual_login blocks on a browser window the server cannot see.
    from humble_catalog import choice_preview, humble_api

    dbp = tmp_path / "t.db"
    _seed(dbp)

    def stale(client=None):
        raise humble_api.NotLoggedIn("no usable HumbleBundle session")

    monkeypatch.setattr(choice_preview, "fetch_choice", stale)
    client = create_app(db_path=str(dbp)).test_client()
    resp = client.post("/api/choice-preview", json={})
    assert resp.status_code == 409
    assert "login" in resp.get_json()["error"]


def test_choice_preview_answers_400_for_a_month_it_cannot_read(tmp_path,
                                                               monkeypatch):
    from humble_catalog import choice_preview
    dbp = tmp_path / "t.db"
    _seed(dbp)

    def boom(client=None):
        raise ValueError("no Humble Choice month on offer")

    monkeypatch.setattr(choice_preview, "fetch_choice", boom)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/choice-preview", json={}).status_code == 400


def test_choice_preview_answers_502_for_an_upstream_failure(tmp_path,
                                                            monkeypatch):
    from humble_catalog import choice_preview
    dbp = tmp_path / "t.db"
    _seed(dbp)

    def boom(client=None):
        raise requests.ConnectionError("humblebundle.com unreachable")

    monkeypatch.setattr(choice_preview, "fetch_choice", boom)
    client = create_app(db_path=str(dbp)).test_client()
    assert client.post("/api/choice-preview", json={}).status_code == 502


class _StubRunner:
    """Stands in for JobRunner so no test spawns a real command."""

    def __init__(self):
        self.started = []
        self.busy = False
        self.cancelled = False

    def start(self, command, options=None, args=(), cleanup=None, force=False):
        from humble_catalog import jobs
        jobs.argv(command, options)          # keep the whitelist in the path
        if self.busy:
            raise jobs.Busy("harvest is already running")
        self.started.append((command, options, force))
        return {"command": command, "options": options or {},
                "started_at": "2026-08-04T00:00:00+00:00"}

    def cancel(self):
        self.cancelled = True
        return True

    def state(self):
        return {"running": None, "log": ["Bundle 1/2: The Hollow Crypt"],
                "last": {"command": "reparse", "state": "done",
                         "exit_code": 0, "finished_at": "2026-08-04T00:00:01"}}


def _job_client(tmp_path):
    app = create_app(db_path=str(tmp_path / "catalog.db"))
    runner = _StubRunner()
    app.config["JOB_RUNNER"] = runner
    return app.test_client(), runner


def test_start_a_job(tmp_path):
    client, runner = _job_client(tmp_path)
    resp = client.post("/api/jobs/start",
                       json={"command": "harvest",
                             "options": {"ignore_quota": True}})
    assert resp.status_code == 202
    assert runner.started == [("harvest", {"ignore_quota": True}, False)]


def test_start_refuses_a_command_outside_the_whitelist(tmp_path):
    client, _ = _job_client(tmp_path)
    # reset is a handoff command, never a background job.
    for command in ("reset", "restore", "login", "rm -rf /"):
        resp = client.post("/api/jobs/start", json={"command": command})
        assert resp.status_code == 400, command


def test_start_refuses_a_non_boolean_option(tmp_path):
    client, _ = _job_client(tmp_path)
    resp = client.post("/api/jobs/start",
                       json={"command": "harvest",
                             "options": {"ignore_quota": "yes"}})
    assert resp.status_code == 400


def test_start_answers_409_when_busy(tmp_path):
    client, runner = _job_client(tmp_path)
    runner.busy = True
    resp = client.post("/api/jobs/start", json={"command": "harvest"})
    assert resp.status_code == 409
    assert "already running" in resp.get_json()["error"]


def test_start_needs_a_command(tmp_path):
    client, _ = _job_client(tmp_path)
    assert client.post("/api/jobs/start", json={}).status_code == 400
    assert client.post("/api/jobs/start", json=[]).status_code == 400


def test_start_refuses_options_that_are_not_an_object(tmp_path):
    client, _ = _job_client(tmp_path)
    resp = client.post("/api/jobs/start",
                       json={"command": "harvest", "options": ["--rm-rf"]})
    assert resp.status_code == 400


def test_start_passes_force_through(tmp_path):
    client, runner = _job_client(tmp_path)
    client.post("/api/jobs/start", json={"command": "reparse", "force": True})
    assert runner.started == [("reparse", {}, True)]


def test_cancel(tmp_path):
    client, runner = _job_client(tmp_path)
    assert client.post("/api/jobs/cancel").status_code == 202
    assert runner.cancelled is True


def test_get_jobs_reports_state_and_progress(tmp_path):
    client, _ = _job_client(tmp_path)
    conn = db.connect(str(tmp_path / "catalog.db"))
    conn.execute("INSERT OR REPLACE INTO run_status "
                 "(command, phase, done, total, current, started_at, updated_at)"
                 " VALUES ('harvest','Source',5,9,'hardcover','t','t')")
    conn.commit()
    conn.close()
    body = client.get("/api/jobs").get_json()
    assert body["log"] == ["Bundle 1/2: The Hollow Crypt"]
    assert body["last"]["state"] == "done"
    # Every unfinished run_status row, whoever started it -- the same
    # table /api/status reads, so the page cannot hold two disagreeing
    # accounts of how far a run has got.
    assert [r["command"] for r in body["progress"]] == ["harvest"]
    assert body["progress"][0]["done"] == 5


def _xlsx_bytes():
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["Name"])
    wb.active.append(["The Hollow Crypt"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_sheets_upload_starts_a_job_with_the_written_path(tmp_path):
    import base64
    client, runner = _job_client(tmp_path)
    blob = _xlsx_bytes()
    resp = client.post("/api/jobs/import-sheets", json={
        "filename": "ratings-audiobooks.xlsx",
        "content_b64": base64.b64encode(blob).decode()})
    assert resp.status_code == 202
    command, _options, _force = runner.started[0]
    assert command == "import_sheets"
    path = Path(resp.get_json()["path"])
    assert path.exists() and path.read_bytes() == blob
    # The name is preserved: import-sheets matches audiobooks by FILE NAME,
    # so a renamed temp file would silently import against the wrong pool.
    assert path.name == "ratings-audiobooks.xlsx"


def test_import_sheets_upload_passes_the_path_as_a_positional_argument(tmp_path):
    # The path is the one string the runner ever puts in argv, and it is
    # one THIS route created -- never anything from the request body.
    import base64
    from humble_catalog import jobs
    seen = {}
    app = create_app(db_path=str(tmp_path / "catalog.db"))

    class _ArgsRunner(_StubRunner):
        def start(self, command, options=None, args=(), cleanup=None,
                  force=False):
            seen["args"] = list(args)
            seen["cleanup"] = cleanup
            return super().start(command, options, args, cleanup, force)

    app.config["JOB_RUNNER"] = _ArgsRunner()
    resp = app.test_client().post("/api/jobs/import-sheets", json={
        "filename": "a.xlsx",
        "content_b64": base64.b64encode(_xlsx_bytes()).decode()})
    assert seen["args"] == [resp.get_json()["path"]]
    assert jobs.argv("import_sheets", {}) + seen["args"] == [
        sys.executable, "-m", "humble_catalog", "import-sheets",
        resp.get_json()["path"]]
    # The temp directory outlives the request; only the runner knows when
    # the child is done with it.
    assert Path(resp.get_json()["path"]).exists()
    seen["cleanup"]()
    assert not Path(resp.get_json()["path"]).exists()


def test_import_sheets_upload_refuses_a_non_xlsx_name(tmp_path):
    import base64
    client, _ = _job_client(tmp_path)
    # The separator cases are checked by hand rather than through
    # pathlib: Path(r"C:\evil.xlsx").name is "evil.xlsx" on Windows and
    # the whole string on POSIX, so a rule built on it would mean two
    # different things on the two platforms.
    for name in ("ratings.csv", "../evil.xlsx", "sub/dir.xlsx",
                 r"..\evil.xlsx", r"C:\evil.xlsx"):
        resp = client.post("/api/jobs/import-sheets", json={
            "filename": name,
            "content_b64": base64.b64encode(b"x").decode()})
        assert resp.status_code == 400, name


def test_import_sheets_upload_refuses_bad_base64(tmp_path):
    client, _ = _job_client(tmp_path)
    resp = client.post("/api/jobs/import-sheets",
                       json={"filename": "a.xlsx", "content_b64": "not!base64"})
    assert resp.status_code == 400


def test_import_sheets_upload_needs_both_fields(tmp_path):
    client, _ = _job_client(tmp_path)
    assert client.post("/api/jobs/import-sheets",
                       json={"filename": "a.xlsx"}).status_code == 400
    assert client.post("/api/jobs/import-sheets",
                       json={"content_b64": "eA=="}).status_code == 400


def test_import_sheets_upload_enforces_the_size_cap(tmp_path):
    import base64
    from humble_catalog import webapp
    client, _ = _job_client(tmp_path)
    big = b"x" * (webapp.MAX_UPLOAD_BYTES + 1)
    resp = client.post("/api/jobs/import-sheets", json={
        "filename": "a.xlsx", "content_b64": base64.b64encode(big).decode()})
    assert resp.status_code == 400
    assert "too large" in resp.get_json()["error"]


def test_import_sheets_upload_leaves_no_file_behind_when_busy(tmp_path):
    import base64
    client, runner = _job_client(tmp_path)
    runner.busy = True
    resp = client.post("/api/jobs/import-sheets", json={
        "filename": "a.xlsx",
        "content_b64": base64.b64encode(_xlsx_bytes()).decode()})
    assert resp.status_code == 409
    # No job will ever run, so nothing else would clean the workbook up.
    assert not list(Path(tempfile.gettempdir()).glob("humble-import-*/a.xlsx"))


def test_index_has_a_tasks_tab_and_section():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert '<a id="tab-tasks" href="#/tasks">' in html
    assert '<section id="section-tasks"' in html
    assert '<script src="/static/tasks.js"></script>' in html


def test_index_has_the_takeover_screen():
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    assert '<div id="handoff-screen" hidden' in html

def _readme():
    return (Path(__file__).parent.parent / "README.md").read_text(
        encoding="utf-8")


def test_readme_documents_the_viewer_s_new_reach():
    exposure = _readme().split("### The viewer's exposure")[1]
    # The security note must not quietly go stale: the viewer can now
    # start processes, and the section that describes its exposure is the
    # one place a reader will look for that.
    assert "start" in exposure and "job" in exposure.lower()


def test_readme_does_not_still_claim_four_tabs():
    # The count is stated twice and both were written when there were
    # four. A section nobody has heard of is a section nobody opens.
    readme = _readme()
    assert "four sections" not in readme
    assert "four tabs" not in readme
    assert "**Tasks**" in readme


def test_status_reports_the_loopback_app_is_not_read_only(tmp_path):
    # The front end decides whether to render editing controls from this
    # flag, so the full viewer must say false, explicitly.
    dbp = tmp_path / "t.db"
    _seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    body = client.get("/api/status").get_json()
    assert body["read_only"] is False
    assert body["runs"] == []


LAN_HOST, LAN_PORT, TOKEN = "192.168.1.20", 8088, "t" * 43
LAN_BASE = f"https://{LAN_HOST}:{LAN_PORT}"
# What the LAN app may serve. Adding a route to the read group fails this
# test until the list is edited on purpose -- which is the point.
LAN_RULES = {"/", "/static/<path:filename>", "/covers/<path:filename>",
             "/api/items", "/api/stats", "/api/keys", "/api/status", "/pair"}


def _lan_client(tmp_path, token=TOKEN):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    app = create_lan_app(db_path=str(dbp), host=LAN_HOST, port=LAN_PORT,
                         token=token)
    return app, app.test_client()


def _paired(client):
    return client.get(f"/pair?token={TOKEN}", base_url=LAN_BASE)


def test_lan_app_serves_only_the_pinned_read_routes(tmp_path):
    app, _client = _lan_client(tmp_path)
    rules = list(app.url_map.iter_rules())
    assert {r.rule for r in rules} == LAN_RULES
    for r in rules:
        assert r.methods <= {"GET", "HEAD", "OPTIONS"}, (r.rule, r.methods)


def test_every_lan_route_refuses_an_unpaired_request(tmp_path):
    app, client = _lan_client(tmp_path)
    for rule in app.url_map.iter_rules():
        if rule.rule == "/pair":
            continue
        path = rule.rule.replace("<path:filename>", "x")
        resp = client.get(path, base_url=LAN_BASE)
        assert resp.status_code == 403, rule.rule
        assert b"Not paired" in resp.data, rule.rule


def test_pairing_sets_a_strict_secure_cookie_and_leaves_the_token_behind(tmp_path):
    _app, client = _lan_client(tmp_path)
    resp = _paired(client)
    assert resp.status_code == 200
    cookie = resp.headers["Set-Cookie"]
    for part in ("hc_lan=" + TOKEN, "Secure", "HttpOnly", "SameSite=Strict",
                 "Max-Age=34560000", "Path=/"):
        assert part in cookie, part
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    # A page that refreshes to /, not a 303: the next navigation is then
    # same-origin, so a Strict cookie is sent even when the link came from
    # a QR-scanner app. The token must not ride along.
    assert b'http-equiv="refresh" content="0;url=/"' in resp.data
    assert TOKEN.encode() not in resp.data


def test_a_paired_phone_can_read_the_catalog(tmp_path):
    _app, client = _lan_client(tmp_path)
    _paired(client)
    items = client.get("/api/items", base_url=LAN_BASE).get_json()["items"]
    assert items[0]["name"] == "All Systems Red"
    assert client.get("/api/status", base_url=LAN_BASE).get_json()[
        "read_only"] is True


def test_a_wrong_token_does_not_pair(tmp_path, capsys):
    _app, client = _lan_client(tmp_path)
    resp = client.get("/pair?token=wrong", base_url=LAN_BASE)
    assert resp.status_code == 403
    assert "Set-Cookie" not in resp.headers
    assert "refused a pairing attempt" in capsys.readouterr().out


def test_a_rotated_token_unpairs_an_old_cookie(tmp_path):
    _app, client = _lan_client(tmp_path, token="n" * 43)
    resp = client.get("/api/items", base_url=LAN_BASE,
                      headers={"Cookie": f"hc_lan={TOKEN}"})
    assert resp.status_code == 403


def test_the_lan_app_refuses_a_foreign_host(tmp_path):
    # DNS rebinding, LAN edition: evil.example re-pointed at the LAN IP
    # still arrives with its own name in Host.
    _app, client = _lan_client(tmp_path)
    _paired(client)
    resp = client.get("/api/items", base_url="https://evil.example:8088",
                      headers={"Cookie": f"hc_lan={TOKEN}"})
    assert resp.status_code == 403
    assert b"Not paired" not in resp.data


def test_the_lan_app_has_no_write_route_to_reach(tmp_path):
    _app, client = _lan_client(tmp_path)
    _paired(client)
    resp = client.post("/api/items/1/rating", json={"rating": 5},
                       base_url=LAN_BASE)
    assert resp.status_code in (404, 405)


def _stub_servers(monkeypatch):
    built = []

    class FakeServer:
        def __init__(self, host, port, app, **kw):
            self.host, self.port, self.app = host, port, app
            self.ssl_context = kw.get("ssl_context")
            self.kw = kw
            built.append(self)
        def server_close(self): pass

    monkeypatch.setattr(webmod, "make_server",
                        lambda host, port, app, **kw: FakeServer(host, port, app, **kw))
    monkeypatch.setattr(webmod, "_run_all", lambda servers, slot=None: None)
    monkeypatch.setattr(webmod.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(lanmod, "lan_address", lambda: "192.168.1.20")
    # pytest's stdin is not a terminal; serve from one is the usual case.
    monkeypatch.setattr(webmod.handoff, "terminal_available", lambda: True)
    # Never probe the real port: a viewer running on this machine would
    # turn every serve test into "already running".
    monkeypatch.setattr(webmod, "viewer_running", lambda port: False)
    return built


def test_serve_lan_runs_the_loopback_and_lan_servers(tmp_path, monkeypatch, capsys):
    built = _stub_servers(monkeypatch)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=8087, lan=lanmod.LanOptions())
    loop, lan_srv = built
    assert (loop.host, loop.port) == ("127.0.0.1", 8087)
    assert loop.app.config["READ_ONLY"] is False and loop.ssl_context is None
    assert (lan_srv.host, lan_srv.port) == ("192.168.1.20", 8088)
    assert lan_srv.app.config["READ_ONLY"] is True
    assert isinstance(lan_srv.ssl_context, _ssl.SSLContext)
    token = (tmp_path / "lan" / "token").read_text().strip()
    assert f"https://192.168.1.20:8088/pair?token={token}" in capsys.readouterr().out


def test_serve_lan_setup_adds_the_certificate_download(tmp_path, monkeypatch, capsys):
    built = _stub_servers(monkeypatch)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=8087,
                 lan=lanmod.LanOptions(setup=True, port=9000))
    assert [(s.host, s.port) for s in built] == [
        ("127.0.0.1", 8087), ("192.168.1.20", 9000), ("192.168.1.20", 9001)]
    out = capsys.readouterr().out
    assert "http://192.168.1.20:9001/ca.crt" in out and "SHA-256" in out


def test_serve_lan_new_token_replaces_the_token(tmp_path, monkeypatch):
    _stub_servers(monkeypatch)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    old = lanmod.load_or_create_token(tmp_path / "lan")
    webmod.serve(db_path=str(dbp), lan=lanmod.LanOptions(new_token=True))
    assert (tmp_path / "lan" / "token").read_text().strip() != old


def _busy_on_8088(monkeypatch, fail):
    closed = []

    class FakeServer:
        def server_close(self): closed.append(self)

    def make(host, port, app, **kw):
        if port == 8088:
            fail()
        return FakeServer()

    monkeypatch.setattr(webmod, "make_server", make)
    monkeypatch.setattr(lanmod, "lan_address", lambda: "192.168.1.20")
    return closed


def _werkzeug_bind_failure():
    # What Werkzeug 3.1 really does when bind() fails: it catches the
    # OSError itself, prints a line to stderr and calls sys.exit(1).
    sys.exit(1)


def _raw_bind_failure():
    raise OSError("address in use")


@pytest.mark.parametrize("fail", [_werkzeug_bind_failure, _raw_bind_failure])
def test_a_busy_port_closes_what_was_opened_and_says_which(tmp_path, monkeypatch, fail):
    closed = _busy_on_8088(monkeypatch, fail)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    with pytest.raises(lanmod.LanStateError, match="192.168.1.20:8088.*--lan-port"):
        webmod.serve(db_path=str(dbp), lan=lanmod.LanOptions())
    assert len(closed) == 1           # the loopback server, opened first


@pytest.mark.parametrize("options, match", [
    (dict(host="abc"), "--lan-host"),
    (dict(host="8.8.8.8"), "--lan-host"),
    (dict(host="fd00::1"), "--lan-host"),
    (dict(port=0), "--lan-port"),
    (dict(port=70000), "--lan-port"),
    (dict(port=65535, setup=True), "--lan-port"),
])
def test_a_bad_lan_address_or_port_is_refused_before_anything_is_written(
        tmp_path, monkeypatch, options, match):
    built = _stub_servers(monkeypatch)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    with pytest.raises(lanmod.LanStateError, match=match):
        webmod.serve(db_path=str(dbp), lan=lanmod.LanOptions(**options))
    assert built == []
    assert not (tmp_path / "lan").exists()


def test_a_viewer_port_with_no_room_above_it_is_refused(tmp_path, monkeypatch):
    # --lan-port defaults to --port + 1, which here is not a port at all.
    built = _stub_servers(monkeypatch)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    with pytest.raises(lanmod.LanStateError, match="--lan-port"):
        webmod.serve(db_path=str(dbp), port=65535, lan=lanmod.LanOptions())
    assert built == [] and not (tmp_path / "lan").exists()


def test_serve_lan_says_where_the_viewer_on_this_pc_is(tmp_path, monkeypatch, capsys):
    _stub_servers(monkeypatch)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=8087, lan=lanmod.LanOptions())
    assert "Viewer on this PC: http://127.0.0.1:8087/" in capsys.readouterr().out


def test_the_lan_app_refuses_an_empty_token(tmp_path):
    # Fails closed: an empty token would match an absent cookie.
    dbp = tmp_path / "t.db"
    _seed(dbp)
    for token in ("", None):
        with pytest.raises(ValueError):
            create_lan_app(db_path=str(dbp), host=LAN_HOST, port=LAN_PORT,
                           token=token)


def _logged_line(handler_cls, path, requestline):
    h = handler_cls.__new__(handler_cls)
    h.command, h.request_version = "GET", "HTTP/1.1"
    if path is not None:
        h.path = path
    h.requestline = requestline
    lines = []
    h.log = lambda _type, message, *args: lines.append(message % args)
    h.log_request(200, 123)
    return h, lines[0]


def test_the_lan_access_log_leaves_the_pairing_token_out():
    secret = "s3cr3t-pairing-value"
    h, line = _logged_line(webmod.LanRequestHandler, f"/pair?token={secret}",
                           f"GET /pair?token={secret} HTTP/1.1")
    assert secret not in line and "GET /pair HTTP/1.1" in line
    assert h.path == f"/pair?token={secret}"      # only the log line changes
    # A request line too malformed to parse is logged whole; still no query.
    _h, line = _logged_line(webmod.LanRequestHandler, None,
                            f"GET /pair?token={secret} HTTP/9")
    assert secret not in line


def test_serve_lan_builds_the_lan_server_with_the_quiet_handler(tmp_path, monkeypatch):
    built = _stub_servers(monkeypatch)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=8087, lan=lanmod.LanOptions())
    loop, lan_srv = built
    assert lan_srv.kw["request_handler"] is webmod.LanRequestHandler
    assert "request_handler" not in loop.kw


def test_create_app_alone_has_no_handoff(tmp_path):
    # The demo server and launch.json call create_app().run(): no serve
    # loop, so nothing could ever drain a handoff.
    assert create_app(db_path=str(tmp_path / "c.db")).config["HANDOFF"] is None


def test_serve_without_lan_goes_through_the_loop(tmp_path, monkeypatch, capsys):
    built = _stub_servers(monkeypatch)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=8087)
    [loop] = built
    assert (loop.host, loop.port) == ("127.0.0.1", 8087)
    assert isinstance(loop.app.config["HANDOFF"], handoffmod.HandoffSlot)
    assert "http://127.0.0.1:8087/" in capsys.readouterr().out


def _handoff_once(monkeypatch, run_result):
    """_run_all hands off once, then the user presses Ctrl-C."""
    calls = []

    def fake_run_all(servers, slot=None):
        calls.append(servers)
        if len(calls) == 1:
            slot.request("reset", ["python", "-m", "humble_catalog", "reset"])
            return slot.take()
        return None

    ran = []

    def fake_terminal(command, line):
        ran.append((command, line))
        if isinstance(run_result, Exception):
            raise run_result
        return run_result

    monkeypatch.setattr(webmod, "_run_all", fake_run_all)
    monkeypatch.setattr(handoffmod, "run_in_terminal", fake_terminal)
    return calls, ran


@pytest.mark.parametrize("lan", [None, "lan"])
def test_a_handoff_runs_the_command_then_rebinds_the_same_apps(
        tmp_path, monkeypatch, lan):
    built = _stub_servers(monkeypatch)
    calls, ran = _handoff_once(monkeypatch, 0)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=8087,
                 lan=lanmod.LanOptions() if lan else None)
    assert [c for c, _ in ran] == ["reset"]
    assert len(calls) == 2                       # served, handed off, served
    per_round = len(built) // 2
    first, second = built[:per_round], built[per_round:]
    # The same app objects, so the job runner's history and the slot's
    # generation survive the restart.
    assert [s.app for s in first] == [s.app for s in second]
    slot = first[0].app.config["HANDOFF"]
    assert slot.state()["generation"] == 1
    assert slot.state()["last"]["exit_code"] == 0
    assert slot.busy() is None


def test_a_crashing_handoff_still_brings_the_viewer_back(
        tmp_path, monkeypatch, capsys):
    built = _stub_servers(monkeypatch)
    calls, _ran = _handoff_once(monkeypatch, RuntimeError("boom"))
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=8087)
    assert len(calls) == 2 and len(built) == 2
    slot = built[0].app.config["HANDOFF"]
    assert slot.state()["last"]["exit_code"] is None
    assert "boom" in capsys.readouterr().err


def test_the_browser_opens_once_not_after_every_handoff(tmp_path, monkeypatch):
    _stub_servers(monkeypatch)
    opened = []
    monkeypatch.setattr(webmod.webbrowser, "open", lambda url: opened.append(url))
    _handoff_once(monkeypatch, 0)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=8087)
    # The page reconnects by itself; a second open would be a second tab.
    assert opened == ["http://127.0.0.1:8087/"]


def test_run_all_stops_for_a_handoff_and_shuts_every_server():
    import threading

    class Server:
        def __init__(self):
            self.stop = threading.Event()
            self.closed = False
        def serve_forever(self):
            self.stop.wait(5)
        def shutdown(self):
            self.stop.set()
        def server_close(self):
            self.closed = True

    slot = handoffmod.HandoffSlot()
    slot.request("login", ["x"])
    servers = [Server(), Server()]
    req = webmod._run_all(servers, slot)
    assert req == {"command": "login", "argv": ["x"]}
    assert all(s.stop.is_set() and s.closed for s in servers)


def _handoff_client(tmp_path, slot=True):
    backups = tmp_path / "backups"
    app = create_app(db_path=str(tmp_path / "catalog.db"),
                     backups_dir=str(backups))
    runner = _StubRunner()
    app.config["JOB_RUNNER"] = runner
    s = handoffmod.HandoffSlot() if slot else None
    app.config["HANDOFF"] = s
    return app.test_client(), runner, s, backups


def _write_snapshot(backups, stamp="20260101-120000"):
    backups.mkdir(exist_ok=True)
    (backups / f"catalog-{stamp}.db").write_bytes(b"x")
    return f"catalog-{stamp}.db"


def test_backups_lists_the_snapshots(tmp_path):
    client, _r, _s, backups = _handoff_client(tmp_path)
    name = _write_snapshot(backups)
    body = client.get("/api/backups").get_json()
    assert [b["name"] for b in body["backups"]] == [name]


def test_handoff_queues_the_whitelisted_command(tmp_path):
    client, _r, slot, _b = _handoff_client(tmp_path)
    resp = client.post("/api/jobs/handoff", json={"command": "reset"})
    assert resp.status_code == 200
    assert resp.get_json() == {"command": "reset", "generation": 0}
    assert slot.take()["argv"][-1] == "reset"


def test_handoff_restore_takes_a_listed_snapshot(tmp_path):
    client, _r, slot, backups = _handoff_client(tmp_path)
    name = _write_snapshot(backups)
    resp = client.post("/api/jobs/handoff", json={
        "command": "restore", "options": {"covers": True}, "snapshot": name})
    assert resp.status_code == 200
    line = slot.take()["argv"]
    assert line[-2:] == [str(backups / name), "--covers"]


@pytest.mark.parametrize("body", [
    {"command": "harvest"},                      # an in-page command
    {"command": "restore"},                      # no snapshot
    {"command": "restore", "snapshot": "../catalog.db"},
    {"command": "reset", "options": {"covers": True}},
    {"command": "reset", "options": ["--yes"]},
    {},
])
def test_handoff_refuses_what_the_whitelist_does_not_allow(tmp_path, body):
    client, _r, slot, _b = _handoff_client(tmp_path)
    assert client.post("/api/jobs/handoff", json=body).status_code == 400
    assert slot.busy() is None


def test_handoff_refuses_a_malformed_body(tmp_path):
    client, _r, _s, _b = _handoff_client(tmp_path)
    for body in ([], "reset", None):
        resp = client.post("/api/jobs/handoff", json=body)
        assert resp.status_code == 400
        assert resp.is_json


def test_handoff_without_a_serve_loop_says_how_to_get_one(tmp_path):
    client, _r, _s, _b = _handoff_client(tmp_path, slot=False)
    resp = client.post("/api/jobs/handoff", json={"command": "login"})
    assert resp.status_code == 409
    assert "python -m humble_catalog login" in resp.get_json()["error"]


def test_handoff_waits_for_a_running_job(tmp_path):
    client, runner, slot, _b = _handoff_client(tmp_path)
    runner.state = lambda: {"running": {"command": "harvest"}, "log": [],
                            "last": None}
    resp = client.post("/api/jobs/handoff", json={"command": "reset"})
    assert resp.status_code == 409
    assert "harvest" in resp.get_json()["error"]
    assert slot.busy() is None


def test_a_second_handoff_is_refused(tmp_path):
    client, _r, _s, _b = _handoff_client(tmp_path)
    client.post("/api/jobs/handoff", json={"command": "login"})
    assert client.post("/api/jobs/handoff",
                       json={"command": "reset"}).status_code == 409


def test_no_job_starts_while_a_handoff_is_pending(tmp_path):
    client, runner, _s, _b = _handoff_client(tmp_path)
    client.post("/api/jobs/handoff", json={"command": "reset"})
    resp = client.post("/api/jobs/start", json={"command": "harvest"})
    assert resp.status_code == 409
    assert runner.started == []
    resp = client.post("/api/jobs/import-sheets",
                       json={"filename": "a.xlsx", "content_b64": "eA=="})
    assert resp.status_code == 409


def test_jobs_reports_the_handoff_state(tmp_path):
    client, _r, slot, _b = _handoff_client(tmp_path)
    slot.request("login", ["x"])
    slot.take()
    slot.finish(0)
    body = client.get("/api/jobs").get_json()
    assert body["handoff"]["available"] is True
    assert body["handoff"]["generation"] == 1
    assert body["handoff"]["last"]["command"] == "login"


def test_jobs_reports_no_handoff_without_a_serve_loop(tmp_path):
    client, _r, _s, _b = _handoff_client(tmp_path, slot=False)
    h = client.get("/api/jobs").get_json()["handoff"]
    assert h == {"available": False, "generation": 0, "pending": None,
                 "last": None}


def test_readme_explains_the_handoff_and_its_guard():
    readme = _readme()
    exposure = readme.split("### The viewer's exposure")[1]
    # The destructive path's real guard is the typed word at the console.
    # The exposure section must say a local process can now QUEUE a
    # reset, and why that still cannot wipe anything unattended.
    assert "hand" in exposure.lower()
    assert "RESET" in exposure
    assert "needed only for `login`, `reset` and `restore`" not in readme


def _sort_cells():
    """The inner HTML of each sortable header cell in index.html."""
    html = (Path(__file__).parent.parent / "humble_catalog" / "webapp"
            / "static" / "index.html").read_text(encoding="utf-8")
    return re.findall(r'<th data-sort="[^"]+">(.*?)</th>', html, re.S)


def test_every_sortable_header_is_a_real_button():
    # The headers were bare <th>s driven by a delegated click listener:
    # not focusable, so the table could be read by keyboard but not
    # reordered. A real button is focusable and answers Enter and Space
    # without a key handler of its own (#39).
    cells = _sort_cells()
    assert len(cells) == 11, cells
    assert all('<button type="button" class="sort-btn"' in c for c in cells), cells


def test_the_sort_indicator_stays_inside_the_header_button():
    # The arrow belongs to the control that changes it, so it is part of
    # the button's own label rather than a sibling the button does not own.
    cells = _sort_cells()
    assert all(c.index('<span class="sort-ind">') > c.index("<button")
               and c.index('<span class="sort-ind">') < c.index("</button>")
               for c in cells), cells


# -- A viewer with no terminal offers no handoff (#98) -------------------
# serve used to create the handoff slot unconditionally. Started detached
# (serve.ps1 -Detached: a hidden console), a reset handed over waited for
# RESET typed into a window nobody could see, with the viewer stepped down
# behind it and the page reconnecting for ever. Reproduced on a throwaway
# catalog before this fix.

def _served_app(tmp_path, monkeypatch, lan=None, terminal=True, **kw):
    built = _stub_servers(monkeypatch)
    monkeypatch.setattr(webmod.handoff, "terminal_available",
                        lambda: terminal)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=8087, lan=lan, **kw)
    return built[0].app


def test_serve_with_a_terminal_offers_the_handoff(tmp_path, monkeypatch):
    app = _served_app(tmp_path, monkeypatch)
    assert app.config["HANDOFF"] is not None


def test_serve_no_handoff_offers_none(tmp_path, monkeypatch):
    # The detached wrappers pass this: a hidden console passes isatty(),
    # so it cannot be detected and has to be said.
    app = _served_app(tmp_path, monkeypatch, terminal_commands=False)
    assert app.config["HANDOFF"] is None


def test_serve_without_a_terminal_offers_none(tmp_path, monkeypatch):
    app = _served_app(tmp_path, monkeypatch, terminal=False)
    assert app.config["HANDOFF"] is None


def test_serve_lan_with_no_handoff_offers_none(tmp_path, monkeypatch):
    app = _served_app(tmp_path, monkeypatch, lan=lanmod.LanOptions(),
                      terminal_commands=False)
    assert app.config["HANDOFF"] is None


def test_serve_says_when_the_terminal_commands_are_off(tmp_path, monkeypatch,
                                                       capsys):
    _served_app(tmp_path, monkeypatch, terminal_commands=False)
    out = capsys.readouterr().out
    assert "login, reset and restore" in out


def test_a_refused_handoff_says_where_to_run_the_command(tmp_path):
    # The old refusal blamed how the viewer was started, which is no
    # longer the only reason, and gave no way forward.
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    client = webmod.create_app(db_path=str(dbp)).test_client()  # no slot
    resp = client.post("/api/jobs/handoff", json={"command": "reset"})
    assert resp.status_code == 409
    error = resp.get_json()["error"]
    assert "python -m humble_catalog reset" in error


# -- serve reuses a viewer that is already running (#97) -----------------
# The usual intent of a second `serve` is "show me the catalog", which
# used to fail with "cannot listen". The probe runs against a real
# listener: what matters is what answers on the port, which a mock of the
# probe itself cannot show.
import threading                                        # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402


def _listener(body, status=200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.seen.append(self.path)
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.seen = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def listener():
    started = []

    def start(body, status=200):
        srv = _listener(body, status)
        started.append(srv)
        return srv
    yield start
    for srv in started:
        srv.shutdown()
        srv.server_close()


_VIEWER_STATUS = json.dumps({"runs": [], "read_only": False})


def test_a_viewer_answering_on_the_port_is_recognised(listener):
    srv = listener(_VIEWER_STATUS)
    assert webmod.viewer_running(srv.server_port) is True
    assert srv.seen == ["/api/status"]


@pytest.mark.parametrize("body,status", [
    ("<html>someone else's app</html>", 200),
    (json.dumps({"hello": "world"}), 200),
    (json.dumps(["runs", "read_only"]), 200),
    (_VIEWER_STATUS, 500),
])
def test_anything_else_on_the_port_is_not_a_viewer(listener, body, status):
    srv = listener(body, status)
    assert webmod.viewer_running(srv.server_port) is False


def test_nothing_listening_is_not_a_viewer():
    import socket
    with socket.socket() as sock:      # a port that was free a moment ago
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert webmod.viewer_running(port) is False


def test_serve_opens_the_running_viewer_instead_of_binding(
        tmp_path, monkeypatch, capsys, listener):
    srv = listener(_VIEWER_STATUS)
    port = srv.server_port
    opened = []
    monkeypatch.setattr(webmod.webbrowser, "open", opened.append)

    def no_bind(*a, **kw):
        raise AssertionError("serve bound a port a viewer already holds")
    monkeypatch.setattr(webmod, "make_server", no_bind)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    webmod.serve(db_path=str(dbp), port=port)       # returns: exit code 0
    url = f"http://127.0.0.1:{port}/"
    assert opened == [url]
    assert f"already running at {url}" in capsys.readouterr().out


def test_serve_still_refuses_a_port_something_else_holds(
        tmp_path, monkeypatch, listener):
    srv = listener("<html>someone else's app</html>")
    monkeypatch.setattr(webmod.webbrowser, "open", lambda url: None)

    def busy(host, port, app, **kw):
        raise OSError("address in use")
    monkeypatch.setattr(webmod, "make_server", busy)
    dbp = tmp_path / "catalog.db"
    _seed(dbp)
    with pytest.raises(SystemExit, match="cannot listen"):
        webmod.serve(db_path=str(dbp), port=srv.server_port)


# -- What a first run on an empty catalog still needs (#99) --------------
# The empty table said "run Fetch new bundles", which fails with no saved
# login. /api/setup reports the state the Library's first-run checklist
# ticks from. It reads no cookie and makes no request: a login is "saved"
# once the browser profile `login` writes exists, which is exactly what a
# first run lacks. Whether it is still valid is for the fetch to say.

def _setup_client(tmp_path, profile=False):
    dbp = tmp_path / "catalog.db"
    db.connect(dbp).close()
    app = create_app(db_path=str(dbp))
    app.config["PROFILE_DIR"] = str(tmp_path / ".playwright-profile")
    if profile:
        (tmp_path / ".playwright-profile").mkdir()
    return dbp, app.test_client()


def test_setup_on_a_first_run_has_nothing_done(tmp_path):
    _dbp, client = _setup_client(tmp_path)
    assert client.get("/api/setup").get_json() == {
        "login_saved": False, "game_stores": 0}


def test_setup_sees_a_saved_login(tmp_path):
    _dbp, client = _setup_client(tmp_path, profile=True)
    assert client.get("/api/setup").get_json()["login_saved"] is True


def test_setup_counts_imported_game_stores(tmp_path):
    dbp, client = _setup_client(tmp_path)
    conn = db.connect(dbp)
    conn.execute("INSERT INTO game_imports VALUES "
                 "('steam', '2026-09-26T00:00:00+00:00', 3, 'test')")
    conn.commit()
    conn.close()
    assert client.get("/api/setup").get_json()["game_stores"] == 1


def test_the_profile_defaults_to_where_login_saves_it(tmp_path):
    # humble_api's profile_dir default; a mismatch would tick nothing.
    import inspect
    from humble_catalog import humble_api
    default = inspect.signature(humble_api.login).parameters[
        "profile_dir"].default
    app = create_app(db_path=str(tmp_path / "catalog.db"))
    assert app.config["PROFILE_DIR"] == default


def test_the_lan_viewer_has_no_setup_route(tmp_path):
    _app, client = _lan_client(tmp_path)
    _paired(client)
    assert client.get("/api/setup", base_url=LAN_BASE).status_code == 404
