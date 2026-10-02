"""Registry of running viewers, one per source pane.

Lets the CLI and adapters decide whether a viewer must be opened, and lets the
`pane.closed` event find the viewer to close.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import item


def _file(source_pane: str | None) -> Path:
    return item.home() / "viewers" / f"{item.scope(source_pane)}.json"


PENDING_SECONDS = 20


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def register(source_pane: str | None, viewer_pane: str | None) -> None:
    _write(_file(source_pane), {"pid": os.getpid(), "viewer_pane": viewer_pane,
                                "source_pane": source_pane})


def mark_pending(source_pane: str | None) -> None:
    """Claim the slot before opening a viewer, so a second caller does not open another."""
    _write(_file(source_pane), {"pending_until": time.time() + PENDING_SECONDS,
                                "source_pane": source_pane})


def unregister(source_pane: str | None) -> None:
    path = _file(source_pane)
    try:
        if json.loads(path.read_text()).get("pid") == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        pass


def lookup(source_pane: str | None) -> dict | None:
    """The live viewer bound to `source_pane`, or None. Removes stale entries."""
    path = _file(source_pane)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if "pending_until" in data:
        if data["pending_until"] > time.time():
            return data
        path.unlink(missing_ok=True)
        return None
    pid = data.get("pid")
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        path.unlink(missing_ok=True)
        return None
    return data


def find_by_viewer_pane(viewer_pane: str) -> dict | None:
    directory = item.home() / "viewers" / item.herdr_session()
    for path in directory.glob("*.json") if directory.is_dir() else []:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if data.get("viewer_pane") == viewer_pane:
            return data
    return None


def forget(source_pane: str | None) -> None:
    _file(source_pane).unlink(missing_ok=True)
