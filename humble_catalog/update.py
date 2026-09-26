"""`update`: the whole import in one command (#101).

extract -> harvest -> enrich -> enrich --series, and import-games with
--games. Each step is the same function its own subcommand calls, run in
this process, so there is still exactly one definition of each: the rule
jobs.py states for the viewer applies here too.

What stops it and what does not:

- A harvest that ends with sources incomplete -- a spent daily quota, a
  source that gave up -- does NOT stop it. The harvest is resumable and
  enrich only reads the cache, so enriching what is there now beats
  enriching nothing; the summary names the sources still behind.
- Anything that raises does: an expired Humble session in extract, or a
  crash in any step. The rest is skipped and the exception propagates,
  after one line saying which step it was.
"""
from datetime import datetime, timezone

from humble_catalog import db, enrich, extract, harvest, import_games

# The run_status rows the steps themselves write. jobs.py reads this to
# refuse an update while one of them runs elsewhere, and to retire them
# when a cancelled update never reached their own finish().
STEP_COMMANDS = ("extract", "harvest", "enrich", "import-games")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _plan(db_path, allow_login, games, harvest_step):
    """The steps to run, as (name, callable) pairs, in order.

    Names are what the markers print and what run_status.phase holds, so
    the job panel reads "harvest 1/4".
    """
    steps = [("extract", lambda: extract.run(db_path=db_path,
                                            allow_login=allow_login))]
    if harvest_step:
        steps.append(("harvest", lambda: harvest.run(db_path=db_path)))
    steps += [("enrich", lambda: enrich.run(db_path=db_path)),
              ("series", lambda: enrich.fill_series(db_path=db_path))]
    if games:
        steps.append(("games", import_games.run))
    return steps


def _status(db_path, phase, done, total, current=None, start=False):
    """Write the update's own run_status row.

    A short-lived connection per write, never one held across the steps:
    each step opens its own, and on Windows a connection held open here
    could hold a lock across a step's writes.
    """
    conn = db.connect(db_path)
    try:
        if start:
            conn.execute(
                "INSERT OR REPLACE INTO run_status (command, phase, done, "
                "total, current, started_at, updated_at) "
                "VALUES ('update', ?, ?, ?, ?, ?, ?)",
                (phase, done, total, current, _now(), _now()))
        else:
            conn.execute(
                "UPDATE run_status SET phase=?, done=?, total=?, current=?, "
                "updated_at=? WHERE command='update'",
                (phase, done, total, current, _now()))
        conn.commit()
    finally:
        conn.close()


def run(db_path="catalog.db", allow_login=True, games=False, no_harvest=False):
    # no_harvest, not `harvest`: a parameter of that name would shadow the
    # module for this whole function body (the C3 class in BACKLOG.md).
    steps = _plan(db_path, allow_login, games, not no_harvest)
    total = len(steps)
    _status(db_path, steps[0][0], 0, total, start=True)
    incomplete = set()
    done = 0
    try:
        for i, (name, step) in enumerate(steps, 1):
            _status(db_path, name, done, total, current=f"step {i}/{total}")
            print(f"\n== update step {i}/{total}: {name} ==", flush=True)
            try:
                result = step()
            except BaseException:
                # BaseException, so a Ctrl-C or a cancel from the viewer
                # also says where it stopped. Re-raised either way.
                print(f"\nupdate stopped at step {i}/{total} ({name}).",
                      flush=True)
                raise
            if name == "harvest":
                incomplete = set(result or ())
            done = i
    finally:
        # However it ended: a row left mid-step keeps the header banner
        # reporting an update that is over.
        _status(db_path, "done", done, total)
    print(f"\nUpdate finished: {total} steps.")
    if incomplete:
        print(f"The harvest is still behind on {', '.join(sorted(incomplete))} "
              "(a spent daily quota, or titles that failed); enrichment used "
              "what is cached so far. The harvest resumes where it stopped: "
              "run update again later to fill the rest.")
