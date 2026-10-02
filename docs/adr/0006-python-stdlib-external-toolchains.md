# ADR-0006: Python standard library; renderer toolchains stay external

- Status: Accepted
- Date: 2026-10-02

## Context

The plugin needs a CLI, a pane TUI, file watching, process execution, hashing and Kitty
escape generation. None of these needs a third-party library. herdr plugins install from
GitHub with a `[[build]]` step; anything heavy there slows or breaks installation.

Renderers are external programs with large toolchains: Java (PlantUML, Structurizr), Go
binaries (d2), Graphviz, and Node plus Chromium (mermaid-cli).

## Decision

- Implement in Python 3.9+, standard library only. No virtualenv, no Pillow. PNG goes to
  the terminal as-is (`f=100`); scaling is done by the terminal through cell placement.
- The `[[build]]` step installs only `@mermaid-js/mermaid-cli` plugin-locally with `npm ci`,
  because Mermaid is the most common format and has no system package on most distros.
- Every other toolchain is the user's to install. `doctor` reports what is missing; a
  missing renderer disables that format only.
- SVG and non-PNG images convert through the first available of `magick`,
  `rsvg-convert`, `ffmpeg`.

Alternatives rejected:

- **Node/TypeScript**: matches mermaid-cli, but needs a compile step and ships
  node_modules for a TUI that needs nothing from npm.
- **Rust or Go binary**: best TUI performance, but needs release builds per platform or a
  toolchain at install time, for a viewer that mostly waits on files.
- **Bundling Java or Kroki**: large, slow installs for formats many users never use.

## Consequences

- Install is fast and works wherever `python3` and `npm` exist.
- No image library means no server-side scaling or cropping; zoom and pan rely on Kitty
  placement options (source rectangle `x,y,w,h`).
- The project needs Python tooling for tests and lint (`pytest`, `ruff`,
  `import-linter`) as dev dependencies only, via `uv`.

## Amendment (2026-10-02, after implementation)

The minimum is Python 3.11, not 3.9: the registry and settings are TOML and `tomllib`
entered the standard library in 3.11. `bin/herdr-diagram` checks the version and exits
with a clear message on older interpreters.
