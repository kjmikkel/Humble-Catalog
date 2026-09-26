"""Commands the viewer hands to the terminal it was started from.

login, reset and restore cannot run as the job runner's background
children. login opens a foreground browser window the user clicks
through. restore swaps catalog.db, which fails while anything holds it
open. reset and restore also ask for a word typed at an interactive
console, and that guard is kept, not reimplemented. So `serve` steps
down, runs the command with the console's own stdin and stdout, and
comes back when it exits.
"""
import os
import subprocess
import sys
import threading
from pathlib import Path

from humble_catalog import jobs
from humble_catalog.backup import _when

# The whole vocabulary of the handoff, in the same shape as
# jobs.COMMANDS: command -> {option accepted in a request: its flag}.
COMMANDS = {
    "login":   {},
    "reset":   {},
    "restore": {"covers": "--covers"},
}


_STDIN = object()


def terminal_available(stdin=_STDIN):
    """Whether this process has an interactive console to hand over to.

    A viewer with no stdin (pythonw), or one reading from a file or
    /dev/null (nohup, a service), has nowhere for reset or restore to ask
    for their typed word, so it must not offer the handoff at all. A
    hidden Windows console passes this check; the detached wrappers say
    so with `serve --no-handoff` instead.
    """
    if stdin is _STDIN:
        stdin = sys.stdin
    if stdin is None:
        return False
    try:
        return bool(stdin.isatty())
    except ValueError:        # a closed stream
        return False


def list_backups(backups_dir="backups"):
    """The snapshots `backup` wrote, newest first.

    The compact timestamp in the name sorts chronologically as text, so
    sorting by name is sorting by age. A raw copy of an unreadable
    catalog (restore's own safety net) is left out: it is kept for
    forensics, never to be put back from a picker.
    """
    d = Path(backups_dir)
    if not d.is_dir():
        return []
    rows = []
    for p in sorted(d.glob("catalog-*.db"), reverse=True):
        if not p.is_file() or p.name.endswith(".unreadable.db"):
            continue
        stem = p.stem[len("catalog-"):]
        rows.append({"name": p.name, "size": p.stat().st_size,
                     "modified": _when(p),
                     "covers": (d / f"covers-{stem}.zip").is_file()})
    return rows


def argv(command, options=None, snapshot=None, backups_dir="backups"):
    """The exact command line for a handoff, or ValueError.

    The snapshot is the one request string that reaches argv, and only
    after it has matched, exactly, a name list_backups returned. So it
    cannot name a path outside backups/, and cannot be anything but a
    file that is there now.
    """
    if command not in COMMANDS:
        raise ValueError(f"unknown command: {command}")
    line = [sys.executable, "-m", "humble_catalog", command]
    if command == "restore":
        names = {r["name"] for r in list_backups(backups_dir)}
        if not isinstance(snapshot, str) or snapshot not in names:
            raise ValueError("choose a snapshot from backups/")
        line.append(str(Path(backups_dir) / snapshot))
    elif snapshot is not None:
        raise ValueError(f"{command} does not take a snapshot")
    return line + jobs.flags(command, COMMANDS[command], options)


class HandoffSlot:
    """The one handoff a route has asked for, and how the last one ended.

    A route calls request(); the serve loop calls take() between polls,
    runs the command, then finish(). `generation` counts finished
    handoffs, and the page reloads once it has moved past the value its
    request was answered with. That is how the page tells "the server is
    back" from "the server has not gone down yet".
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = None
        self._active = None
        self.generation = 0
        self.last = None

    def request(self, command, line):
        with self._lock:
            held = self._pending or self._active
            if held is not None:
                raise jobs.Busy(f"{held['command']} is already being handed "
                                "to the terminal")
            self._pending = {"command": command, "argv": list(line)}
            return self.generation

    def busy(self):
        with self._lock:
            held = self._pending or self._active
            return held["command"] if held else None

    def take(self):
        with self._lock:
            req, self._pending = self._pending, None
            if req is not None:
                self._active = req
            return req

    def finish(self, exit_code):
        with self._lock:
            command = self._active["command"] if self._active else None
            self.last = {"command": command, "exit_code": exit_code,
                         "finished_at": jobs._now()}
            self._active = None
            self.generation += 1

    def state(self):
        with self._lock:
            held = self._pending or self._active
            return {"generation": self.generation,
                    "pending": held["command"] if held else None,
                    "last": dict(self.last) if self.last else None}


def run_in_terminal(command, line, _run=subprocess.run):
    """Run a handoff command in this console. Returns its exit code, or
    None when it never finished (Ctrl-C, or it could not start).

    Deliberately no stdin/stdout/stderr arguments: the child inherits the
    console, which is the entire point. No creationflags either. The job
    runner's CREATE_NEW_PROCESS_GROUP would detach it from Ctrl-C, and
    here the user's Ctrl-C is meant for exactly this child.

    Ctrl-C reaches the child and this process alike. It is caught here so
    that it aborts the command and not the viewer. A second Ctrl-C, once
    the viewer is back, quits `serve` as it always has.
    """
    print(f"\n--- The viewer handed `{command}` to this terminal. It comes "
          "back when the command finishes. ---\n", flush=True)
    try:
        return _run(line, cwd=os.getcwd()).returncode
    except KeyboardInterrupt:
        print(f"\n`{command}` interrupted. Bringing the viewer back.")
        return None
    except OSError as exc:
        print(f"Could not start `{command}`: {exc}")
        return None
