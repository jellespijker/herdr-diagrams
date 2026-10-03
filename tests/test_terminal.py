import pytest

from herdr_diagrams import terminal


@pytest.mark.parametrize("env, name, support", [
    ({"TERM_PROGRAM": "ghostty", "TERM_PROGRAM_VERSION": "1.3.1"}, "Ghostty", "yes"),
    ({"TERM": "xterm-ghostty"}, "Ghostty", "yes"),
    ({"TERM": "xterm-kitty", "KITTY_WINDOW_ID": "1"}, "kitty", "yes"),
    ({"TERM_PROGRAM": "WezTerm"}, "WezTerm", "yes"),
    ({"TERM_PROGRAM": "iTerm.app", "TERM_PROGRAM_VERSION": "3.6.1"}, "iTerm2", "partial"),
    ({"KONSOLE_VERSION": "240802"}, "Konsole", "partial"),
    ({"TERM_PROGRAM": "WarpTerminal"}, "Warp", "partial"),
    ({"TERM": "alacritty", "ALACRITTY_WINDOW_ID": "1"}, "Alacritty", "no"),
    ({"TERM": "foot"}, "foot", "no"),
    ({"VTE_VERSION": "7800"}, "GNOME Terminal / VTE", "no"),
    ({"WT_SESSION": "x"}, "Windows Terminal", "no"),
    ({"TERM_PROGRAM": "Apple_Terminal"}, "Terminal.app", "no"),
    ({"TERM_PROGRAM": "vscode"}, "VS Code terminal", "no"),
    ({"TERM": "xterm-256color", "GHOSTTY_RESOURCES_DIR": "/x", "ALACRITTY_WINDOW_ID": "1"},
     "Alacritty", "no"),
])
def test_identify(env, name, support):
    found, _ = terminal.identify(env)
    assert found == name
    assert terminal.TERMINALS[found][0] == support


def test_detect_from_environment_and_multiplexers(monkeypatch):
    monkeypatch.setattr(terminal, "_processes", lambda: [])
    info = terminal.detect({"TERM_PROGRAM": "ghostty"})
    assert info.ok and info.source == "environment" and "shows images" in info.summary()
    info = terminal.detect({"TERM_PROGRAM": "ghostty", "TMUX": "/tmp/tmux-1/default,1,0"})
    assert not info.ok and "tmux" in info.summary()
    info = terminal.detect({"TERM": "dumb"})
    assert info.support == "unknown" and "Ghostty, kitty, WezTerm" in info.summary()


def test_detect_prefers_the_herdr_client_of_this_session(monkeypatch):
    clients = [
        (["herdr", "server"], {"TERM_PROGRAM": "herdr"}),
        (["herdr", "--session", "alpha"], {"TERM": "alacritty"}),
        (["herdr"], {"TERM_PROGRAM": "WezTerm"}),
    ]
    monkeypatch.setattr(terminal, "_processes", lambda: clients)
    assert terminal.detect({}).name == "WezTerm"
    assert terminal.detect({"HERDR_SESSION": "alpha"}).name == "Alacritty"


def test_image_problem_and_override(monkeypatch):
    monkeypatch.setattr(terminal, "_processes", lambda: [])
    monkeypatch.setenv("HERDR_DIAGRAMS_IMAGES", "auto")
    monkeypatch.setattr(terminal, "kitty_graphics_setting", lambda: "default (on)")
    assert "Alacritty cannot show images" in terminal.image_problem(terminal.detect({"TERM": "alacritty"}))
    assert terminal.image_problem(terminal.detect({"TERM_PROGRAM": "ghostty"})) is None
    monkeypatch.setenv("HERDR_DIAGRAMS_IMAGES", "on")
    assert terminal.image_problem(terminal.detect({"TERM": "alacritty"})) is None
    monkeypatch.setenv("HERDR_DIAGRAMS_IMAGES", "off")
    assert "turned off" in terminal.image_problem()
    monkeypatch.setenv("HERDR_DIAGRAMS_IMAGES", "auto")
    monkeypatch.setattr(terminal, "kitty_graphics_setting", lambda: "OFF ([terminal] in x)")
    assert "kitty_graphics" in terminal.image_problem()


def test_platform(monkeypatch):
    for plat, name, support in (("linux", "Linux", "yes"), ("darwin", "macOS", "yes"),
                                ("win32", "Windows", "no"), ("freebsd14", "freebsd14", "unknown")):
        monkeypatch.setattr(terminal.sys, "platform", plat)
        assert terminal.platform()[:2] == (name, support)
