"""Scroll sync: find which diagram the visible part of the chat is about.

The viewer reads the text visible in its source pane and looks for anchors of each
Item: the `[diagram: <title>]` marker the skill asks agents to write next to a diagram,
or distinctive source lines when the diagram itself is printed in the chat (the Claude
Stop hook case). The bottom-most anchored Item wins.
"""

from __future__ import annotations

import re

from . import item

MARKER = "[diagram: {title}]"
_KEYWORD_LINE = re.compile(
    r"^(@start\w+|@end\w+|```.*|~~~.*|flowchart\b.*|graph\b.*|sequenceDiagram|classDiagram|"
    r"stateDiagram(-v2)?|erDiagram|gantt|mindmap|timeline|journey|pie|direction:.*|[{}()\[\]]+|end)$",
    re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def marker(title: str) -> str:
    return MARKER.format(title=title)


def anchors(it: item.Item) -> tuple[list[str], list[str]]:
    """(strong anchors, source-line anchors), normalized."""
    strong = []
    if it.title:
        strong.append(_norm(marker(it.title)))
    lines = []
    for raw in (it.source or "").splitlines():
        line = raw.strip()
        if len(line) < 6 or _KEYWORD_LINE.match(line):
            continue
        lines.append(_norm(line)[:40])
        if len(lines) == 6:
            break
    return strong, lines


def locate(it: item.Item, visible_lines: list[str]) -> int | None:
    """Bottom-most visible line index that anchors `it`, or None."""
    strong, lines = anchors(it)
    hits_strong = [i for i, text in enumerate(visible_lines) if any(a in text for a in strong)]
    if hits_strong:
        return hits_strong[-1]
    if not lines:
        return None
    hits = [i for i, text in enumerate(visible_lines) if any(a in text for a in lines)]
    matched = {a for a in lines for text in visible_lines if a in text}
    needed = min(2, len(lines))
    return hits[-1] if len(matched) >= needed else None


def visible_item(items: list[item.Item], visible_text: str) -> int | None:
    """Index into `items` of the diagram the visible chat is about, or None."""
    visible_lines = [_norm(line) for line in visible_text.splitlines()]
    best, best_pos = None, -1
    for index, it in enumerate(items):
        pos = locate(it, visible_lines)
        if pos is not None and pos >= best_pos:
            best, best_pos = index, pos
    return best
