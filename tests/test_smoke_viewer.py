"""The viewer smoke test's own guard (#114).

The smoke test itself needs Chromium and runs as its own CI job; see
scripts/smoke_viewer.py. What is tested here is the one decision it
makes that could make it pass for the wrong reason: whether the
humble_catalog it drives is the installed package or the checkout.
"""
import importlib.util
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def smoke():
    spec = importlib.util.spec_from_file_location(
        "smoke_viewer", ROOT / "scripts" / "smoke_viewer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


INSTALLED = "/tmp/smoke/lib/python3.12/site-packages/humble_catalog/__init__.py"
CHECKOUT = "/home/runner/work/Humble-Catalog/humble_catalog/__init__.py"


def test_an_installed_package_passes_when_required(smoke):
    assert smoke.package_problem(INSTALLED, require_installed=True) is None


def test_the_checkout_fails_when_installed_is_required(smoke):
    # CI's whole point: a job that quietly served the source tree would
    # pass on a wheel with no viewer in it, as #107's did.
    problem = smoke.package_problem(CHECKOUT, require_installed=True)
    assert problem is not None and CHECKOUT in problem


def test_the_checkout_is_fine_locally(smoke):
    assert smoke.package_problem(CHECKOUT, require_installed=False) is None


# The decision must not depend on which OS the test runs on. `Path` on
# Linux and macOS does not split on "\", so a check built on Path.parts
# passed on Windows and failed on every other runner. Each case runs
# under both path flavours, so the failure shows on any machine.
_FLAVOURS = {"posix": PurePosixPath, "windows": PureWindowsPath}


@pytest.mark.parametrize("flavour", sorted(_FLAVOURS))
@pytest.mark.parametrize("path", [
    r"C:\venv\Lib\site-packages\humble_catalog\__init__.py",
    "/tmp/smoke/lib/python3.12/site-packages/humble_catalog/__init__.py",
])
def test_site_packages_counts_as_installed_on_any_os(smoke, monkeypatch,
                                                      flavour, path):
    monkeypatch.setattr(smoke, "Path", _FLAVOURS[flavour])
    assert smoke.package_problem(path, require_installed=True) is None


@pytest.mark.parametrize("flavour", sorted(_FLAVOURS))
@pytest.mark.parametrize("path", [
    r"C:\src\Humble-Catalog\humble_catalog\__init__.py",
    "/home/runner/work/Humble-Catalog/humble_catalog/__init__.py",
    # A folder merely NAMED like it is not an installed package.
    "/home/me/site-packages-notes/humble_catalog/__init__.py",
])
def test_a_checkout_is_refused_on_any_os(smoke, monkeypatch, flavour, path):
    monkeypatch.setattr(smoke, "Path", _FLAVOURS[flavour])
    assert smoke.package_problem(path, require_installed=True) is not None


def test_it_opens_every_section_the_viewer_has(smoke):
    # A section added to the viewer and forgotten here would never be
    # smoke-tested. The list is compared with the page's own tab markup.
    html = (ROOT / "humble_catalog" / "webapp" / "static"
            / "index.html").read_text(encoding="utf-8")
    tabs = [line.split('id="tab-', 1)[1].split('"', 1)[0]
            for line in html.splitlines() if 'id="tab-' in line]
    assert tabs and list(smoke.SECTIONS) == tabs
