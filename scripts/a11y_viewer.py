"""Accessibility ratchet over the rendered viewer, on the demo catalog (#152).

Runs axe-core in headless Chromium over every section of the viewer, at
desktop and phone width, in the light and dark themes, and in the states
a section only shows when opened: the overview, the column picker, the
inline editor, the phone sheet on a rated and an unrated card, and
Maintenance's panels. Each violation is compared with
tests/a11y-baseline.txt, and the run fails on:
- a violation that is not in the baseline;
- a baseline line that no longer occurs, so the file only shrinks;
- a section listed in smoke_viewer.SECTIONS with no state here;
- a state that drew nothing to check (a scan of an empty page passes).

axe-core comes from node_modules (package.json pins it), never a CDN.
Like the smoke test, this serves the demo catalog only: invented titles,
so nothing it prints names an owned item.

What axe cannot see is out of scope: focus after a re-render (#146),
live-region announcements (#148) and failed-write feedback (#142). Those
have per-flow tests of their own.

Run:    npm ci --ignore-scripts
        python scripts/a11y_viewer.py [--require-installed] [--write-baseline]
Needs:  python -m playwright install chromium
"""
import argparse
import importlib.util
import re
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASELINE = ROOT / "tests" / "a11y-baseline.txt"
AXE = ROOT / "node_modules" / "axe-core" / "axe.min.js"

WIDTHS = (1280, 375)
THEMES = ("light", "dark")
# WCAG 2.0-2.2, A and AA: the level the decided standards hold the viewer
# to. axe's best-practice rules are left out; they are not requirements.
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

CARD = "#card-list .card"


def _smoke():
    spec = importlib.util.spec_from_file_location(
        "smoke_viewer", HERE / "smoke_viewer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- The states ---------------------------------------------------------
# Each is (name, section, width it applies to or None, what to do once the
# section is open, a selector that must match before axe runs). The
# selector is what makes a pass mean something: a section that drew
# nothing has nothing to violate.

def _open_details(page, selector):
    page.eval_on_selector_all(selector, "els => els.forEach(d => d.open = true)")


def _open_sheet(page, rated):
    # The card's meta line shows the rating as stars; a card without one is
    # unrated. Demo data has both.
    page.evaluate("""(rated) => {
      const cards = [...document.querySelectorAll('#card-list .card')];
      const card = cards.find(c => c.textContent.includes('\\u2605') === rated);
      card.querySelector('.card-open').click();
    }""", rated)


def states(smoke):
    rows = smoke.ROW
    out = [
        ("library", "library", None, None, f"{rows}, {CARD}"),
        ("library+overview", "library", None,
         lambda p: _open_details(p, "#stats-panel details"), "#stats-panel details[open]"),
        ("library+columns", "library", 1280,
         lambda p: _open_details(p, "#column-picker"), "#column-picker[open] .col-check"),
        ("library+editor", "library", 1280,
         lambda p: p.click("#catalog tbody .edit"), "#catalog tbody .edit-field"),
        ("library+sheet-rated", "library", 375,
         lambda p: _open_sheet(p, True), "#edit-sheet:not([hidden]) .sheet-star"),
        ("library+sheet-unrated", "library", 375,
         lambda p: _open_sheet(p, False), "#edit-sheet:not([hidden]) .sheet-star"),
        ("maintenance", "maintenance", None,
         lambda p: _open_details(p, "#section-maintenance details"),
         "#section-maintenance details[open]"),
        ("keys", "keys", None, None, "#key-table tbody tr"),
        ("bundles", "bundles", None, None, "#bundle-url"),
        ("tasks", "tasks", None, None, "#task-cards .task-go"),
    ]
    return out


def uncovered(smoke):
    """Sections the viewer has that no state visits."""
    return sorted(set(smoke.SECTIONS) - {s[1] for s in states(smoke)})


# ---- Keys and the baseline ---------------------------------------------

def normalise_target(target):
    """A selector that survives demo data changing row by row.

    axe names a node by position (tr:nth-child(3) > td:nth-child(5)); the
    position of a row is data, not a defect, so it is folded away.
    """
    return re.sub(r":nth-child\(\d+\)", "", target)


def key(state, width, theme, rule, target):
    return f"{state} | {width} | {theme} | {rule} | {normalise_target(target)}"


def parse_baseline(text):
    """The keys listed: the first five fields of each non-comment line."""
    keys = set()
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            keys.add(" | ".join(part.strip() for part in line.split(" | ")[:5]))
    return keys


def compare(found, baseline):
    """(new, stale): violations not listed, and listed ones now gone."""
    return sorted(found - baseline), sorted(baseline - found)


# ---- The browser --------------------------------------------------------

def _set_theme(page, theme):
    # The app's own toggle, as a user would: it is what writes hc-theme.
    # Unset at first (the system's choice), so reaching the theme the
    # system already shows takes two clicks: away and back, explicitly.
    for _ in range(3):
        if page.evaluate("document.documentElement.dataset.theme") == theme:
            return
        page.click("#theme-toggle")
    raise RuntimeError(f"the theme toggle never reached {theme}")


def _drive(base, axe_path, problems):
    from playwright.sync_api import sync_playwright
    smoke = _smoke()
    found = set()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width in WIDTHS:
                for theme in THEMES:
                    context = browser.new_context(
                        viewport={"width": width, "height": 800})
                    page = context.new_page()
                    page.goto(base + "/")
                    page.wait_for_selector(f"{smoke.ROW}, {CARD}", timeout=15_000)
                    _set_theme(page, theme)
                    for name, section, only, setup, ready in states(smoke):
                        if only not in (None, width):
                            continue
                        # A fresh page per state: one state's open panel or
                        # sheet must not leak into the next one's scan.
                        page.goto(base + "/")
                        page.wait_for_selector(f"{smoke.ROW}, {CARD}", timeout=15_000)
                        page.click(f"#tab-{section}")
                        page.wait_for_selector(f"#section-{section}", state="visible")
                        page.wait_for_load_state("networkidle")
                        if setup:
                            setup(page)
                        try:
                            page.wait_for_selector(ready, timeout=5_000)
                        except Exception:   # noqa: BLE001 - reported
                            problems.append(f"{name} at {width} px ({theme}) "
                                            f"drew nothing to check: {ready}")
                            continue
                        page.add_script_tag(path=str(axe_path))
                        result = page.evaluate(
                            "(tags) => axe.run(document, {runOnly: {type: 'tag', values: tags}})",
                            TAGS)
                        for v in result["violations"]:
                            for node in v["nodes"]:
                                target = " ".join(str(t) for t in node["target"])
                                found.add(key(name, width, theme, v["id"], target))
                        print(f"{name} @ {width} {theme}: "
                              f"{len(result['violations'])} rules violated")
                    context.close()
        finally:
            browser.close()
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require-installed", action="store_true",
                        help="Refuse to run unless humble_catalog comes "
                             "from an installed package (CI)")
    parser.add_argument("--axe", type=Path, default=AXE,
                        help="Path to axe.min.js (default: node_modules)")
    parser.add_argument("--write-baseline", action="store_true",
                        help="Print every violation as a baseline line, to "
                             "annotate by hand; does not pass or fail")
    args = parser.parse_args(argv)
    # Targets can hold the viewer's own glyphs (a star), which a Windows
    # console's code page cannot print.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not args.axe.is_file():
        print(f"A11Y CHECK REFUSED: no axe-core at {args.axe}; run npm ci")
        return 1
    smoke = _smoke()
    missing = uncovered(smoke)
    if missing:
        print(f"A11Y CHECK FAILED: no state visits {', '.join(missing)}")
        return 1
    demo = smoke._load_demo()
    import humble_catalog
    problem = smoke.package_problem(humble_catalog.__file__, args.require_installed)
    if problem:
        print(f"A11Y CHECK REFUSED: {problem}")
        return 1

    from werkzeug.serving import WSGIRequestHandler, make_server

    class Quiet(WSGIRequestHandler):
        def log_request(self, *args, **kwargs):
            pass

    db_path = Path(tempfile.mkdtemp()) / "a11y.db"
    demo.seed(db_path)
    server = make_server("127.0.0.1", 0, demo.make_app(db_path),
                         threaded=True, request_handler=Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    problems = []
    try:
        found = _drive(f"http://127.0.0.1:{server.server_port}", args.axe, problems)
    finally:
        server.shutdown()

    if args.write_baseline:
        for line in sorted(found):
            print(f"{line} | #? | ")
        return 0
    new, stale = compare(found, parse_baseline(BASELINE.read_text(encoding="utf-8")))
    for line in new:
        problems.append(f"new violation: {line}")
    for line in stale:
        problems.append(f"fixed, so remove from tests/a11y-baseline.txt: {line}")
    if problems:
        print("A11Y CHECK FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"a11y check passed ({len(found)} known violations, all in the baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
