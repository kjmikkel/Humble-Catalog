"""The release gate the tag workflow runs before publishing (#112).

It exists because a release is the one thing CI does that cannot be
taken back quietly: a published wheel is downloaded by whoever finds it.
So everything that can be decided from files is decided here, in tested
Python, and the workflow only calls it.
"""
import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def release():
    spec = importlib.util.spec_from_file_location(
        "check_release", ROOT / "scripts" / "check_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- The tag names the version being released ---------------------------

def test_a_tag_matching_the_version_passes(release):
    assert release.tag_problem("v0.3.0", "0.3.0") is None


def test_a_tag_for_another_version_is_refused(release):
    # Tagging before bumping pyproject would publish 0.2.0's wheel under a
    # v0.3.0 release: the file name and the release name would disagree.
    problem = release.tag_problem("v0.3.0", "0.2.0")
    assert "v0.3.0" in problem and "0.2.0" in problem


def test_a_tag_without_the_v_is_refused(release):
    assert release.tag_problem("0.3.0", "0.3.0") is not None


def test_the_version_is_read_from_pyproject(release, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    assert release.project_version(tmp_path / "pyproject.toml") == "1.2.3"


# -- dist/ holds exactly what gets published ----------------------------

def _wheel(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return path


def _static(tmp_path, *names):
    d = tmp_path / "static"
    d.mkdir()
    for n in names:
        (d / n).write_text("x", encoding="utf-8")
    return d


def test_dist_needs_exactly_one_wheel_and_one_sdist(release, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    assert release.dist_problems(dist) != []
    _wheel(dist / "humble_catalog-0.3.0-py3-none-any.whl", [])
    (dist / "humble_catalog-0.3.0.tar.gz").write_bytes(b"")
    assert release.dist_problems(dist) == []
    # A leftover wheel from an earlier build would be published beside the
    # new one, under the new release's name.
    _wheel(dist / "humble_catalog-0.2.0-py3-none-any.whl", [])
    assert release.dist_problems(dist) != []


def test_a_wheel_missing_a_static_file_is_named(release, tmp_path):
    static = _static(tmp_path, "index.html", "app.js")
    whl = _wheel(tmp_path / "w.whl",
                 ["humble_catalog/webapp/static/index.html"])
    assert release.missing_static(whl, static) == [
        "humble_catalog/webapp/static/app.js"]


def test_a_complete_wheel_has_nothing_missing(release, tmp_path):
    static = _static(tmp_path, "index.html", "app.js")
    whl = _wheel(tmp_path / "w.whl",
                 ["humble_catalog/webapp/static/index.html",
                  "humble_catalog/webapp/static/app.js"])
    assert release.missing_static(whl, static) == []


def test_the_static_folder_it_checks_against_is_the_real_one(release):
    # Guards against a moved folder making every wheel look complete.
    assert (release.STATIC / "index.html").is_file()


# -- main(): the gate the workflow calls --------------------------------

def _good_release(tmp_path, version="0.3.0"):
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8")
    static = _static(tmp_path, "index.html")
    dist = tmp_path / "dist"
    dist.mkdir()
    _wheel(dist / f"humble_catalog-{version}-py3-none-any.whl",
           ["humble_catalog/webapp/static/index.html"])
    (dist / f"humble_catalog-{version}.tar.gz").write_bytes(b"")
    return tmp_path / "pyproject.toml", dist, static


def test_main_passes_a_good_release(release, tmp_path, capsys):
    pyproject, dist, static = _good_release(tmp_path)
    assert release.main(["--tag", "v0.3.0", "--dist", str(dist)],
                        pyproject=pyproject, static=static) == 0


def test_main_reports_every_problem_at_once(release, tmp_path, capsys):
    # One run should say everything that is wrong, not one thing per tag.
    pyproject, dist, static = _good_release(tmp_path)
    (static / "app.js").write_text("x", encoding="utf-8")
    assert release.main(["--tag", "v9.9.9", "--dist", str(dist)],
                        pyproject=pyproject, static=static) == 1
    out = capsys.readouterr().out
    assert "v9.9.9" in out and "app.js" in out


def test_main_without_a_tag_checks_only_the_artifacts(release, tmp_path):
    # The pull-request dry run has no tag to compare.
    pyproject, dist, static = _good_release(tmp_path)
    assert release.main(["--dist", str(dist)],
                        pyproject=pyproject, static=static) == 0
