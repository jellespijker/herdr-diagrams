"""Background watcher that opens viewers (ADR-0011).

An agent that runs sandboxed can write Items but cannot reach the herdr socket, so
`show` cannot open a viewer itself. This process runs outside any agent sandbox,
started by the plugin, and opens a viewer when a new Item appears for a pane that
has none. One instance per herdr session, guarded by a lock file.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

from . import herdr, item, viewers

POLL = 0.5
LIST_EVERY = 2.0
MAX_MISSES = 6  # herdr unreachable for ~12 s: the server is gone, stop


def lock_path() -> Path:
    return item.prepare_home() / f"daemon-{item.herdr_session()}.lock"


def running() -> bool:
    """True when another process holds this session's daemon lock."""
    try:
        with open(lock_path(), "a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def ensure() -> bool:
    """Start the daemon unless it runs. Only call this from outside agent sandboxes."""
    if running() or not herdr.binary():
        return False
    cli = Path(__file__).resolve().parents[2] / "bin" / "herdr-diagram"
    with open(item.prepare_home() / "daemon.log", "a") as log:
        subprocess.Popen([sys.executable, str(cli), "daemon"], stdin=subprocess.DEVNULL, stdout=log,
                         stderr=log, start_new_session=True, close_fds=True)
    return True


def _newest(key: str) -> str | None:
    directory = item.spool_root() / item.herdr_session() / key
    names = [p.name for p in directory.glob("*.json")] if directory.is_dir() else []
    return max(names) if names else None


def enrich(pane: str, harness: str | None, session: str | None) -> None:
    """Fill in harness and session that a sandboxed `show` could not ask herdr for.

    Without the session, lifecycle cleanup (ADR-0009) would never archive these Items.
    """
    if not session:
        return
    for it in item.list_items(pane):
        if it.origin.get("session"):
            continue
        it.origin["session"] = session
        if harness and it.origin.get("harness", "unknown") == "unknown":
            it.origin["harness"] = {"antigravity": "agy", "gemini": "agy"}.get(harness, harness)
        item.write(it, pane)


def run() -> int:
    handle = open(lock_path(), "a")  # noqa: SIM115 - held open for the process lifetime: it is the lock
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0  # another daemon serves this session
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    seen = {key: _newest(key) for key in item.pane_ids_with_items()}  # no viewers for old Items
    alive: dict[str, str] = {}
    agents: dict[str, tuple] = {}
    unknown: dict[str, float] = {}
    misses, last_list = 0, 0.0
    while True:
        if time.time() - last_list >= LIST_EVERY:
            last_list = time.time()
            listing = herdr.call("pane", "list")
            if listing is None:
                misses += 1
                if misses >= MAX_MISSES:
                    return 0
                time.sleep(POLL)
                continue
            misses = 0
            alive = {item.pane_key(p["pane_id"]): p["pane_id"]
                     for p in listing.get("panes", []) if p.get("pane_id")}
            agents = {p["pane_id"]: (p.get("agent"), (p.get("agent_session") or {}).get("value"))
                      for p in listing.get("panes", []) if p.get("pane_id")}
        for key in item.pane_ids_with_items():
            newest = _newest(key)
            if newest is None or newest == seen.get(key):
                continue
            pane = alive.get(key)
            if pane is None and time.time() - unknown.setdefault(key, time.time()) < 10:
                last_list = 0.0  # maybe a new pane: refresh the listing, retry next round
                continue
            seen[key] = newest
            unknown.pop(key, None)
            if pane:
                enrich(pane, *agents.get(pane, (None, None)))
            if pane and not viewers.lookup(pane):
                viewers.mark_pending(pane)
                if herdr.open_viewer(pane) is None:
                    viewers.forget(pane)
        time.sleep(POLL)
