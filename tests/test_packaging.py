"""What a non-editable install actually contains (#107).

Every other test runs against the source tree, through the editable
install the README and CI both use, which serves the viewer's files
straight from the checkout. So a wheel with no viewer in it went unseen:
`pip install .`, a git URL, or a released wheel all started a viewer
with no page to serve.

The builds call setuptools' PEP 517 hooks directly -- the same code pip
and `python -m build` run -- in a subprocess, without build isolation,
so no test downloads anything. They build from a copy holding only what
a build reads, which also proves the package definition is enough on
its own, without whatever else a checkout happens to contain.
"""
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
STATIC = ROOT / "humble_catalog" / "webapp" / "static"
# What [project] in pyproject.toml reads besides the package itself.
BUILD_INPUTS = ("pyproject.toml", "README.md", "LICENSE")


def _static_files():
    """Every file in the viewer's static folder, as a path inside a wheel.

    Read from disk at test time rather than listed by hand, so a new
    script or icon is covered without anyone remembering to add it.
    """
    return sorted(p.relative_to(ROOT).as_posix()
                  for p in STATIC.iterdir() if p.is_file())


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """(wheel names, sdist names), each relative to the package root."""
    src = tmp_path_factory.mktemp("src")
    for name in BUILD_INPUTS:
        shutil.copy2(ROOT / name, src / name)
    shutil.copytree(ROOT / "humble_catalog", src / "humble_catalog",
                    ignore=shutil.ignore_patterns("__pycache__"))
    out = tmp_path_factory.mktemp("dist")
    # The hooks return the file names they wrote; the markers keep them
    # apart from anything setuptools logs to stdout on the way.
    code = ("import sys; from setuptools import build_meta as b; "
            "d = sys.argv[1]; "
            "print('WHEEL=' + b.build_wheel(d)); "
            "print('SDIST=' + b.build_sdist(d))")
    proc = subprocess.run([sys.executable, "-c", code, str(out)], cwd=src,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    names = dict(line.split("=", 1) for line in proc.stdout.splitlines()
                 if line.startswith(("WHEEL=", "SDIST=")))
    with zipfile.ZipFile(out / names["WHEEL"]) as whl:
        wheel = set(whl.namelist())
        entry_points = next(
            (whl.read(n).decode("utf-8") for n in wheel
             if n.endswith(".dist-info/entry_points.txt")), "")
    with tarfile.open(out / names["SDIST"]) as tar:
        # An sdist nests everything under "<name>-<version>/".
        sdist = {m.name.split("/", 1)[1] for m in tar.getmembers()
                 if "/" in m.name}
    return wheel, sdist, entry_points


def test_there_are_static_files_to_check():
    # Guards the two tests below against passing vacuously if the folder
    # ever moves: an empty expected list would match any wheel.
    assert "humble_catalog/webapp/static/index.html" in _static_files()


def test_the_wheel_ships_every_static_file(built):
    wheel, _sdist, _entry_points = built
    assert [f for f in _static_files() if f not in wheel] == []


def test_the_sdist_ships_every_static_file(built):
    # A wheel built from the sdist -- which is what pip does with one --
    # can only contain what the sdist carried.
    _wheel, sdist, _entry_points = built
    assert [f for f in _static_files() if f not in sdist] == []


# -- The `humble-catalog` command (#96) ---------------------------------
# Without it an installed catalog is `python -m humble_catalog ...` from
# an activated venv, which is the step a newcomer does not know to take.

def test_the_wheel_installs_a_humble_catalog_command(built):
    _wheel, _sdist, entry_points = built
    assert "[console_scripts]" in entry_points
    assert "humble-catalog = humble_catalog.__main__:main" in entry_points


def test_the_command_points_at_a_real_function():
    import humble_catalog.__main__ as cli
    assert callable(cli.main)
