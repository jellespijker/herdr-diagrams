"""Claude Code adapter (docs/spec.md §9.2): a `Stop` hook.

Reads the hook input from stdin, takes the last assistant turn from the
transcript JSONL and writes one Item per fenced diagram block. May import only
the Item and detection modules.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .. import detect, item

DEDUP_SECONDS = 600


def _text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content
                         if isinstance(part, dict) and part.get("type") == "text")
    return ""


def _is_prompt(entry: dict) -> bool:
    """A user entry typed by the human, not a tool result or meta message."""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(
        isinstance(p, dict) and p.get("type") == "text" for p in content)


def last_turn_text(transcript: Path) -> str:
    entries = []
    with open(transcript, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    start = 0
    for index, entry in enumerate(entries):
        if _is_prompt(entry):
            start = index + 1
    texts = [_text_of(e.get("message") or {}) for e in entries[start:]
             if e.get("type") == "assistant" and not e.get("isSidechain")]
    return "\n".join(t for t in texts if t)


def _digest(fmt: str, source: str) -> str:
    return hashlib.sha256(f"{fmt}\0{source}".encode()).hexdigest()


def recent_digests(pane: str | None) -> set[str]:
    cutoff = time.time() - DEDUP_SECONDS
    return {_digest(it.format, it.source) for it in item.list_items(pane)
            if it.source is not None and it.created >= cutoff}


def run(hook_input: dict, pane: str | None) -> list[Path]:
    """Write Items for the diagrams in the last turn. Returns the written files."""
    # Claude Code may run the Stop hook before the final message reaches the transcript,
    # so the hook input's last_assistant_message is read as well. Duplicates collapse below.
    texts = []
    transcript = hook_input.get("transcript_path")
    if transcript and Path(transcript).is_file():
        texts.append(last_turn_text(Path(transcript)))
    if isinstance(hook_input.get("last_assistant_message"), str):
        texts.append(hook_input["last_assistant_message"])
    blocks = detect.fenced_blocks("\n".join(texts))
    seen = recent_digests(pane)
    written = []
    for fmt, source in blocks:
        digest = _digest(fmt, source)
        if digest in seen:
            continue
        seen.add(digest)
        it = item.new(fmt, source=source, pane=pane, harness="claude",
                      session=hook_input.get("session_id"), cwd=hook_input.get("cwd"),
                      via="claude-stop")
        written.append(item.write(it))
    return written


HOOK_MARKER = "hook claude-stop"


def _is_ours(handler: dict) -> bool:
    command = handler.get("command", "")
    return HOOK_MARKER in command or command.endswith("claude-stop.sh")


def install_hook(settings: Path, command: str, uninstall: bool = False) -> str:
    """Add (or remove) the Stop hook in a Claude Code settings.json. Idempotent."""
    settings = settings.expanduser()
    if settings.is_symlink():  # dotfile managers link settings.json; edit the target
        settings = settings.resolve()
    data = {}
    if settings.is_file():
        text = settings.read_text()
        data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict) or \
            not isinstance(data.get("hooks", {}).get("Stop", []), list):
        raise ValueError(f"unexpected structure in {settings}; edit it by hand")
    stop = data.setdefault("hooks", {}).setdefault("Stop", [])
    present = any(_is_ours(h) for group in stop for h in group.get("hooks", []))
    if uninstall:
        if not present:
            return f"not installed in {settings}"
        for group in stop:
            group["hooks"] = [h for h in group.get("hooks", []) if not _is_ours(h)]
        data["hooks"]["Stop"] = [g for g in stop if g.get("hooks")]
        if not data["hooks"]["Stop"]:
            del data["hooks"]["Stop"]
        if not data["hooks"]:
            del data["hooks"]
        action = "removed from"
    else:
        if present:
            return f"already installed in {settings}"
        stop.append({"hooks": [{"type": "command", "command": command, "timeout": 120}]})
        action = "installed in"
    mode = 0o600
    if settings.is_file():
        mode = settings.stat().st_mode & 0o777
        backup = settings.with_name(settings.name + ".bak-herdr-diagrams")
        backup.write_text(settings.read_text())
        os.chmod(backup, mode)
    settings.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.with_name(f".{settings.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(tmp, mode)
    tmp.replace(settings)
    return f"Stop hook {action} {settings}"
