# ADR-0009: Follow pane and agent lifecycles; archive instead of delete

- Status: Accepted
- Date: 2026-10-02
- Amends: [ADR-0002](0002-item-contract-v1.md) (spool layout gains `archive/`)

## Context

Diagrams pile up per pane. Four situations leave stale or orphaned Items:

1. A new agent session starts in a pane that already showed diagrams.
2. A pane closes.
3. A pane moves to another tab or space; herdr gives it a new ID (`w1:pD` -> `w3:p2`).
4. A herdr session stops; no `pane.closed` events fire for its panes.

Deleting outright loses diagrams the user may still want to export.

## Decision

- Items leave the live spool by moving to `archive/<herdr-session>/<pane-key>/<time>-<reason>/`.
  `gc` deletes spool, archive and cache files older than its cutoff (7 days by default).
- Plugin hooks, all handled by `herdr-diagram event`:
  - `pane.agent_detected`: wait up to 10 s for herdr to report the agent session ID, then
    archive the pane's Items whose `origin.session` is set and differs. Items without a
    session (queued from a plain shell) stay.
  - `pane.closed`: close the pane's viewer, archive its Items.
  - `pane.moved`: move the spool directory to the new pane ID and close the viewer bound to
    the old ID; the next `show` opens one for the new ID.
  - `startup`: archive Items of panes that `herdr pane list` no longer reports, then `gc`.
- `herdr-diagram export --archived` includes archived Items.
- The last 50 event payloads are kept in `events.log` for debugging.

## Consequences

- The viewer shows only the current agent session; earlier diagrams remain recoverable for
  a week.
- A session ID that herdr reports late (after 10 s) means nothing is archived for that
  start; the next start catches up.
- Startup pruning depends on `herdr pane list`; when herdr cannot be asked, nothing is pruned.
