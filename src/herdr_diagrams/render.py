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
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import item as item_mod

ROOT = Path(__file__).resolve().parents[2]
BUNDLED_REGISTRY = ROOT / "renderers.toml"
MAX_ARTIFACT_BYTES = 20 << 20
DEFAULT_TIMEOUT = 30
PLACEHOLDERS = ("{in}", "{out}", "{outdir}", "{root}", "{cwd}")


def config_dir() -> Path:
    if override := os.environ.get("HERDR_PLUGIN_CONFIG_DIR"):
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "herdr" / "plugins" / "config" / "herdr-diagrams"


def load_settings() -> dict:
    """User settings from <config dir>/config.toml. Keys: theme."""
    path = config_dir() / "config.toml"
    settings = {"theme": "dark"}
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


def _argv_for(entry: dict, theme: str) -> list[str]:
    return list(entry["argv"]) + list(entry.get("themes", {}).get(theme, []))


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
    return {}


def _run(entry: dict, theme: str, source: bytes, workdir: Path, cwd: str | None) -> list[Path]:
    """Run one renderer step. Returns produced files (one, or many for fanout)."""
    in_file = workdir / f"input.{entry.get('in_ext', 'txt')}"
    out_file = workdir / f"output.{entry.get('out', 'png')}"
    outdir = workdir / "out"
    outdir.mkdir(exist_ok=True)
    in_file.write_bytes(source)
    values = {"{in}": str(in_file), "{out}": str(out_file), "{outdir}": str(outdir),
              "{root}": str(ROOT), "{cwd}": cwd or str(workdir)}
    argv = []
    for arg in _argv_for(entry, theme):
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
    try:
        proc = subprocess.run(
            argv, input=source if stdio else None, capture_output=True,
            cwd=str(workdir), env=env, timeout=entry.get("timeout", DEFAULT_TIMEOUT),
        )
    except subprocess.TimeoutExpired:
        raise RenderError(f"{Path(argv[0]).name} timed out") from None
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
    for argv in candidates:
        if subprocess.run(argv, capture_output=True, timeout=60).returncode == 0 and dest.is_file():
            return
    raise RenderError(f"cannot convert {file.suffix} to PNG",
                      "Install ImageMagick, librsvg or ffmpeg, or press o to open externally.")


def _store(produced: list[Path], key: str) -> list[Path]:
    cache = item_mod.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for index, file in enumerate(produced):
        dest = cache / (f"{key}.png" if len(produced) == 1 else f"{key}-{index:02d}.png")
        tmp = dest.with_suffix(".tmp.png")
        _png_from(file, tmp)
        if tmp.stat().st_size > MAX_ARTIFACT_BYTES:
            tmp.unlink()
            raise RenderError("rendered image exceeds 20 MiB")
        os.replace(tmp, dest)
        artifacts.append(dest)
    (cache / f"{key}.list").write_text("\n".join(p.name for p in artifacts))
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
                  theme: str | None = None, cwd: str | None = None) -> Result:
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
    key = cache_key(fmt, chain, theme, data)
    if hit := _cached(key):
        return Result(artifacts=hit, cached=True)
    try:
        with tempfile.TemporaryDirectory(prefix="render-", dir=_scratch()) as tmp:
            produced = _run(entry, theme, data, _mk(tmp, "s0"), cwd)
            if len(chain) > 1:
                finals = []
                for index, intermediate in enumerate(produced):
                    finals += _run(chain[1], theme, intermediate.read_bytes(),
                                   _mk(tmp, f"s1-{index}"), cwd)
                produced = finals
            return Result(artifacts=_store(produced, key))
    except RenderError as exc:
        return Result(error=str(exc), detail=exc.detail)
    except OSError as exc:
        return Result(error=f"render failed: {exc}")


def render_item(it: item_mod.Item, *, registry: dict | None = None,
                theme: str | None = None) -> Result:
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
    if it.source is not None:
        data = it.source.encode()
    else:
        try:
            data = Path(it.path).read_bytes()
        except OSError as exc:
            return Result(error=f"cannot read source: {exc}")
    return render_source(it.format, data, registry=registry, theme=theme,
                         cwd=it.origin.get("cwd"))


def _scratch() -> str:
    path = item_mod.cache_dir() / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _mk(tmp: str, name: str) -> Path:
    path = Path(tmp) / name
    path.mkdir()
    return path
