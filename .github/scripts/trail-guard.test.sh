#!/usr/bin/env bash
# Tests for trail-guard.sh. Run: bash .github/scripts/trail-guard.test.sh
set -u
guard="$(dirname "$0")/trail-guard.sh"
failures=0

expect() { # expect <pass|fail> <description> <author> <owner> <changed files...>
  local want=$1 desc=$2 author=$3 owner=$4; shift 4
  if printf '%s\n' "$@" | bash "$guard" "$author" "$owner" >/dev/null 2>&1; then got=pass; else got=fail; fi
  if [ "$got" = "$want" ]; then echo "ok   $desc"; else echo "FAIL $desc (wanted $want, got $got)"; failures=$((failures + 1)); fi
}

expect pass "owner may change .trail/"            kjmikkel kjmikkel .trail/learnings/a.md
expect pass "owner may change agent config"       kjmikkel kjmikkel CLAUDE.md .claude/settings.json
expect pass "others may change files outside"     someone  kjmikkel humble_catalog/cli.py README.md
expect pass "others may touch a look-alike path"  someone  kjmikkel docs/.trail/x.md .trailer humble_catalog/dist/x.js
expect pass "no changed files"                    someone  kjmikkel ""
expect fail "others may not add a learning"       someone  kjmikkel README.md .trail/learnings/a.md
expect fail "others may not change the hook"      someone  kjmikkel .trail/hook.cjs
expect fail "a look-alike login is not the owner" KJMIKKEL-fake kjmikkel .trail/hook.cjs

# hook.cjs imports trail from <repo>/node_modules and, last, <repo>/dist/claude
expect fail "others may not plant a trail package" someone kjmikkel node_modules/@trailhq/trail-code/package.json
expect fail "others may not plant dist/claude"     someone kjmikkel dist/claude/hooks.js

# Windows checkouts are case-insensitive and drop trailing dots and spaces
expect fail "upper-case .TRAIL/"                  someone  kjmikkel .TRAIL/learnings/a.md
expect fail "trailing dot .trail./"               someone  kjmikkel .trail./learnings/a.md
expect fail "trailing space '.trail /'"           someone  kjmikkel ".trail /learnings/a.md"
expect fail "8.3 short name TRAIL~1/"             someone  kjmikkel TRAIL~1/learnings/a.md

# other files Claude Code loads as instructions, hooks or MCP servers
expect fail "others may not change .claude/"      someone  kjmikkel .claude/settings.json
expect fail "others may not change nested .claude/" someone kjmikkel docs/.claude/settings.json
expect fail "others may not change CLAUDE.md"     someone  kjmikkel tests/CLAUDE.md
expect fail "others may not change CLAUDE.local.md" someone kjmikkel CLAUDE.local.md
expect fail "others may not change AGENTS.md"     someone  kjmikkel AGENTS.md
expect fail "others may not change .mcp.json"     someone  kjmikkel .mcp.json

# a symlink or submodule is one path with no trailing slash; node and Claude follow it
expect fail "symlink named node_modules"          someone  kjmikkel node_modules
expect fail "symlink named .trail"                someone  kjmikkel .trail
expect fail "symlink named dist"                  someone  kjmikkel dist
expect fail "symlink named dist/claude"           someone  kjmikkel dist/claude
expect fail "symlink named .claude"               someone  kjmikkel .claude
expect fail "nested symlink named .claude"        someone  kjmikkel docs/.claude
expect pass "others may change a dist/ file"      someone  kjmikkel dist/other/x.js

# case-insensitive APFS case-folds (long s to s) and HFS+ ignores zero-width characters
expect fail "long s in .mcp.json"                 someone  kjmikkel $'.mcp.j\xc5\xbfon'
expect fail "long s in agents.md"                 someone  kjmikkel $'agent\xc5\xbf.md'
expect fail "zero-width non-joiner in .trail/"    someone  kjmikkel $'.tr\xe2\x80\x8cail/learnings/a.md'
expect fail "dotless i in .trail/"                someone  kjmikkel $'.tra\xc4\xb1l/learnings/a.md'
expect fail "fullwidth C in CLAUDE.md"            someone  kjmikkel $'\xef\xbc\xa3LAUDE.md'
expect pass "others may add non-ASCII elsewhere"  someone  kjmikkel $'docs/Reader\xe2\x80\x99s guide.md'

# .trail/hook.cjs runs npm through cmd.exe, which looks in the current directory first
expect fail "planted npm.cmd at the root"         someone  kjmikkel npm.cmd
expect fail "planted node.EXE at the root"        someone  kjmikkel node.EXE
expect fail "planted npm.bat. at the root"        someone  kjmikkel "npm.bat."
expect fail "planted git.js at the root"          someone  kjmikkel git.js
expect pass "others may change scripts/run.bat"   someone  kjmikkel scripts/run.bat
expect pass "owner may add a root script"         kjmikkel kjmikkel setup.cmd

# this repo's agent instructions: the jeffy loop, superpowers plans, handoffs
expect fail "others may not change PLAN.md"       someone  kjmikkel PLAN.md
expect fail "others may not change BACKLOG.md"    someone  kjmikkel BACKLOG.md
expect fail "others may not change JOURNAL.md"    someone  kjmikkel JOURNAL.md JOURNAL-archive.md
expect fail "others may not change a jeffy probe" someone  kjmikkel .jeffy/probes/db-items/probe.py
expect fail "others may not change a plan"        someone  kjmikkel docs/superpowers/plans/x.md
expect fail "others may not add a handoff"        someone  kjmikkel docs/handoffs/x.md
expect fail "others may not change the launcher"  someone  kjmikkel "Humble Catalog.cmd"
expect pass "others may change docs/BACKLOG.md"   someone  kjmikkel docs/BACKLOG.md docs/TEST-DATA.md
expect pass "owner may add a handoff"             kjmikkel kjmikkel docs/handoffs/x.md

# Python's splitlines() also splits on these; bash read does not. A desync
# would pair each later path with its neighbour's folded name.
expect fail "carriage return shifts the next path" someone kjmikkel $'a
b' .trail/hook.cjs
expect fail "NEL shifts the next path"            someone  kjmikkel $'aÂb' .trail/hook.cjs
expect fail "line separator shifts the next path" someone  kjmikkel $'aâ¨b' .trail/hook.cjs
expect fail "control character in a name"         someone  kjmikkel $'docs/ab.md'

# hook.cjs: npm runs from the session's directory, which may be any folder;
# and a root package.json can self-reference the trail package name.
expect fail "planted npm.cmd in a subfolder"      someone  kjmikkel docs/npm.cmd
expect fail "planted NPM.Bat deep down"           someone  kjmikkel humble_catalog/web/NPM.Bat
expect fail "root package.json"                   someone  kjmikkel package.json
expect pass "a package.json elsewhere"            someone  kjmikkel tests/fixtures/package.json

expect fail "nested node_modules"                 someone  kjmikkel docs/node_modules/@trailhq/trail-code/package.json
expect fail "nested dist/claude"                  someone  kjmikkel docs/dist/claude/hooks.js
expect fail "npm with any extension"              someone  kjmikkel docs/npm.cpl
expect fail "root .cpl"                           someone  kjmikkel x.cpl
expect fail "planted node.exe in a subfolder"     someone  kjmikkel docs/node.exe
expect pass "others may change viewer JS"         someone  kjmikkel humble_catalog/web/static/app.js

[ "$failures" -eq 0 ] && echo "all passed" || { echo "$failures failed"; exit 1; }
