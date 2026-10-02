# Changelog

## 0.1.0 (2026-10-02)

First release.

- Render Mermaid, PlantUML, Structurizr (C4), D2 and Graphviz diagrams, and PNG/SVG/JPEG
  images, as Kitty graphics in a herdr split pane beside the agent.
- `herdr-diagram show` for any agent, taught by one shared skill for Claude Code, Codex,
  opencode, Copilot CLI and agy; render errors go back to the agent.
- Claude Code Stop hook that shows diagram blocks from answers (`install-hook claude`).
- Viewer: navigation, list of all diagrams, zoom and pan, source view, Structurizr views,
  scroll sync with the agent's chat, export.
- Export to PNG, SVG and source files.
- One viewer per pane, across spaces, tabs and herdr sessions; diagrams follow pane moves
  and are archived when a pane closes or a new agent session starts.
- Works inside agent sandboxes: a plugin daemon opens viewers; `allow claude` adds the
  permission rules.
- Renderers are configuration (`renderers.toml`); untrusted sources are sandboxed or refused.
- Linux tested; macOS supported (CI); Windows not yet.
