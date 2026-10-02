"""PTY test: run the real viewer in a pseudo-terminal and check what it draws."""

import fcntl
import os
import pty
import select
import signal
import struct
import termios
import time

from conftest import CLI, FIXTURES
from herdr_diagrams import item


def read_until(fd, needle: bytes, timeout: float = 30.0) -> bytes:
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            buf += chunk
            if needle in buf:
                return buf
    raise AssertionError(f"{needle!r} not seen; got tail {buf[-400:]!r}")


def spawn_viewer(bind: str, images: str = "on"):
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["HERDR_DIAGRAMS_IMAGES"] = images
        os.execv(str(CLI), [str(CLI), "view", "--bind", bind])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 1000, 630))
    return pid, fd


def stop(pid, fd):
    """Quit with q; fall back to SIGTERM (handled: cleans up), then SIGKILL. Always reap."""
    try:
        os.write(fd, b"q")
        for sig in (None, signal.SIGTERM, signal.SIGKILL):
            if sig:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    return
            for _ in range(100):
                done, _ = os.waitpid(pid, os.WNOHANG)
                if done:
                    return
                time.sleep(0.1)
    finally:
        os.close(fd)


def test_viewer_draws_items_and_navigates():
    pid, fd = spawn_viewer("w9:p1")
    try:
        read_until(fd, b"Waiting for diagrams")
        item.write(item.new("image", path=str(FIXTURES / "pixel.png"), title="first", pane="w9:p1"))
        out = read_until(fd, b"a=p,")
        assert b"1/1" in out and b"first" in out
        assert b"\x1b_Ga=t,f=100,t=d," in out
        item.write(item.new("image", path=str(FIXTURES / "pixel.png"), title="second", pane="w9:p1"))
        read_until(fd, b"second")
        os.write(fd, b"k")
        out = read_until(fd, b"pinned")
        assert b"1/2" in out
        item.write(item.new("image", path=str(FIXTURES / "pixel.png"), title="third", pane="w9:p1"))
        read_until(fd, b"+1 new")
        os.write(fd, b"r")
        read_until(fd, b"3/3")
        os.write(fd, b"s")
        read_until(fd, str(FIXTURES / "pixel.png").encode())
    finally:
        stop(pid, fd)


def test_viewer_shows_render_errors():
    pid, fd = spawn_viewer("w9:p2")
    try:
        read_until(fd, b"Waiting for diagrams")
        item.write(item.new("image", path="/nonexistent/missing.png", pane="w9:p2"))
        read_until(fd, b"cannot read image")
    finally:
        stop(pid, fd)


def test_viewer_registers_and_unregisters():
    from herdr_diagrams import viewers

    pid, fd = spawn_viewer("w9:p3")
    read_until(fd, b"Waiting for diagrams")
    assert viewers.lookup("w9:p3")["pid"] == pid
    stop(pid, fd)
    assert viewers.lookup("w9:p3") is None


def test_viewer_list_overlay_and_export(tmp_path):
    pid, fd = spawn_viewer("w9:p4")
    try:
        read_until(fd, b"Waiting for diagrams")
        for name in ("alpha", "beta", "gamma"):
            item.write(item.new("image", path=str(FIXTURES / "pixel.png"), title=name, pane="w9:p4",
                                cwd=str(tmp_path)))
        read_until(fd, b"3/3")
        os.write(fd, b"i")
        out = read_until(fd, b"Enter show")
        assert b"alpha" in out and b"gamma" in out
        os.write(fd, b"jj\r")
        read_until(fd, b"1/3")
        os.write(fd, b"e")
        read_until(fd, b"exported")
        assert (tmp_path / "diagrams" / "alpha.png").is_file()
    finally:
        stop(pid, fd)


def test_viewer_explains_when_the_terminal_cannot_show_images():
    pid, fd = spawn_viewer("w9:p5", images="off")
    try:
        read_until(fd, b"Diagrams will open with o")
        item.write(item.new("image", path=str(FIXTURES / "pixel.png"), title="pic", pane="w9:p5"))
        out = read_until(fd, b"open the diagram in your image viewer")
        assert b"a=p," not in out  # nothing is drawn
    finally:
        stop(pid, fd)
