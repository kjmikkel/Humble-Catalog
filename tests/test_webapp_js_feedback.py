"""Bundles and Maintenance say what happened, aloud as well as on screen (#148).

Kept apart from test_webapp_js.py so that work on separate issues does
not keep appending to the end of the same file, where any two open
branches conflict.
"""
import json
from pathlib import Path

from tests.js_harness import eval_js
from tests.test_webapp_js import _BUNDLE_REPORT

_STATIC = Path(__file__).resolve().parent.parent / "humble_catalog" / "webapp" / "static"

_REFUSED = """app.setFetch(() => Promise.resolve({ok: false, status: 400,
  json: () => Promise.resolve({error: "not a HumbleBundle URL: example.test"})}));"""


def test_the_live_regions_exist_from_first_paint():
    # A11Y-7: a region inserted along with its text is not reliably read,
    # so each one is in the markup, empty, before any check runs.
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    assert '<p id="bundles-alert" class="visually-hidden" role="alert"></p>' in html
    assert '<p id="bundles-status" class="visually-hidden" role="status"></p>' in html
    assert '<p id="bundle-url-msg" class="field-msg" role="alert"></p>' in html
    assert 'aria-describedby="bundle-url-msg"' in html


def test_a_refused_bundle_url_is_announced_as_an_alert():
    spoken = eval_js("""(async () => {
      dom.reset();
      %s
      await app.previewBundle("https://example.test/x");
      return [dom.writes["#bundles-alert:text"], dom.writes["#bundles-status:text"]];
    })()""" % _REFUSED)
    assert spoken == ["not a HumbleBundle URL: example.test", ""]


def test_a_bundle_report_is_announced_as_a_status():
    spoken = eval_js("""(async () => {
      dom.reset();
      app.setFetch(() => Promise.resolve({ok: true, json: () => Promise.resolve(%s)}));
      await app.previewBundle("https://www.humblebundle.com/books/x");
      return [dom.writes["#bundles-alert:text"], dom.writes["#bundles-status:text"]];
    })()""" % json.dumps(_BUNDLE_REPORT))
    assert spoken == ["", f"Bundle report ready: {_BUNDLE_REPORT['name']}"]


def test_a_browse_announces_how_many_bundles_it_listed():
    spoken = eval_js("""(async () => {
      dom.reset();
      app.resetBrowse();
      app.setFetch(() => Promise.resolve({ok: true, json: () => Promise.resolve(
        {bundles: [{name: "A", url: "https://www.humblebundle.com/books/a"},
                   {name: "B", url: "https://example.test/not-humble"}]})}));
      await app.browseBundles();
      return dom.writes["#bundles-status:text"];
    })()""")
    assert spoken == "1 current bundle listed"


def test_starting_a_check_clears_every_stale_error():
    errors = eval_js("""(async () => {
      dom.reset();
      app.setBundleErrors("old bundle error", "old browse error", "old choice error");
      let during = null;
      app.setFetch(() => { during = app.getBundleErrors(); return new Promise(() => {}); });
      app.previewBundle("https://www.humblebundle.com/books/x");
      await Promise.resolve();
      return [during, dom.writes["#bundle-url-msg:text"],
              dom.writes["#bundles-status:text"]];
    })()""")
    assert errors == [[None, None, None], "", "Checking the bundle…"]


def test_an_empty_check_says_so_beside_the_field():
    got = eval_js("""(async () => {
      dom.reset();
      globalThis.fetched = false;
      app.setFetch(() => { globalThis.fetched = true; return new Promise(() => {}); });
      document.querySelector("#bundle-url").value = "   ";
      app.submitBundleUrl();
      return [dom.writes["#bundle-url-msg:text"], dom.focused, globalThis.fetched];
    })()""")
    assert got == ["Paste a HumbleBundle URL first.", ["#bundle-url"], False]


def test_the_maintenance_url_result_is_a_status_region():
    src = (_STATIC / "maintenance.js").read_text(encoding="utf-8")
    assert '<span class="url-result" role="status" data-id="${r.id}"></span>' in src
