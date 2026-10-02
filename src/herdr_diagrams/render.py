"""Renderer registry, argv expansion, cache, fanout/then (docs/spec.md §6, ADR-0003).

A renderer is data: an argv template plus a few conventions declared in
renderers.toml. This module turns an Item into one or more PNG artifacts in the
content-addressed cache. It knows nothing about harnesses, panes or displays.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import item as item_mod

ROOT = Path(__file__).resolve().parents[2]
BUNDLED_REGISTRY = ROOT / "renderers.toml"
MAX_ARTIFACT_BYTES = 20 << 20
DEFAULT_TIMEOUT = 30
PLACEHOLDERS = ("{in}", "{out}", "{outdir}", "{root}", "{cwd}")


_CONFIG_DIR: Path | None = None


def config_dir() -> Path:
    """The plugin config dir: from herdr's env, else asked from herdr, else the XDG default."""
    global _CONFIG_DIR
    if override := os.environ.get("HERDR_PLUGIN_CONFIG_DIR"):
        return Path(override)
    if _CONFIG_DIR is None:
        exe = os.environ.get("HERDR_BIN_PATH") or shutil.which("herdr")
        if exe and os.access(exe, os.X_OK):
            try:
                proc = subprocess.run([exe, "plugin", "config-dir", "herdr-diagrams"],
                                      capture_output=True, text=True, timeout=5)
                if proc.returncode == 0 and proc.stdout.strip().startswith(os.sep):
                    _CONFIG_DIR = Path(proc.stdout.strip())
            except (OSError, subprocess.TimeoutExpired):
                pass
        if _CONFIG_DIR is None:
            base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
            _CONFIG_DIR = Path(base) / "herdr" / "plugins" / "config" / "herdr-diagrams"
    return _CONFIG_DIR


def load_settings() -> dict:
    """User settings from <config dir>/config.toml. Keys: theme."""
    path = config_dir() / "config.toml"
    settings = {"theme": "dark", "scroll_sync": True, "export_dir": "{cwd}/diagrams",
                "export_theme": "light"}
    if path.is_file():
        try:
            settings.update(tomllib.loads(path.read_text()))
        except (OSError, tomllib.TOMLDecodeError):
            pass
    if env_theme := os.environ.get("HERDR_DIAGRAMS_THEME"):
        settings["theme"] = env_theme
    return settings


def load_registry() -> dict:
    """Bundled registry overlaid key by key with the user's renderers.toml."""
    registry = tomllib.loads(BUNDLED_REGISTRY.read_text())
    user = config_dir() / "renderers.toml"
    if user.is_file():
        registry.update(tomllib.loads(user.read_text()))
    return registry


class RenderError(RuntimeError):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


@dataclass
class Result:
    artifacts: list[Path] = field(default_factory=list)
    error: str | None = None
    detail: str = ""
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.artifacts)


def short_detail(detail: str, limit: int = 12) -> str:
    """Renderer stderr without stack traces, for people and agents."""
    keep = []
    for line in (detail or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(("at ", "(file://", "file://")) or "node_modules" in stripped:
            continue
        keep.append(line.rstrip())
    while keep and not keep[-1].strip():
        keep.pop()
    return "\n".join(keep[:limit])


def program_available(argv0: str) -> bool:
    argv0 = argv0.replace("{root}", str(ROOT))
    if os.sep in argv0:
        return os.access(argv0, os.X_OK)
    return shutil.which(argv0) is not None


def availability(registry: dict) -> dict[str, tuple[bool, str]]:
    """Per renderer key: (available, program)."""
    result = {}
    for key, entry in registry.items():
        program = entry["argv"][0]
        result[key] = (program_available(program), program.replace("{root}", str(ROOT)))
    return result


def _argv_for(entry: dict, theme: str, svg: bool = False) -> list[str]:
    base = entry.get("svg_argv") if svg and entry.get("svg_argv") else entry["argv"]
    return list(base) + list(entry.get("themes", {}).get(theme, []))


def supports_svg(entry: dict) -> bool:
    return bool(entry.get("svg_argv")) or bool(entry.get("fanout"))


def _referenced_files(entry, theme: str) -> list[Path]:
    """Plugin files named in a renderer's argv, e.g. a theme config."""
    entries = entry if isinstance(entry, list) else [entry] if entry else []
    files = []
    for one in entries:
        for arg in _argv_for(one, theme):
            if arg.startswith("{root}/"):
                path = Path(arg.replace("{root}", str(ROOT)))
                if path.is_file() and path.suffix in (".json", ".toml", ".css", ".puml", ".iuml"):
                    files.append(path)
    return files


def cache_key(fmt: str, entry, theme: str, data: bytes) -> str:
    """Content address of an artifact: format, renderer entry, theme, config files, source."""
    digest = hashlib.sha256()
    digest.update(json.dumps({"format": fmt, "entry": entry, "theme": theme},
                             sort_keys=True).encode())
    for path in _referenced_files(entry, theme):
        digest.update(b"\0" + path.read_bytes())
    digest.update(b"\0")
    digest.update(data)
    return digest.hexdigest()


def _chromium_env() -> dict:
    """Point puppeteer at a system browser when its own download is missing."""
    if os.environ.get("PUPPETEER_EXECUTABLE_PATH"):
        return {}
    cache = Path(os.environ.get("PUPPETEER_CACHE_DIR") or Path.home() / ".cache" / "puppeteer")
    if any(cache.glob("chrome-headless-shell/*")) or any(cache.glob("chrome/*")):
        return {}
    for name in ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome"):
        if found := shutil.which(name):
            return {"PUPPETEER_EXECUTABLE_PATH": found}
    for app in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium"):
        if os.access(app, os.X_OK):
            return {"PUPPETEER_EXECUTABLE_PATH": app}
    return {}


def _exec(argv: list[str], *, stdin: bytes | None, cwd: str | None, env: dict | None,
          timeout: float) -> subprocess.CompletedProcess:
    """Run argv in its own process group; on timeout kill the whole group.

    Renderers start helpers (mmdc starts Chromium, wrapper scripts start Java) that a
    plain timeout would leave running.
    """
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
                            start_new_session=True)
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if hasattr(os, "killpg"):
                os.killpg(proc.pid, signal.SIGKILL)
            else:  # Windows: no process groups via setsid
                proc.kill()
        except OSError:
            pass
        proc.communicate()
        raise RenderError(f"{Path(argv[0]).name} timed out after {timeout:g} s") from None
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def _run(entry: dict, theme: str, source: bytes, workdir: Path, cwd: str | None,
         svg: bool = False) -> list[Path]:
    """Run one renderer step. Returns produced files (one, or many for fanout)."""
    in_file = workdir / f"input.{entry.get('in_ext', 'txt')}"
    out_file = workdir / f"output.{'svg' if svg else entry.get('out', 'png')}"
    outdir = workdir / "out"
    outdir.mkdir(exist_ok=True)
    in_file.write_bytes(source)
    values = {"{in}": str(in_file), "{out}": str(out_file), "{outdir}": str(outdir),
              "{root}": str(ROOT), "{cwd}": cwd or str(workdir)}
    argv = []
    for arg in _argv_for(entry, theme, svg and not entry.get("fanout")):
        for placeholder in PLACEHOLDERS:
            arg = arg.replace(placeholder, values[placeholder])
        argv.append(arg)
    if not program_available(argv[0]):
        raise RenderError(f"renderer not installed: {argv[0]}",
                          "Install it, or override the entry in renderers.toml. "
                          "Run `herdr-diagram doctor` for details.")
    env = dict(os.environ)
    env.update({k: str(v) for k, v in entry.get("env", {}).items()})
    env.update(_chromium_env())
    stdio = bool(entry.get("stdio"))
    proc = _exec(argv, stdin=source if stdio else None, cwd=str(workdir), env=env,
                 timeout=entry.get("timeout", DEFAULT_TIMEOUT))
    stderr = proc.stderr.decode(errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-20:])
        raise RenderError(f"{Path(argv[0]).name} exited with {proc.returncode}", tail)
    if stdio:
        out_file.write_bytes(proc.stdout)
    if entry.get("fanout"):
        produced = sorted(Path(p) for p in glob.glob(str(outdir / "**" / entry["fanout"]),
                                                      recursive=True))
        if not produced:
            raise RenderError(f"{Path(argv[0]).name} produced no {entry['fanout']} files",
                              stderr.strip()[-2000:])
        return produced
    if not out_file.is_file() or out_file.stat().st_size == 0:
        raise RenderError(f"{Path(argv[0]).name} produced no output",
                          stderr.strip()[-2000:])
    return [out_file]


def _png_from(file: Path, dest: Path) -> None:
    """Convert any image file to PNG at `dest`."""
    with open(file, "rb") as handle:
        if handle.read(8) == b"\x89PNG\r\n\x1a\n":
            shutil.copyfile(file, dest)
            return
    candidates = []
    if file.suffix.lower() == ".svg" and shutil.which("rsvg-convert"):
        candidates.append(["rsvg-convert", "-z", "2", "-o", str(dest), str(file)])
    if shutil.which("magick"):
        candidates.append(["magick", "-density", "192", f"{file}[0]", str(dest)])
    if shutil.which("ffmpeg"):
        candidates.append(["ffmpeg", "-loglevel", "error", "-y", "-i", str(file),
                           "-frames:v", "1", str(dest)])
    if shutil.which("sips"):  # macOS built-in
        candidates.append(["sips", "-s", "format", "png", str(file), "--out", str(dest)])
    for argv in candidates:
        if _exec(argv, stdin=None, cwd=None, env=None, timeout=60).returncode == 0 and dest.is_file():
            return
    raise RenderError(f"cannot convert {file.suffix} to PNG",
                      "Install ImageMagick, librsvg or ffmpeg, or press o to open externally.")


def _store(produced: list[Path], key: str, ext: str = "png") -> list[Path]:
    item_mod.prepare_home()
    cache = item_mod.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for index, file in enumerate(produced):
        dest = cache / (f"{key}.{ext}" if len(produced) == 1 else f"{key}-{index:02d}.{ext}")
        tmp = dest.with_name(f".{dest.stem}.{os.getpid()}.{threading.get_ident()}.tmp.{ext}")
        if ext == "png":
            _png_from(file, tmp)
        else:
            shutil.copyfile(file, tmp)
        if tmp.stat().st_size > MAX_ARTIFACT_BYTES:
            tmp.unlink()
            raise RenderError("rendered image exceeds 20 MiB")
        os.replace(tmp, dest)
        artifacts.append(dest)
    listing = cache / f".{key}.{os.getpid()}.{threading.get_ident()}.list.tmp"
    listing.write_text("\n".join(p.name for p in artifacts))
    os.replace(listing, cache / f"{key}.list")
    return artifacts


def _cached(key: str) -> list[Path] | None:
    listing = item_mod.cache_dir() / f"{key}.list"
    if not listing.is_file():
        return None
    files = [item_mod.cache_dir() / name for name in listing.read_text().split()]
    if files and all(f.is_file() for f in files):
        for f in files + [listing]:
            os.utime(f)
        return files
    return None


def render_source(fmt: str, data: bytes, *, registry: dict | None = None,
                  theme: str | None = None, cwd: str | None = None, svg: bool = False) -> Result:
    """Render diagram source `data` of registry key `fmt` to cached PNG artifacts."""
    registry = registry if registry is not None else load_registry()
    theme = theme or load_settings()["theme"]
    if fmt not in registry:
        return Result(error=f"no renderer for format {fmt!r}")
    entry = registry[fmt]
    chain = [entry]
    if then := entry.get("then"):
        if then not in registry:
            return Result(error=f"renderer {fmt!r} chains to unknown {then!r}")
        chain.append(registry[then])
    text = data.decode(errors="replace")
    for pattern in entry.get("reject", []):
        if match := re.search(pattern, text, re.MULTILINE):
            return Result(error=f"refused: {fmt} source uses {match.group(0).strip()!r}",
                          detail="This construct can run code or reach the network, so "
                                 "herdr-diagrams does not render it. Change the "
                                 "reject list in renderers.toml if you trust the source.")
    if svg and not supports_svg(chain[-1]):
        return Result(error=f"{fmt} has no SVG output configured (svg_argv in renderers.toml)")
    key = cache_key(fmt + (":svg" if svg else ""), chain, theme, data)
    if hit := _cached(key):
        return Result(artifacts=hit, cached=True)
    try:
        with tempfile.TemporaryDirectory(prefix="render-", dir=_scratch()) as tmp:
            produced = _run(entry, theme, data, _mk(tmp, "s0"), cwd, svg=svg and len(chain) == 1)
            if len(chain) > 1:
                finals = []
                for index, intermediate in enumerate(produced):
                    finals += _run(chain[1], theme, intermediate.read_bytes(),
                                   _mk(tmp, f"s1-{index}"), cwd, svg=svg)
                produced = finals
            return Result(artifacts=_store(produced, key, "svg" if svg else "png"))
    except RenderError as exc:
        return Result(error=str(exc), detail=exc.detail)
    except OSError as exc:
        return Result(error=f"render failed: {exc}")


def render_item(it: item_mod.Item, *, registry: dict | None = None,
                theme: str | None = None, svg: bool = False) -> Result:
    if it.format == "image":
        if not it.path:
            return Result(error="image items need a path")
        try:
            data = Path(it.path).read_bytes()
        except OSError as exc:
            return Result(error=f"cannot read image: {exc}")
        key = cache_key("image", None, "", data)
        if hit := _cached(key):
            return Result(artifacts=hit, cached=True)
        try:
            return Result(artifacts=_store([Path(it.path)], key))
        except RenderError as exc:
            return Result(error=str(exc), detail=exc.detail)
        except OSError as exc:
            return Result(error=f"cannot store image: {exc}")
    if it.source is not None:
        data = it.source.encode()
    else:
        try:
            data = Path(it.path).read_bytes()
        except OSError as exc:
            return Result(error=f"cannot read source: {exc}")
    return render_source(it.format, data, registry=registry, theme=theme,
                         cwd=it.origin.get("cwd"), svg=svg)


def _scratch() -> str:
    item_mod.prepare_home()
    path = item_mod.cache_dir() / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _mk(tmp: str, name: str) -> Path:
    path = Path(tmp) / name
    path.mkdir()
    return path


SOURCE_EXT = {"mermaid": "mmd", "plantuml": "puml", "structurizr": "dsl", "d2": "d2",
              "graphviz": "dot"}


def slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    return text[:60] or "diagram"


def _unique(path: Path, content: bytes) -> Path:
    """`path`, or `path` with -2, -3 ... when a different file already has that name."""
    candidate, n = path, 1
    while candidate.exists() and candidate.read_bytes() != content:
        n += 1
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
    return candidate


def export(it: item_mod.Item, directory: Path, *, registry: dict | None = None,
           theme: str = "light",
           kinds: tuple[str, ...] = ("png", "svg", "src")) -> tuple[list[Path], list[str]]:
    """Write an Item as PNG, SVG and source files. Returns (written files, problems)."""
    registry = registry if registry is not None else load_registry()
    directory.mkdir(parents=True, exist_ok=True)
    stem = slug(it.display_title)
    outputs: list[tuple[Path, bytes]] = []
    problems = []
    if "src" in kinds:
        if it.format == "image" and it.path:
            data = Path(it.path).read_bytes() if Path(it.path).is_file() else b""
            if data:
                outputs.append((directory / f"{stem}{Path(it.path).suffix.lower()}", data))
        elif it.source is not None:
            outputs.append((directory / f"{stem}.{SOURCE_EXT.get(it.format, 'txt')}", it.source.encode()))
    for kind in ("png", "svg"):
        if kind not in kinds or it.format == "image":
            continue
        result = render_item(it, registry=registry, theme=theme, svg=kind == "svg")
        if not result.ok:
            problems.append(f"{kind}: {result.error}")
            continue
        many = len(result.artifacts) > 1
        for index, artifact in enumerate(result.artifacts):
            name = f"{stem}-{index + 1}.{kind}" if many else f"{stem}.{kind}"
            outputs.append((directory / name, artifact.read_bytes()))
    if it.format == "image" and "png" in kinds:
        result = render_item(it, registry=registry)
        if result.ok:
            outputs.append((directory / f"{stem}.png", result.artifacts[0].read_bytes()))
    written = []
    for path, content in outputs:
        target = _unique(path, content)
        target.write_bytes(content)
        written.append(target)
    return written, problems


def export_dir(it: item_mod.Item, override: str | None = None) -> Path:
    """Where `export` writes: --dir, else config `export_dir` with {cwd} and {home} filled in."""
    template = override or load_settings()["export_dir"]
    cwd = it.origin.get("cwd") or os.getcwd()
    return Path(template.replace("{cwd}", cwd).replace("{home}", str(Path.home()))).expanduser()
