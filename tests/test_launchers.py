"""The double-click launchers at the top of the checkout (#96).

They exist so starting the viewer needs no terminal knowledge: no venv
to activate, no command to type. Each hands straight to its OS's serve
wrapper, which already checks the venv, honours HUMBLE_PORT and opens a
viewer that is already running, so none of that is repeated here.

The window must stay visible and open: login, reset and restore are
handed to that console (humble_catalog/handoff.py), and an error that
closes its own window is an error nobody read.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "Humble Catalog.cmd"
MACOS = ROOT / "Humble Catalog.command"


def _text(path):
    return path.read_bytes().decode("utf-8")


def test_both_launchers_exist():
    assert WINDOWS.is_file() and MACOS.is_file()


def test_the_windows_launcher_runs_the_serve_wrapper():
    text = _text(WINDOWS).lower()
    assert r"scripts\windows\serve.ps1" in text
    # Double-clicking a .cmd runs with the caller's directory, not the
    # file's; %~dp0 is the file's own folder.
    assert "%~dp0" in text
    # Without Bypass a default execution policy refuses the .ps1.
    assert "-executionpolicy bypass" in text


def test_the_windows_launcher_holds_the_window_on_a_failure():
    text = _text(WINDOWS).lower()
    assert "pause" in text and "errorlevel" in text


def test_the_windows_launcher_never_hides_its_window():
    # The handoff runs in this console.
    text = _text(WINDOWS).lower()
    assert "-detached" not in text and "start " not in text


def test_the_macos_launcher_runs_the_serve_wrapper():
    text = _text(MACOS)
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "scripts/macos/serve.sh" in text
    assert 'dirname "$0"' in text
    assert "--detached" not in text


def test_the_macos_launcher_holds_the_window_on_a_failure():
    assert "read " in _text(MACOS)


def test_the_macos_launcher_has_lf_endings():
    # A CRLF shebang is "bash\r", which macOS refuses to run.
    assert b"\r\n" not in MACOS.read_bytes()


def test_the_windows_launcher_has_crlf_endings():
    # cmd.exe misreads labels and GOTOs in an LF-only batch file.
    data = WINDOWS.read_bytes()
    assert b"\r\n" in data and data.count(b"\n") == data.count(b"\r\n")


def test_line_endings_are_pinned_for_every_checkout():
    attrs = _text(ROOT / ".gitattributes")
    assert "*.command text eol=lf" in attrs
    assert "*.cmd text eol=crlf" in attrs


def _git_mode(path):
    try:
        out = subprocess.run(
            ["git", "ls-files", "-s", "--", path.name], cwd=ROOT,
            capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    if not out:
        pytest.skip(f"{path.name} is not committed yet")
    return out.split()[0]


def test_the_macos_launcher_is_executable_in_git():
    # Finder runs a .command only if it is executable, and a checkout
    # takes the mode from the index, not from the file on this disk.
    assert _git_mode(MACOS) == "100755"
