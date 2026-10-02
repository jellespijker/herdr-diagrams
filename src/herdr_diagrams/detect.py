"""Format detection (docs/spec.md §5)."""

from __future__ import annotations

import re
from pathlib import PurePath

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}

EXTENSIONS = {
    ".mmd": "mermaid",
    ".mermaid": "mermaid",
    ".puml": "plantuml",
    ".plantuml": "plantuml",
    ".pu": "plantuml",
    ".iuml": "plantuml",
    ".dsl": "structurizr",
    ".d2": "d2",
    ".dot": "graphviz",
    ".gv": "graphviz",
}

MERMAID_KEYWORDS = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram",
    "stateDiagram-v2", "erDiagram", "journey", "gantt", "pie", "quadrantChart",
    "requirementDiagram", "gitGraph", "mindmap", "timeline", "sankey-beta",
    "xychart-beta", "block-beta", "packet-beta", "kanban", "architecture-beta",
    "C4Context", "C4Container", "C4Component", "C4Dynamic", "C4Deployment",
    "zenuml", "radar-beta", "treemap-beta",
)

_GRAPHVIZ_START = re.compile(r"^(strict\s+)?(di)?graph\b[^{]*\{", re.IGNORECASE)
_MERMAID_START = re.compile(r"^(" + "|".join(map(re.escape, MERMAID_KEYWORDS)) + r")\b")


class DetectError(ValueError):
    """The format could not be determined."""


def _alias_map(registry: dict) -> dict[str, str]:
    aliases = {}
    for key, entry in registry.items():
        aliases[key] = key
        for alias in entry.get("detect", []):
            aliases.setdefault(alias.lower(), key)
    aliases["image"] = "image"
    return aliases


def resolve_name(name: str, registry: dict) -> str:
    """Map a user-given format or fence info string to a registry key."""
    key = _alias_map(registry).get(name.strip().lower())
    if key is None:
        raise DetectError(f"unknown format {name!r}")
    return key


def from_extension(path: str) -> str | None:
    suffix = PurePath(path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    return EXTENSIONS.get(suffix)


def from_source(source: str) -> str | None:
    lines = [ln.strip() for ln in source.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith(("%%", "//", "#"))]
    if not lines:
        return None
    first = lines[0]
    if first.startswith("---"):  # mermaid front matter
        try:
            end = lines.index("---", 1)
            first = lines[end + 1] if end + 1 < len(lines) else ""
        except ValueError:
            return None
    if first.startswith(("@startuml", "@startmindmap", "@startgantt", "@startwbs",
                         "@startsalt", "@startjson", "@startyaml", "@startditaa")):
        return "plantuml"
    if re.match(r"^workspace\b.*\{?$", first):
        return "structurizr"
    if _GRAPHVIZ_START.match(first):
        return "graphviz"
    if _MERMAID_START.match(first):
        return "mermaid"
    if re.match(r"^[\w.\"' -]+\s*(->|<-|<->|--)\s*[\w.\"' -]+(:.*)?$", first) or \
            re.match(r"^[\w.-]+\s*:\s*\{?$", first) or first.startswith(("direction:", "vars:")):
        return "d2"
    return None


def detect(registry: dict, *, fmt: str | None = None, path: str | None = None,
           source: str | None = None) -> str:
    """Return the registry key (or "image") for an Item. First match wins."""
    if fmt:
        return resolve_name(fmt, registry)
    if path:
        found = from_extension(path)
        if found:
            return found
    if source is None and path:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                source = handle.read(4096)
        except OSError:
            source = None
    if source:
        found = from_source(source)
        if found:
            return found
    raise DetectError("cannot detect format; pass --format")

# Fence info strings that adapters treat as diagrams, mapped to registry keys.
FENCE_NAMES = {
    "mermaid": "mermaid", "mmd": "mermaid",
    "plantuml": "plantuml", "puml": "plantuml", "uml": "plantuml", "c4plantuml": "plantuml",
    "structurizr": "structurizr", "structurizr-dsl": "structurizr",
    "d2": "d2",
    "dot": "graphviz", "graphviz": "graphviz", "gv": "graphviz",
}

# Up to three spaces of indentation, as in CommonMark; code blocks inside list items.
_FENCE = re.compile(
    r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[\w+.-]+)[^\n]*\n"
    r"(?P<body>.*?)^[ ]{0,3}(?P=fence)[ \t]*$",
    re.MULTILINE | re.DOTALL)


def normalize(fmt: str, source: str) -> str:
    """Repair common omissions in agent-written sources before rendering."""
    if fmt == "plantuml" and not re.search(r"^\s*@start\w+", source, re.MULTILINE):
        return f"@startuml\n{source.strip()}\n@enduml\n"
    return source


def fenced_blocks(text: str) -> list[tuple[str, str]]:
    """(format, source) for every fenced diagram block in Markdown `text`."""
    blocks = []
    for match in _FENCE.finditer(text):
        fmt = FENCE_NAMES.get(match.group("info").lower())
        indent = len(match.group("indent"))
        lines = match.group("body").strip("\n").splitlines()
        body = "\n".join(line[indent:] if line[:indent].isspace() else line for line in lines)
        if fmt and body.strip():
            blocks.append((fmt, normalize(fmt, body)))
    return blocks
