"""Daemon and sandbox behaviour, with a fake herdr binary that records its calls."""

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import CLI, FIXTURES
from herdr_diagrams import daemon, item, viewers

LAYOUT = '{"result":{"layout":{"panes":[{"pane_id":"w1:p1","rect":{"width":200,"height":50}}]}}}'
PANES = ('{"result":{"panes":[{"pane_id":"w1:p1","agent":"claude",'
         '"agent_session":{"value":"sess-1"}},{"pane_id":"w1:p2"}]}}')
OPENED = '{"result":{"pane":{"pane_id":"w1:p9"}}}'
FAKE_HERDR = """#!/bin/sh
echo "$@" >> "@LOG@"
case "$1 $2" in
  "pane list") echo '@PANES@' ;;
  "pane layout") echo '@LAYOUT@' ;;
  "plugin pane") echo '@OPENED@' ;;
  *) echo '{"result":{}}' ;;
esac
"""


@pytest.fixture
def fake_herdr(tmp_path, monkeypatch):
    log = tmp_path / "herdr-calls.log"
    exe = tmp_path / "herdr"
    script = FAKE_HERDR.replace("@PANES@", PANES).replace("@LAYOUT@", LAYOUT).replace("@OPENED@", OPENED)
    exe.write_text(script.replace("@LOG@", str(log)))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("HERDR_BIN_PATH", str(exe))
    log.write_text("")
    return log


def wait_for(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_daemon_opens_a_viewer_for_new_items_only(fake_herdr):
    item.write(item.new("d2", source="old -> item", pane="w1:p2"))  # before start: ignored
    proc = subprocess.Popen([sys.executable, str(CLI), "daemon"], env=os.environ.copy())
    try:
        assert wait_for(daemon.running)
        assert subprocess.run([sys.executable, str(CLI), "daemon"], timeout=10).returncode == 0  # 2nd exits
        time.sleep(1)
        assert "plugin pane open" not in fake_herdr.read_text()
        item.write(item.new("d2", source="a -> b", pane="w1:p1"))
        assert wait_for(lambda: "--target-pane w1:p1" in fake_herdr.read_text())
        assert "--target-pane w1:p2" not in fake_herdr.read_text()
        assert viewers.lookup("w1:p1")  # pending claim stops a second open
        assert wait_for(lambda: item.list_items("w1:p1")[0].origin.get("session") == "sess-1")
    finally:
        proc.kill()
        proc.wait()


def test_ensure_without_herdr_does_nothing():
    assert daemon.ensure() is False
    assert daemon.running() is False


def test_state_directory_is_private():
    home = item.prepare_home()
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    home.chmod(0o755)
    item.write(item.new("d2", source="a -> b", pane="w1:p1"))
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_show_in_a_read_only_sandbox_explains_itself(tmp_path):
    home = tmp_path / "home"
    item.prepare_home()
    home.chmod(0o500)
    try:
        proc = subprocess.run([str(CLI), "show", str(FIXTURES / "sample.dot")], capture_output=True,
                              text=True, env={**os.environ, "HERDR_PANE_ID": "w1:p1"}, timeout=60)
    finally:
        home.chmod(0o700)
    assert proc.returncode == 4
    assert "sandbox" in proc.stderr and "herdr-diagram allow claude" in proc.stderr


def test_allow_rules_for_claude(tmp_path):
    from herdr_diagrams.harness import claude

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": ["Read"]}}))
    state = item.home()
    assert "added" in claude.allow(settings, state)
    assert "already" in claude.allow(settings, state)
    rules = json.loads(settings.read_text())["permissions"]["allow"]
    assert rules[0] == "Read" and "Bash(herdr-diagram:*)" in rules
    assert any(r.startswith("Edit(") and r.endswith("/**)") for r in rules)
    assert "removed 2" in claude.allow(settings, state, uninstall=True)
    assert json.loads(settings.read_text())["permissions"]["allow"] == ["Read"]
    default = Path.home() / ".local" / "state" / "herdr-diagrams"
    assert claude.allow_rules(default) == ["Bash(herdr-diagram:*)", "Edit(~/.local/state/herdr-diagrams/**)"]
