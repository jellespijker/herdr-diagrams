# ADR-0007: `show` renders before queueing and reports errors to the agent

- Status: Accepted
- Date: 2026-10-02
- Amends: [ADR-0001](0001-pipeline-with-spool-contract.md) (the rule that ingest never renders)

## Context

ADR-0001 keeps ingest free of rendering: the CLI writes an Item, the viewer renders it.
In practice agents write invalid diagrams often enough to matter: a missing arrow target
in Mermaid, an unclosed brace in Graphviz. With render-in-viewer only, the agent hears
"shown", tells the user so, and the user finds an error screen in the pane. The agent
never learns that its diagram was broken, so it cannot fix it.

## Decision

`herdr-diagram show` renders the Item once, synchronously, before writing it to the spool.

- On success it queues the Item. The artifact is now in the content-addressed cache, so
  the viewer displays it without rendering again.
- On failure it prints the renderer error without stack traces, queues nothing and exits 1.
  The skill tells the agent to fix the source and call `show` again.
- `--no-wait` restores the old behaviour for callers that cannot wait.

Harness adapters (the Claude `Stop` hook) still only write Items: the turn is already over,
there is nobody to report an error to, and a hook must return quickly.

## Consequences

- Agents get a fix loop: the error text, including the line number, arrives in the same
  tool call. Verified with Mermaid and Graphviz parse errors.
- `show` takes as long as one render (about 0.1 s for Graphviz, 1–3 s for Mermaid and
  PlantUML with a cold JVM or browser).
- The viewer stays the only place that displays; the CLI never draws.
- The import rules are unchanged: `cli` may use `render`; adapters may not.
