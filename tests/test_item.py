import json

import jsonschema
import pytest

from conftest import ROOT
from herdr_diagrams import item

SCHEMA = json.loads((ROOT / "schema" / "item.v1.json").read_text())


def test_pane_key():
    assert item.pane_key("w1:p3") == "w1_p3"
    assert item.pane_key(None) == item.NOPANE
    assert item.pane_key("..") == item.NOPANE
    assert item.pane_key("a/b") == "a_b"


def test_write_read_roundtrip():
    it = item.new("mermaid", source="flowchart LR\n A-->B", title="t", pane="w1:p1", harness="claude")
    path = item.write(it)
    assert path.parent.name == "w1_p1" and path.parent.parent.name == "default"
    assert not list(path.parent.glob("*.tmp"))
    back = item.read(path)
    assert back.to_json() == it.to_json()
    jsonschema.validate(json.loads(path.read_text()), SCHEMA)


def test_list_items_oldest_first_and_skips_garbage():
    first = item.write(item.new("d2", source="a -> b", pane="w1:p1"))
    second = item.write(item.new("d2", source="b -> c", pane="w1:p1"))
    (first.parent / "junk.json").write_text("{not json")
    (first.parent / "old.json").write_text(json.dumps({"v": 99, "id": "x"}))
    ids = [it.id for it in item.list_items("w1:p1")]
    assert ids == [first.stem, second.stem]


@pytest.mark.parametrize("bad", [
    {"v": 2, "id": "a", "format": "mermaid", "source": "x", "created": 1},
    {"v": 1, "id": "", "format": "mermaid", "source": "x", "created": 1},
    {"v": 1, "id": "a", "format": "mermaid", "created": 1},
    {"v": 1, "id": "a", "format": "mermaid", "source": "x", "path": "/x", "created": 1},
    {"v": 1, "id": "a", "format": "image", "path": "relative.png", "created": 1},
    {"v": 1, "id": "a", "format": "mermaid", "source": "x", "created": True},
    {"v": 1, "id": "a", "format": "mermaid", "source": "x" * (item.MAX_SOURCE_BYTES + 1), "created": 1},
])
def test_validate_rejects(bad):
    with pytest.raises(item.ItemError):
        item.validate(bad)


def test_schema_and_validator_agree_on_valid_items():
    for data in (item.new("image", path="/tmp/x.png").to_json(),
                 item.new("plantuml", source="@startuml\n@enduml", cwd="/").to_json()):
        item.validate(data)
        jsonschema.validate(data, SCHEMA)


@pytest.mark.parametrize("source, title", [
    ("@startuml\ntitle Rendering an Item\nA->B\n@enduml", "Rendering an Item"),
    ("---\ntitle: Auth flow\n---\nflowchart LR\nA-->B", "Auth flow"),
    ('workspace "Shop" {\n}', "Shop"),
    ("%% comment\nflowchart LR\nA-->B", "flowchart LR"),
    ("digraph pipeline {\n a -> b\n}", "pipeline"),
    ("direction: right\nagent -> pane", "agent -> pane"),
])
def test_display_title(source, title):
    assert item.Item(format="x", source=source).display_title == title


def test_detect_harness_from_env():
    assert item.detect_harness({"CLAUDECODE": "1"}) == "claude"
    assert item.detect_harness({}) == "unknown"


def test_herdr_session_name():
    assert item.herdr_session({}) == "default"
    assert item.herdr_session({"HERDR_SESSION": "alpha"}) == "alpha"
    socket = "/h/.config/herdr/sessions/demo/herdr.sock"
    assert item.herdr_session({"HERDR_SOCKET_PATH": socket}) == "demo"
    assert item.herdr_session({"HERDR_SOCKET_PATH": "/h/.config/herdr/herdr.sock"}) == "default"
    assert item.herdr_session({"HERDR_SESSION": "../x"}) == ".._x"


def test_same_pane_id_in_two_sessions_does_not_collide(monkeypatch):
    monkeypatch.setenv("HERDR_SESSION", "alpha")
    item.write(item.new("d2", source="a -> b", pane="w1:p1"))
    monkeypatch.setenv("HERDR_SESSION", "beta")
    assert item.list_items("w1:p1") == []
    item.write(item.new("d2", source="c -> d", pane="w1:p1"))
    assert [it.source for it in item.list_items("w1:p1")] == ["c -> d"]
    assert item.list_items("w1:p1")[0].origin["herdr_session"] == "beta"


def test_clean_text_strips_terminal_controls():
    nasty = "Title\x1b]52;c;ZXZpbA==\x07 and \x1b_Ga=d\x1b\\ \x9b2J ok\tx\ny"
    cleaned = item.clean_text(nasty)
    assert "\x1b" not in cleaned and "\x07" not in cleaned and "\x9b" not in cleaned
    assert cleaned.endswith("ok\tx\ny")
    assert "\x1b" not in item.Item(format="d2", source="x", title=nasty).display_title


def test_archive_other_sessions_keeps_current_and_sessionless():
    old = item.write(item.new("d2", source="a -> b", pane="w1:p1", session="old"))
    cur = item.write(item.new("d2", source="b -> c", pane="w1:p1", session="new"))
    shell = item.write(item.new("d2", source="c -> d", pane="w1:p1"))
    target = item.archive_other_sessions("w1:p1", "new")
    assert [it.file.name for it in item.list_items("w1:p1")] == [cur.name, shell.name]
    assert (target / old.name).is_file() and "previous-session" in target.name


def test_archive_pane_and_move_pane():
    first = item.write(item.new("d2", source="a -> b", pane="w1:p1"))
    item.move_pane("w1:p1", "w3:p2")
    assert item.list_items("w1:p1") == [] and item.list_items("w3:p2")[0].id == first.stem
    target = item.archive_pane("w3:p2", "pane-closed")
    assert item.list_items("w3:p2") == [] and (target / first.name).is_file()
    assert item.pane_ids_with_items() == []
