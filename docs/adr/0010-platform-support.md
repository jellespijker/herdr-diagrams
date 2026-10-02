# ADR-0010: Platform support: Linux and macOS; Windows later

- Status: Accepted
- Date: 2026-10-02

## Context

herdr runs on Linux and macOS, with Windows in preview. The plugin was built and tested on
Linux. An audit of the code for macOS and Windows found:

**macOS**: every API used exists (termios, tty, fcntl, pty, process groups, symlinks).
Differences are in tools and defaults:

- `/usr/bin/python3` is 3.9 on many Macs; the plugin needs 3.11 (`tomllib`).
- Opener and clipboard are `open` and `pbcopy`; image conversion can use the built-in `sips`.
- Chrome and Chromium live in `/Applications`, not on `PATH`.
- `readlink -f` is missing on older macOS.

**Windows**:

- The viewer's terminal loop uses `termios`, `tty`, `select` on stdin and `SIGWINCH`; Windows
  consoles need `msvcrt` and polling for resize.
- Plugin commands are argv arrays such as `bin/herdr-diagram`, which Windows cannot execute
  without `python` in front; herdr also resolves relative programs differently there.
- `install-skill` creates symlinks, which need Developer Mode on Windows.
- The build and hook entry points are POSIX shell scripts.
- Kitty graphics: WezTerm supports them on Windows; Windows Terminal does not. Whether herdr
  forwards them on Windows is unknown.

## Decision

- Support Linux and macOS (`platforms = ["linux", "macos"]` in the manifest).
- Close the macOS gaps in code: `bin/herdr-diagram` re-executes itself with a Python 3.11+
  found on `PATH` or in Homebrew; image conversion falls back to `sips`; the Chromium
  fallback checks `/Applications`; the hook script avoids `readlink -f`; config and skill
  paths come from herdr and honour `CLAUDE_CONFIG_DIR`.
- Run the test suite on `macos-latest` in CI.
- Windows is out of scope for now. The CLI avoids POSIX-only calls where cheap (the timeout
  kill falls back to `Popen.kill`), so `show`, `render` and `export` do not fail on import.

## Consequences

- macOS is verified by unit tests in CI and by the audit, not yet by a person in a herdr pane.
  Kitty forwarding, cell pixel size and the popups need a manual check on a Mac.
- Windows support needs: a Windows input loop in the viewer, copies instead of symlinks in
  `install-skill`, PowerShell `[[build]]` and action entries with `python` in the argv, and a
  check that herdr on Windows forwards Kitty graphics.

## Amendment (2026-10-02, 0.1.1)

The plugin now checks OS and terminal and tells the user, instead of leaving an empty pane:

- The install build refuses unsupported operating systems and ends with a three-line summary
  (`doctor --brief`): OS, terminal, missing renderers.
- The terminal is identified from the herdr client process, which runs directly in the
  user's terminal; herdr itself does not report the outer terminal or its graphics support.
- The viewer shows an explanation and the `o`/`s`/`e` alternatives when the terminal cannot
  show images; `show` passes the same note to the agent. `images = "on"` overrides a wrong
  detection.
