---
title: Jobs started from the demo viewer run against the real catalog.db
author: Mikkel
date: 2026-11-09
branch: main
cost: { minutes: 28, tokens: 225177 }
id: l-0722d140
scope: repo
status: active
touches:
  - humble_catalog/webapp/static/bundles.js
  - humble_catalog/webapp/static/index.html
  - humble_catalog/webapp/static/style.css
  - tests/js/harness.mjs
  - tests/test_webapp_js.py
  - docs/ui-ux/inventory.md
  - docs/ui-ux/reports/2026-11-09-whole-app.md
  - scripts/demo_catalog.py
  - README.md
---

## Decided
- UI/UX reviews use the demo viewer (`scripts/demo_catalog.py`, port 8099) and never `catalog.db`. The owner confirmed the review audience as README.md:3/8: one person cataloguing their own purchases, desktop first, plus the read-only LAN phone viewer.
- Bundles "Check"/"Browse" may fetch live humblebundle.com during a review: read-only, public data.

## Tried and ruled out
- Pressing Run in the Tasks tab of the demo viewer, even for harmless jobs (backup, check). `jobs.argv` (humble_catalog/jobs.py:101-110) passes no database path, and the child runs with `cwd=os.getcwd()` (jobs.py:224-228). The CLI therefore opens `catalog.db` in the repo root, which is the real library. `make_app` in demo_catalog.py redirects only covers and backups.
- Injecting axe-core from a CDN into the page: the auto-mode permission check refuses it. Use hand-written page scripts, or a locally installed axe.

## Watch out
- Until the runner gets the viewer's db_path, a screenshot of the demo's job panel can show real titles. Treat it like `harvest --failures` output.
- The report is at docs/ui-ux/reports/2026-11-09-whole-app.md; F-12 tracks this.
