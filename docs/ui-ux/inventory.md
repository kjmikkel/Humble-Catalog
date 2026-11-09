# UI inventory: Humble Catalog viewer

Whole-app run, 2026-11-09, `main` @ 7947158. Observed on the demo catalog
(`scripts/demo_catalog.py`, port 8099, invented titles) in the built-in
browser (Chromium) at 1280×800, 640×400 (≈200% zoom of 1280) and 375×812,
in the light and dark themes.

## Items

| id | kind | name | code | how reached | observed | states visited | components |
|---|---|---|---|---|---|---|---|
| S0 | window | Shell: header, search, section tabs, theme toggle, run banner | `static/index.html:20-36`, `static/shell.js` | every page | run | light, dark, 375, 640, keyboard, server down (poll fails) | page header, search field, tab bar with count badge, icon button (theme) |
| S1 | page | Library: filter sidebar, toolbar, bulk bar, table | `static/index.html:39-151`, `static/catalog.js` | `#/library` (default) | run | loaded, filtered (1 result), light, dark, 640, keyboard, server down | select, autocomplete field, chip (filter, removable), toggle chip (status), sort header button, data table, star rating (radiogroup), row select (status), icon button (redo, edit), disclosure (columns), checkbox list, export select, text button |
| S1a | panel | Library overview (statistics) | `static/stats.js`, `index.html:112` | S1 → "N items — overview" disclosure | run | collapsed, expanded, 375, 640 | disclosure, stat table, count button |
| S1b | form | Inline row editor (desktop) | `static/catalog.js:~1500-1590` | S1 row → ✎ Edit | run | open, cancel, keyboard | text field, autocomplete field, removable chip, select, text button |
| D1 | dialog | Restored-filters banner | `index.html:89-93` | reload with filters saved | seen in code only | — | banner, text button |
| D2 | sheet | Phone edit sheet | `index.html:147-149`, `catalog.js:~860-960` | 375px, tap a card | run | open, Escape close, rated / unrated item | modal sheet, segmented toggle buttons, star buttons, primary button |
| S1c | list | Phone card list | `catalog.js:~830-870` | S1 below 600px | run | 375 | card (button), link |
| S2 | page | Maintenance: review queue and possible duplicates | `index.html:153-156`, `static/maintenance.js` | `#/maintenance` | run | both panels open, 375, light, dark | disclosure, candidate button, URL field, text button, two-step confirm button, merge autocomplete fields |
| S3 | page | Keys | `index.html:157-161`, `static/keys.js` | `#/keys` | run | default filters, 375, light, dark | search field, toggle chip (state filter), data table in scroll container, text button (hide) |
| S4 | page | Bundles: check a URL, recent list, browse live bundles, Choice check | `index.html:162-197`, `static/bundles.js` | `#/bundles` | run (live humblebundle.com fetches allowed by owner) | empty, empty submit, invalid URL, loading, browse list, report, light, dark | URL field, text button, checkbox, filter field, toggle buttons (Books/Games), list with link + button, report table + bar chart, two-column item list |
| S4a | panel | This month's Choice report | `bundles.js`, `api/choice-preview` | S4 → Choice "Check" | not reached (not pressed this run) | — | report |
| S5 | page | Tasks: job cards, job panel | `index.html:199-203`, `static/tasks.js` | `#/tasks` | run (cards only; no job started, see F-12) | idle, light, dark | section heading, card, text button (Run, disabled Run), file chooser, select, checkbox |
| S5a | panel | Running job log / cancel | `tasks.js:~400-518` | S5 → Run | seen in code only | — | log panel, cancel button |
| D3 | dialog | Terminal hand-off screen | `index.html:204`, `api/jobs/handoff` | S5 → Run on a "uses the terminal" card | seen in code only | — | alert dialog |
| S6 | page | LAN read-only viewer and `/pair` | `webapp/__init__.py:1013-1100` | `serve --lan` on a phone | seen in code only | — | same as S1/S1c with editing suppressed |

## Flows

| id | flow | items |
|---|---|---|
| FL1 | Rate and set status on desktop | S1 → star / status select |
| FL2 | Narrow the library with filters | S1 sidebar → autocomplete → chip → "Clear all filters" |
| FL3 | Edit fields inline | S1 → ✎ → S1b → Save / Cancel |
| FL4 | Phone edit | S1c → D2 → Done / Escape |
| FL5 | Check a live bundle | S4 → Browse → Check → report |

## Components

| component type | used in |
|---|---|
| icon button | S0 (theme), S1 (redo, edit), S1b / S1 chips (× remove) |
| autocomplete field (combobox) | S0 search, S1 filters ×8, S1 bulk tag, S1b tag fields, S2 merge fields |
| toggle chip / toggle button | S1 status chips, S3 state chips, S4 Books/Games, D2 status and stars |
| star rating | S1 (radiogroup), D2 (buttons), S1c (text) |
| data table | S1, S1a, S3, S4 report |
| removable chip | S1 active filters, S1 filter chips, S1b |
| select | S1 filters, S1 row status, S1 export, S5 restore |
| status / error message | S1 table status, S2 fetch result, S4 bundle error, S5 task message |
| two-step confirm button | S2 (choose, apply, keep, dismiss) |
| badge | S0 tab counts, S1 review / edited / queued |
| modal sheet | D2 |
| card | S1c, S5 |
| disclosure | S1a, S1 columns, S2 panels |
