"""Thin wrapper around the herdr CLI, which is the plugin API."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

PLUGIN_ID = "herdr-diagrams"


def binary() -> str | None:
    explicit = os.environ.get("HERDR_BIN_PATH")
    if explicit:  # set by herdr for plugin processes; a stale path means no herdr
        return explicit if os.access(explicit, os.X_OK) else None
    return shutil.which("herdr")


def call(*args: str, timeout: float = 10, socket: str | None = None) -> dict | None:
    """Run `herdr <args>` and return the parsed JSON `result`, or None on any error.

    `socket` targets another herdr session's server instead of this process's own.
    """
    exe = binary()
    if not exe:
        return None
    env = None
    if socket:
        env = {k: v for k, v in os.environ.items()
               if k not in ("HERDR_SESSION", "HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID")}
        env["HERDR_SOCKET_PATH"] = socket
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for stream in (proc.stdout, proc.stderr):
        try:
            data = json.loads(stream)
        except ValueError:
            continue
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return None
    return None


def pane_exists(pane_id: str) -> bool | None:
    """True or False when herdr answered; None when it could not be asked."""
    exe = binary()
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "pane", "get", pane_id], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for stream in (proc.stdout, proc.stderr):
        try:
            data = json.loads(stream)
        except ValueError:
            continue
        if "result" in data:
            return True
        if (data.get("error") or {}).get("code") == "pane_not_found":
            return False
    return None


def pane(pane_id: str) -> dict | None:
    result = call("pane", "get", pane_id)
    return (result or {}).get("pane")


def pane_rect(pane_id: str) -> dict | None:
    result = call("pane", "layout", "--pane", pane_id)
    layout = (result or {}).get("layout") or {}
    for entry in layout.get("panes", []):
        if entry.get("pane_id") == pane_id:
            return entry.get("rect")
    return None


def open_viewer(source_pane: str, cwd: str | None = None) -> dict | None:
    """Open the plugin's viewer pane beside `source_pane`, without stealing focus."""
    rect = pane_rect(source_pane) or {}
    wide = rect.get("width", 0) >= 2.2 * rect.get("height", 1) and rect.get("width", 0) >= 120
    args = ["plugin", "pane", "open", "--plugin", PLUGIN_ID, "--entrypoint", "viewer",
            "--placement", "split", "--target-pane", source_pane,
            "--direction", "right" if wide or not rect else "down",
            "--env", f"HERDR_DIAGRAMS_BIND={source_pane}", "--no-focus"]
    if cwd:
        args += ["--cwd", cwd]
    return call(*args)


def close_pane(pane_id: str) -> None:
    call("pane", "close", pane_id)


def set_title(pane_id: str, title: str) -> None:
    call("pane", "rename", pane_id, title)


def read_visible(pane_id: str, lines: int = 300) -> str | None:
    """Text currently visible in a pane, or None when herdr cannot be asked."""
    exe = binary()
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "pane", "read", pane_id, "--source", "visible", "--lines", str(lines)],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 and not proc.stdout.startswith('{"error"') else None


def running_sessions() -> list[dict]:
    """Running herdr sessions: [{"name", "socket_path", ...}] from `herdr session list --json`."""
    exe = binary()
    if not exe:
        return []
    try:
        proc = subprocess.run([exe, "session", "list", "--json"], capture_output=True, text=True, timeout=10)
        data = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    sessions = data.get("sessions") or (data.get("result") or {}).get("sessions") or []
    return [s for s in sessions if isinstance(s, dict) and s.get("running") and s.get("socket_path")]


def reload_config_everywhere() -> tuple[list[str], list[str]]:
    """Reload config.toml in every running herdr session. Returns (reloaded, failed) names."""
    reloaded, failed = [], []
    sessions = running_sessions()
    if not sessions:  # older herdr without session listing: at least this session
        return (["current"], []) if call("server", "reload-config") is not None else ([], ["current"])
    for session in sessions:
        result = call("server", "reload-config", socket=session["socket_path"])
        (reloaded if result is not None else failed).append(session.get("name", "?"))
    return reloaded, failed
