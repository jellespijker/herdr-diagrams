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
    assert path.parent.name == "w1_p1"
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
