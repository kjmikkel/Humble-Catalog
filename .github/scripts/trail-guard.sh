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
protected='^\.trail(/|$)|^node_modules(/|$)|^dist$|^dist/claude(/|$)|(^|/)\.claude(/|$)|(^|/)claude(\.local)?\.md$|(^|/)agents\.md$|(^|/)\.mcp\.json$'
protected+='|^\.jeffy(/|$)|^(plan|backlog)\.md$|^journal[^/]*\.md$|^docs/superpowers(/|$)|^docs/handoffs(/|$)'
short_name='(^|/)[^/]*~[0-9][^/]*(/|$)' # 8.3 alias such as TRAIL~1, which Windows may resolve to .trail
# .trail/hook.cjs runs `npm root -g` through cmd.exe, which tries the current
# directory first with every default PATHEXT extension.
root_exec='^[^/]+\.(com|exe|bat|cmd|vbs|vbe|js|jse|wsf|wsh|msc)$'

# Fold look-alikes a filesystem may treat as the same name: compatibility forms
# (fullwidth letters), case (APFS folds long s to s, Windows upper-cases dotless
# i to I), and marks and zero-width characters (HFS+ ignores the latter).
fold='
import sys, unicodedata as u
for line in sys.stdin.buffer.read().decode("utf-8", "replace").splitlines():
    s = "".join(c for c in u.normalize("NFKD", line) if u.category(c) not in ("Mn", "Cf"))
    sys.stdout.buffer.write((s.casefold().replace("ı", "i") + "\n").encode())
'

# Match each path as a Windows checkout sees it: folded as above, with trailing
# dots and spaces dropped from every component.
paths=$(cat)
folded=$(printf '%s\n' "$paths" | python3 -I -c "$fold" | sed -E 's#[. ]+(/|$)#\1#g')
touched=$(while IFS= read -r f && IFS= read -r n <&3; do
  if printf '%s\n' "$n" | grep -qE "$protected|$short_name|$root_exec"; then printf '%s\n' "$f"; fi
done < <(printf '%s\n' "$paths") 3< <(printf '%s\n' "$folded"))

if [ -n "$touched" ] && [ "$author" != "$owner" ]; then
  echo "::error::Only @$owner may change agent context and code-loading paths. This PR by @$author touches:"
  echo "$touched"
  exit 1
fi
echo "ok: no protected paths changed, or changed by the owner"
