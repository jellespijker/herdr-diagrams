"""The release guards in scripts/release_check.py."""

import importlib.util
import json
import shutil

import pytest

from conftest import ROOT

spec = importlib.util.spec_from_file_location("release_check", ROOT / "scripts" / "release_check.py")
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for name in ("herdr-plugin.toml", "pyproject.toml", "package.json", "package-lock.json", "CHANGELOG.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    monkeypatch.setattr(release_check, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["release_check.py"])
    return tmp_path


def test_current_repo_is_consistent(repo, capsys):
    assert release_check.main() == 0
    assert "ok: version" in capsys.readouterr().out


def test_version_mismatch_is_an_error(repo, capsys):
    package = json.loads((repo / "package.json").read_text())
    package["version"] = "9.9.9"
    (repo / "package.json").write_text(json.dumps(package))
    assert release_check.main() == 1
    assert "versions differ" in capsys.readouterr().out


def test_missing_changelog_entry_is_an_error(repo, capsys):
    text = (repo / "CHANGELOG.md").read_text()
    version = release_check.versions()["herdr-plugin.toml"]
    (repo / "CHANGELOG.md").write_text(text.replace(f"## {version} (", "## 0.0.0 ("))
    assert release_check.main() == 1
    assert f"no (or an empty) '## {version}" in capsys.readouterr().out


def test_changelog_sections():
    sections = release_check.changelog_sections()
    assert "Unreleased" in sections
    version = release_check.versions()["herdr-plugin.toml"]
    assert sections[version]
