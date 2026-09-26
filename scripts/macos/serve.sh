#!/usr/bin/env bash
# Start the catalog viewer.
#
# Foreground by default (Ctrl+C stops it). --detached runs it in the
# background and returns; use stop.sh to shut that one down. A detached
# viewer has no terminal, so it is started with --no-handoff: login,
# reset and restore are then run from a terminal.
#
# Restart after changing Python code. A running server serves static
# files from disk on every request but holds its Python in memory, so a
# stale process pairs new JS with an old API - which is exactly how the
# viewer once rendered zero rows and hid every panel.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
require_venv
cd "$ROOT"

# A busy port is serve's to judge: it opens a viewer that is already
# running, and refuses anything else. Asked in the foreground, so that
# answer is seen even with --detached.
if [ -n "$(find_listener_pids)" ]; then
  exec "$PYTHON" -m humble_catalog serve --port "$PORT"
fi

if [ "${1:-}" = "--detached" ]; then
  nohup "$PYTHON" -m humble_catalog serve --port "$PORT" --no-handoff >/dev/null 2>&1 &
  echo "Viewer started detached on port $PORT (PID $!)."
  echo "Stop it with: $(dirname "${BASH_SOURCE[0]}")/stop.sh"
else
  exec "$PYTHON" -m humble_catalog serve --port "$PORT"
fi
