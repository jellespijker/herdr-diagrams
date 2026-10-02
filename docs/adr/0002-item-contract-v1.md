# ADR-0002: Item contract v1: versioned JSON per pane

- Status: Accepted
- Date: 2026-10-02

## Context

The spool contract ([ADR-0001](0001-pipeline-with-spool-contract.md)) is written by code we
do not fully control: shell hooks, adapters for several harnesses, and agents calling the
CLI. It must route each diagram to the viewer beside the right agent, and survive later
additions such as session IDs or themes.

Facts that shape it:

- Processes inside a herdr pane inherit `HERDR_PANE_ID` (for example `w1:p3`). Verified on
  herdr 0.9.3: `bin/mmv` called from a pane received it.
- Harness processes do **not** receive plugin variables such as `HERDR_PLUGIN_STATE_DIR`.
- A viewer must never read a half-written file.

## Decision

- One JSON file per Item, schema `schema/item.v1.json`, with a mandatory integer `v`.
- Exactly one of `source` (inline text) or `path` (absolute file) is set. Plain images use
  `format = "image"` with `path`, so images and diagrams share one code path.
- Location: `${HERDR_DIAGRAMS_HOME:-$XDG_STATE_HOME/herdr-diagrams}/spool/<pane-key>/`, where
  `<pane-key>` is `HERDR_PANE_ID` with `:` replaced by `_`; `_nopane` outside herdr.
- Writers write `<name>.json.tmp` and rename it into place.
- Compatibility: adding optional fields keeps `v = 1`. Removing or changing a field bumps
  `v`. Readers skip unknown versions and log once.

Alternatives rejected:

- **One shared spool with a pane field**: every viewer would scan every Item; cleanup on
  `pane.closed` becomes a filter instead of a directory removal.
- **Raw `.mmd`/`.puml` files without metadata**: no title, no origin, no room for session or
  cwd; format only from the extension.
- **Using `HERDR_PLUGIN_STATE_DIR`**: not visible to harness processes.

## Consequences

- Routing needs no cooperation from the harness: the environment carries the pane ID.
- A moved pane gets a new ID in herdr; Items written before the move stay under the old
  key. Accepted for v1; the viewer may later follow `pane move` events.
- The schema file is the contract test fixture for every adapter.

## Amendment (2026-10-02, after implementation)

Pane IDs are unique only within one herdr session (server): two sessions both have `w1:p1`.
The spool and the viewer registry are therefore scoped by session:
`spool/<herdr-session>/<pane-key>/`. The session name comes from `HERDR_SESSION`, or from
`HERDR_SOCKET_PATH` for plugin processes, or is `default`. Items record it in the optional
field `origin.herdr_session`; as an additive field it keeps `v = 1`.
