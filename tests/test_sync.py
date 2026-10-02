from herdr_diagrams import item, sync


def make(title=None, source="flowchart LR\n  checkout --> payment\n  payment --> receipt"):
    return item.Item(format="mermaid", source=source, title=title, id=title or "x", created=1)


ITEMS = [
    make("Login flow", "sequenceDiagram\n  User->>App: open app\n  App->>Auth: authorize"),
    make("Order states", "stateDiagram-v2\n  Pending --> Paid\n  Paid --> Shipped"),
    make(None, "flowchart LR\n  cart[Shopping cart] --> checkout{Checkout step}\n"
               "  checkout --> pay[Pay order]"),
]


def test_marker_wins_and_bottom_most_is_chosen():
    text = "Intro\n[diagram: Login flow]\nmore text\n  [diagram:   Order states]  \nend"
    assert sync.visible_item(ITEMS, text) == 1
    assert sync.visible_item(ITEMS, "[diagram: Login flow]") == 0


def test_printed_source_lines_anchor_hook_items():
    chat = "Here you go:\n  flowchart LR\n    cart[Shopping cart] --> checkout{Checkout step}\n" \
           "    checkout --> pay[Pay order]\n"
    assert sync.visible_item(ITEMS, chat) == 2


def test_one_matching_line_is_not_enough():
    assert sync.visible_item(ITEMS, "cart[Shopping cart] --> checkout{Checkout step}") is None


def test_nothing_visible():
    assert sync.visible_item(ITEMS, "just prose about payments") is None
    assert sync.visible_item([], "[diagram: Login flow]") is None


def test_keyword_lines_are_not_anchors():
    strong, lines = sync.anchors(make(None, "@startuml\nAlice -> Bob: hello there\n@enduml"))
    assert strong == [] and lines == ["alice -> bob: hello there"]
