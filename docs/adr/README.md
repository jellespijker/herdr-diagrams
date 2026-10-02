# Architecture decision records

Format: Michael Nygard's (Context, Decision, Consequences). One decision per file,
numbered, never renumbered. To change a decision, add a new record that supersedes the
old one and set the old one's status to `Superseded by ADR-NNNN`.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-pipeline-with-spool-contract.md) | Pipeline of three stages joined by a spool file contract | Accepted |
| [0002](0002-item-contract-v1.md) | Item contract v1: versioned JSON per pane | Accepted |
| [0003](0003-renderers-as-data.md) | Renderers as data, with sandboxing and no public network renderer | Accepted |
| [0004](0004-display-kitty-graphics-in-herdr-pane.md) | Display with Kitty graphics in a herdr pane, not inline | Accepted |
| [0005](0005-harness-integration-cli-and-skill-first.md) | Harness integration: CLI and shared skill first, adapters later | Accepted |
| [0006](0006-python-stdlib-external-toolchains.md) | Python standard library; renderer toolchains stay external | Accepted |
| [0007](0007-show-renders-before-queueing.md) | `show` renders before queueing and reports errors to the agent | Accepted |
