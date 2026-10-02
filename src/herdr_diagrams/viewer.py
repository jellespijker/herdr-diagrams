"""Viewer pane (docs/spec.md §8).

Bound to one source pane. Watches that pane's spool, renders Items in a worker
thread and draws the artifacts with the Kitty graphics protocol.
"""

from __future__ import annotations

import os
import queue
import select
import shutil
import signal
import subprocess
import sys
import termios
import textwrap
import threading
import time
import tty
from pathlib import Path

from . import daemon, display, herdr, item, render, sync, viewers

POLL_SPOOL = 0.4
POLL_PANE = 5.0
POLL_SYNC = 1.0
IMAGE_ID_BASE = 4200

KEYS_HELP = ["j/k item", "i list", "e export", "h/l view", "s source", "o open", "+/- zoom",
             "0 fit", "arrows pan", "t sync", "E export all", "y copy path", "r follow", "q quit"]

ARROWS = {b"\x1b[A": "up", b"\x1b[B": "down", b"\x1b[C": "right", b"\x1b[D": "left",
          b"\x1bOA": "up", b"\x1bOB": "down", b"\x1bOC": "right", b"\x1bOD": "left"}


def _style(text: str, code: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"


class Viewer:
    def __init__(self, bind: str | None, out_fd: int = 1, in_fd: int = 0):
        self.bind = bind
        self.out_fd, self.in_fd = out_fd, in_fd
        self.registry = render.load_registry()
        self.theme = render.load_settings()["theme"]
        self.items: list[item.Item] = []
        self.index = -1
        self.follow = True
        self.unseen = 0
        self.view = 0
        self.zoom = 1.0
        self.pan = [0.5, 0.5]
        self.show_source = False
        self.results: dict[str, render.Result] = {}
        self.pending: set[str] = set()
        self.jobs: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.wake_r, self.wake_w = os.pipe()
        self.dirty = True
        self.spool_stamp = None
        self.shown_id: int | None = None
        self.next_id = IMAGE_ID_BASE
        self.flash = ""
        self.flash_until = 0.0
        self.running = True
        self.sync = bool(render.load_settings().get("scroll_sync", True)) and bool(bind)
        self.sync_paused = False  # manual navigation pauses sync until t or r
        self.show_list = False
        self.list_cursor = 0
        self.last_visible = None
        self.sync_target: int | None = None

    # --- terminal -----------------------------------------------------------

    def write(self, data: str) -> None:
        payload = data.encode()
        while payload:
            written = os.write(self.out_fd, payload)
            payload = payload[written:]

    def size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines

    def wake(self) -> None:
        try:
            os.write(self.wake_w, b"x")
        except OSError:
            pass

    # --- spool --------------------------------------------------------------

    def poll_spool(self) -> None:
        directory = item.spool_dir(self.bind)
        try:  # names too: coarse mtimes can hide a second write in the same tick
            stamp = (directory.stat().st_mtime_ns, tuple(sorted(os.listdir(directory))))
        except OSError:
            stamp = None
        if stamp == self.spool_stamp:
            return
        self.spool_stamp = stamp
        fresh = item.list_items(self.bind)
        known = {it.id for it in self.items}
        added = [it for it in fresh if it.id not in known]
        current_id = self.current.id if self.current else None
        self.items = fresh
        if self.follow or self.index < 0:
            self.select(len(self.items) - 1)
        else:
            ids = [it.id for it in self.items]
            self.index = ids.index(current_id) if current_id in ids else len(ids) - 1
            self.unseen += len(added)
        self.dirty = True

    @property
    def current(self) -> item.Item | None:
        if 0 <= self.index < len(self.items):
            return self.items[self.index]
        return None

    def select(self, index: int) -> None:
        if not self.items:
            self.index = -1
            return
        index = max(0, min(index, len(self.items) - 1))
        if index != self.index:
            self.view, self.zoom, self.pan = 0, 1.0, [0.5, 0.5]
        self.index = index
        if index == len(self.items) - 1:
            self.unseen = 0
        self.request(self.items[index])
        if index > 0:
            self.request(self.items[index - 1])
        self.dirty = True

    # --- rendering ------------------------------------------------------------

    def request(self, it: item.Item) -> None:
        with self.lock:
            if it.id in self.results or it.id in self.pending:
                return
            self.pending.add(it.id)
        self.jobs.put(it)

    def worker(self) -> None:
        while self.running:
            try:
                it = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                result = render.render_item(it, registry=self.registry, theme=self.theme)
            except Exception as exc:  # keep the viewer alive on renderer bugs
                result = render.Result(error=f"internal error: {exc}")
            with self.lock:
                self.results[it.id] = result
                self.pending.discard(it.id)
            self.dirty = True
            self.wake()

    # --- drawing --------------------------------------------------------------

    def clear_image(self) -> str:
        if self.shown_id is None:
            return ""
        out = display.delete(self.shown_id)
        self.shown_id = None
        return out

    def header(self, cols: int) -> str:
        it = self.current
        left = f" ◆ diagrams · {self.bind or 'no pane'}"
        if it:
            left += f" · {self.index + 1}/{len(self.items)} · {it.format}"
            result = self.results.get(it.id)
            if result and len(result.artifacts) > 1:
                left += f" · view {self.view + 1}/{len(result.artifacts)}"
            left += f" · {it.display_title}"
        right = f"+{self.unseen} new (r) " if self.unseen else ("following " if self.follow else "pinned ")
        if self.sync:
            right = ("⇅ paused " if self.sync_paused else "⇅ ") + right
        if self.zoom != 1.0:
            right = f"{self.zoom:.1f}x · " + right
        room = max(0, cols - len(right) - 1)
        if len(left) > room:
            left = left[: max(0, room - 1)] + "…"
        line = left + " " * max(1, cols - len(left) - len(right)) + right
        return "\x1b[1;1H\x1b[2K" + _style(line[:cols].ljust(cols), "7")

    def footer(self, cols: int, rows: int) -> str:
        if time.time() < self.flash_until:
            text = self.flash
        else:
            text = ""
            for part in KEYS_HELP:
                if len(text) + len(part) + 2 > cols:
                    break
                text += ("  " if text else "") + part
        return f"\x1b[{rows};1H\x1b[2K" + _style(text[:cols], "2")

    def centered(self, lines: list[str], cols: int, rows: int, code: str = "2") -> str:
        body_rows = rows - 2
        top = 2 + max(0, (body_rows - len(lines)) // 2)
        out = []
        for offset, line in enumerate(lines[:body_rows]):
            line = line[:cols]
            col = max(1, (cols - len(line)) // 2 + 1)
            out.append(f"\x1b[{top + offset};{col}H" + _style(line, code))
        return "".join(out)

    def draw(self) -> None:
        # Clear the flag first: a render finishing mid-draw must trigger another draw.
        self.dirty = False
        cols, rows = self.size()
        out = [self.clear_image(), "\x1b[2J", self.header(cols), self.footer(cols, rows)]
        it = self.current
        if it is None:
            out.append(self.centered([
                "Waiting for diagrams" + (f" from pane {self.bind}" if self.bind else ""),
                "",
                "herdr-diagram show diagram.mmd",
                "echo 'flowchart LR; A-->B' | herdr-diagram show -",
            ], cols, rows))
        elif self.show_list:
            out.append(self.list_view(cols, rows))
        elif self.show_source:
            out.append(self.source_view(it, cols, rows))
        else:
            out.append(self.image_view(it, cols, rows))
        self.write("".join(out))

    def list_view(self, cols: int, rows: int) -> str:
        """All diagrams of the pane, newest first; the cursor row is highlighted."""
        out = ["\x1b[2;2H" + _style("Diagrams  (j/k move · Enter show · e export · i/Esc close)", "1")]
        body = rows - 4
        order = list(range(len(self.items) - 1, -1, -1))
        pos = order.index(self.list_cursor) if self.list_cursor in order else 0
        start = max(0, min(pos - body // 2, len(order) - body))
        for row, index in enumerate(order[start:start + body]):
            it = self.items[index]
            stamp = time.strftime("%H:%M", time.localtime(it.created))
            mark = "▸" if index == self.index else " "
            line = f"{mark} {index + 1:>3}  {stamp}  {it.format:<11} {it.display_title}"[: cols - 3]
            code = "7" if index == self.list_cursor else "0"
            out.append(f"\x1b[{row + 4};2H" + _style(line.ljust(cols - 3), code))
        return "".join(out)

    def source_view(self, it: item.Item, cols: int, rows: int) -> str:
        if it.source is not None:
            text = it.source
        else:
            try:
                text = Path(it.path).read_text(errors="replace") if it.format != "image" else it.path
            except OSError as exc:
                text = str(exc)
        text = item.clean_text(text.expandtabs(4))
        lines = []
        for raw in text.splitlines():
            lines += textwrap.wrap(raw, cols - 2, replace_whitespace=False) or [""]
        out = []
        for offset, line in enumerate(lines[: rows - 2]):
            out.append(f"\x1b[{offset + 2};2H{line}")
        return "".join(out)

    def error_view(self, result: render.Result, cols: int, rows: int) -> str:
        detail = item.clean_text(render.short_detail(result.detail))
        error = item.clean_text(result.error or "render failed")
        lines = [ln for raw in detail.splitlines() for ln in (textwrap.wrap(raw, cols - 4) or [""])]
        out = ["\x1b[3;3H" + _style(f"✗ {error}"[: cols - 4], "1;31")]
        for offset, line in enumerate(lines[: rows - 7]):
            out.append(f"\x1b[{5 + offset};3H" + _style(line, "31"))
        out.append(f"\x1b[{rows - 2};3H" + _style("s: show source", "2"))
        return "".join(out)

    def image_view(self, it: item.Item, cols: int, rows: int) -> str:
        with self.lock:
            result = self.results.get(it.id)
        if result is None:
            self.request(it)
            return self.centered([f"rendering {it.format}…"], cols, rows)
        if not result.ok:
            return self.error_view(result, cols, rows)
        self.view = min(self.view, len(result.artifacts) - 1)
        artifact = result.artifacts[self.view]
        try:
            img_w, img_h = display.png_size(str(artifact))
        except (OSError, ValueError) as exc:
            return self.centered([f"cannot read image: {exc}"], cols, rows, "31")
        box_cols, box_rows = cols - 2, rows - 3
        cell = display.cell_size(self.out_fd)
        out_cols, out_rows, scale = display.fit(img_w, img_h, box_cols, box_rows, cell, self.zoom)
        src = None
        if self.zoom > 1.0:
            src = display.crop(img_w, img_h, out_cols, out_rows, cell, scale, *self.pan)
        # Re-transmit on every draw: re-placing an image whose placement was
        # deleted is not reliable through herdr, and artifacts are small.
        self.next_id = IMAGE_ID_BASE + (self.next_id - IMAGE_ID_BASE + 1) % 1000
        image_id = self.next_id
        out = [display.transmit(image_id, str(artifact))]
        top = 2 + max(0, (rows - 2 - out_rows) // 2)
        left = 1 + max(0, (cols - out_cols) // 2)
        out.append(display.place(image_id, top, left, out_cols, out_rows, src))
        self.shown_id = image_id
        return "".join(out)

    # --- input ----------------------------------------------------------------

    def notify(self, text: str) -> None:
        self.flash, self.flash_until = text, time.time() + 6
        self.dirty = True

    def artifact(self) -> Path | None:
        it = self.current
        result = self.results.get(it.id) if it else None
        if result and result.ok:
            return result.artifacts[min(self.view, len(result.artifacts) - 1)]
        return None

    def open_external(self) -> None:
        target = self.artifact()
        if target is None:
            self.notify("nothing rendered to open")
            return
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen([opener, str(target)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            self.notify(f"opened {target.name}")
        except OSError as exc:
            self.notify(f"{opener}: {exc}")

    def copy_path(self) -> None:
        target = self.artifact()
        if target is None:
            self.notify("nothing rendered to copy")
            return
        for argv in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["pbcopy"]):
            if shutil.which(argv[0]):
                subprocess.run(argv, input=str(target).encode(), check=False)
                self.notify(f"copied {target}")
                return
        self.notify(str(target))

    def handle(self, key: str) -> None:
        result = self.results.get(self.current.id) if self.current else None
        views = len(result.artifacts) if result and result.ok else 1
        if self.show_list:
            self.handle_list(key)
            self.dirty = True
            return
        if key in ("j", "k", "g", "up", "down") and not (key in ("up", "down") and self.zoom > 1):
            self.sync_paused = self.sync  # the user navigates on their own now
        if key == "q":
            self.running = False
        elif key == "j" or (key == "down" and self.zoom == 1.0):
            self.follow = False
            self.select(self.index + 1)
            if self.index == len(self.items) - 1:
                self.follow = True
        elif key == "k" or (key == "up" and self.zoom == 1.0):
            self.follow = False
            self.select(self.index - 1)
        elif key in ("up", "down", "left", "right"):
            step = 0.15 / self.zoom
            axis, sign = {"up": (1, -1), "down": (1, 1), "left": (0, -1), "right": (0, 1)}[key]
            self.pan[axis] = min(1.0, max(0.0, self.pan[axis] + sign * step))
        elif key == "l":
            self.view = min(views - 1, self.view + 1)
        elif key == "h":
            self.view = max(0, self.view - 1)
        elif key in ("+", "="):
            self.zoom = min(8.0, self.zoom * 1.5)
        elif key == "-":
            self.zoom = max(1.0, self.zoom / 1.5)
        elif key == "0":
            self.zoom, self.pan = 1.0, [0.5, 0.5]
        elif key == "s":
            self.show_source = not self.show_source
        elif key == "t":
            if self.sync and self.sync_paused:
                self.sync_paused = False
            else:
                self.sync = not self.sync and bool(self.bind)
            self.last_visible = None
            self.notify("scroll sync on: the viewer follows the chat" if self.sync and not self.sync_paused
                        else "scroll sync off")
        elif key == "i":
            self.show_list = bool(self.items)
            self.list_cursor = max(0, self.index)
        elif key == "e":
            self.export([self.current] if self.current else [])
        elif key == "E":
            self.export(list(self.items))
        elif key == "o":
            self.open_external()
        elif key == "y":
            self.copy_path()
        elif key == "r":
            self.follow, self.sync_paused = True, False
            self.last_visible = None
            self.select(len(self.items) - 1)
        elif key == "g":
            self.follow = False
            self.select(0)
        elif key == "G":
            self.follow = True
            self.select(len(self.items) - 1)
        self.dirty = True

    def handle_list(self, key: str) -> None:
        if key in ("j", "down"):
            self.list_cursor = max(0, self.list_cursor - 1)  # the list shows newest first
        elif key in ("k", "up"):
            self.list_cursor = min(len(self.items) - 1, self.list_cursor + 1)
        elif key in ("\r", "\n", "l", "right"):
            self.show_list = False
            self.sync_paused = self.sync
            self.follow = self.list_cursor == len(self.items) - 1
            self.select(self.list_cursor)
        elif key in ("i", "q", "esc", "h", "left"):
            self.show_list = False
        elif key == "e" and 0 <= self.list_cursor < len(self.items):
            self.export([self.items[self.list_cursor]])

    def export(self, items: list[item.Item]) -> None:
        """Export in the background; report the result in the footer."""
        if not items:
            self.notify("nothing to export")
            return
        self.notify(f"exporting {len(items)} diagram(s)…")

        def run() -> None:
            settings = render.load_settings()
            files, problems, target = [], [], None
            for it in items:
                try:
                    target = render.export_dir(it)
                    written, failed = render.export(it, target, registry=self.registry,
                                                    theme=settings["export_theme"])
                except Exception as exc:  # report, never kill the export thread silently
                    written, failed = [], [f"export failed: {exc}"]
                files += written
                problems += failed
            text = f"exported {len(files)} files to {target}"
            if problems:
                text += f" · {len(problems)} failed: {item.clean_text(problems[0])}"
            self.notify(text)
            self.wake()

        threading.Thread(target=run, daemon=True).start()

    def read_keys(self) -> list[str]:
        try:
            data = os.read(self.in_fd, 4096)
        except OSError:
            return []
        keys, i = [], 0
        while i < len(data):
            if data[i:i + 3] == b"\x1b_G":  # graphics protocol response; ignore
                end = data.find(b"\x1b\\", i)
                i = len(data) if end < 0 else end + 2
                continue
            seq = data[i:i + 3]
            if seq in ARROWS:
                keys.append(ARROWS[seq])
                i += 3
                continue
            if data[i] == 0x1B and i + 1 == len(data):
                keys.append("esc")
                i += 1
                continue
            if data[i] == 0x1B:  # other escape sequence: skip it whole
                j = i + 1
                if j < len(data) and data[j] in b"[O":
                    j += 1
                    while j < len(data) and not 0x40 <= data[j] <= 0x7E:
                        j += 1
                    j += 1
                i = j
                continue
            keys.append(chr(data[i]))
            i += 1
        return keys

    # --- lifecycle --------------------------------------------------------------

    def watcher(self) -> None:
        """Background checks that call herdr, so a slow server never blocks the UI.

        Every POLL_SYNC seconds: find the diagram visible in the chat (scroll sync).
        Every POLL_PANE seconds: stop when herdr says the source pane is gone.
        """
        last_pane_check = 0.0
        while self.running:
            time.sleep(POLL_SYNC)
            if self.sync and not self.sync_paused and self.items:
                visible = herdr.read_visible(self.bind)
                if visible is not None and visible != self.last_visible:
                    self.last_visible = visible
                    target = sync.visible_item(list(self.items), visible)
                    if target is not None:
                        self.sync_target = target
                        self.wake()
            if self.bind and time.time() - last_pane_check > POLL_PANE:
                last_pane_check = time.time()
                if herdr.pane_exists(self.bind) is False:
                    self.running = False
                    self.wake()

    def apply_sync(self) -> None:
        target, self.sync_target = self.sync_target, None
        if target is None or not self.sync or self.sync_paused:
            return
        if 0 <= target < len(self.items) and target != self.index:
            self.follow = target == len(self.items) - 1
            self.select(target)

    def run(self) -> int:
        viewers.register(self.bind, os.environ.get("HERDR_PANE_ID"))
        try:
            daemon.ensure()  # the viewer pane runs outside agent sandboxes
        except OSError:
            pass
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.watcher, daemon=True).start()
        old = termios.tcgetattr(self.in_fd) if os.isatty(self.in_fd) else None
        signal.signal(signal.SIGWINCH, lambda *_: (setattr(self, "dirty", True), self.wake()))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "running", False))
        signal.signal(signal.SIGHUP, lambda *_: setattr(self, "running", False))
        try:
            if old:
                tty.setcbreak(self.in_fd)
            self.write("\x1b[?1049h\x1b[?25l\x1b[2J")
            while self.running:
                self.poll_spool()
                self.apply_sync()
                if self.dirty:
                    self.draw()
                ready, _, _ = select.select([self.in_fd, self.wake_r], [], [], POLL_SPOOL)
                if self.wake_r in ready:
                    os.read(self.wake_r, 1024)
                if self.in_fd in ready:
                    for key in self.read_keys():
                        self.handle(key)
        finally:
            self.running = False
            self.write(display.delete_all() + "\x1b[2J\x1b[?25h\x1b[?1049l")
            if old:
                termios.tcsetattr(self.in_fd, termios.TCSADRAIN, old)
            viewers.unregister(self.bind)
        return 0


def main(bind: str | None) -> int:
    return Viewer(bind).run()
