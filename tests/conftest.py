import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CLI = ROOT / "bin" / "herdr-diagram"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own spool, cache and config, and no herdr."""
    monkeypatch.setenv("HERDR_DIAGRAMS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("HERDR_DIAGRAMS_NO_OPEN", "1")
    monkeypatch.setenv("HERDR_BIN_PATH", "/nonexistent/herdr")
    for key in ("HERDR_PANE_ID", "HERDR_DIAGRAMS_THEME", "HERDR_DIAGRAMS_BIND", "HERDR_SESSION",
                "HERDR_SOCKET_PATH", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_HOME",
                "CODEX_SANDBOX", "OPENCODE", "OPENCODE_BIN_PATH", "AGY_SESSION_ID", "COPILOT_CLI"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def needs(program: str):
    return pytest.mark.skipif(shutil.which(program) is None, reason=f"{program} not installed")


needs_mmdc = pytest.mark.skipif(not (ROOT / "node_modules" / ".bin" / "mmdc").exists(),
                                reason="mermaid-cli not installed (npm ci)")
