"""Zoom keeps the image point under the pointer in place."""

from herdr_diagrams import display, viewer


def make_viewer(monkeypatch):
    monkeypatch.setattr(display, "cell_size", lambda fd: display.CellSize(10.0, 20.0, True))
    v = viewer.Viewer("w1:p1")
    v.geom = {"artifact": None, "id": 1, "img": (4000, 1000), "cols": 100, "rows": 40,
              "item": "x", "view": 0}
    return v


def point_under(v, column, row):
    lay = v.layout()
    sx, sy, sw, sh = lay["src"]
    fx = (column - lay["left"] + 0.5) / lay["cols"]
    fy = (row - lay["top"] + 0.5) / lay["rows"]
    return sx + fx * sw, sy + fy * sh


def test_wheel_zoom_keeps_anchor(monkeypatch):
    v = make_viewer(monkeypatch)
    column, row = 70, 20
    before = point_under(v, column, row)
    v.zoom_at(column, row, 1.25)
    v.zoom_at(column, row, 1.25)
    after = point_under(v, column, row)
    assert v.zoom > 1.5
    assert abs(after[0] - before[0]) < 40 and abs(after[1] - before[1]) < 40  # within ~1 cell


def test_zoom_out_to_fit_resets_pan(monkeypatch):
    v = make_viewer(monkeypatch)
    v.zoom_at(10, 10, 2.0)
    v.zoom_at(10, 10, 0.1)
    assert v.zoom == 1.0 and v.pan == [0.5, 0.5]


def test_drag_moves_view_opposite_to_pointer(monkeypatch):
    v = make_viewer(monkeypatch)
    v.zoom = 3.0
    start = list(v.pan)
    v.pan_by_cells(-10, 0, start)  # pointer moved left: view moves right
    assert v.pan[0] > start[0] and v.pan[1] == start[1]
