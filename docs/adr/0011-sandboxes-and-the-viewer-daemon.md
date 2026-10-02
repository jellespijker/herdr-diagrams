# ADR-0011: Work inside agent sandboxes; a plugin daemon opens viewers

- Status: Accepted
- Date: 2026-10-02
- Amends: [ADR-0005](0005-harness-integration-cli-and-skill-first.md), [ADR-0007](0007-show-renders-before-queueing.md)

## Context

The state folder (`~/.local/state/herdr-diagrams`) lies outside every project. Agents run
`herdr-diagram show` under their approval mode and, when enabled, an OS sandbox. Tested on
Linux with Claude Code 2.1 and its bubblewrap sandbox:

- Without a rule, `show` fails: the state folder is read-only inside the sandbox.
- With `Edit(~/.local/state/herdr-diagrams/**)` in `permissions.allow`, writing works.
- The herdr Unix socket stays unreachable (`allowUnixSockets` is macOS-only; the alternative,
  `allowAllUnixSockets`, opens every socket on the machine). So `show` cannot open a viewer
  and cannot ask herdr for the agent session.
- A `$VARIABLE` or `&&` around the command triggers an approval prompt even with an allow rule.

Hooks, plugin events, plugin panes and plugin startup commands all run outside agent sandboxes.

## Decision

- **Daemon.** The plugin starts `herdr-diagram daemon` from `[[startup]]`, any plugin event, the
  `open` action and every viewer, guarded by one lock file per herdr session. It polls the
  spool, opens a viewer when a new Item appears for a pane without one (with the same pending
  claim as `show`), and fills in `origin.session` and `origin.harness` that a sandboxed
  `show` could not obtain. It exits when herdr stops answering.
- **Clear failure.** `show` checks write access first. In a read-only sandbox it exits with
  status 4 and names the fix per agent. The skill tells the agent to fall back to a fenced
  diagram in its answer, which the Claude Stop hook still shows.
- **Rules, not wider sandboxes.** `herdr-diagram allow claude` adds `Bash(herdr-diagram show:*)`, `Bash(herdr-diagram list:*)` and
  the `Edit` rule for the state folder. No socket exemptions and no `excludedCommands`: the
  renderers process untrusted input and stay sandboxed when the agent is.
- **Skill.** Agents call `herdr-diagram` as one plain command, so allow rules match.
- **Privacy.** The state folder is created `0700`; existing folders are tightened on use.

## Consequences

- Sandboxed agents get the same result as unsandboxed ones, with one-time setup.
- One small background process per herdr session in which the plugin is active.
- Agents other than Claude Code are configured by hand; the README lists the settings, marked
  as tested or taken from the docs.

## Amendment (2026-10-02, pre-release review)

- The allow rules cover `show` and `list` only. `render` and `export` write to paths the
  caller names and keep their approval prompt.
- Item fields are agent-controlled, and the viewer exports outside the agent's sandbox.
  Export therefore never writes through a symlink (`O_NOFOLLOW`, no symlinked target
  directory), ignores an `origin.cwd` that is not an existing directory, and exports image
  Items as PNG only. Image Items must have an image extension and matching content.
- The daemon marks an Item as handled only after a viewer exists, so a `show` that is still
  holding its pending claim cannot make the daemon skip it.
