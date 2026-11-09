"""The accessibility ratchet's own logic (#152).

The scan itself needs Chromium and axe-core and runs in CI's smoke job;
see scripts/a11y_viewer.py. What is tested here is everything that could
make it pass for the wrong reason: the baseline comparison, the target
folding, the section coverage and the pinned axe-core.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def a11y():
    spec = importlib.util.spec_from_file_location(
        "a11y_viewer", ROOT / "scripts" / "a11y_viewer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_section_has_a_state(a11y):
    # smoke_viewer.SECTIONS is itself pinned to index.html's tabs by
    # test_smoke_viewer, so a new section reaches this check too.
    assert a11y.uncovered(a11y._smoke()) == []


def test_a_missing_section_is_reported(a11y):
    class Smoke:
        SECTIONS = ("library", "maintenance", "keys", "bundles", "tasks", "reports")
        ROW = "tr"
    assert a11y.uncovered(Smoke) == ["reports"]


def test_every_state_waits_for_something_to_check(a11y):
    for name, section, only, setup, ready in a11y.states(a11y._smoke()):
        assert ready, name
        assert only in (None, *a11y.WIDTHS), name


def test_row_positions_are_folded_out_of_targets(a11y):
    assert (a11y.normalise_target("#catalog > tbody > tr:nth-child(3) > td:nth-child(5) > .tag")
            == "#catalog > tbody > tr > td > .tag")


def test_new_and_stale_are_both_reported(a11y):
    found = {a11y.key("keys", 375, "dark", "color-contrast", "td:nth-child(2) > span")}
    baseline = a11y.parse_baseline(
        "# a comment\n"
        "\n"
        "library | 1280 | light | target-size | .edit-num | #152 | a reason\n")
    new, stale = a11y.compare(found, baseline)
    assert new == ["keys | 375 | dark | color-contrast | td > span"]
    assert stale == ["library | 1280 | light | target-size | .edit-num"]


def test_a_listed_violation_matches_whatever_its_reason_says(a11y):
    found = {a11y.key("tasks", 1280, "light", "label", "#sheet-file")}
    baseline = a11y.parse_baseline(
        "tasks | 1280 | light | label | #sheet-file | #999 | a | reason | with bars\n")
    assert a11y.compare(found, baseline) == ([], [])


def test_the_committed_baseline_is_well_formed(a11y):
    for line in (ROOT / "tests" / "a11y-baseline.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            parts = [p.strip() for p in line.split(" | ")]
            assert len(parts) >= 7, line
            assert parts[1] in {str(w) for w in a11y.WIDTHS}, line
            assert parts[2] in a11y.THEMES, line
            assert parts[5].startswith("#") and parts[5][1:].isdigit(), line


def test_axe_core_is_pinned_exactly_and_never_from_a_cdn(a11y):
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    version = pkg["devDependencies"]["axe-core"]
    assert version[0].isdigit(), version          # no ^ or ~ range
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"]["node_modules/axe-core"]["version"] == version
    assert a11y.AXE.parts[-3:] == ("node_modules", "axe-core", "axe.min.js")
    src = (ROOT / "scripts" / "a11y_viewer.py").read_text(encoding="utf-8")
    assert "cdn" not in src.lower().replace("never a cdn", "")
