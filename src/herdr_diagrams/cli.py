"""`herdr-diagram` command line (docs/spec.md §7)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from . import detect, herdr, item, render, skill, viewers

EXIT_RUNTIME, EXIT_USAGE, EXIT_DETECT = 1, 2, 3


def version() -> str:
    try:
        return tomllib.loads((render.ROOT / "herdr-plugin.toml").read_text())["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


def current_pane(explicit: str | None = None) -> str | None:
    return explicit or os.environ.get("HERDR_PANE_ID") or None


def ensure_viewer(pane: str | None, cwd: str | None = None) -> str:
    """Open a viewer beside `pane` unless one is running. Returns a status word."""
    if not pane or os.environ.get("HERDR_DIAGRAMS_NO_OPEN") == "1":
        return "not-opened"
    if viewers.lookup(pane):
        return "running"
    if not herdr.binary():
        return "no-herdr"
    viewers.mark_pending(pane)
    result = herdr.open_viewer(pane, cwd)
    if result is None:
        viewers.forget(pane)
        return "open-failed"
    return "opened"


def _origin_from_herdr(pane: str | None) -> tuple[str | None, str | None]:
    """Harness kind and session ID that herdr detected for `pane`."""
    if not pane or not herdr.binary():
        return None, None
    info = herdr.pane(pane) or {}
    harness = info.get("agent")
    session = (info.get("agent_session") or {}).get("value")
    if harness and harness not in item.HARNESSES:
        harness = {"antigravity": "agy", "gemini": "agy"}.get(harness, harness)
    return harness, session


def cmd_show(args) -> int:
    registry = render.load_registry()
    pane = current_pane(args.pane)
    source = path = None
    if args.file in (None, "-"):
        if args.file is None and sys.stdin.isatty():
            print("herdr-diagram show: give a FILE or pipe a diagram on stdin", file=sys.stderr)
            return EXIT_USAGE
        source = sys.stdin.read()
    else:
        file = Path(args.file).expanduser()
        if not file.is_file():
            print(f"herdr-diagram show: no such file: {file}", file=sys.stderr)
            return EXIT_RUNTIME
        path = str(file.resolve())
    try:
        fmt = detect.detect(registry, fmt=args.format, path=path, source=source)
    except detect.DetectError as exc:
        print(f"herdr-diagram show: {exc}", file=sys.stderr)
        return EXIT_USAGE if args.format else EXIT_DETECT
    if path and fmt != "image":
        source, path = Path(path).read_text(errors="replace"), None
    harness, session = _origin_from_herdr(pane)
    try:
        it = item.new(fmt, source=source, path=path, title=args.title, pane=pane,
                      harness=harness, session=session)
    except item.ItemError as exc:
        print(f"herdr-diagram show: {exc}", file=sys.stderr)
        return EXIT_RUNTIME
    if not args.no_wait:
        result = render.render_item(it, registry=registry)
        if not result.ok:
            print(f"herdr-diagram show: {fmt} render failed: {item.clean_text(result.error)}",
                  file=sys.stderr)
            if detail := render.short_detail(result.detail):
                print(item.clean_text(detail), file=sys.stderr)
            print("Nothing was queued. Fix the diagram and run show again.", file=sys.stderr)
            return EXIT_RUNTIME
    if not it.title:
        it.title = it.display_title  # a title is what the chat marker refers to
    written = item.write(it)
    state = "not-opened" if args.no_open else ensure_viewer(pane, it.origin.get("cwd"))
    where = {"running": f"shown in the viewer beside pane {pane}",
             "opened": f"viewer opened beside pane {pane}",
             "not-opened": "queued",
             "no-herdr": "queued (herdr not found; open the viewer manually)",
             "open-failed": "queued (could not open the viewer; run the herdr-diagrams.open action)"}[state]
    if not pane:
        where = "queued outside herdr (no HERDR_PANE_ID); run `herdr-diagram render` for a file"
    print(f"{fmt}: {it.display_title} — {where}")
    if pane and it.origin.get("harness", "unknown") != "unknown":
        print(f"Write this line in your answer where the diagram belongs: [diagram: {it.display_title}]")
    if args.verbose:
        print(written)
    return 0


def cmd_list(args) -> int:
    pane = current_pane(args.pane)
    items = item.list_items(pane)
    if args.json:
        print(json.dumps([it.to_json() for it in items], indent=1))
        return 0
    for it in reversed(items):
        stamp = time.strftime("%H:%M:%S", time.localtime(it.created))
        print(f"{stamp}  {it.format:<11} {it.display_title}")
    return 0


def cmd_render(args) -> int:
    registry = render.load_registry()
    file = Path(args.file).expanduser()
    if not file.is_file():
        print(f"herdr-diagram render: no such file: {file}", file=sys.stderr)
        return EXIT_RUNTIME
    try:
        fmt = detect.detect(registry, fmt=args.format, path=str(file))
    except detect.DetectError as exc:
        print(f"herdr-diagram render: {exc}", file=sys.stderr)
        return EXIT_USAGE if args.format else EXIT_DETECT
    if fmt == "image":
        it = item.Item(format="image", path=str(file.resolve()), id="render", created=0)
        result = render.render_item(it, registry=registry)
    else:
        result = render.render_source(fmt, file.read_bytes(), registry=registry,
                                      theme=args.theme, cwd=str(file.parent.resolve()))
    if not result.ok:
        print(f"herdr-diagram render: {result.error}", file=sys.stderr)
        if result.detail:
            print(result.detail, file=sys.stderr)
        return EXIT_RUNTIME
    out = Path(args.output)
    outputs = [out] if len(result.artifacts) == 1 else [
        out.with_name(f"{out.stem}-{i + 1}{out.suffix}") for i in range(len(result.artifacts))]
    for artifact, dest in zip(result.artifacts, outputs, strict=False):
        shutil.copyfile(artifact, dest)
        print(dest)
    return 0


def cmd_export(args) -> int:
    items = item.list_items(current_pane(args.pane))
    if args.archived:
        items = archived_items(current_pane(args.pane)) + items
    if not items:
        print("herdr-diagram export: no diagrams for this pane", file=sys.stderr)
        return EXIT_RUNTIME
    if args.all:
        chosen = items
    else:
        try:
            chosen = [items[-args.index if args.index else -1]]
        except IndexError:
            print(f"herdr-diagram export: there are only {len(items)} diagrams", file=sys.stderr)
            return EXIT_USAGE
    kinds = tuple(k for k in ("png", "svg", "src") if getattr(args, k)) or ("png", "svg", "src")
    theme = args.theme or render.load_settings()["export_theme"]
    status = 0
    for it in chosen:
        written, problems = render.export(it, render.export_dir(it, args.dir), theme=theme, kinds=kinds)
        for path in written:
            print(path)
        for problem in problems:
            print(f"herdr-diagram export: {it.display_title}: {item.clean_text(problem)}", file=sys.stderr)
            status = EXIT_RUNTIME
    return status


def archived_items(pane: str | None) -> list[item.Item]:
    root = item.archive_root() / item.scope(pane)
    found = []
    for file in sorted(root.rglob("*.json")) if root.is_dir() else []:
        try:
            found.append(item.read(file))
        except (OSError, ValueError):
            continue
    return sorted(found, key=lambda it: it.id)


def cmd_view(args) -> int:
    from . import viewer  # termios-heavy; import only when needed

    bind = args.bind or os.environ.get("HERDR_DIAGRAMS_BIND")
    if not bind:
        context = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON") or "{}")
        bind = (context.get("pane") or {}).get("pane_id") if isinstance(context.get("pane"), dict) \
            else context.get("pane_id")
    return viewer.main(bind)


def cmd_open(args) -> int:
    pane = current_pane(args.pane)
    if not pane:
        print("herdr-diagram open: no pane; run inside herdr or pass --pane", file=sys.stderr)
        return EXIT_USAGE
    state = ensure_viewer(pane)
    print(f"viewer for {pane}: {state}")
    return 0 if state in ("opened", "running") else EXIT_RUNTIME


def _kitty_graphics_setting() -> str:
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


def cmd_doctor(args) -> int:
    ok = True

    def line(label: str, value: str, good: bool = True) -> None:
        nonlocal ok
        ok = ok and good
        print(f"  {'✓' if good else '✗'} {label:<22} {value}")

    print(f"herdr-diagrams {version()}  ({render.ROOT})")
    print("system")
    line("platform", f"{sys.platform}, Python {sys.version.split()[0]}", sys.platform != "win32")
    local_bin = str(Path.home() / ".local" / "bin")
    on_path = local_bin in os.environ.get("PATH", "").split(os.pathsep)
    line("~/.local/bin on PATH", "yes" if on_path else f"no: add {local_bin} to PATH for agents", on_path)
    exe = herdr.binary()
    herdr_version = ""
    if exe:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True)
        herdr_version = " ".join(proc.stdout.split()[-1:])
    print("herdr")
    line("binary", f"{exe} {herdr_version}".strip() if exe else "not found", bool(exe))
    inside = os.environ.get("HERDR_ENV") == "1" or bool(os.environ.get("HERDR_PANE_ID"))
    line("inside herdr", (f"yes, pane {os.environ['HERDR_PANE_ID']}" if os.environ.get("HERDR_PANE_ID")
                          else "yes") if inside else "no (run it in a herdr pane)", inside)
    setting = _kitty_graphics_setting()
    line("kitty_graphics", setting, "OFF" not in setting)
    print("paths")
    line("home", str(item.home()))
    line("config", str(render.config_dir()))
    print(f"renderers (theme: {render.load_settings()['theme']})")
    registry = render.load_registry()
    for key, (available, program) in render.availability(registry).items():
        program = program.replace(str(render.ROOT) + "/", "")  # bundled tools: plugin-relative
        line(key, program if available else f"missing: {program}", available)
    for name in ("rsvg-convert", "magick", "ffmpeg"):
        found = shutil.which(name)
        if found:
            line("image conversion", found)
            break
    else:
        line("image conversion", "none of rsvg-convert, magick, ffmpeg (SVG/JPEG need one)", False)
    print("skills")
    for name, dest, _readers, state in skill.status():
        line(name, f"{state}: {dest}", state == "installed")
    if not ok:
        print("\nSome checks failed. Missing renderers only disable their format.")
    wait_for_key(args)
    return 0


def wait_for_key(args) -> None:
    """Keep a popup pane open until the user has read its output."""
    if getattr(args, "wait", False) and sys.stdin.isatty():
        print("\nPress Enter to close.", end="", flush=True)
        try:
            sys.stdin.readline()
        except (OSError, KeyboardInterrupt):
            pass


def cmd_popup(args) -> int:
    """Plugin action helper: show a command's output in a popup pane."""
    result = herdr.call("plugin", "pane", "open", "--plugin", herdr.PLUGIN_ID,
                        "--entrypoint", args.name)
    return 0 if result is not None else EXIT_RUNTIME


def cmd_install_skill(args) -> int:
    if args.status:
        for name, dest, readers, state in skill.status():
            print(f"{state:<10} {name:<7} {dest}  ({readers})")
        return 0
    try:
        for row in skill.install(args.harness or None, uninstall=args.uninstall):
            print(row)
    except ValueError as exc:
        print(f"herdr-diagram install-skill: {exc}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        wait_for_key(args)
    return 0


def cmd_hook(args) -> int:
    """Harness hooks. Must never fail the harness: always exit 0, print nothing."""
    try:
        if args.name == "claude-stop":
            from .harness import claude

            data = json.loads(sys.stdin.read() or "{}")
            pane = current_pane()
            written = claude.run(data, pane)
            if written:
                ensure_viewer(pane, data.get("cwd"))
    except Exception as exc:  # a hook must never break the agent
        log = item.home() / "hook-errors.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a") as handle:
            handle.write(f"{time.ctime()} {args.name}: {exc!r}\n")
    return 0


def cmd_install_hook(args) -> int:
    from .harness import claude

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    settings = Path(args.settings).expanduser() if args.settings else claude_dir / "settings.json"
    cli_link = Path.home() / ".local" / "bin" / "herdr-diagram"
    if cli_link.is_symlink() and cli_link.resolve() == skill.CLI_SRC.resolve():
        command = f"{cli_link} hook claude-stop"
    else:
        command = f"{skill.CLI_SRC} hook claude-stop"
    try:
        print(claude.install_hook(settings, command, uninstall=args.uninstall))
    except (OSError, ValueError) as exc:
        print(f"herdr-diagram install-hook: {exc}", file=sys.stderr)
        return EXIT_RUNTIME
    return 0


def _log_event(event: str, raw: str, keep: int = 50) -> None:
    """Keep the last few event payloads, for debugging herdr integration."""
    log = item.home() / "events.log"
    try:
        lines = log.read_text().splitlines()[-(keep - 1):] if log.exists() else []
        lines.append(json.dumps({"t": int(time.time()), "event": event, "payload": raw[:2000]}))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(lines) + "\n")
    except OSError:
        pass


def cmd_event(args) -> int:
    """Plugin event and startup handler: keep the spool in step with herdr's panes."""
    event = os.environ.get("HERDR_PLUGIN_EVENT", "")
    raw = os.environ.get("HERDR_PLUGIN_EVENT_JSON") or "{}"
    _log_event(event, raw)
    try:
        data = json.loads(raw)
    except ValueError:
        return 0
    data = data.get("data", data) if isinstance(data, dict) else {}
    if event == "startup":
        prune_missing_panes()
        gc(time.time() - _parse_age("7d"))
    elif event == "pane.closed":
        pane = data.get("pane_id") or (data.get("pane") or {}).get("pane_id")
        if pane:
            close_viewer_of(pane)
            item.archive_pane(pane, "pane-closed")
    elif event == "pane.moved":
        old, new = data.get("previous_pane_id"), (data.get("pane") or {}).get("pane_id")
        if old and new and old != new:
            close_viewer_of(old)  # it is bound to the old ID; `show` opens a new one
            item.move_pane(old, new)
    elif event == "pane.agent_detected":
        pane = data.get("pane_id")
        if pane:
            archive_previous_sessions(pane)
    return 0


def close_viewer_of(pane: str) -> None:
    bound = viewers.lookup(pane)
    if bound and bound.get("viewer_pane"):
        herdr.close_pane(bound["viewer_pane"])
    viewers.forget(pane)


def archive_previous_sessions(pane: str, attempts: int = 10) -> None:
    """A new agent session started in `pane`: archive diagrams of earlier sessions.

    herdr reports the agent before its session ID, so wait for the ID briefly.
    """
    for _ in range(attempts):
        session = ((herdr.pane(pane) or {}).get("agent_session") or {}).get("value")
        if session:
            item.archive_other_sessions(pane, session)
            return
        time.sleep(1)


def prune_missing_panes() -> None:
    """After a herdr restart, archive diagrams of panes that no longer exist."""
    listing = herdr.call("pane", "list")
    if listing is None:
        return
    alive = {item.pane_key(p.get("pane_id")) for p in listing.get("panes", [])}
    for key in item.pane_ids_with_items():
        if key not in alive and key != item.NOPANE:
            pane = key.replace("_", ":", 1)
            viewers.forget(pane)
            item.archive_pane(pane, "pane-gone")


def _parse_age(text: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if text and text[-1] in units:
        return float(text[:-1]) * units[text[-1]]
    return float(text)


def gc(cutoff: float) -> int:
    """Delete spool, archive and cache files older than `cutoff`; drop empty directories."""
    removed = 0
    roots = (item.spool_root(), item.archive_root(), item.cache_dir())
    for root in roots:
        if not root.is_dir():
            continue
        for file in root.rglob("*"):
            if file.is_file() and file.stat().st_mtime < cutoff:
                file.unlink()
                removed += 1
    for root in roots:
        if not root.is_dir():
            continue
        for directory in sorted((d for d in root.rglob("*") if d.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
    return removed


def cmd_gc(args) -> int:
    try:
        cutoff = time.time() - _parse_age(args.older_than)
    except ValueError:
        print(f"herdr-diagram gc: bad age {args.older_than!r}; use e.g. 7d, 12h, 30m", file=sys.stderr)
        return EXIT_USAGE
    print(f"removed {gc(cutoff)} files older than {args.older_than}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="herdr-diagram",
        description="Show Mermaid, PlantUML, Structurizr, D2 and Graphviz diagrams, and images, "
                    "in a herdr pane beside the coding agent.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("show", help="queue a diagram or image for the viewer beside this pane")
    p.add_argument("file", nargs="?", help="diagram or image file; '-' or omitted reads stdin")
    p.add_argument("-f", "--format", help="mermaid, plantuml, structurizr, d2, graphviz, image")
    p.add_argument("-t", "--title")
    p.add_argument("--pane", help="source pane (default: $HERDR_PANE_ID)")
    p.add_argument("--no-open", action="store_true", help="do not open a viewer")
    p.add_argument("--no-wait", action="store_true",
                   help="queue without rendering first (render errors then show only in the viewer)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("list", help="list this pane's diagrams, newest first")
    p.add_argument("--pane")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("render", help="render a diagram file to PNG without the viewer")
    p.add_argument("file")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("-f", "--format")
    p.add_argument("--theme", choices=["dark", "light"], default="light")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("export", help="write diagrams as PNG, SVG and source files")
    p.add_argument("--pane")
    p.add_argument("--all", action="store_true", help="every diagram of the pane, not only the newest")
    p.add_argument("-n", "--index", type=int, help="the n-th newest diagram (1 = newest)")
    p.add_argument("--archived", action="store_true", help="include archived diagrams of the pane")
    p.add_argument("-d", "--dir", help="target directory (default: config export_dir, {cwd}/diagrams)")
    p.add_argument("--theme", choices=["light", "dark"], help="default: config export_theme, light")
    for kind in ("png", "svg", "src"):
        p.add_argument(f"--{kind}", action="store_true", help=f"only {kind} (combinable)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("open", help="open the viewer beside a pane")
    p.add_argument("--pane")
    p.set_defaults(func=cmd_open)

    p = sub.add_parser("view", help="run the viewer in this terminal (used by the plugin pane)")
    p.add_argument("--bind", help="source pane to follow")
    p.set_defaults(func=cmd_view)

    p = sub.add_parser("doctor", help="check herdr, graphics, renderers and skills")
    p.add_argument("--wait", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("popup", help=argparse.SUPPRESS)
    p.add_argument("name", choices=["doctor", "install-skill", "uninstall-skill"])
    p.set_defaults(func=cmd_popup)

    p = sub.add_parser("install-skill", help="link the skill and CLI into each harness")
    p.add_argument("--harness", action="append",
                   help="claude, agents (codex/opencode/copilot/gemini), agy, cli; repeatable")
    p.add_argument("--uninstall", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--wait", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_install_skill)

    p = sub.add_parser("install-hook", help="add the automatic Claude Code Stop hook")
    p.add_argument("harness", choices=["claude"])
    p.add_argument("--settings", help="settings.json to edit (default: ~/.claude/settings.json)")
    p.add_argument("--uninstall", action="store_true")
    p.set_defaults(func=cmd_install_hook)

    p = sub.add_parser("hook", help="harness hook entry point")
    p.add_argument("name", choices=["claude-stop"])
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("event", help="herdr plugin event handler")
    p.set_defaults(func=cmd_event)

    p = sub.add_parser("gc", help="delete old diagrams and cached images")
    p.add_argument("--older-than", default="7d")
    p.set_defaults(func=cmd_gc)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
