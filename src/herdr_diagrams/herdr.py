"""Thin wrapper around the herdr CLI and herdr-core (hc) / herdr-app."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

PLUGIN_ID = "herdr-diagrams"


def binary() -> str | None:
    explicit = os.environ.get("HERDR_BIN_PATH")
    if explicit:  # set by herdr for plugin processes; a stale path means no herdr
        return explicit if os.access(explicit, os.X_OK) else None
    return shutil.which("herdr")


def hc_binary() -> str | None:
    for name in ("hc", "herdr-core"):
        if found := shutil.which(name):
            return found
        candidate = Path.home() / ".local" / "bin" / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def app_binary() -> str | None:
    if found := shutil.which("herdr-app"):
        return found
    candidate = Path.home() / ".local" / "bin" / "herdr-app"
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


def is_hc_terminal(pane_id: str | None) -> bool:
    """True when `pane_id` is a herdr-core terminal ID (`t3` or `omarchy/t3`), not `w1:p3`."""
    if not pane_id:
        return False
    return ":" not in pane_id


def local_hc_id(pane_id: str) -> str:
    """Strip an optional `<machine>/` prefix from a herdr-core terminal ID."""
    return pane_id.rsplit("/", 1)[-1] if "/" in pane_id else pane_id


def hc_get(pane_id: str, timeout: float = 5) -> dict | None:
    """Return `hc get <id> --json` for a herdr-core terminal, or None."""
    exe = hc_binary()
    if not exe:
        return None
    target = local_hc_id(pane_id)
    try:
        proc = subprocess.run([exe, "get", target, "--json"],
                              capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout)
        return data if isinstance(data, dict) and "address" in data else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def hc_read_visible(pane_id: str, timeout: float = 5) -> str | None:
    """Visible screen text of a herdr-core terminal (`hc read --lines 0`)."""
    exe = hc_binary()
    if not exe:
        return None
    target = local_hc_id(pane_id)
    try:
        proc = subprocess.run([exe, "read", "--lines", "0", target],
                              capture_output=True, text=True, timeout=timeout)
        return proc.stdout if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _run_herdr_app(args: list[str], machine: str | None = None, timeout: float = 6) -> dict | None:
    """Run `herdr-app <args>` locally or on a connected `hc` machine and parse JSON stdout."""
    if machine:
        exe = hc_binary()
        if not exe:
            return None
        cmd = [exe, "exec", "--on", machine, "herdr-app", *args]
    else:
        exe = app_binary()
        if not exe:
            return None
        cmd = [exe, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout)
        return data if isinstance(data, dict) else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def connected_hc_machines(timeout: float = 5) -> list[str]:
    """Names of connected peer machines reported by `hc ls --json`."""
    exe = hc_binary()
    if not exe:
        return []
    try:
        proc = subprocess.run([exe, "ls", "--json"], capture_output=True, text=True, timeout=timeout)
        data = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    machines = data.get("machines") if isinstance(data, dict) else []
    return [m["name"] for m in (machines or [])
            if isinstance(m, dict) and m.get("state") == "connected" and m.get("name")]


def _find_terminal_in_app_ls(ls_data: dict, local_id: str, remote_only: bool) -> tuple[str, str] | None:
    """Find `(pane_id, qualified_terminal_id)` for `local_id` in `herdr-app ls` JSON."""
    for space in ls_data.get("spaces") or []:
        if not isinstance(space, dict):
            continue
        is_remote_space = bool(space.get("machine"))
        if remote_only and not is_remote_space:
            continue
        for tab in space.get("tabs") or []:
            for term in (tab.get("terminals") if isinstance(tab, dict) else None) or []:
                if not isinstance(term, dict):
                    continue
                t_addr = str(term.get("terminal") or "")
                p_id = str(term.get("pane") or "")
                if not p_id:
                    continue
                if (not remote_only and t_addr == local_id) or (
                    remote_only and t_addr.endswith(f"/{local_id}")
                ):
                    return p_id, t_addr
    return None


def open_app_viewer(source_pane: str) -> dict | None:
    """Open the native GPUI `diagrams` mod beside `source_pane` in Herdr-App."""
    local_id = local_hc_id(source_pane)
    candidates: list[tuple[str | None, bool]] = [(None, False)]
    candidates.extend((m, True) for m in connected_hc_machines())
    for machine, remote_only in candidates:
        ls_data = _run_herdr_app(["ls"], machine=machine)
        if not ls_data:
            continue
        found = _find_terminal_in_app_ls(ls_data, local_id, remote_only=remote_only)
        if not found:
            continue
        pane_id, qualified_term = found
        payload = json.dumps({
            "direction": "right",
            "pane": pane_id,
            "mod": "diagrams",
            "props": {"bind": qualified_term},
        })
        res = _run_herdr_app(["do", "pane.split", payload], machine=machine)
        if res and not res.get("error"):
            return {"pane": res.get("pane"), "machine": machine, "mod": "diagrams"}
    return None


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
    if is_hc_terminal(pane_id):
        info = hc_get(pane_id)
        if info is None:
            return None
        if "state" in info:
            return info.get("state") == "live"
        return info.get("finished_ms") is None
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
    if is_hc_terminal(pane_id):
        info = hc_get(pane_id)
        if not info:
            return None
        status = info.get("status") if isinstance(info.get("status"), dict) else {}
        fg = info.get("foreground") if isinstance(info.get("foreground"), dict) else {}
        app = status.get("app") or fg.get("name")
        return {
            "pane_id": info.get("address", local_hc_id(pane_id)),
            "agent": app,
            "cwd": fg.get("cwd") or info.get("cwd"),
            "agent_session": {"value": str(info.get("created_ms", ""))} if info.get("created_ms") else {},
        }
    result = call("pane", "get", pane_id)
    return (result or {}).get("pane")


def pane_rect(pane_id: str) -> dict | None:
    if is_hc_terminal(pane_id):
        info = hc_get(pane_id)
        if not info:
            return None
        return {"width": info.get("cols", 120), "height": info.get("rows", 40)}
    result = call("pane", "layout", "--pane", pane_id)
    layout = (result or {}).get("layout") or {}
    for entry in layout.get("panes", []):
        if entry.get("pane_id") == pane_id:
            return entry.get("rect")
    return None


def open_viewer(source_pane: str, cwd: str | None = None) -> dict | None:
    """Open the plugin's viewer pane beside `source_pane`, without stealing focus."""
    if is_hc_terminal(source_pane):
        return open_app_viewer(source_pane)
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
    if not is_hc_terminal(pane_id):
        call("pane", "rename", pane_id, title)


def read_visible(pane_id: str, lines: int = 300) -> str | None:
    """Text currently visible in a pane, or None when herdr cannot be asked."""
    if is_hc_terminal(pane_id):
        return hc_read_visible(pane_id)
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
