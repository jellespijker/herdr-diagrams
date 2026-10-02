import tomllib

from herdr_diagrams import keys

CONFIG = """[keys]
prefix = "ctrl+space"
detach = "prefix+d"
split = ["prefix+h", "alt+enter"]

[[keys.command]]
key = "prefix+e"
type = "plugin_action"
command = "x.y"
description = "Review diffs"
"""


def test_setup_adds_block_once_and_removes_it(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    changed, message = keys.setup(path=path)
    assert changed and "prefix+i" in message
    data = tomllib.loads(path.read_text())
    assert {"key": "prefix+i", "type": "plugin_action", "command": "herdr-diagrams.open",
            "description": "Diagrams: open the viewer beside this pane"} in data["keys"]["command"]
    assert keys.setup(path=path) == (False, f"prefix+i already opens the viewer ({path})")
    changed, _ = keys.setup("prefix+m", path=path)  # switching keys replaces the block
    assert changed and path.read_text().count(keys.BEGIN) == 1
    assert keys.installed_key(path.read_text()) == "prefix+m"
    assert (tmp_path / "config.toml.bak-herdr-diagrams").is_file()
    changed, _ = keys.setup(remove=True, path=path)
    assert changed and keys.BEGIN not in path.read_text()
    assert tomllib.loads(path.read_text())["keys"]["detach"] == "prefix+d"


def test_setup_refuses_taken_keys(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    for taken, by in (("prefix+d", "herdr keys.detach"), ("prefix+e", "Review diffs"),
                      ("alt+enter", "herdr keys.split"), ("prefix+g", "a built-in herdr binding")):
        changed, message = keys.setup(taken, path=path)
        assert not changed and by in message and "Try: herdr-diagram setup-keys --key prefix+i" in message
    assert path.read_text() == CONFIG


def test_setup_creates_config_when_missing(tmp_path):
    path = tmp_path / "herdr" / "config.toml"
    assert keys.setup(path=path)[0]
    assert keys.installed_key(path.read_text()) == "prefix+i"
