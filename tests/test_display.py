import base64
import re

import pytest

from conftest import FIXTURES
from herdr_diagrams import display

CELL = display.CellSize(10.0, 20.0, True)


def test_png_size():
    assert display.png_size(str(FIXTURES / "pixel.png")) == (4, 2)
    with pytest.raises(ValueError):
        display.png_size(str(FIXTURES / "sample.dot"))


def test_fit_keeps_aspect_and_box():
    cols, rows, scale = display.fit(2000, 500, 80, 40, CELL)  # wide image, limited by width
    assert cols == 80 and rows == 10 and scale == pytest.approx(0.4)
    cols, rows, _ = display.fit(500, 2000, 80, 40, CELL)  # tall image, limited by height
    assert rows == 40 and cols == 20


def test_fit_caps_upscale_only_when_measured():
    assert display.fit(10, 10, 80, 40, CELL)[2] == 2.0
    guessed = display.CellSize(10.0, 20.0, False)
    assert display.fit(10, 10, 80, 40, guessed)[2] == 80.0


def test_zoom_crops_source_rectangle():
    cols, rows, scale = display.fit(2000, 1000, 80, 40, CELL, zoom=2.0)
    assert (cols, rows) == (80, 40)
    x, y, w, h = display.crop(2000, 1000, cols, rows, CELL, scale, 0.5, 0.5)
    assert (w, h) == (1000, 1000) and (x, y) == (500, 0)  # 800x800 px box at 0.8x
    assert display.crop(2000, 1000, cols, rows, CELL, scale, 0.0, 1.0)[:2] == (0, 0)
    assert display.crop(2000, 1000, cols, rows, CELL, scale, 1.0, 0.0)[:2] == (1000, 0)


def test_transmit_chunks_base64(tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG" + bytes(range(256)) * 40)
    out = display.transmit(7, str(big))
    chunks = re.findall(r"\x1b_G([^;]*);([^\x1b]*)\x1b\\", out)
    assert chunks[0][0] == "a=t,f=100,t=d,i=7,q=2,m=1"
    assert chunks[-1][0] == "m=0"
    assert all(len(payload) <= display.CHUNK for _, payload in chunks)
    assert base64.b64decode("".join(p for _, p in chunks)) == big.read_bytes()


def test_place_and_delete_sequences():
    assert display.place(9, 3, 5, 40, 12) == "\x1b[3;5H\x1b_Ga=p,i=9,p=1,c=40,r=12,C=1,q=2\x1b\\"
    assert display.place(9, 1, 1, 2, 2, (1, 2, 3, 4)).endswith(",x=1,y=2,w=3,h=4\x1b\\")
    assert display.delete(9) == "\x1b_Ga=d,d=I,i=9,q=2\x1b\\"
