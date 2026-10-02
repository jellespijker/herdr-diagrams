import json

import jsonschema

from conftest import FIXTURES, ROOT
from herdr_diagrams import item
from herdr_diagrams.harness import claude

TRANSCRIPT = FIXTURES / "claude-transcript.jsonl"
SCHEMA = json.loads((ROOT / "schema" / "item.v1.json").read_text())


def hook_input():
    return {"session_id": "s1", "transcript_path": str(TRANSCRIPT), "cwd": "/tmp"}


def test_last_turn_skips_earlier_turns_and_tool_results():
    text = claude.last_turn_text(TRANSCRIPT)
    assert "sequenceDiagram" in text and "@startuml" in text
    assert "old --> stale" not in text


def test_run_writes_valid_items_once():
    written = claude.run(hook_input(), "w1:p1")
    items = [item.read(p) for p in written]
    assert [it.format for it in items] == ["mermaid", "plantuml"]
    for path in written:
        jsonschema.validate(json.loads(path.read_text()), SCHEMA)
    assert items[0].origin == {"harness": "claude", "pane": "w1:p1", "session": "s1",
                               "cwd": "/tmp", "via": "claude-stop"}
    assert claude.run(hook_input(), "w1:p1") == []  # de-duplicated


def test_run_without_transcript_is_a_no_op():
    assert claude.run({}, "w1:p1") == []
    assert claude.run({"transcript_path": "/nonexistent"}, "w1:p1") == []


def test_install_hook_is_idempotent_and_preserves_other_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "sonnet", "hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": "echo other"}]}]}}))
    assert "installed" in claude.install_hook(settings, "/x/herdr-diagram hook claude-stop")
    assert "already" in claude.install_hook(settings, "/x/herdr-diagram hook claude-stop")
    data = json.loads(settings.read_text())
    assert data["model"] == "sonnet" and len(data["hooks"]["Stop"]) == 2
    assert (tmp_path / "settings.json.bak-herdr-diagrams").is_file()
    assert "removed" in claude.install_hook(settings, "", uninstall=True)
    data = json.loads(settings.read_text())
    assert data["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "echo other"}]}]


def test_install_hook_creates_settings(tmp_path):
    settings = tmp_path / "new" / "settings.json"
    claude.install_hook(settings, "cmd hook claude-stop")
    assert json.loads(settings.read_text())["hooks"]["Stop"][0]["hooks"][0]["command"] == \
        "cmd hook claude-stop"
