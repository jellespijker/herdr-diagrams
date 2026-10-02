"""Kitty graphics protocol output (docs/spec.md §8.3, ADR-0004).

Writes escape sequences to the viewer pane's own stdout. herdr forwards them to
a Kitty-graphics terminal (Ghostty, kitty, WezTerm). This module knows PNG files
and cell boxes only; it knows nothing about formats, Items or renderers.
"""

from __future__ import annotations

import base64
import fcntl
import os
import struct
import termios
from dataclasses import dataclass

CHUNK = 4096
ESC = "\x1b"
ST = "\x1b\\"


def png_size(path: str) -> tuple[int, int]:
    """Pixel width and height from a PNG header."""
    with open(path, "rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"not a PNG file: {path}")
    return struct.unpack(">II", header[16:24])


@dataclass
class CellSize:
    width: float
    height: float
    measured: bool


def cell_size(fd: int) -> CellSize:
    """Cell size in pixels from TIOCGWINSZ; a typical 1:2.1 guess when unknown."""
    try:
        rows, cols, xpix, ypix = struct.unpack(
            "HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
        if xpix and ypix and cols and rows:
            return CellSize(xpix / cols, ypix / rows, True)
    except OSError:
        pass
    return CellSize(10.0, 21.0, False)


def fit(img_w: int, img_h: int, cols: int, rows: int, cell: CellSize,
        zoom: float = 1.0, max_upscale: float = 2.0) -> tuple[int, int, float]:
    """Cells (cols, rows) to place an image in a box, and the effective scale.

    At zoom 1 the image fits the box. Zoom > 1 enlarges it; the caller crops with
    a source rectangle when it no longer fits.
    """
    box_w, box_h = cols * cell.width, rows * cell.height
    scale = min(box_w / img_w, box_h / img_h)
    if cell.measured:
        scale = min(scale, max_upscale)
    scale *= zoom
    out_cols = max(1, min(cols, round(img_w * scale / cell.width)))
    out_rows = max(1, min(rows, round(img_h * scale / cell.height)))
    return out_cols, out_rows, scale


def crop(img_w: int, img_h: int, cols: int, rows: int, cell: CellSize, scale: float,
         pan_x: float, pan_y: float) -> tuple[int, int, int, int]:
    """Source rectangle (x, y, w, h) in image pixels for a zoomed view.

    pan_x and pan_y run from 0 (left/top) to 1 (right/bottom).
    """
    view_w = min(img_w, int(cols * cell.width / scale))
    view_h = min(img_h, int(rows * cell.height / scale))
    x = int((img_w - view_w) * min(max(pan_x, 0.0), 1.0))
    y = int((img_h - view_h) * min(max(pan_y, 0.0), 1.0))
    return x, y, max(1, view_w), max(1, view_h)


def _apc(keys: str, payload: str = "") -> str:
    return f"{ESC}_G{keys};{payload}{ST}" if payload else f"{ESC}_G{keys}{ST}"


def transmit(image_id: int, path: str) -> str:
    """Escape sequence that uploads a PNG (direct, chunked) without placing it."""
    with open(path, "rb") as handle:
        data = base64.standard_b64encode(handle.read()).decode()
    parts = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [""]
    out = []
    for index, part in enumerate(parts):
        more = 1 if index < len(parts) - 1 else 0
        if index == 0:
            out.append(_apc(f"a=t,f=100,t=d,i={image_id},q=2,m={more}", part))
        else:
            out.append(_apc(f"m={more}", part))
    return "".join(out)


def place(image_id: int, row: int, col: int, cols: int, rows: int,
          src: tuple[int, int, int, int] | None = None) -> str:
    """Move the cursor to (row, col), 1-based, and place an uploaded image there."""
    keys = f"a=p,i={image_id},p=1,c={cols},r={rows},C=1,q=2"
    if src:
        x, y, w, h = src
        keys += f",x={x},y={y},w={w},h={h}"
    return f"{ESC}[{row};{col}H" + _apc(keys)


def delete(image_id: int, free: bool = True) -> str:
    """Remove placements of an image; with `free`, also drop its data."""
    return _apc(f"a=d,d={'I' if free else 'i'},i={image_id},q=2")


def delete_all() -> str:
    return _apc("a=d,d=A,q=2")


def probe() -> str:
    """Query that a Kitty-graphics terminal answers with `_Gi=31;OK`."""
    return _apc("i=31,s=1,v=1,a=q,t=d,f=24", "AAAA")


def supported_terminal() -> bool:
    """Heuristic from the environment: is the outer terminal Kitty-graphics capable?"""
    names = " ".join(os.environ.get(k, "") for k in ("TERM", "TERM_PROGRAM", "GHOSTTY_RESOURCES_DIR"))
    return any(n in names.lower() for n in ("ghostty", "kitty", "wezterm", "herdr"))
