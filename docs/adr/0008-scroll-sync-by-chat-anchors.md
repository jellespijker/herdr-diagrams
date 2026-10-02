# ADR-0008: Scroll sync by anchors in the visible chat text

- Status: Accepted
- Date: 2026-10-02

## Context

A conversation often produces several diagrams. When the user scrolls the agent's chat
back to an earlier answer, the viewer should show the diagram that answer is about.

What the viewer can observe:

- herdr reports a pane's scroll offset, but Claude Code (and other full-screen TUIs) scroll
  inside their own alternate screen. herdr's offset stays 0; only the visible text changes.
- `herdr pane read --source visible` returns that visible text for any pane.
- Claude Code collapses tool calls ("Ran 1 shell command"), so the `herdr-diagram show`
  command line is usually not on screen.

## Decision

The viewer polls the source pane's visible text once per second in a background thread
and selects the Item whose anchor is lowest on screen:

1. **Marker:** the skill asks agents to write `[diagram: <title>]` on its own line next to
   each diagram, and `show` prints that line as a reminder when an agent calls it.
2. **Source lines:** for diagrams printed in the answer (the Stop hook case), two or more
   distinctive source lines on screen identify the Item.

A manual selection holds for 8 seconds. Sync can be turned off with `t` or
`scroll_sync = false`.

Alternatives rejected:

- **herdr scroll offset**: stays 0 for alternate-screen TUIs, which include Claude Code.
- **Kitty Unicode placeholders inline in the chat**: needs the harness to print placeholder
  cells (ADR-0004).
- **Timestamps**: the viewer cannot map a scroll position to a time.

## Consequences

- Works for every harness whose output is text in a herdr pane; no harness API needed.
- Depends on agents writing the marker. If they do not, Items queued through `show` are
  not synced, while hook-captured Items still are.
- One `herdr pane read` per second per viewer; cheap, and skipped when the text is unchanged.
- An answer that shows the end of one diagram's text and the start of the next selects the
  lower one. Acceptable: that is the diagram the user is scrolling towards.
