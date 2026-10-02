import pytest

from herdr_diagrams import detect, render

REGISTRY = render.load_registry()


@pytest.mark.parametrize("source, fmt", [
    ("flowchart LR\n A-->B", "mermaid"),
    ("sequenceDiagram\n A->>B: hi", "mermaid"),
    ("---\ntitle: x\n---\nerDiagram\n A ||--o{ B : has", "mermaid"),
    ("@startuml\nA -> B\n@enduml", "plantuml"),
    ("@startmindmap\n* a\n@endmindmap", "plantuml"),
    ('workspace "x" {\n}', "structurizr"),
    ("digraph G { a -> b }", "graphviz"),
    ("strict graph { a -- b }", "graphviz"),
    ("direction: right\na -> b", "d2"),
    ("x -> y: hello", "d2"),
])
def test_from_source(source, fmt):
    assert detect.detect(REGISTRY, source=source) == fmt


@pytest.mark.parametrize("name, fmt", [
    ("a.mmd", "mermaid"), ("a.puml", "plantuml"), ("a.dsl", "structurizr"),
    ("a.d2", "d2"), ("a.dot", "graphviz"), ("a.gv", "graphviz"),
    ("a.PNG", "image"), ("a.svg", "image"), ("a.jpeg", "image"),
])
def test_from_extension(name, fmt):
    assert detect.from_extension(name) == fmt


@pytest.mark.parametrize("alias, fmt", [
    ("Mermaid", "mermaid"), ("puml", "plantuml"), ("dot", "graphviz"),
    ("c4", "structurizr"), ("image", "image"),
])
def test_explicit_format_aliases(alias, fmt):
    assert detect.detect(REGISTRY, fmt=alias, source="whatever") == fmt


def test_unknown_format_and_undetectable():
    with pytest.raises(detect.DetectError):
        detect.detect(REGISTRY, fmt="visio")
    with pytest.raises(detect.DetectError):
        detect.detect(REGISTRY, source="just some prose")


def test_fenced_blocks():
    text = (
        "intro\n```mermaid\nflowchart LR\n  A-->B\n```\n"
        "```python\nprint(1)\n```\n"
        "~~~puml\n@startuml\nA->B\n@enduml\n~~~\n"
        "````dot\ndigraph { a -> b }\n````\n"
        "```mermaid\n\n```\n"
    )
    assert detect.fenced_blocks(text) == [
        ("mermaid", "flowchart LR\n  A-->B"),
        ("plantuml", "@startuml\nA->B\n@enduml"),
        ("graphviz", "digraph { a -> b }"),
    ]


def test_every_registry_entry_has_detect_keys_and_a_fixture():
    from conftest import FIXTURES
    exts = {"mermaid": "mmd", "plantuml": "puml", "structurizr": "dsl", "d2": "d2", "graphviz": "dot"}
    for key, entry in REGISTRY.items():
        assert entry.get("detect"), key
        assert (FIXTURES / f"sample.{exts[key]}").is_file(), f"no fixture for {key}"


def test_fenced_blocks_all_formats_indented_and_aliases():
    text = (
        "1. Sequence:\n   ```plantuml\n   Alice -> Bob: hi\n   ```\n"
        "```structurizr-dsl\nworkspace {\n}\n```\n"
        "  ```d2\n  a -> b\n  ```\n"
        "```graphviz\ndigraph { a -> b }\n```\n"
        "```c4plantuml\n@startuml\nPerson(u, \"User\")\n@enduml\n```\n"
    )
    blocks = detect.fenced_blocks(text)
    assert [fmt for fmt, _ in blocks] == ["plantuml", "structurizr", "d2", "graphviz", "plantuml"]
    assert blocks[0][1] == "@startuml\nAlice -> Bob: hi\n@enduml\n"  # wrapped, indent removed
    assert blocks[2][1] == "a -> b"


def test_normalize_leaves_complete_sources_alone():
    mindmap = "@startmindmap\n* a\n@endmindmap"
    assert detect.normalize("plantuml", mindmap) == mindmap
    assert detect.normalize("mermaid", "flowchart LR") == "flowchart LR"
