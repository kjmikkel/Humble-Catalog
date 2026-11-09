---
title: "Viewer jobs run in the folder of the viewer's own catalog.db"
author: Mikkel
date: 2026-11-09
branch: fix/demo-jobs-use-demo-db
cost: { minutes: 1, tokens: 1599 }
id: l-a6515db1
scope: repo
status: active
replaces: l-0722d140
touches:
  - "humble_catalog/jobs.py#JobRunner"
  - "scripts/demo_catalog.py#demo_db_path"
  - "scripts/demo_catalog.py#make_app"
---

## Decided
- `JobRunner` spawns the CLI in the folder that holds the viewer's own database (`humble_catalog/jobs.py`, `__init__`), and refuses to start a job when that file isn't named `catalog.db`. The CLI has no `--db` flag and opens `catalog.db`, `covers/`, `cache/` and `backups/` relative to its working directory, so this is the only way a job can't land on a different catalog than the one on screen (#143).
- The demo keeps its database at `<temp>/humble-catalog-demo/catalog.db` (`demo_db_path` in scripts/demo_catalog.py), and its restore picker reads `backups/` beside it. Tasks → Run in the demo is now safe: it acts on the demo catalog only.

## Tried and ruled out
- Adding a `--db` flag to every CLI command: it touches every subcommand and every path derived from the working directory (covers, cache, backups, lan). Running in the database's folder gets the same result with one change.
- Running jobs in the viewer's working directory (the old behaviour): that is how the demo, launched from the repo root, ran jobs on the real library.

## Watch out
- A viewer pointed at a database not named `catalog.db` (e.g. `scripts/smoke_viewer.py`'s `smoke.db`) can't run jobs; `/api/jobs/start` answers 400 with the reason. Name the file `catalog.db` in its own folder if a test needs real jobs.
