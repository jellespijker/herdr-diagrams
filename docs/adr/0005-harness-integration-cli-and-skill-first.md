# ADR-0005: Harness integration: CLI and shared skill first, adapters later

- Status: Accepted
- Date: 2026-10-02

## Context

The plugin must serve Claude Code, agy, opencode, Codex and Copilot CLI. They differ in
hooks, transcript formats and extension mechanisms, and these change between releases.
What they share:

- They all run shell commands.
- They all inherit the pane environment, including `HERDR_PANE_ID`.
- They all load skills in the Agent Skills format (`SKILL.md` with frontmatter), from
  harness-specific directories.

## Decision

Integrate on two levels:

1. **Level 1, all harnesses**: the `herdr-diagram show` CLI, taught by one shared skill,
   `skills/herdr-diagrams/SKILL.md`. The `install-skill` action symlinks the skill into each
   harness's skill directory and the CLI into `~/.local/bin`. It never overwrites a real file.
2. **Level 2, per harness, on demand**: adapters that extract fenced diagram blocks from a
   finished turn and write Items. Claude Code first, through a `Stop` hook reading the
   transcript JSONL. Adapters may import only the Item and detection modules.

CLI and adapters may both be active; adapters skip blocks whose hash matches an Item in the
same pane spool from the last 10 minutes.

Alternatives rejected:

- **Adapters only**: each harness needs reverse-engineered transcript parsing before it
  works at all; agy and Copilot may have no usable hook.
- **Per-harness skills or instructions** (CLAUDE.md, GEMINI.md, AGENTS.md snippets): several
  copies drift apart. One symlinked skill updates every harness at once.

## Consequences

- Any harness works on day one, at the cost of the agent deciding to call the tool.
- Diagrams the agent writes only into its answer appear only where an adapter exists.
- Skill directories for Codex, opencode, agy and Copilot CLI must be verified; until then
  `install-skill` supports Claude Code and prints manual instructions for the rest.
- Adapters depend on undocumented transcript formats and need fixture tests that fail
  loudly when a harness changes its format.

## Amendment (2026-10-02, after implementation)

- Skill directories are resolved (docs/spec.md §10): `~/.agents/skills` serves Codex,
  opencode, Copilot CLI and Gemini CLI; `~/.claude/skills` serves Claude Code;
  `~/.gemini/config/skills` serves agy. Discovery was confirmed for Claude Code, opencode
  and Copilot CLI.
- In a live test Claude Code did not trigger the skill until its description named the
  trigger directly ("whenever you are about to write a Mermaid ... diagram in an answer").
  Skill descriptions must state the moment of use, not only the topic.
- The Claude adapter ships with `herdr-diagram install-hook claude`, which edits
  `~/.claude/settings.json` idempotently, so users do not hand-edit JSON.
