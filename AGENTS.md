# Agent notes

Herdr plugin: diagrams from coding agents, rendered and shown as images in a herdr split pane.

Read first: `docs/spec.md` (what to build) and `docs/adr/` (why). Do not contradict an
accepted ADR silently; propose a superseding ADR instead.

- Manifest: `herdr-plugin.toml`. Plugin docs:
  https://raw.githubusercontent.com/herdrdev/herdr/v0.9.3/docs/next/website/src/content/docs/plugins.mdx
- Plugin processes run with the plugin root as cwd and get `HERDR_BIN_PATH`,
  `HERDR_PLUGIN_ID`, `HERDR_PLUGIN_ROOT`, `HERDR_PLUGIN_CONFIG_DIR`, `HERDR_PANE_ID`.
  Commands are argv arrays, no shell expansion.
- Harness processes do NOT get plugin variables; the spool lives at a fixed path
  (`spec.md` §4.1).
- Python standard library only at runtime (ADR-0006). Dev tools via `uv`.
- Module boundaries (`spec.md` §12) are enforced by import-linter; keep them.
- Prior art (no license, read only, do not copy code): hx-w/herdr-visuals,
  haretoke/herdr-image-viewer, olehsharov/herdr-imgpopup.

Dev loop: `herdr plugin link "$PWD"`, then `herdr plugin log list --plugin herdr-diagrams`.
