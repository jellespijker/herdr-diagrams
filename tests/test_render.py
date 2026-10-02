import shutil

import pytest

from conftest import FIXTURES, needs, needs_mmdc
from herdr_diagrams import item, render

PNG = b"\x89PNG\r\n\x1a\n"


def assert_png(result):
    assert result.ok, (result.error, result.detail)
    for artifact in result.artifacts:
        data = artifact.read_bytes()
        assert data.startswith(PNG) and len(data) > 100


@pytest.mark.parametrize("fmt, fixture", [
    pytest.param("mermaid", "sample.mmd", marks=needs_mmdc),
    pytest.param("plantuml", "sample.puml", marks=needs("plantuml")),
    pytest.param("d2", "sample.d2", marks=needs("d2")),
    pytest.param("graphviz", "sample.dot", marks=needs("dot")),
])
def test_golden_render(fmt, fixture):
    for theme in ("dark", "light"):
        result = render.render_source(fmt, (FIXTURES / fixture).read_bytes(), theme=theme)
        assert_png(result)
        assert len(result.artifacts) == 1


@needs("structurizr-cli")
@needs("plantuml")
def test_structurizr_fans_out_to_one_image_per_view():
    result = render.render_source("structurizr", (FIXTURES / "sample.dsl").read_bytes())
    assert_png(result)
    assert len(result.artifacts) == 2


@needs("dot")
def test_cache_hit_and_theme_in_key():
    data = (FIXTURES / "sample.dot").read_bytes()
    first = render.render_source("graphviz", data, theme="dark")
    again = render.render_source("graphviz", data, theme="dark")
    light = render.render_source("graphviz", data, theme="light")
    assert not first.cached and again.cached
    assert again.artifacts == first.artifacts
    assert light.artifacts != first.artifacts


@needs("dot")
def test_renderer_error_is_reported_not_raised():
    result = render.render_source("graphviz", b"digraph { a -> }")
    assert not result.ok
    assert "exited with" in result.error
    assert "syntax error" in result.detail.lower()


def test_missing_renderer(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "renderers.toml").write_text(
        '[graphviz]\ndetect = ["dot"]\nargv = ["definitely-not-installed", "{in}"]\n')
    result = render.render_source("graphviz", b"digraph {}")
    assert result.error == "renderer not installed: definitely-not-installed"
    assert render.availability(render.load_registry())["graphviz"][0] is False


def test_user_registry_adds_formats(tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "renderers.toml").write_text(
        '[echo]\ndetect = ["echo"]\nargv = ["sh", "-c", "cp {root}/tests/fixtures/pixel.png {out}"]\n'
        'out = "png"\n')
    registry = render.load_registry()
    assert {"mermaid", "echo"} <= set(registry)
    assert_png(render.render_source("echo", b"anything", registry=registry))


def test_image_passthrough_and_svg_conversion(tmp_path):
    png = render.render_item(item.new("image", path=str(FIXTURES / "pixel.png")))
    assert_png(png)
    if shutil.which("rsvg-convert") or shutil.which("magick"):
        svg = tmp_path / "x.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
                       '<rect width="20" height="10" fill="red"/></svg>')
        assert_png(render.render_item(item.new("image", path=str(svg))))


def test_short_detail_drops_stack_traces():
    detail = "Error: Parse error on line 2\n    at Foo (file:///x/node_modules/y.js:1:2)\nExpecting X"
    assert render.short_detail(detail) == "Error: Parse error on line 2\nExpecting X"


def test_cache_key_follows_referenced_config(tmp_path, monkeypatch):
    entry = render.load_registry()["mermaid"]
    key = render.cache_key("mermaid", entry, "dark", b"x")
    assert key == render.cache_key("mermaid", entry, "dark", b"x")
    assert key != render.cache_key("mermaid", entry, "light", b"x")
    assert key != render.cache_key("mermaid", entry, "dark", b"y")
    files = render._referenced_files(entry, "dark")
    assert [f.name for f in files] == ["puppeteer.json", "mermaid-dark.json"]


@pytest.mark.parametrize("fmt, source", [
    ("structurizr", 'workspace {\n  !script groovy {\n    println "x"\n  }\n}'),
    ("structurizr", "workspace {\n  !include https://example.com/model.dsl\n}"),
    ("structurizr", "workspace {\n  !plugin com.example.Plugin\n}"),
    ("d2", 'x: {icon: https://example.com/a.svg}'),
])
def test_reject_rules_refuse_code_and_network(fmt, source):
    result = render.render_source(fmt, source.encode())
    assert not result.ok and result.error.startswith("refused:")


def test_timeout_kills_the_process_group(tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "renderers.toml").write_text(
        '[slow]\ndetect = ["slow"]\nargv = ["sh", "-c", "sleep 30 & sleep 30; touch {out}"]\n'
        'out = "png"\ntimeout = 1\n')
    import time
    started = time.time()
    result = render.render_source("slow", b"x", registry=render.load_registry())
    assert "timed out" in result.error and time.time() - started < 10


def test_export_refuses_symlinks_and_never_copies_image_paths(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    (project / "diagrams").mkdir(parents=True)
    (project / "diagrams" / "evil.dot").symlink_to(outside / "planted.desktop")
    it = item.new("graphviz", source="digraph { a -> b }", title="evil", cwd=str(project))
    written, problems = render.export(it, project / "diagrams", kinds=("src",))
    assert not (outside / "planted.desktop").exists()
    assert [p.name for p in written] == ["evil-2.dot"]
    linked = tmp_path / "linked"
    linked.symlink_to(outside)
    written, problems = render.export(it, linked, kinds=("src",))
    assert written == [] and "symlink" in problems[0]
    secret = tmp_path / "id_ed25519"
    secret.write_text("TOPSECRET")
    leak = item.new("image", path=str(secret))
    written, problems = render.export(leak, project / "out")
    assert written == [] and "not an image" in problems[0]
    assert not any("TOPSECRET" in p.read_text(errors="ignore") for p in project.rglob("*") if p.is_file())


def test_export_skips_identical_files(tmp_path):
    it = item.new("d2", source="a -> b", title="same")
    first, _ = render.export(it, tmp_path, kinds=("src",))
    again, _ = render.export(it, tmp_path, kinds=("src",))
    assert len(first) == 1 and again == []
