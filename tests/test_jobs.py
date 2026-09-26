import sys
import time
import pytest
from humble_catalog import db, jobs


def test_argv_builds_from_the_whitelist():
    assert jobs.argv("harvest", {"ignore_quota": True}) == [
        sys.executable, "-m", "humble_catalog", "harvest", "--ignore-quota"]


def test_argv_always_passes_no_login_to_extract():
    # Non-negotiable: without it a background extract can block forever on
    # a browser window the page cannot show.
    assert "--no-login" in jobs.argv("extract", {})


def test_argv_renames_underscored_commands():
    assert jobs.argv("import_games", {})[3] == "import-games"


def test_argv_refuses_an_unknown_command():
    with pytest.raises(ValueError, match="unknown command"):
        jobs.argv("rm", {})


def test_argv_refuses_an_option_the_command_does_not_have():
    with pytest.raises(ValueError, match="does not accept"):
        jobs.argv("reparse", {"ignore_quota": True})


def test_argv_refuses_a_non_boolean_option():
    # The guard that keeps request strings out of argv entirely.
    with pytest.raises(ValueError, match="must be true or false"):
        jobs.argv("harvest", {"ignore_quota": "; rm -rf /"})


def test_argv_omits_options_set_to_false():
    assert jobs.argv("harvest", {"ignore_quota": False}) == [
        sys.executable, "-m", "humble_catalog", "harvest"]


def _fake_runner(monkeypatch, tmp_path, script):
    """A JobRunner whose 'reparse' command is `script` instead of the CLI.

    Spawning the real CLI in a unit test would be slow and would touch a
    real catalog; only the plumbing is under test here.
    """
    monkeypatch.chdir(tmp_path)
    db.connect("catalog.db").close()
    runner = jobs.JobRunner(db_path="catalog.db")
    monkeypatch.setattr(jobs, "argv",
                        lambda command, options=None: [sys.executable, "-c",
                                                       script])
    return runner


def test_start_captures_the_child_s_output(monkeypatch, tmp_path):
    runner = _fake_runner(monkeypatch, tmp_path,
                          "print('Bundle 1/2: The Hollow Crypt')")
    runner.start("reparse")
    assert runner.wait(timeout=30) == 0
    assert "Bundle 1/2: The Hollow Crypt" in runner.state()["log"]


def test_state_reports_the_running_job_then_the_finished_one(monkeypatch,
                                                             tmp_path):
    runner = _fake_runner(monkeypatch, tmp_path, "import time; time.sleep(1)")
    runner.start("reparse")
    assert runner.state()["running"]["command"] == "reparse"
    runner.wait(timeout=30)
    assert runner.state()["running"] is None
    assert runner.state()["last"] == {
        "command": "reparse", "state": "done", "exit_code": 0,
        "finished_at": runner.state()["last"]["finished_at"]}


def test_a_failing_child_is_reported_as_failed(monkeypatch, tmp_path):
    runner = _fake_runner(monkeypatch, tmp_path, "raise SystemExit(3)")
    runner.start("reparse")
    runner.wait(timeout=30)
    assert runner.state()["last"]["state"] == "failed"
    assert runner.state()["last"]["exit_code"] == 3


def test_a_second_start_while_one_runs_is_refused(monkeypatch, tmp_path):
    runner = _fake_runner(monkeypatch, tmp_path, "import time; time.sleep(2)")
    runner.start("reparse")
    with pytest.raises(jobs.Busy):
        runner.start("reparse")
    runner.wait(timeout=30)


def test_the_log_is_bounded(monkeypatch, tmp_path):
    runner = _fake_runner(
        monkeypatch, tmp_path,
        f"[print(i) for i in range({jobs.LOG_LINES + 50})]")
    runner.start("reparse")
    runner.wait(timeout=60)
    assert len(runner.state()["log"]) == jobs.LOG_LINES


def test_cleanup_runs_after_the_child_exits(monkeypatch, tmp_path):
    runner = _fake_runner(monkeypatch, tmp_path, "print('done')")
    called = []
    runner.start("reparse", cleanup=lambda: called.append(True))
    runner.wait(timeout=30)
    assert called == [True]


def test_cancel_stops_a_running_job(monkeypatch, tmp_path):
    # The child ignores nothing and simply sleeps; the interrupt ends it.
    runner = _fake_runner(monkeypatch, tmp_path,
                          "import time; time.sleep(60)")
    runner.start("reparse")
    time.sleep(0.5)          # let the interpreter reach the sleep
    assert runner.cancel() is True
    runner.wait(timeout=30)
    assert runner.state()["running"] is None
    assert runner.state()["last"]["state"] == "cancelled"


def test_cancel_with_nothing_running_is_false(monkeypatch, tmp_path):
    runner = _fake_runner(monkeypatch, tmp_path, "print('x')")
    assert runner.cancel() is False


def _record_run(command, done=3):
    conn = db.connect("catalog.db")
    conn.execute("INSERT OR REPLACE INTO run_status "
                 "(command, phase, done, total, current, started_at, updated_at)"
                 " VALUES (?,'Bundle',?,9,'x','t','t')", (command, done))
    conn.commit()
    conn.close()


def _phase(command):
    conn = db.connect("catalog.db")
    try:
        return conn.execute("SELECT phase FROM run_status WHERE command=?",
                            (command,)).fetchone()["phase"]
    finally:
        conn.close()


def test_a_dead_job_does_not_leave_run_status_claiming_it_runs(monkeypatch,
                                                               tmp_path):
    # The child writes a run_status row and dies without finishing it --
    # what a crash, or a kill, leaves behind. The banner reads this table,
    # so a stale row is a viewer that lies about a run that ended.
    runner = _fake_runner(
        monkeypatch, tmp_path,
        "from humble_catalog import db;"
        "c = db.connect('catalog.db');"
        "c.execute(\"INSERT OR REPLACE INTO run_status "
        "(command, phase, done, total, current, started_at, updated_at) "
        "VALUES ('reparse','Bundle',1,9,'x','t','t')\");"
        "c.commit(); raise SystemExit(1)")
    runner.start("reparse")
    runner.wait(timeout=30)
    assert _phase("reparse") == "done"


def test_start_refuses_when_a_terminal_run_is_recorded(monkeypatch, tmp_path):
    runner = _fake_runner(monkeypatch, tmp_path, "print('x')")
    _record_run("reparse")
    with pytest.raises(jobs.Busy, match="already"):
        runner.start("reparse")


def test_force_starts_anyway(monkeypatch, tmp_path):
    runner = _fake_runner(monkeypatch, tmp_path, "print('x')")
    _record_run("reparse")
    runner.start("reparse", force=True)
    assert runner.wait(timeout=30) == 0


def test_the_run_status_guard_uses_the_cli_spelling(monkeypatch, tmp_path):
    # run_status.command holds what the CLI passes to Progress, and
    # import_sheets.py writes 'import-sheets'. Looking the row up under
    # the JSON key would find nothing, so the guard would never fire for
    # the two hyphenated commands and the finalizer would never close
    # their rows.
    runner = _fake_runner(monkeypatch, tmp_path, "print('x')")
    _record_run("import-sheets")
    with pytest.raises(jobs.Busy, match="already"):
        runner.start("import_sheets")
    runner.start("import_sheets", force=True)
    runner.wait(timeout=30)
    assert _phase("import-sheets") == "done"


def test_flags_is_the_shared_option_validator():
    assert jobs.flags("harvest", {"ignore_quota": "--ignore-quota"},
                      {"ignore_quota": True}) == ["--ignore-quota"]
    with pytest.raises(ValueError, match="does not accept"):
        jobs.flags("reparse", {}, {"x": True})


# -- A job's output is UTF-8 end to end (#102) --------------------------
# The reader decodes the pipe as UTF-8, but a Python child writing to a
# pipe on Windows encodes with the locale code page (cp1252) unless told
# otherwise: a title with a character cp1252 lacks killed the job with
# UnicodeEncodeError, and one it could encode reached the log as U+FFFD.
# PYTHONIOENCODING=cp1252 in the test's own environment reproduces that
# default on every OS, so the test fails on Linux CI too, not only on
# Windows.

def test_a_child_prints_a_title_outside_cp1252_without_crashing(monkeypatch,
                                                                tmp_path):
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    runner = _fake_runner(monkeypatch, tmp_path, "print('Tit\\u0307le')")
    runner.start("reparse")
    runner.wait(timeout=30)
    assert runner.state()["last"]["state"] == "done"
    assert runner.state()["log"] == ["Tiṫle"]


def test_a_child_s_accented_title_reaches_the_log_intact(monkeypatch,
                                                        tmp_path):
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    runner = _fake_runner(monkeypatch, tmp_path, "print('caf\\u00e9')")
    runner.start("reparse")
    runner.wait(timeout=30)
    assert runner.state()["log"] == ["café"]
