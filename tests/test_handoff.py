import sys

import pytest

from humble_catalog import handoff, jobs


def _snap(d, stamp, covers=False):
    d.mkdir(exist_ok=True)
    p = d / f"catalog-{stamp}.db"
    p.write_bytes(b"x" * 10)
    if covers:
        (d / f"covers-{stamp}.zip").write_bytes(b"z")
    return p


def test_argv_for_login_and_reset_is_the_bare_command():
    assert handoff.argv("login") == [
        sys.executable, "-m", "humble_catalog", "login"]
    assert handoff.argv("reset", {}) == [
        sys.executable, "-m", "humble_catalog", "reset"]


def test_argv_refuses_an_in_page_command():
    # harvest is the job runner's; the handoff table knows only three.
    with pytest.raises(ValueError, match="unknown command"):
        handoff.argv("harvest")


def test_argv_refuses_a_non_boolean_option(tmp_path):
    d = tmp_path / "backups"
    _snap(d, "20260101-120000")
    with pytest.raises(ValueError, match="must be true or false"):
        handoff.argv("restore", {"covers": "yes"},
                     snapshot="catalog-20260101-120000.db", backups_dir=d)


def test_restore_needs_a_snapshot(tmp_path):
    with pytest.raises(ValueError, match="snapshot"):
        handoff.argv("restore", {}, backups_dir=tmp_path)


def test_restore_takes_only_a_listed_snapshot(tmp_path):
    d = tmp_path / "backups"
    _snap(d, "20260101-120000")
    for bad in ("../catalog.db", "catalog-20991231-000000.db",
                str(d / "catalog-20260101-120000.db"), 7):
        with pytest.raises(ValueError, match="snapshot"):
            handoff.argv("restore", {}, snapshot=bad, backups_dir=d)


def test_restore_argv_names_the_listed_file_and_the_covers_flag(tmp_path):
    d = tmp_path / "backups"
    _snap(d, "20260101-120000", covers=True)
    line = handoff.argv("restore", {"covers": True},
                        snapshot="catalog-20260101-120000.db", backups_dir=d)
    assert line == [sys.executable, "-m", "humble_catalog", "restore",
                    str(d / "catalog-20260101-120000.db"), "--covers"]


def test_only_restore_takes_a_snapshot(tmp_path):
    d = tmp_path / "backups"
    _snap(d, "20260101-120000")
    with pytest.raises(ValueError, match="snapshot"):
        handoff.argv("reset", {}, snapshot="catalog-20260101-120000.db",
                     backups_dir=d)


def test_list_backups_is_newest_first_and_pairs_covers(tmp_path):
    d = tmp_path / "backups"
    _snap(d, "20260101-120000", covers=True)
    _snap(d, "20260301-090000")
    rows = handoff.list_backups(d)
    assert [r["name"] for r in rows] == [
        "catalog-20260301-090000.db", "catalog-20260101-120000.db"]
    assert [r["covers"] for r in rows] == [False, True]
    assert rows[0]["size"] == 10
    assert len(rows[0]["modified"]) == len("2026-03-01 09:00")


def test_list_backups_leaves_out_raw_copies_of_a_damaged_catalog(tmp_path):
    # restore's own safety copy of an unreadable catalog. Nobody means to
    # put a damaged file back from a picker.
    d = tmp_path / "backups"
    _snap(d, "20260101-120000")
    (d / "catalog-20260102-120000.unreadable.db").write_bytes(b"?")
    assert [r["name"] for r in handoff.list_backups(d)] == [
        "catalog-20260101-120000.db"]


def test_list_backups_of_a_missing_directory_is_empty(tmp_path):
    assert handoff.list_backups(tmp_path / "nope") == []


def test_a_slot_holds_one_handoff_until_it_is_finished():
    slot = handoff.HandoffSlot()
    assert slot.request("reset", ["x"]) == 0
    with pytest.raises(jobs.Busy, match="reset"):
        slot.request("login", ["y"])
    assert slot.take() == {"command": "reset", "argv": ["x"]}
    # Taken is not free: until the command has run and the viewer is back,
    # a second request would queue a handoff nobody asked for twice.
    assert slot.busy() == "reset"
    with pytest.raises(jobs.Busy):
        slot.request("login", ["y"])
    slot.finish(0)
    assert slot.busy() is None
    assert slot.state()["generation"] == 1
    assert slot.state()["last"]["command"] == "reset"
    assert slot.state()["last"]["exit_code"] == 0


def test_take_on_an_empty_slot_is_none():
    assert handoff.HandoffSlot().take() is None


def test_run_in_terminal_inherits_the_console(capsys):
    seen = {}

    class Done:
        returncode = 3

    def fake_run(line, **kw):
        seen["line"], seen["kw"] = line, kw
        return Done()

    assert handoff.run_in_terminal("reset", ["a", "b"], _run=fake_run) == 3
    assert seen["line"] == ["a", "b"]
    # No stdio redirection and no shell: inheriting the console is what
    # lets reset read RESET and puts the login window in front.
    for key in ("stdin", "stdout", "stderr", "shell", "creationflags"):
        assert key not in seen["kw"]
    out = capsys.readouterr().out
    assert "reset" in out and "viewer" in out.lower()


def test_run_in_terminal_survives_ctrl_c(capsys):
    def interrupted(line, **kw):
        raise KeyboardInterrupt

    assert handoff.run_in_terminal("login", ["a"], _run=interrupted) is None
    assert "interrupted" in capsys.readouterr().out.lower()


def test_run_in_terminal_survives_a_failed_spawn(capsys):
    def missing(line, **kw):
        raise FileNotFoundError("no python")

    assert handoff.run_in_terminal("login", ["a"], _run=missing) is None
    assert "could not start" in capsys.readouterr().out.lower()


# -- Is there a terminal to hand over to at all? (#98) -------------------
# A viewer whose stdin is not a terminal (pythonw, nohup ... < /dev/null,
# a service) has nowhere for login, reset or restore to run: reset and
# restore would refuse, and the page would wait on a reconnect for
# nothing. A hidden Windows console DOES pass isatty(), which is why the
# detached wrappers also pass --no-handoff explicitly.

class _Stdin:
    def __init__(self, tty):
        self._tty = tty

    def isatty(self):
        return self._tty


def test_a_terminal_stdin_can_take_a_handoff():
    assert handoff.terminal_available(_Stdin(True)) is True


def test_a_redirected_stdin_cannot():
    assert handoff.terminal_available(_Stdin(False)) is False


def test_no_stdin_at_all_cannot():
    # pythonw, and a process started with its standard handles closed.
    assert handoff.terminal_available(None) is False


def test_a_closed_stdin_cannot():
    class Closed:
        def isatty(self):
            raise ValueError("I/O operation on closed file")
    assert handoff.terminal_available(Closed()) is False
