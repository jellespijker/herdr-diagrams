"""Which terminal and OS the user runs, and whether the viewer can show images there.

herdr forwards only the Kitty graphics protocol, and it does not report what the outer
terminal supports. The herdr *client* process runs directly in that terminal, so its
environment names it (TERM_PROGRAM, TERM, terminal-specific variables). This module finds
the client of the current herdr session; when it cannot, it falls back to this process's
environment, which herdr inherited from the terminal that started the server.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import item

# name -> (support, note). support: yes | partial | no
TERMINALS = {
    "Ghostty": ("yes", "tested"),
    "kitty": ("yes", "reference implementation of the protocol"),
    "WezTerm": ("yes", "implements the protocol"),
    "Konsole": ("partial", "partial protocol support; zoom may not work"),
    "iTerm2": ("partial", "protocol support since 3.6; untested"),
    "Warp": ("partial", "recent protocol support; untested"),
    "Alacritty": ("no", "no image protocol"),
    "foot": ("no", "supports Sixel only, which herdr does not forward"),
    "GNOME Terminal / VTE": ("no", "VTE terminals support Sixel at most, which herdr does not forward"),
    "xterm": ("no", "supports Sixel only, which herdr does not forward"),
    "Windows Terminal": ("no", "supports Sixel only, which herdr does not forward"),
    "Terminal.app": ("no", "no image protocol"),
    "VS Code terminal": ("no", "no Kitty graphics protocol"),
    "JetBrains terminal": ("no", "no Kitty graphics protocol"),
}

PLATFORMS = {
    "linux": ("yes", "supported and tested"),
    "darwin": ("yes", "supported; tested in CI, not yet by hand"),
    "win32": ("no", "not supported yet (see docs/adr/0010-platform-support.md)"),
}


@dataclass
class Info:
    name: str | None          # terminal name, None when unknown
    version: str | None
    support: str              # yes | partial | no | unknown
    note: str
    source: str               # "herdr client" | "environment"
    multiplexer: str | None   # tmux / zellij / screen between herdr and the terminal
    ssh: bool

    @property
    def ok(self) -> bool:
        return self.support in ("yes", "partial") and not self.multiplexer

    def summary(self) -> str:
        if self.multiplexer:
            return (f"herdr runs inside {self.multiplexer}, which blocks the image protocol; "
                    "run herdr directly in the terminal")
        if self.name is None:
            return "terminal unknown; images need a Kitty-graphics terminal (Ghostty, kitty, WezTerm)"
        label = f"{self.name} {self.version}".strip() if self.version else self.name
        verdict = {"yes": "shows images", "partial": "may show images",
                   "no": "cannot show images"}[self.support]
        return f"{label} {verdict} ({self.note})"


def identify(env: dict) -> tuple[str | None, str | None]:
    """(terminal name, version) from a terminal's environment variables."""
    program = env.get("TERM_PROGRAM", "")
    term = env.get("TERM", "")
    version = env.get("TERM_PROGRAM_VERSION") or None
    if program == "ghostty" or term == "xterm-ghostty":
        return "Ghostty", version if program == "ghostty" else None
    if program == "WezTerm" or term == "wezterm" or env.get("WEZTERM_PANE"):
        return "WezTerm", version if program == "WezTerm" else None
    if term == "xterm-kitty" or env.get("KITTY_WINDOW_ID"):
        return "kitty", None
    if program == "iTerm.app" or env.get("ITERM_SESSION_ID") or env.get("LC_TERMINAL") == "iTerm2":
        return "iTerm2", version if program == "iTerm.app" else env.get("LC_TERMINAL_VERSION")
    if program == "WarpTerminal":
        return "Warp", version
    if program == "Apple_Terminal":
        return "Terminal.app", version
    if program == "vscode":
        return "VS Code terminal", version
    if env.get("TERMINAL_EMULATOR", "").startswith("JetBrains"):
        return "JetBrains terminal", None
    if env.get("KONSOLE_VERSION"):
        return "Konsole", env.get("KONSOLE_VERSION")
    if env.get("WT_SESSION"):
        return "Windows Terminal", None
    if env.get("ALACRITTY_WINDOW_ID") or env.get("ALACRITTY_SOCKET") or term == "alacritty":
        return "Alacritty", None
    if term.startswith("foot"):
        return "foot", None
    if env.get("VTE_VERSION"):
        return "GNOME Terminal / VTE", env.get("VTE_VERSION")
    if env.get("XTERM_VERSION"):
        return "xterm", env.get("XTERM_VERSION")
    if env.get("GHOSTTY_RESOURCES_DIR"):  # weakest hint: also inherited by programs started from Ghostty
        return "Ghostty", None
    return None, None


def _multiplexer(env: dict) -> str | None:
    if env.get("TMUX"):
        return "tmux"
    if env.get("ZELLIJ") is not None or env.get("ZELLIJ_SESSION_NAME"):
        return "zellij"
    if env.get("STY"):
        return "GNU screen"
    return None


def _session_of(argv: list[str]) -> str:
    """herdr session a client command line attaches to."""
    for flag in ("--session",):
        if flag in argv and argv.index(flag) + 1 < len(argv):
            return argv[argv.index(flag) + 1]
    if "attach" in argv and argv.index("attach") + 1 < len(argv):
        return argv[argv.index("attach") + 1]
    return "default"


def _processes() -> list[tuple[list[str], dict]]:
    """(argv, environment) of this user's herdr processes. Linux: /proc; macOS: ps."""
    found = []
    if os.path.isdir("/proc"):
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                if not argv or os.path.basename(argv[0]) != b"herdr":
                    continue
                raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
            except OSError:
                continue
            env = dict(e.decode(errors="replace").split("=", 1) for e in raw if b"=" in e)
            found.append(([a.decode(errors="replace") for a in argv if a], env))
    elif sys.platform == "darwin":
        try:
            out = subprocess.run(["ps", "-E", "-ww", "-x", "-o", "command="], capture_output=True,
                                 text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        for line in out.splitlines():
            words = line.split()
            if not words or os.path.basename(words[0]) != "herdr":
                continue
            env = dict(w.split("=", 1) for w in words[1:] if re.match(r"^[A-Z_][A-Z0-9_]*=", w))
            argv = [w for w in words if not re.match(r"^[A-Z_][A-Z0-9_]*=", w)]
            found.append((argv, env))
    return found


def detect(env: dict | None = None) -> Info:
    env = dict(os.environ) if env is None else env
    session = item.herdr_session(env)
    clients = [(argv, cenv) for argv, cenv in _processes()
               if "server" not in argv[1:] and _session_of(argv) == session]
    if clients:
        argv, client_env = clients[-1]
        name, version = identify(client_env)
        source, mux_env = "herdr client", client_env
    else:
        name, version = identify(env)
        source, mux_env = "environment", env
    support, note = TERMINALS.get(name, ("unknown", "not recognised")) if name else ("unknown", "")
    return Info(name=name, version=version, support=support, note=note, source=source,
                multiplexer=_multiplexer(mux_env), ssh=bool(mux_env.get("SSH_CONNECTION")))


def platform() -> tuple[str, str, str]:
    """(platform name, support, note) for this OS."""
    name = {"linux": "Linux", "darwin": "macOS", "win32": "Windows"}.get(sys.platform, sys.platform)
    support, note = PLATFORMS.get(sys.platform, ("unknown", "untested; Linux and macOS are supported"))
    return name, support, note


def kitty_graphics_setting() -> str:
    """herdr's `kitty_graphics` setting as text; contains "OFF" when images are disabled."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "herdr" / "config.toml"
    try:
        data = tomllib.loads(config.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return "default (on)"
    for section in ("terminal", "experimental"):
        value = (data.get(section) or {}).get("kitty_graphics")
        if value is not None:
            return f"{'on' if value else 'OFF'} ([{section}] in {config})"
    return "default (on)"


def images_setting() -> str:
    """auto | on | off, from HERDR_DIAGRAMS_IMAGES or `images` in the plugin config.toml."""
    value = os.environ.get("HERDR_DIAGRAMS_IMAGES")
    if not value:
        from .render import load_settings  # late import: render is heavier
        value = str(load_settings().get("images", "auto"))
    return value.lower() if value.lower() in ("auto", "on", "off") else "auto"


def image_problem(info: Info | None = None) -> str | None:
    """Why the viewer cannot show images here, or None when it probably can."""
    setting = images_setting()
    if setting == "on":
        return None
    if setting == "off":
        return "images are turned off (images = \"off\" in the plugin config)."
    if "OFF" in kitty_graphics_setting():
        return "herdr's kitty_graphics setting is off: set `[terminal] kitty_graphics = true`."
    info = info or detect()
    if info.multiplexer or info.support == "no":
        return (info.summary() + ". If images do work in your terminal, set images = \"on\" "
                "in the plugin config.")
    return None
