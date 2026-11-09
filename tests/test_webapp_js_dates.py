"""Dates in the viewer are ISO 8601, never the browser locale (I18N-1, #156).

Kept apart from test_webapp_js.py so that work on separate issues does
not keep appending to the end of the same file, where any two open
branches conflict.
"""
import re

from tests.js_harness import VIEWER_JS, eval_js


def test_iso_date_and_time_in_local_time():
    # Built from local components, so the answer is the same in any zone.
    got = eval_js("""(() => {
      const d = new Date(2026, 10, 9, 8, 49);
      return [app.isoDate(d), app.isoDateTime(d),
              app.isoDate(new Date(2026, 0, 2, 3, 4)),
              app.isoDateTime(new Date(2026, 0, 2, 3, 4))];
    })()""")
    assert got == ["2026-11-09", "2026-11-09 08:49", "2026-01-02", "2026-01-02 03:04"]


def test_a_string_without_a_zone_reads_as_local_time():
    assert eval_js('app.isoDateTime("2026-11-09T23:30:00")') == "2026-11-09 23:30"


def test_nothing_parseable_gives_an_empty_string():
    got = eval_js('[null, undefined, "", "not a date"].map(app.isoDate)')
    assert got == ["", "", "", ""]


def test_the_recent_bundles_line_uses_the_iso_time():
    got = eval_js("""(() => {
      const store = {};
      globalThis.localStorage = {getItem: (k) => store[k] ?? null,
                                 setItem: (k, v) => { store[k] = String(v); },
                                 removeItem: (k) => { delete store[k]; }};
      store[app.RECENT_BUNDLES_KEY] = JSON.stringify([{
        url: "https://www.humblebundle.com/books/x", name: "Test Bundle",
        checked: "2026-11-09T08:49:00"}]);
      app.renderRecentBundles();
      return dom.writes["#bundle-recent"];
    })()""")
    assert "checked 2026-11-09 08:49" in got


def test_no_viewer_script_formats_a_date_by_locale():
    # toLocaleLowerCase is case folding, not date formatting; it stays.
    for path in VIEWER_JS:
        src = path.read_text(encoding="utf-8")
        hits = re.findall(r"\.toLocale(?!LowerCase|UpperCase)\w*\(", src)
        assert not hits, f"{path.name}: {hits}"
