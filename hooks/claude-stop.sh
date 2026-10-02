#!/bin/sh
# Claude Code Stop hook: show the diagrams from the last assistant turn.
# Prefer `herdr-diagram install-hook claude`, which registers the CLI directly.
dir=$(cd "$(dirname "$0")" && pwd -P)
exec "$dir/../bin/herdr-diagram" hook claude-stop
