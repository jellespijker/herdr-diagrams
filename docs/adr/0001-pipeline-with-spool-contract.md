# ADR-0001: Pipeline of three stages joined by a spool file contract

- Status: Accepted
- Date: 2026-10-02

## Context

The plugin varies along three independent dimensions:

- **Harness**: where diagrams come from. Claude Code, agy, opencode, Codex, Copilot CLI,
  and new agents every few months.
- **Format**: Mermaid, PlantUML, Structurizr, D2, Graphviz, plain images. Each needs its
  own toolchain.
- **Display**: how an image reaches the screen. Kitty graphics in a herdr pane today;
  an external viewer as an escape hatch.

Wiring these directly gives a harness × format × display matrix. The harnesses run in other
processes, often other languages, and cannot share an in-process API with the viewer.

## Decision

Structure the plugin as three stages — ingest, render, display — joined by one contract: an
Item JSON file in a per-pane spool directory ([ADR-0002](0002-item-contract-v1.md)).

- Ingest (the CLI and harness adapters) only writes Items.
- Render maps a format to an image and knows nothing of harnesses or panes.
- Display receives a PNG and a cell box and knows nothing of formats.
- The viewer pane orchestrates: spool → render → display.

The dependency rules are enforced with `import-linter`.

Alternatives rejected:

- **One plugin per format** (herdr-mermaid, herdr-plantuml, ...): duplicates the viewer,
  the skill and every harness adapter per format; agents must pick the right tool.
- **A socket or daemon API between harness and viewer**: needs a running server before an
  agent can queue anything, and gives no persistence when the viewer is closed. A file
  drop works with any language and with no viewer running.
- **Scraping pane output** with `herdr pane read` as the main input: Claude's renderer
  strips code fences and alt-screen output is not in scrollback. Fragile.

## Consequences

- Adding a harness touches only ingest; adding a format only the renderer registry;
  replacing the display only the display module.
- Items survive a closed viewer and a herdr restart; the spool needs garbage collection (`gc`).
- File watching adds up to ~500 ms latency when inotify is unavailable.
- The Item contract becomes a public interface that external hooks write; it must be
  versioned and changed with care.
