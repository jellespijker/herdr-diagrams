"""Registry of running viewers, one per source pane.

Lets the CLI and adapters decide whether a viewer must be opened, and lets the
`pane.closed` event find the viewer to close.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import item


def _file(source_pane: str | None) -> Path:
    return item.home() / "viewers" / f"{item.pane_key(source_pane)}.json"


def register(source_pane: str | None, viewer_pane: str | None) -> None:
    path = _file(source_pane)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "viewer_pane": viewer_pane,
                                "source_pane": source_pane}))


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
    pid = data.get("pid")
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        path.unlink(missing_ok=True)
        return None
    return data


def find_by_viewer_pane(viewer_pane: str) -> dict | None:
    directory = item.home() / "viewers"
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
