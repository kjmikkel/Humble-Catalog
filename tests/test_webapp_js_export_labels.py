"""The export column picker uses the table's labels (CONTENT-3, #155).

Kept apart from test_webapp_js.py so that work on separate issues does
not keep appending to the end of the same file, where any two open
branches conflict.
"""
import re
from pathlib import Path

from tests.js_harness import eval_js

_INDEX = (Path(__file__).resolve().parent.parent / "humble_catalog" / "webapp"
          / "static" / "index.html")


def test_every_export_column_has_a_label():
    missing = eval_js("app.EXPORT_COLUMNS.filter(c => !app.EXPORT_LABELS[c])")
    assert missing == []


def test_no_label_is_left_over_from_a_removed_column():
    extra = eval_js(
        "Object.keys(app.EXPORT_LABELS).filter(c => !app.EXPORT_COLUMNS.includes(c))")
    assert extra == []


def test_a_field_the_table_shows_has_the_tables_word():
    # The sortable headers name their field in data-sort, so the table's
    # own vocabulary can be read straight from the page.
    html = _INDEX.read_text(encoding="utf-8")
    headers = dict(re.findall(
        r'<th data-sort="(\w+)"><button[^>]*>([^<]+)', html))
    labels = eval_js("app.EXPORT_LABELS")
    for field in ("type", "publisher", "authors", "genre", "series",
                  "my_rating", "external_rating", "read_status"):
        assert labels[field] == headers[field], field
    assert labels["title"] == headers["name"]
    assert labels["bundles"] == headers["bundle"]


def test_the_picker_shows_the_label_then_the_raw_name():
    html = eval_js("""(() => { app.renderColumnPicker();
                               return dom.writes["#column-picker-body"]; })()""")
    assert ' data-col="my_rating" checked> Mine <span class="col-raw">(my_rating)</span>' in html
    assert ' data-col="user_comment" checked> Notes <span class="col-raw">(user_comment)</span>' in html
