"""Install the shared skill and the CLI as symlinks (docs/spec.md §10, ADR-0005).

One skill directory in the plugin is linked into every harness's skill
directory, so an update reaches all of them. Real files are never overwritten.
"""

from __future__ import annotations

import os
from pathlib import Path

from .render import ROOT

SKILL_NAME = "herdr-diagrams"
SKILL_SRC = ROOT / "skills" / SKILL_NAME
CLI_SRC = ROOT / "bin" / "herdr-diagram"


def targets() -> dict[str, tuple[Path, str]]:
    """Link name -> (destination, which harnesses read it)."""
    home = Path.home()
    return {
        "agents": (home / ".agents" / "skills" / SKILL_NAME,
                   "Codex, opencode, Copilot CLI, Gemini CLI"),
        "claude": (Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude") / "skills" / SKILL_NAME,
                   "Claude Code"),
        "agy": (home / ".gemini" / "config" / "skills" / SKILL_NAME, "Antigravity CLI (agy)"),
        "cli": (home / ".local" / "bin" / "herdr-diagram", "the herdr-diagram command"),
    }


ALIASES = {"codex": "agents", "opencode": "agents", "copilot": "agents", "gemini": "agents"}


def _source_for(name: str) -> Path:
    return CLI_SRC if name == "cli" else SKILL_SRC


def status() -> list[tuple[str, Path, str, str]]:
    """(name, destination, readers, state) with state installed|missing|foreign|other-link."""
    rows = []
    for name, (dest, readers) in targets().items():
        source = _source_for(name)
        if dest.is_symlink():
            state = "installed" if Path(os.readlink(dest)).resolve() == source.resolve() else "other-link"
        elif dest.exists():
            state = "foreign"
        else:
            state = "missing"
        rows.append((name, dest, readers, state))
    return rows


def install(names: list[str] | None = None, uninstall: bool = False) -> list[str]:
    """Create or remove the links. Returns one report line per target."""
    wanted = {ALIASES.get(n, n) for n in names} if names else set(targets())
    unknown = wanted - set(targets())
    if unknown:
        raise ValueError(f"unknown harness: {', '.join(sorted(unknown))}")
    report = []
    for name, dest, readers, state in status():
        if name not in wanted:
            continue
        source = _source_for(name)
        if uninstall:
            if state == "installed":
                dest.unlink()
                report.append(f"removed  {dest}")
            else:
                report.append(f"skipped  {dest} ({state})")
            continue
        if name == "agy" and not dest.parent.parent.is_dir() and names is None:
            report.append(f"skipped  {dest} (agy not set up)")
            continue
        if state == "installed":
            report.append(f"ok       {dest}  ({readers})")
        elif state == "missing":
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(source)
            report.append(f"linked   {dest}  ({readers})")
        else:
            report.append(f"skipped  {dest}: exists and is not ours ({state})")
    return report
