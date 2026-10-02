#!/bin/sh
# Claude Code Stop hook: show the diagrams from the last assistant turn.
# Register it in ~/.claude/settings.json; see README.md.
exec "$(dirname "$(readlink -f "$0")")/../bin/herdr-diagram" hook claude-stop
