"""Install the shared skill and the CLI as symlinks (docs/spec.md §10, ADR-0005).

One skill directory in the plugin is linked into every harness's skill
directory, so an update reaches all of them. Real files are never overwritten.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .render import ROOT

SKILL_NAME = "herdr-diagrams"
SKILL_SRC = ROOT / "skills" / SKILL_NAME
CLI_SRC = ROOT / "bin" / "herdr-diagram"
MOD_SRC = ROOT / "mods" / "diagrams"


def app_home() -> Path:
    if override := os.environ.get("HERDR_APP_HOME"):
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "herdr-app"


def mod_dest(home: Path | None = None) -> Path:
    return (home or app_home()) / "mods" / "diagrams"


def mod_cache_dir(home: Path | None = None) -> Path:
    """Artifact cache directory outside `mods/diagrams/` so writing PNGs never triggers mod hot-reload."""
    return (home or app_home()) / "data" / "diagrams-cache"


def install_app_mod(home: Path | None = None, uninstall: bool = False) -> tuple[str, Path]:
    """Install or remove the native Herdr-App GPUI mod in `<app_home>/mods/diagrams`."""
    dest = mod_dest(home)
    if uninstall:
        if dest.is_symlink() or dest.is_dir():
            if dest.is_symlink():
                dest.unlink()
            else:
                shutil.rmtree(dest, ignore_errors=True)
            return "removed", dest
        return "skipped", dest
    if not MOD_SRC.is_dir():
        return "missing-src", dest
    dest.mkdir(parents=True, exist_ok=True)
    legacy_cache = dest / "cache"
    if legacy_cache.is_dir():
        shutil.rmtree(legacy_cache, ignore_errors=True)
    mod_cache_dir(home).mkdir(parents=True, exist_ok=True)
    for item in MOD_SRC.iterdir():
        if item.is_file():
            shutil.copy2(item, dest / item.name)
    return "installed", dest


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
