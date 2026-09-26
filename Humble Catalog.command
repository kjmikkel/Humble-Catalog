#!/usr/bin/env bash
# Double-click in Finder to open the Humble Catalog viewer (#96).
#
# Keep this window open while you use the catalog: Log in, Reset and
# Restore in the Tasks tab run here. Close it, or press Ctrl+C, to stop
# the viewer. Everything else -- the venv check, HUMBLE_PORT, opening a
# viewer that is already running -- is scripts/macos/serve.sh's job.
cd "$(dirname "$0")" || exit 1
status=0
./scripts/macos/serve.sh || status=$?
if [ "$status" -ne 0 ]; then
  echo
  echo "The viewer stopped with an error; the message is above."
  read -r -p "Press Return to close this window. "
fi
exit "$status"
