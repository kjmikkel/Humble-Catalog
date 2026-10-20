---
title: Trail setup and the agent-context guard
author: Mikkel
date: 2026-10-17
branch: chore/trail-workflow
cost: { minutes: 1, tokens: 1320 }
touches:
  - ".github/scripts/trail-guard.sh"
  - ".claude/settings.json"
  - ".gitignore"
  - CLAUDE.md
---

## Decided
- Ported from the Dracula-Night-by-Night repo: Trail hook in committed `.claude/settings.json`; personal workflow prefs (Sonnet subagents, 400K autoCompactWindow, clear-context on plan accept) live in gitignored `settings.local.json`, not the shared file.
- Owner-only `guard` workflow (pull_request_target, never checks out PR code) plus CODEOWNERS protect every path agents read as instructions or load as code. Beyond Dracula's list this repo adds PLAN.md, BACKLOG.md, JOURNAL*.md, .jeffy/, docs/superpowers/ and docs/handoffs/. `docs/BACKLOG.md` stays open to contributors.
- The handoff skill is global (`~/.claude/skills/handoff`) and defers to CLAUDE.md for privacy; no repo copy.

## Tried and ruled out
- Keeping the handoff skill in the repo: it would shadow or duplicate the global one under the same name.

## Watch out
- `trail init` reads past Claude sessions here, and those saw real library titles. Read every learning before committing it, and run leak_check.
- Trail writes `graft/` (session files, telemetry id) at the repo root; it is gitignored. `.trail/cache/` is ignored by `.trail/.gitignore`, and leak_check skips any dir named `cache`.
- The guard only blocks merges once `trail-owner-only` is a required check on main.
- Edit the guard's patterns in lowercase: paths are casefolded before matching. Run `bash .github/scripts/trail-guard.test.sh` after any change.
- The guard pairs raw and folded paths line by line, so the Python folder must split on "
" only: `splitlines()` also splits on , NEL and U+2028 and shifts every later path (a real bypass, also present in the Dracula copy). Names with control or separator characters fail closed.
- hook.cjs runs `npm` through cmd.exe from the session's directory (any depth), and Node's package self-reference makes a root `package.json` a resolution input. Both are protected.
- The guard trusts the PR opener; that holds only while the owner is the sole account with push access here.
