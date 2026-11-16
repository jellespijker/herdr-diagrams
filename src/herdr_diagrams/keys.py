"""Add the plugin's keybinding to herdr's config.toml (`setup-keys`).

A plugin manifest cannot declare keybindings; herdr's menu lists the `[[keys.command]]`
entries of the user's config.toml. This module manages one marked block there.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

DEFAULT_KEY = "prefix+i"
DEFAULT_APP_KEY = "ctrl-shift-i"
BEGIN = "# >>> herdr-diagrams keys (managed by `herdr-diagram setup-keys`) >>>"
END = "# <<< herdr-diagrams keys <<<"
ACTION = "herdr-diagrams.open"
# Built-in herdr bindings (0.9.3) that are not always written to config.toml.
BUILTIN = {
    "prefix+b", "prefix+c", "prefix+e", "prefix+g", "prefix+h", "prefix+j", "prefix+k", "prefix+l",
    "prefix+n", "prefix+o", "prefix+p", "prefix+q", "prefix+r", "prefix+s", "prefix+v", "prefix+w",
    "prefix+x", "prefix+z", "prefix+d", "prefix+minus", "prefix+tab", "prefix+alt+g",
    "prefix+ctrl+k", "prefix+shift+d", "prefix+shift+g", "prefix+shift+n", "prefix+shift+p",
    "prefix+shift+r", "prefix+shift+t", "prefix+shift+tab", "prefix+shift+w", "prefix+shift+x",
}
SUGGESTIONS = ("prefix+i", "prefix+m", "prefix+y", "prefix+u", "prefix+f", "prefix+shift+i")


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "herdr" / "config.toml"
    return path.resolve() if path.is_symlink() else path


def _strip_block(text: str) -> str:
    return re.sub(rf"\n?{re.escape(BEGIN)}.*?{re.escape(END)}\n?", "\n", text, flags=re.DOTALL)


def used_keys(text: str) -> dict[str, str]:
    """Key -> what uses it, from a config.toml (our own block excluded)."""
    try:
        data = tomllib.loads(_strip_block(text))
    except tomllib.TOMLDecodeError:
        return {}
    used: dict[str, str] = {}
    keys = data.get("keys") or {}
    for name, value in keys.items():
        for key in value if isinstance(value, list) else [value]:
            if isinstance(key, str):
                used[key.lower()] = f"herdr keys.{name}"
    for entry in keys.get("command", []) if isinstance(keys.get("command"), list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("key"), str):
            used[entry["key"].lower()] = entry.get("description") or entry.get("command", "command")
    return used


def conflict(key: str, text: str) -> str | None:
    key = key.lower()
    used = used_keys(text)
    if key in used:
        return used[key]
    if key in BUILTIN:
        return "a built-in herdr binding"
    return None


def free_suggestion(text: str) -> str | None:
    return next((k for k in SUGGESTIONS if not conflict(k, text)), None)


def block(key: str) -> str:
    return (f"{BEGIN}\n[[keys.command]]\nkey = \"{key}\"\ntype = \"plugin_action\"\n"
            f"command = \"{ACTION}\"\ndescription = \"Diagrams: open the viewer beside this pane\"\n{END}\n")


def installed_key(text: str) -> str | None:
    match = re.search(rf"{re.escape(BEGIN)}.*?key = \"([^\"]+)\".*?{re.escape(END)}", text, re.DOTALL)
    return match.group(1) if match else None


def setup(key: str | None = None, remove: bool = False, path: Path | None = None) -> tuple[bool, str]:
    """Write or remove the managed block. Returns (changed, message)."""
    path = path or config_path()
    text = path.read_text() if path.is_file() else ""
    current = installed_key(text)
    if remove:
        if current is None:
            return False, f"no herdr-diagrams keybinding in {path}"
        new = _strip_block(text).rstrip("\n") + "\n"
        message = f"removed the {current} keybinding from {path}"
    else:
        key = (key or DEFAULT_KEY).lower()
        if current == key:
            return False, f"{key} already opens the viewer ({path})"
        if (taken := conflict(key, text)):
            hint = free_suggestion(text)
            return False, (f"{key} is already used by {taken}. "
                           + (f"Try: herdr-diagram setup-keys --key {hint}" if hint else "Pick another key."))
        new = _strip_block(text).rstrip("\n") + "\n\n" + block(key)
        message = f"{key} now opens the diagram viewer (added to {path})"
    try:
        tomllib.loads(new)
    except tomllib.TOMLDecodeError as exc:
        return False, f"refusing to write an invalid config.toml: {exc}"
    if path.is_file():
        backup = path.with_name(path.name + ".bak-herdr-diagrams")
        backup.write_text(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(new)
    if path.is_file():
        os.chmod(tmp, path.stat().st_mode & 0o777)
    os.replace(tmp, path)
    return True, message


def app_keys_path(app_home: Path | None = None) -> Path:
    if app_home is None:
        if override := os.environ.get("HERDR_APP_HOME"):
            app_home = Path(override)
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
            app_home = Path(base) / "herdr-app"
    path = app_home / "keys.json"
    return path.resolve() if path.is_symlink() else path


def _is_diagrams_app_binding(val: object) -> bool:
    if isinstance(val, str):
        return val in ("mod.open:diagrams", "diagrams.open")
    if isinstance(val, dict):
        return val.get("command") == "pane.split" and (val.get("args") or {}).get("mod") == "diagrams"
    return False


def installed_app_key(path: Path | None = None) -> str | None:
    path = path or app_keys_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    global_keys = data.get("global") if isinstance(data, dict) else None
    if not isinstance(global_keys, dict):
        return None
    for k, v in global_keys.items():
        if _is_diagrams_app_binding(v):
            return k
    return None


def setup_app(key: str | None = None, remove: bool = False, path: Path | None = None) -> tuple[bool, str]:
    """Write or remove the Herdr-App keybinding in `~/.config/herdr-app/keys.json`."""
    path = path or app_keys_path()
    if not path.parent.is_dir():
        return False, f"no herdr-app folder at {path.parent}"
    text = path.read_text() if path.is_file() else "{}\n"
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        return False, f"refusing to edit invalid keys.json ({path}): {exc}"
    if not isinstance(data, dict):
        data = {}
    global_keys = data.setdefault("global", {})
    if not isinstance(global_keys, dict):
        return False, f"unexpected global section in {path}"
    current = next((k for k, v in list(global_keys.items()) if _is_diagrams_app_binding(v)), None)
    if remove:
        changed = False
        if current is not None:
            global_keys.pop(current, None)
            changed = True
        if "mod:diagrams" in data:
            data.pop("mod:diagrams", None)
            changed = True
        if not changed:
            return False, f"no herdr-diagrams keybinding in {path}"
        message = f"removed the {current or 'mod:diagrams'} keybinding from {path}"
    else:
        app_key = (key or DEFAULT_APP_KEY).lower()
        if app_key.startswith("prefix+"):
            app_key = DEFAULT_APP_KEY
        target_val = {"command": "pane.split", "args": {"direction": "right", "mod": "diagrams"}}
        existing = global_keys.get(app_key)
        if existing is not None and not _is_diagrams_app_binding(existing):
            return False, f"{app_key} is already used in {path} by {existing!r}"
        if current == app_key and data.get("mod:diagrams") == {app_key: "pane.close"}:
            return False, f"{app_key} already opens the diagrams mod ({path})"
        if current and current != app_key:
            global_keys.pop(current, None)
        global_keys[app_key] = target_val
        data["mod:diagrams"] = {app_key: "pane.close"}
        message = f"{app_key} now opens the Herdr-App diagrams mod (added to {path})"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)
    return True, message
