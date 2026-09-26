"""Run the viewer's JavaScript for real, instead of grepping app.js.

The other JS tests in this suite are text assertions: they pin that code
exists, not that it behaves. That gap let a regression through once --
`tagBadges` threw on a missing field and blanked the whole page while
every text assertion still passed.

Node is optional. Without it these tests skip, so the suite still runs on
a machine that only has Python.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_HARNESS = Path(__file__).parent / "js" / "harness.mjs"
_STATIC = _ROOT / "humble_catalog" / "webapp" / "static"
# The viewer's own scripts in <script> order. fuzzy.js is loaded by the
# harness itself (it has to be published by hand), so it is not listed.
# Appending here is the whole cost of adding a viewer script.
VIEWER_JS = [_STATIC / "app.js", _STATIC / "catalog.js",
             _STATIC / "stats.js",
             _STATIC / "maintenance.js", _STATIC / "keys.js",
             _STATIC / "bundles.js", _STATIC / "tasks.js",
             _STATIC / "shell.js"]


def node_executable():
    """The path to `node`; without one, skip -- or fail, where it is required.

    A skip is right on a contributor's machine, where Node is optional.
    In CI it would hide the loss of the whole JS suite behind a skip
    count, so the workflow sets HUMBLE_REQUIRE_NODE and a missing Node
    fails instead (#109). An empty value counts as unset.
    """
    node = shutil.which("node")
    if node is not None:
        return node
    if os.environ.get("HUMBLE_REQUIRE_NODE"):
        pytest.fail("node not found, and HUMBLE_REQUIRE_NODE is set: the "
                    "JS behaviour tests must run here, not skip")
    pytest.skip("node not installed; JS behaviour tests skipped")


def eval_js(expression):
    """Evaluate `expression` with app.js loaded in a stubbed DOM.

    `app` holds app.js's top-level bindings (plus setItems/getItems/
    setFetch to drive state); `dom` records innerHTML writes by selector,
    so a test can ask which renderers actually ran. The expression is
    awaited, so it may be async. Returns the JSON-decoded result.
    """
    node = node_executable()
    # encoding is explicit: text=True alone decodes with the locale
    # codepage, which on Windows is cp1252, and Node writes UTF-8. That
    # silently mangled every non-ASCII character -- a euro sign came back
    # as its own trailing byte -- so no test could assert on rendered
    # currency, punctuation or an accented title.
    proc = subprocess.run(
        [node, str(_HARNESS), ",".join(str(p) for p in VIEWER_JS), expression],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    if proc.returncode != 0:
        raise AssertionError(
            f"JS harness failed:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout)


def eval_js_error(expression):
    """Return the error message `expression` throws, or None if it doesn't.

    Lets a test assert that something no longer throws without the harness
    itself failing when it still does.
    """
    return eval_js(
        "(async () => { try { await (%s); return null; }"
        " catch (e) { return e.constructor.name + ': ' + e.message; } })()"
        % expression)
