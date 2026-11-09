"""No new write may ignore whether it worked (#151, ratchet for #142).

post() resolves on any HTTP status and rejects only when the server is
unreachable, so a caller that just awaits it shows a refused or lost write
exactly like a saved one. This scans every viewer script for post() calls
whose result is thrown away, or assigned and then never checked, and
compares them with tests/unchecked-writes-baseline.txt.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "humble_catalog" / "webapp" / "static"
_BASELINE = Path(__file__).resolve().parent / "unchecked-writes-baseline.txt"

# How far below an assignment its .ok or .status check may sit.
_CHECK_WINDOW = 12

_CALL = re.compile(r"\bpost\(")
_DEFINITION = re.compile(r"\bfunction\s+post\(")
_ASSIGNED = re.compile(r"(\w+)\s*=\s*await\s+post\(")
_ROUTE = re.compile(r"""post\(\s*(["'`])(.*?)\1""")
# The nearest enclosing name: a top-level function, or a top-level
# listener, which is where most of the viewer's click handling lives.
_OWNER = re.compile(r'^(?:async\s+)?function\s+(\w+)|^\s{0,2}(?:document|\$\([^)]*\))'
                    r'\.addEventListener\("(\w+)"')


def _strip_comment(line):
    # Enough for this codebase: no viewer script puts "//" inside a string
    # on a line that also calls post(), and comments describing post()
    # ("posts through its `post()`") must not count as calls.
    return line.split("//", 1)[0]


def scan():
    """Every unchecked post(): a set of 'file | function | route' keys.

    Also returns how many calls were looked at, so a scan that matched
    nothing cannot pass as a clean one.
    """
    found, calls = set(), 0
    for path in sorted(_STATIC.glob("*.js")):
        lines = path.read_text(encoding="utf-8").splitlines()
        owner = "(top level)"
        for n, raw in enumerate(lines):
            m = _OWNER.match(raw)
            if m:
                owner = m.group(1) or f"{m.group(2)} listener"
            line = _strip_comment(raw)
            if not _CALL.search(line) or _DEFINITION.search(line):
                continue
            calls += 1
            route = _ROUTE.search(" ".join(lines[n:n + 2]))
            key = f"{path.name} | {owner} | {route.group(2) if route else '?'}"
            assigned = _ASSIGNED.search(line)
            if assigned:
                var = re.escape(assigned.group(1))
                # Stops at the next function or listener: a check that
                # belongs to the next one must not excuse this one.
                window = []
                for later in lines[n + 1:n + 1 + _CHECK_WINDOW]:
                    if _OWNER.match(later):
                        break
                    window.append(later)
                window = "\n".join(window)
                if re.search(rf"\b{var}\.(ok|status)\b", window):
                    continue
            found.add(key)
    return found, calls


def _baseline():
    keys = set()
    for line in _BASELINE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            keys.add(" | ".join(part.strip() for part in line.split("|")[:3]))
    return keys


def test_the_scan_sees_the_viewers_writes():
    # Not vacuous: a pattern that stopped matching would report zero.
    _, calls = scan()
    assert calls >= 10, calls


def test_no_write_ignores_its_result_unless_listed():
    found, _ = scan()
    new = sorted(found - _baseline())
    assert not new, (
        "post() whose result is never checked -- use saved() from app.js, "
        "or check .ok, so a refused or lost write is reported (#142):\n  "
        + "\n  ".join(new))


def test_every_listed_case_still_occurs():
    found, _ = scan()
    gone = sorted(_baseline() - found)
    assert not gone, (
        "fixed, so remove from tests/unchecked-writes-baseline.txt:\n  "
        + "\n  ".join(gone))


def test_the_scan_flags_the_shapes_it_is_meant_to(tmp_path, monkeypatch):
    # The three ways a result goes unread, and the two that are fine.
    (tmp_path / "x.js").write_text("""\
async function dropped() {
  await post("/api/a", {});
}
function returned() {
  armOrFire(btn, () => post("/api/b", {}));
}
async function unchecked() {
  const resp = await post("/api/c", {});
  render();
}
async function checked() {
  const resp = await post("/api/d", {});
  if (!resp.ok) return;
}
// A comment that mentions post( is not a call.
async function post(url, body) { return fetch(url); }
""", encoding="utf-8")
    monkeypatch.setattr(__import__(__name__), "_STATIC", tmp_path)
    found, calls = scan()
    assert calls == 4
    assert found == {"x.js | dropped | /api/a", "x.js | returned | /api/b",
                     "x.js | unchecked | /api/c"}
