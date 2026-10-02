"""Item contract v1 (docs/spec.md §4, ADR-0002).

An Item is one diagram or image queued for display, stored as one JSON file in
the spool directory of its source pane. This module is the only code that knows
the on-disk layout; every writer and reader goes through it.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

VERSION = 1
MAX_SOURCE_BYTES = 1 << 20
NOPANE = "_nopane"
HARNESSES = ("claude", "agy", "opencode", "codex", "copilot", "unknown")


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean_text(text: str) -> str:
    """Untrusted text without terminal control characters (keeps newline and tab)."""
    return _CONTROL.sub("", text)


class ItemError(ValueError):
    """An Item does not satisfy the contract."""


def home() -> Path:
    if override := os.environ.get("HERDR_DIAGRAMS_HOME"):
        return Path(override)
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "herdr-diagrams"


def spool_root() -> Path:
    return home() / "spool"


def cache_dir() -> Path:
    return home() / "cache"


def pane_key(pane_id: str | None) -> str:
    """Directory name for a herdr pane ID: `w1:p3` -> `w1_p3`."""
    if not pane_id:
        return NOPANE
    key = pane_id.replace(":", "_").replace("/", "_")
    if key in ("", ".", ".."):
        return NOPANE
    return key


def herdr_session(env: dict | None = None) -> str:
    """Name of the herdr session (server) this process belongs to.

    Pane IDs are only unique within one session, so every per-pane path is scoped by it.
    herdr sets HERDR_SESSION in panes; plugin processes get HERDR_SOCKET_PATH, which is
    `.../sessions/<name>/herdr.sock` for named sessions.
    """
    env = os.environ if env is None else env
    name = env.get("HERDR_SESSION")
    if not name:
        socket = Path(env.get("HERDR_SOCKET_PATH") or "")
        name = socket.parent.name if socket.parent.parent.name == "sessions" else "default"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name if name not in ("", ".", "..") else "default"


def scope(pane_id: str | None) -> Path:
    """Relative per-pane path: `<herdr session>/<pane key>`."""
    return Path(herdr_session()) / pane_key(pane_id)


def spool_dir(pane_id: str | None) -> Path:
    return spool_root() / scope(pane_id)


@dataclass
class Item:
    format: str
    source: str | None = None
    path: str | None = None
    title: str | None = None
    origin: dict = field(default_factory=dict)
    id: str = ""
    created: int = 0
    v: int = VERSION
    file: Path | None = None  # where it was read from; not serialized

    def to_json(self) -> dict:
        data = {
            "v": self.v,
            "id": self.id,
            "format": self.format,
            "source": self.source,
            "path": self.path,
            "title": self.title,
            "origin": self.origin,
            "created": self.created,
        }
        return data

    @property
    def display_title(self) -> str:
        return clean_text(self._raw_title()).replace("\n", " ").replace("\t", " ")

    def _raw_title(self) -> str:
        if self.title:
            return self.title
        if self.path:
            return Path(self.path).name
        lines = [ln.strip() for ln in (self.source or "").splitlines()]
        for line in lines:  # an explicit title in the diagram wins
            match = re.match(r"^(?:title:?|workspace)\s+[\"']?([^\"'{]+)", line, re.IGNORECASE)
            if match and match.group(1).strip():
                return match.group(1).strip()[:60]
        for line in lines:
            graph = re.match(r'^(?:strict\s+)?(?:di)?graph\s+"?([\w .-]+?)"?\s*\{', line)
            if graph:
                return graph.group(1)[:60]
            if line and not line.startswith(("%%", "'", "//", "#", "```", "@start", "---",
                                             "direction:", "vars:", "classes:")):
                return line[:60]
        return self.format


def validate(data: dict) -> None:
    """Raise ItemError unless `data` satisfies schema/item.v1.json."""
    if not isinstance(data, dict):
        raise ItemError("item is not an object")
    if data.get("v") != VERSION:
        raise ItemError(f"unsupported item version: {data.get('v')!r}")
    for key, typ in (("id", str), ("format", str), ("created", int)):
        if not isinstance(data.get(key), typ) or isinstance(data.get(key), bool):
            raise ItemError(f"field {key!r} must be {typ.__name__}")
    if not data["id"] or not data["format"]:
        raise ItemError("fields 'id' and 'format' must be non-empty")
    source, path = data.get("source"), data.get("path")
    if (source is None) == (path is None):
        raise ItemError("exactly one of 'source' and 'path' must be set")
    if source is not None:
        if not isinstance(source, str):
            raise ItemError("field 'source' must be a string")
        if len(source.encode()) > MAX_SOURCE_BYTES:
            raise ItemError("field 'source' exceeds 1 MiB")
    if path is not None and (not isinstance(path, str) or not os.path.isabs(path)):
        raise ItemError("field 'path' must be an absolute path")
    title = data.get("title")
    if title is not None and not isinstance(title, str):
        raise ItemError("field 'title' must be a string")
    origin = data.get("origin", {})
    if not isinstance(origin, dict):
        raise ItemError("field 'origin' must be an object")
    for key in ("harness", "pane", "herdr_session", "session", "cwd", "via"):
        if key in origin and origin[key] is not None and not isinstance(origin[key], str):
            raise ItemError(f"field 'origin.{key}' must be a string")


def detect_harness(env: dict | None = None) -> str:
    """Best guess of the harness that runs this process, from its environment."""
    env = os.environ if env is None else env
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if env.get("CODEX_SANDBOX") or env.get("CODEX_HOME") or env.get("CODEX_MANAGED_BY_NPM"):
        return "codex"
    if env.get("OPENCODE") or env.get("OPENCODE_BIN_PATH"):
        return "opencode"
    if env.get("ANTIGRAVITY_CLI") or env.get("AGY_SESSION_ID") or "antigravity" in env.get("_", ""):
        return "agy"
    if env.get("COPILOT_CLI") or env.get("COPILOT_AGENT_SESSION_ID"):
        return "copilot"
    return "unknown"


def new(
    fmt: str,
    *,
    source: str | None = None,
    path: str | None = None,
    title: str | None = None,
    pane: str | None = None,
    harness: str | None = None,
    session: str | None = None,
    cwd: str | None = None,
    via: str = "cli",
) -> Item:
    now_ns = time.time_ns()
    origin = {
        "harness": harness or detect_harness(),
        "pane": pane,
        "herdr_session": herdr_session(),
        "session": session,
        "cwd": cwd or os.getcwd(),
        "via": via,
    }
    item = Item(
        format=fmt,
        source=source,
        path=os.path.abspath(path) if path else None,
        title=title,
        origin={k: v for k, v in origin.items() if v is not None},
        id=f"{now_ns}-{secrets.token_hex(2)}",
        created=now_ns // 1_000_000_000,
    )
    validate(item.to_json())
    return item


def write(item: Item, pane: str | None = None) -> Path:
    """Atomically write `item` into the spool of `pane` (default: origin.pane)."""
    validate(item.to_json())
    target_dir = spool_dir(pane if pane is not None else item.origin.get("pane"))
    target_dir.mkdir(parents=True, exist_ok=True)
    final = target_dir / f"{item.id}.json"
    tmp = target_dir / f"{item.id}.json.tmp"
    tmp.write_text(json.dumps(item.to_json(), indent=1))
    os.replace(tmp, final)
    item.file = final
    return final


def read(file: Path) -> Item:
    data = json.loads(Path(file).read_text())
    validate(data)
    return Item(
        format=data["format"],
        source=data.get("source"),
        path=data.get("path"),
        title=data.get("title"),
        origin=data.get("origin") or {},
        id=data["id"],
        created=data["created"],
        v=data["v"],
        file=Path(file),
    )


def list_items(pane: str | None) -> list[Item]:
    """Items of one pane, oldest first. Invalid files are skipped."""
    directory = spool_dir(pane)
    if not directory.is_dir():
        return []
    items = []
    for file in sorted(directory.glob("*.json")):
        try:
            items.append(read(file))
        except (OSError, ValueError):
            continue
    return items


def remove_pane(pane: str | None) -> None:
    shutil.rmtree(spool_dir(pane), ignore_errors=True)
