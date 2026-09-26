"""`update`: the whole import in one command (#101).

The steps themselves are faked: each has its own tests, and running them
for real would need a Humble session and the network. What is under test
is the sequence -- order, what stops it, what does not, and what it
leaves in run_status for the viewer to read.
"""
import pytest

from humble_catalog import db, enrich, extract, harvest, humble_api, \
    import_games, update


@pytest.fixture
def steps(monkeypatch, tmp_path):
    """Replace every step with a recorder. Returns (calls, db_path)."""
    db_path = str(tmp_path / "catalog.db")
    db.connect(db_path).close()
    calls = []

    def fake(name, returns=None):
        def run(*args, **kwargs):
            calls.append((name, kwargs))
            return returns
        return run

    monkeypatch.setattr(extract, "run", fake("extract"))
    monkeypatch.setattr(harvest, "run", fake("harvest", returns=set()))
    monkeypatch.setattr(enrich, "run", fake("enrich"))
    monkeypatch.setattr(enrich, "fill_series", fake("series"))
    monkeypatch.setattr(import_games, "run", fake("games"))
    return calls, db_path


def _names(calls):
    return [name for name, _kw in calls]


def _row(db_path):
    conn = db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM run_status WHERE command='update'").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def test_runs_the_import_steps_in_order(steps):
    calls, db_path = steps
    update.run(db_path=db_path)
    # enrich matches against what harvest cached, and --series fills only
    # what no source supplied, so this order is the only correct one.
    assert _names(calls) == ["extract", "harvest", "enrich", "series"]


def test_every_step_works_on_the_same_catalog(steps):
    calls, db_path = steps
    update.run(db_path=db_path)
    assert all(kw.get("db_path") == db_path for _name, kw in calls)


def test_passes_allow_login_through_to_extract(steps):
    calls, db_path = steps
    update.run(db_path=db_path, allow_login=False)
    assert dict(calls)["extract"]["allow_login"] is False


def test_games_adds_the_game_import_last(steps):
    calls, db_path = steps
    update.run(db_path=db_path, games=True)
    assert _names(calls) == ["extract", "harvest", "enrich", "series",
                             "games"]


def test_no_harvest_skips_only_the_harvest(steps):
    calls, db_path = steps
    update.run(db_path=db_path, no_harvest=True)
    assert _names(calls) == ["extract", "enrich", "series"]


def test_prints_a_marker_as_each_step_starts(steps, capsys):
    _calls, db_path = steps
    update.run(db_path=db_path)
    out = capsys.readouterr().out
    for i, name in enumerate(["extract", "harvest", "enrich", "series"], 1):
        assert f"step {i}/4: {name}" in out


# -- Quota: the harvest is resumable, so it never stops the update -------

def test_a_harvest_left_incomplete_still_enriches(steps, monkeypatch,
                                                  capsys):
    calls, db_path = steps
    monkeypatch.setattr(harvest, "run", lambda **kw: (
        calls.append(("harvest", kw)), {"google_books"})[1])
    update.run(db_path=db_path)
    assert _names(calls) == ["extract", "harvest", "enrich", "series"]
    out = capsys.readouterr().out
    # Says which source is behind and what to do about it, so a partial
    # enrichment is never mistaken for a finished one.
    assert "google_books" in out
    assert "run update again" in out


def test_a_complete_harvest_mentions_no_pending_source(steps, capsys):
    _calls, db_path = steps
    update.run(db_path=db_path)
    assert "run update again" not in capsys.readouterr().out


# -- Anything else stops it ---------------------------------------------

def test_a_failing_step_stops_the_sequence(steps, monkeypatch, capsys):
    calls, db_path = steps

    def broken(**kw):
        raise RuntimeError("matcher exploded")
    monkeypatch.setattr(enrich, "run", broken)
    with pytest.raises(RuntimeError, match="matcher exploded"):
        update.run(db_path=db_path)
    assert _names(calls) == ["extract", "harvest"]
    assert "stopped at step 3/4 (enrich)" in capsys.readouterr().out


def test_an_expired_session_stops_before_the_harvest(steps, monkeypatch):
    calls, db_path = steps

    def logged_out(**kw):
        raise humble_api.NotLoggedIn("session expired")
    monkeypatch.setattr(extract, "run", logged_out)
    with pytest.raises(humble_api.NotLoggedIn):
        update.run(db_path=db_path)
    assert calls == []


# -- What the viewer reads ----------------------------------------------

def test_run_status_names_the_step_in_progress(steps, monkeypatch):
    calls, db_path = steps
    seen = {}

    def harvest_run(**kw):
        seen.update(_row(db_path))
        return set()
    monkeypatch.setattr(harvest, "run", harvest_run)
    update.run(db_path=db_path)
    # The job panel draws "<phase> <done>/<total>": "harvest 1/4" while
    # the second of four steps runs, one step having finished.
    assert (seen["phase"], seen["done"], seen["total"]) == ("harvest", 1, 4)


def test_run_status_is_done_after_a_finished_update(steps):
    _calls, db_path = steps
    update.run(db_path=db_path)
    assert _row(db_path)["phase"] == "done"


def test_run_status_is_done_after_a_failed_update(steps, monkeypatch):
    # A row left mid-step would keep the header banner reporting an update
    # that is over.
    _calls, db_path = steps

    def broken(**kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(enrich, "run", broken)
    with pytest.raises(RuntimeError):
        update.run(db_path=db_path)
    assert _row(db_path)["phase"] == "done"
