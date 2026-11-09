"""The autocomplete fields follow the WAI-ARIA combobox pattern (#150).

Runs autocomplete.js itself in tests/js/autocomplete_harness.mjs, a DOM
just big enough for one module: the viewer harness stubs Autocomplete out.
"""
import json
import subprocess
from pathlib import Path

from tests.js_harness import node_executable

_ROOT = Path(__file__).resolve().parent.parent
_HARNESS = _ROOT / "tests" / "js" / "autocomplete_harness.mjs"
_MODULE = _ROOT / "humble_catalog" / "webapp" / "static" / "autocomplete.js"

_GENRES = '["Fantasy", "Fairy tales", "History"]'


def _run(body):
    proc = subprocess.run(
        [node_executable(), str(_HARNESS), str(_MODULE), body],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    if proc.returncode != 0:
        raise AssertionError(f"autocomplete harness failed:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout)


def _attached(then, counts="undefined"):
    return _run("""(() => {
      const input = field("f-genre");
      globalThis.picked = null;
      Autocomplete.attach(input, () => %s, (v, via) => { picked = [v, via]; }, %s);
      %s
    })()""" % (_GENRES, counts, then))


def test_an_attached_field_is_a_collapsed_combobox():
    got = _attached("return attrs(input);")
    assert got == {"role": "combobox", "aria-autocomplete": "list",
                   "aria-expanded": "false"}


def test_typing_opens_a_named_listbox_of_options():
    got = _attached("""type(input, "fa");
      const list = openList();
      return {input: attrs(input), list: [list.id, attrs(list)],
              options: list.children.map(o => [o.id, attrs(o)])};""")
    assert got["input"]["aria-expanded"] == "true"
    assert got["input"]["aria-controls"] == "f-genre-suggestions"
    assert "aria-activedescendant" not in got["input"]
    assert got["list"] == ["f-genre-suggestions",
                           {"role": "listbox", "aria-label": "Suggestions"}]
    assert got["options"] == [
        ["f-genre-suggestions-0", {"role": "option", "aria-selected": "false"}],
        ["f-genre-suggestions-1", {"role": "option", "aria-selected": "false"}],
    ]


def test_the_arrows_move_the_active_descendant_and_the_selection():
    got = _attached("""type(input, "fa");
      key(input, "ArrowDown");
      const first = [input.getAttribute("aria-activedescendant"),
                     openList().children.map(o => o.getAttribute("aria-selected"))];
      key(input, "ArrowDown");
      const second = input.getAttribute("aria-activedescendant");
      key(input, "ArrowDown");   // wraps, as before
      return [first, second, input.getAttribute("aria-activedescendant")];""")
    assert got == [["f-genre-suggestions-0", ["true", "false"]],
                   "f-genre-suggestions-1", "f-genre-suggestions-0"]


def test_closing_collapses_the_field_and_drops_the_references():
    got = _attached("""type(input, "fa");
      key(input, "ArrowDown");
      key(input, "Escape");
      return [attrs(input), openList()];""")
    assert got == [{"role": "combobox", "aria-autocomplete": "list",
                    "aria-expanded": "false"}, None]


def test_picking_with_enter_still_commits_the_highlighted_value():
    got = _attached("""type(input, "fa");
      key(input, "ArrowDown"); key(input, "ArrowDown");
      key(input, "Enter");
      return [picked, input.getAttribute("aria-expanded")];""")
    assert got == [["Fairy tales", True], "false"]


def test_an_option_with_a_count_is_named_with_a_separator():
    got = _attached("""type(input, "hist");
      return attrs(openList().children[0])["aria-label"];""",
                    counts='() => new Map([["History", 3]])')
    assert got == "History, 3"


def test_a_field_without_an_id_still_gets_a_unique_list():
    got = _run("""(() => {
      const ids = [];
      for (let n = 0; n < 2; n++) {
        const input = field("");
        Autocomplete.attach(input, () => %s, () => {});
        type(input, "fa");
        ids.push(input.getAttribute("aria-controls"));
      }
      return ids;
    })()""" % _GENRES)
    assert got[0] != got[1]
    assert all(i.endswith("-suggestions") for i in got)
