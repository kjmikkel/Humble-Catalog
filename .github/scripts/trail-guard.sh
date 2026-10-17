#!/usr/bin/env bash
# Fail when someone other than the repo owner changes a path that feeds coding
# agents code or instructions: Trail injects .trail/learnings into context at
# session start, and .trail/hook.cjs imports trail from <repo>/node_modules or
# <repo>/dist/claude; Claude Code also loads .claude/, CLAUDE.md, AGENTS.md
# and .mcp.json. In this repo the jeffy loop also reads PLAN.md, BACKLOG.md,
# JOURNAL*.md and runs .jeffy/probes, an executing session follows
# docs/superpowers/plans, and a new session is told to "read the handoff in
# docs/handoffs and continue".
# Usage: <changed file paths, one per line> | trail-guard.sh <pr-author> <repo-owner>
set -euo pipefail
author=$1
owner=$2

# (/|$): a symlink or submodule named node_modules, .claude or dist is one path
# with no slash, and node and Claude follow it.
protected='^\.trail(/|$)|(^|/)node_modules(/|$)|(^|/)dist$|(^|/)dist/claude(/|$)|(^|/)\.claude(/|$)|(^|/)claude(\.local)?\.md$|(^|/)agents\.md$|(^|/)\.mcp\.json$'
protected+='|^\.jeffy(/|$)|^(plan|backlog)\.md$|^journal[^/]*\.md$|^docs/superpowers(/|$)|^docs/handoffs(/|$)'
# hook.cjs require.resolve()s trail from the repo, and Node honours package
# self-reference: a root package.json named after trail, with "exports"
# pointing elsewhere, would hand it any folder in the repo.
protected+='|^package\.json$'
short_name='(^|/)[^/]*~[0-9][^/]*(/|$)' # 8.3 alias such as TRAIL~1, which Windows may resolve to .trail
# .trail/hook.cjs runs `npm root -g` through cmd.exe, which tries the current
# directory first with every default PATHEXT extension. That is the session's
# directory, which may be any folder, so npm.* (any extension, since PATHEXT
# varies by machine) is blocked at every depth. hook.cjs resolves trail from
# CLAUDE_PROJECT_DIR, falling back to the cwd, hence node_modules and
# dist/claude at every depth above.
pathext='(com|exe|bat|cmd|vbs|vbe|js|jse|wsf|wsh|msc|cpl)'
root_exec="^[^/]+\.$pathext\$|(^|/)npm\.[^/]*\$"
# A name the folder below cannot fold safely: see fold.
unsafe='^<unsafe>$'

# Fold look-alikes a filesystem may treat as the same name: compatibility forms
# (fullwidth letters), case (APFS folds long s to s, Windows upper-cases dotless
# i to I), and marks and zero-width characters (HFS+ ignores the latter).
# Split on "\n" only, exactly as bash read does. splitlines() also splits on
# \r, NEL and U+2028, and one extra line would pair every later path with its
# neighbour's folded name. A name holding any control or line/paragraph
# separator character fails closed instead.
fold='
import sys, unicodedata as u
lines = sys.stdin.buffer.read().decode("utf-8", "replace").split("\n")
for line in lines[:-1] if lines and lines[-1] == "" else lines:
    if any(u.category(c) in ("Cc", "Zl", "Zp") for c in line):
        sys.stdout.buffer.write(b"<unsafe>\n")
        continue
    s = "".join(c for c in u.normalize("NFKD", line) if u.category(c) not in ("Mn", "Cf"))
    sys.stdout.buffer.write((s.casefold().replace("ı", "i") + "\n").encode())
'

# Match each path as a Windows checkout sees it: folded as above, with trailing
# dots and spaces dropped from every component.
paths=$(cat)
folded=$(printf '%s\n' "$paths" | python3 -I -c "$fold" | sed -E 's#[. ]+(/|$)#\1#g')
# The pairing below is only sound line for line; fail closed if it is not.
if [ "$(printf '%s\n' "$paths" | wc -l)" != "$(printf '%s\n' "$folded" | wc -l)" ]; then
  echo "::error::Folding changed the number of paths; cannot pair them safely."
  exit 1
fi
touched=$(while IFS= read -r f && IFS= read -r n <&3; do
  if printf '%s\n' "$n" | grep -qE "$protected|$short_name|$root_exec|$unsafe"; then printf '%s\n' "$f"; fi
done < <(printf '%s\n' "$paths") 3< <(printf '%s\n' "$folded"))

if [ -n "$touched" ] && [ "$author" != "$owner" ]; then
  echo "::error::Only @$owner may change agent context and code-loading paths. This PR by @$author touches:"
  echo "$touched"
  exit 1
fi
echo "ok: no protected paths changed, or changed by the owner"
