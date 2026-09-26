"""Smoke-test the viewer in a real browser, against the demo catalog (#114).

Every other viewer test stops short of a browser: the JS harness stubs
the DOM, and the webapp tests use Flask's test client. So two kinds of
failure could ship green: a script that loads in the wrong order or
from the wrong path, and new JS talking to an old API -- which once drew
zero rows with every panel hidden and nothing on screen to explain it.

This serves the demo catalog (invented titles only, scripts/demo_catalog.py)
on a free local port, opens it in headless Chromium, and fails on:
- any console error or uncaught exception;
- any response of 400 or above, a missing script or stylesheet among them;
- a Library that never draws a row;
- a section tab that does not open its section.

CI runs it with --require-installed, from a fresh venv holding the built
wheel: then it refuses to run against the checkout, so what it tests is
what a user installs.

Run:    python scripts/smoke_viewer.py [--require-installed] [--screenshot PATH]
Needs:  python -m playwright install chromium
"""
import argparse
import importlib.util
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The section tabs, in page order. tests/test_smoke_viewer.py compares
# this with index.html, so a new section cannot go unvisited.
SECTIONS = ("library", "maintenance", "keys", "bundles", "tasks")

# The table's own rows, not its "Loading the catalog…" placeholder.
ROW = "#catalog tbody tr:not(.table-empty)"


def package_problem(module_file, require_installed):
    """Why this humble_catalog must not be smoke-tested, or None."""
    if require_installed and "site-packages" not in Path(module_file).parts:
        return (f"humble_catalog was imported from {module_file}, not from "
                "an installed package: this run would test the checkout")
    return None


def _load_demo():
    # By path, because scripts/ is not a package. The demo leaves an
    # installed humble_catalog alone (see its _checkout_on_path).
    spec = importlib.util.spec_from_file_location(
        "demo_catalog", HERE / "demo_catalog.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    return demo


def _drive(base, problems, screenshot):
    """Open the viewer and visit every section; append what went wrong."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("console", lambda m: m.type == "error"
                    and problems.append(f"console error: {m.text}"))
            page.on("pageerror", lambda e: problems.append(
                f"uncaught exception: {e}"))
            page.on("response", lambda r: r.status >= 400
                    and problems.append(f"HTTP {r.status}: {r.url}"))
            page.goto(base + "/")
            try:
                page.wait_for_selector(ROW, timeout=15_000)
                print(f"library: {page.locator(ROW).count()} rows drawn")
            except Exception:   # noqa: BLE001 - reported, not raised
                problems.append("the Library drew no rows within 15 s")
            for section in SECTIONS:
                page.click(f"#tab-{section}")
                try:
                    page.wait_for_selector(f"#section-{section}",
                                           state="visible", timeout=5_000)
                    print(f"{section}: opens")
                except Exception:   # noqa: BLE001
                    problems.append(f"the {section} tab did not open its "
                                    "section")
            # Let the requests a section fires on opening settle, so their
            # failures are counted too.
            page.wait_for_load_state("networkidle")
            if problems and screenshot:
                # Demo data only: nothing from a real library is in frame.
                page.screenshot(path=screenshot, full_page=True)
                print(f"screenshot: {screenshot}")
        finally:
            browser.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require-installed", action="store_true",
                        help="Refuse to run unless humble_catalog comes "
                             "from an installed package (CI)")
    parser.add_argument("--screenshot", metavar="PATH",
                        help="Where to save a screenshot if anything fails")
    args = parser.parse_args(argv)

    demo = _load_demo()
    import humble_catalog
    print(f"humble_catalog: {humble_catalog.__file__}")
    problem = package_problem(humble_catalog.__file__, args.require_installed)
    if problem:
        print(f"SMOKE TEST REFUSED: {problem}")
        return 1

    from werkzeug.serving import WSGIRequestHandler, make_server

    class Quiet(WSGIRequestHandler):
        # A line per request buries the verdict; failures are reported by
        # the browser's own response hook instead.
        def log_request(self, *args, **kwargs):
            pass

    db_path = Path(tempfile.mkdtemp()) / "smoke.db"
    demo.seed(db_path)
    # Port 0: the OS picks a free one, so this never collides with a
    # viewer or demo already running on 8087 or 8099.
    server = make_server("127.0.0.1", 0, demo.make_app(db_path),
                         threaded=True, request_handler=Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    problems = []
    try:
        _drive(f"http://127.0.0.1:{server.server_port}", problems,
               args.screenshot)
    finally:
        server.shutdown()
    if problems:
        print("SMOKE TEST FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
