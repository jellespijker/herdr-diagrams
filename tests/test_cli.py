import json
import os
import subprocess

from conftest import CLI, FIXTURES, needs
from herdr_diagrams import item


def run(*args, stdin=None, env=None):
    return subprocess.run([str(CLI), *args], input=stdin, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, timeout=120)


@needs("dot")
def test_show_queues_for_the_current_pane():
    proc = run("show", "-t", "Pipeline", str(FIXTURES / "sample.dot"), env={"HERDR_PANE_ID": "w2:p7"})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("graphviz: Pipeline")
    (only,) = item.list_items("w2:p7")
    assert only.format == "graphviz" and only.source.startswith("digraph")


@needs("dot")
def test_show_from_stdin_detects_format():
    proc = run("show", "-", stdin="digraph { x -> y }", env={"HERDR_PANE_ID": "w1:p1"})
    assert proc.returncode == 0, proc.stderr
    assert item.list_items("w1:p1")[0].format == "graphviz"


@needs("dot")
def test_show_reports_render_errors_and_queues_nothing():
    proc = run("show", "-f", "dot", "-", stdin="digraph { a -> }", env={"HERDR_PANE_ID": "w1:p1"})
    assert proc.returncode == 1
    assert "render failed" in proc.stderr and "Nothing was queued" in proc.stderr
    assert item.list_items("w1:p1") == []


def test_show_exit_codes():
    assert run("show", "-", stdin="no diagram here").returncode == 3
    assert run("show", "/nonexistent.mmd").returncode == 1
    assert run("show", "-f", "visio", "-", stdin="x").returncode == 2


def test_show_image_keeps_path():
    proc = run("show", str(FIXTURES / "pixel.png"), env={"HERDR_PANE_ID": "w1:p1"})
    assert proc.returncode == 0, proc.stderr
    (only,) = item.list_items("w1:p1")
    assert only.format == "image" and only.path == str(FIXTURES / "pixel.png")


@needs("dot")
def test_render_to_file(tmp_path):
    out = tmp_path / "out.png"
    proc = run("render", str(FIXTURES / "sample.dot"), "-o", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.read_bytes().startswith(b"\x89PNG")


def test_list_json():
    item.write(item.new("d2", source="a -> b", pane="w1:p1"))
    data = json.loads(run("list", "--json", env={"HERDR_PANE_ID": "w1:p1"}).stdout)
    assert [d["format"] for d in data] == ["d2"]


def test_hook_never_fails(tmp_path):
    proc = run("hook", "claude-stop", stdin="not json")
    assert proc.returncode == 0 and proc.stdout == ""
    log = tmp_path / "home" / "hook-errors.log"
    assert "claude-stop" in log.read_text()


def test_hook_writes_items_from_transcript():
    hook = json.dumps({"transcript_path": str(FIXTURES / "claude-transcript.jsonl"), "session_id": "s"})
    proc = run("hook", "claude-stop", stdin=hook, env={"HERDR_PANE_ID": "w3:p1"})
    assert proc.returncode == 0 and proc.stdout == ""
    assert [it.format for it in item.list_items("w3:p1")] == ["mermaid", "plantuml"]


def test_event_pane_closed_removes_spool():
    item.write(item.new("d2", source="a -> b", pane="w1:p9"))
    event = json.dumps({"pane_id": "w1:p9"})
    proc = run("event", env={"HERDR_PLUGIN_EVENT": "pane.closed", "HERDR_PLUGIN_EVENT_JSON": event})
    assert proc.returncode == 0
    assert item.list_items("w1:p9") == []


def test_install_skill_status_in_fake_home(tmp_path):
    env = {"HOME": str(tmp_path / "fakehome")}
    assert run("install-skill", "--harness", "claude", "--harness", "codex", env=env).returncode == 0
    status = run("install-skill", "--status", env=env).stdout
    assert "installed  claude" in status and "installed  agents" in status
    assert "missing    cli" in status
    assert run("install-skill", "--uninstall", env=env).returncode == 0
    assert not (tmp_path / "fakehome" / ".claude" / "skills" / "herdr-diagrams").exists()


def test_doctor_runs():
    proc = run("doctor")
    assert proc.returncode == 0
    assert "renderers" in proc.stdout and "mermaid" in proc.stdout


def test_exit_codes_for_usage_errors():
    assert run("gc", "--older-than", "abc").returncode == 2
    assert run("render", str(FIXTURES / "sample.dot"), "-o", "/tmp/x.png", "-f", "visio").returncode == 2


def test_show_output_names_the_chat_marker():
    proc = run("show", str(FIXTURES / "pixel.png"), "-t", "Tiny", env={"HERDR_PANE_ID": "w1:p1"})
    assert "[diagram:" not in proc.stdout  # a person in a shell needs no marker hint
    proc = run("show", str(FIXTURES / "pixel.png"), "-t", "Tiny",
               env={"HERDR_PANE_ID": "w1:p1", "CLAUDECODE": "1"})
    assert "[diagram: Tiny]" in proc.stdout


def test_gc_removes_old_files_and_empty_dirs(tmp_path):
    path = item.write(item.new("d2", source="a -> b", pane="w1:p1"))
    os.utime(path, (0, 0))
    assert run("gc", "--older-than", "1d").returncode == 0
    assert not path.parent.exists()


def test_pending_viewer_claim(monkeypatch):
    from herdr_diagrams import viewers

    viewers.mark_pending("w1:p1")
    assert viewers.lookup("w1:p1")["source_pane"] == "w1:p1"
    monkeypatch.setattr(viewers, "PENDING_SECONDS", -1)
    viewers.mark_pending("w1:p1")
    assert viewers.lookup("w1:p1") is None


def event(name, payload):
    return run("event", env={"HERDR_PLUGIN_EVENT": name, "HERDR_PLUGIN_EVENT_JSON": json.dumps(payload)})


def test_event_pane_moved_follows_the_pane():
    item.write(item.new("d2", source="a -> b", pane="w1:pD"))
    payload = {"event": "pane_moved", "data": {"previous_pane_id": "w1:pD", "pane": {"pane_id": "w3:p2"}}}
    assert event("pane.moved", payload).returncode == 0
    assert item.list_items("w1:pD") == [] and len(item.list_items("w3:p2")) == 1


def test_event_pane_closed_archives(tmp_path):
    item.write(item.new("d2", source="a -> b", pane="w1:p9"))
    event("pane.closed", {"data": {"pane_id": "w1:p9"}})
    assert item.list_items("w1:p9") == []
    assert list((tmp_path / "home" / "archive").rglob("*.json"))


def test_startup_without_herdr_is_harmless():
    item.write(item.new("d2", source="a -> b", pane="w1:p1"))
    assert event("startup", {}).returncode == 0
    assert len(item.list_items("w1:p1")) == 1  # herdr unknown: nothing pruned


@needs("dot")
def test_export_writes_png_svg_and_source(tmp_path):
    item.write(item.new("graphviz", source=(FIXTURES / "sample.dot").read_text(), title="Pipe line",
                        pane="w1:p1", cwd=str(tmp_path)))
    proc = run("export", env={"HERDR_PANE_ID": "w1:p1"})
    assert proc.returncode == 0, proc.stderr
    names = sorted(p.name for p in (tmp_path / "diagrams").iterdir())
    assert names == ["pipe-line.dot", "pipe-line.png", "pipe-line.svg"]
    run("export", env={"HERDR_PANE_ID": "w1:p1"})  # same content: no -2 copies
    assert len(list((tmp_path / "diagrams").iterdir())) == 3
    out = tmp_path / "only-svg"
    assert run("export", "--svg", "-d", str(out), env={"HERDR_PANE_ID": "w1:p1"}).returncode == 0
    assert [p.name for p in out.iterdir()] == ["pipe-line.svg"]


def test_export_without_items_and_bad_index():
    assert run("export", env={"HERDR_PANE_ID": "w1:p1"}).returncode == 1
    item.write(item.new("d2", source="a -> b", pane="w1:p1"))
    assert run("export", "-n", "5", env={"HERDR_PANE_ID": "w1:p1"}).returncode == 2
