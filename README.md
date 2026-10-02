# herdr-diagrams

Your coding agent draws a diagram; you see a picture, not a code block.

A [Herdr](https://herdr.dev) plugin that renders **Mermaid, PlantUML, Structurizr (C4), D2
and Graphviz** diagrams, and plain images, from **Claude Code, Codex, opencode, Copilot CLI,
agy** and any other agent that can run a shell command. The images appear in a split pane
next to the agent, drawn with the Kitty graphics protocol.

![Claude Code explains an order flow; the sequence diagram appears in the pane beside it](docs/screenshots/claude-sequence.png)

![The same conversation: a Structurizr C4 container view in the viewer pane](docs/screenshots/claude-c4.png)

## How it works

```mermaid
flowchart LR
    agent([Coding agent]) -->|herdr-diagram show| spool[(spool)]
    hook[Claude Stop hook] --> spool
    spool --> viewer[Viewer pane]
    viewer -->|mmdc · plantuml · d2 · dot| cache[(PNG cache)]
    cache -->|Kitty graphics| terminal[Ghostty / kitty / WezTerm]
```

- A shared **skill** teaches every agent to call `herdr-diagram show`. The first diagram
  opens a viewer pane beside the agent's pane; later ones appear in it.
- `show` renders before it returns. A broken diagram comes back to the agent as an error
  with a line number, so the agent fixes it instead of telling you it worked.
- For Claude Code, an optional **Stop hook** also picks up diagram blocks from its answers,
  without the agent doing anything: ` ```mermaid `, ` ```plantuml ` / `puml` / `c4plantuml`
  (`@startuml` is added when missing), ` ```structurizr `, ` ```d2 `, ` ```dot ` / `graphviz`,
  also inside list items.
- **The viewer follows the chat.** Scroll the agent's conversation back and the viewer
  switches to the diagram on screen; scroll down and it follows the newest again.
- Every agent pane gets its own viewer, in every space, tab and herdr session.
- Renderers are configuration, not code: add a format by editing `renderers.toml`.

![PlantUML, D2, Graphviz and Mermaid in the viewer](docs/screenshots/formats.png)

![Scroll sync: the chat scrolled back to the checkout answer shows the sequence diagram (top); back at the bottom it shows the newest, the ER diagram (bottom)](docs/screenshots/scroll-sync.png)

## Approval modes and sandboxes

Diagrams and images live outside the project, in `~/.local/state/herdr-diagrams` (private,
`0700`). How that interacts with an agent's approval mode and sandbox:

| Route | Approval prompt? | Sandbox? |
|---|---|---|
| Claude Code **Stop hook** (`install-hook claude`) | Never: hooks run outside the agent's tool calls | Not affected |
| Agent runs **`herdr-diagram show`** (the skill) | Yes, unless the command is allow-listed or the mode auto-approves | Needs write access to the state folder; the viewer is opened by the plugin's daemon, so no socket access is needed |
| **Viewer, daemon, events** | Never: herdr runs them as the plugin | Not affected |

Per agent, to run `show` without prompts and inside a sandbox (✓ tested here, · from the docs).
Allow only `show` (and `list`): `render` and `export` write files to paths the caller
chooses, so they should keep asking.

| Agent | Allow the command | If its sandbox is on |
|---|---|---|
| Claude Code ✓ | `herdr-diagram allow claude` adds `Bash(herdr-diagram show:*)`, `Bash(herdr-diagram list:*)` and `Edit(~/.local/state/herdr-diagrams/**)` to `permissions.allow` | The `Edit` rule also makes the folder writable in the sandbox (tested with the bubblewrap sandbox on Linux) |
| Codex · | `prefix_rule(pattern=["herdr-diagram", "show"], decision="allow")` in `~/.codex/rules/default.rules` | An allow rule runs the command outside the sandbox. Or add the folder to `[sandbox_workspace_write] writable_roots` |
| opencode · | `"permission": {"bash": {"herdr-diagram show *": "allow"}}` in `opencode.json` | No sandbox |
| Copilot CLI · | `--allow-tool 'shell(herdr-diagram show:*)'` | Off by default; else add the folder to `sandbox.userPolicy.filesystem.readwritePaths` |
| agy · | `"permissions": {"allow": ["command(herdr-diagram show)"]}` in `~/.gemini/antigravity-cli/settings.json` | `"allow": ["write_file(~/.local/state/herdr-diagrams)"]`, or `unsandboxed(herdr-diagram show)` |
| Gemini CLI · | `"tools": {"allowed": ["run_shell_command(herdr-diagram show)"]}` | Container sandbox: mount the folder with `SANDBOX_MOUNTS` |

Modes:

- **Ask / default**: one prompt per `show` until the command is allow-listed.
- **Auto** (Claude's classifier, Codex `on-request`): usually runs; the allow rule removes the guesswork.
- **Yolo / bypass / full access**: runs without prompts. No sandbox, so nothing else is needed.
- **Sandboxed** (Claude `sandbox.enabled`, Codex `workspace-write`): `show` fails with exit
  status 4 and a message that names the fix, until the folder is writable. The skill then
  tells the agent to put the diagram in its answer instead, where the Stop hook (Claude)
  still picks it up.

Why the folder is outside the project: diagrams are per pane and per session, must not end
up in commits, and the viewer and daemon (outside any sandbox) must find them for every
project. `export` writes into the project only when you ask for it.

## Terminals

The viewer draws with the Kitty graphics protocol, and herdr forwards only that protocol (no
Sixel, no iTerm2 inline images). The outer terminal decides, and the plugin checks it for you:
it reads the environment of the herdr client running in your terminal, and reports the
result as a herdr notification after install (and at herdr startup when it changed), in
`herdr-diagram doctor`, in the viewer pane and to the agent.

| Terminal | Status |
|---|---|
| Ghostty | Tested (1.3, Linux) |
| kitty | Should work: the protocol's reference implementation |
| WezTerm | Should work: implements the protocol; not tested here |
| Konsole, iTerm2 3.6+, Warp | Partial or recent protocol support; untested, may not support source-rectangle zoom |
| Alacritty, foot, GNOME Terminal and other VTE terminals, xterm, Windows Terminal, Terminal.app | No images. Everything else works; press `o` to open a diagram in your image viewer |

- Run herdr directly in the terminal. A tmux or zellij layer between them blocks the graphics.
- Over SSH it works when the terminal on your side supports the protocol: the graphics travel
  in the terminal stream. With `herdr --remote`, enable `kitty_graphics` on the client machine.
- `herdr-diagram doctor` shows the detected terminal, the OS, and whether herdr's
  `kitty_graphics` is on.
- When the terminal cannot show images, the viewer says so and still lists the diagrams;
  `o` opens one in your image viewer, `s` shows the source, `e` exports it.
- Detection wrong? Set `images = "on"` (or `"off"`) in the plugin config, or
  `HERDR_DIAGRAMS_IMAGES=on`.

## Platforms

| Platform | Status |
|---|---|
| Linux | Tested: Ghostty 1.3 + herdr 0.9.3 on Arch, all formats, Claude Code, opencode and Copilot CLI skill discovery |
| macOS | Supported, not yet tested on a Mac. Uses only POSIX APIs available there; uses `open`, `pbcopy`, `sips` and Chrome from `/Applications` where Linux uses `xdg-open`, `wl-copy`, ImageMagick and Chromium. If `python3` is Apple's 3.9, the command switches to a newer Python on `PATH` or from Homebrew. CI runs the tests on macOS. |
| Windows | Not supported yet. See [ADR-0010](docs/adr/0010-platform-support.md) for what is missing. The install step and the commands say so instead of failing obscurely. |

## Requirements

- Herdr 0.9.3 or later, with `[terminal] kitty_graphics = true` (the default)
- A terminal with the Kitty graphics protocol: Ghostty, kitty or WezTerm
- Python 3.11 or later, Node.js 18+ and npm
- Per format, as you need them:

  | Format | Tool | Arch | Debian/Ubuntu | macOS |
  |---|---|---|---|---|
  | Mermaid | bundled (`@mermaid-js/mermaid-cli`) | | | |
  | PlantUML (1.2024+ for the dark theme) | `plantuml` (Java) | `pacman -S plantuml` | [plantuml.jar](https://plantuml.com/download) wrapper; apt's is too old | `brew install plantuml` |
  | Graphviz | `dot` | `pacman -S graphviz` | `apt install graphviz` | `brew install graphviz` |
  | D2 | `d2` | `mise use -g d2` | [install script](https://d2lang.com/tour/install) | `brew install d2` |
  | Structurizr | `structurizr-cli` + PlantUML | [release zip](https://github.com/structurizr/cli/releases) | same | `brew install structurizr-cli` |
  | SVG/JPEG images | `rsvg-convert`, `magick` or `ffmpeg` | usually present | `apt install librsvg2-bin` | `brew install librsvg` |

## Install

```sh
herdr plugin install jellespijker/herdr-diagrams
herdr plugin action invoke herdr-diagrams.install-skill
herdr plugin action invoke herdr-diagrams.doctor
```

`install-skill` links the skill and the `herdr-diagram` command (symlinks, nothing copied):

| Link | Used by |
|---|---|
| `~/.agents/skills/herdr-diagrams` | Codex, opencode, Copilot CLI, Gemini CLI |
| `~/.claude/skills/herdr-diagrams` | Claude Code |
| `~/.gemini/config/skills/herdr-diagrams` | Antigravity CLI (agy), if installed |
| `~/.local/bin/herdr-diagram` | the command line |

Optional, for Claude Code:

```sh
herdr-diagram install-hook claude      # show diagrams from its answers automatically
herdr-diagram allow claude             # let it run `show` without prompts, also sandboxed
```

Both edit `~/.claude/settings.json` (or the file it links to), keep its file mode and write a
backup. `--uninstall` reverts each.

Keybinding: plugins cannot register keys themselves; herdr's menu shows the bindings in
`~/.config/herdr/config.toml`. Add one with the action "Diagrams: add keybinding", or:

```sh
herdr-diagram setup-keys                 # prefix+i opens the viewer beside the current pane
herdr-diagram setup-keys --key prefix+m  # another key; taken keys are refused with a suggestion
herdr-diagram setup-keys --remove
```

It writes a marked `[[keys.command]]` block (with a backup), checks the file with
`herdr config check` and reloads herdr.

## Use

Ask your agent to explain something "with a diagram". Or show one yourself from any pane:

```sh
herdr-diagram show docs/architecture.dsl
herdr-diagram show --title "Login" - <<'EOF'
sequenceDiagram
    User->>App: open
    App->>Auth: authorize
EOF
herdr-diagram show screenshot.png
```

When a diagram is broken, nothing is queued and the error goes to whoever called `show`:

```
$ herdr-diagram show checkout.mmd
herdr-diagram show: mermaid render failed: mmdc exited with 1
Error: Parse error on line 3:
...t  checkout --> pay[Pay]
---------------------^
Expecting 'SQE', 'DOUBLECIRCLEEND', 'PE', ... got 'SQS'
Nothing was queued. Fix the diagram and run show again.
```

### Viewer keys

| Key | Action |
|---|---|
| `j` / `k` | Next / previous diagram (pauses scroll sync) |
| `i` | List of all diagrams of this pane; `Enter` shows one, `e` exports it |
| `e` / `E` | Export this diagram / all diagrams (PNG, SVG and source) |
| `h` / `l` | Previous / next view of a Structurizr workspace |
| `+` / `-` / `0` | Zoom in / out / fit |
| arrows | Pan when zoomed |
| mouse wheel | Zoom in / out around the pointer |
| drag (left button) | Pan |
| Shift+wheel, horizontal wheel | Pan sideways |
| double-click | Fit |
| middle click | Open in your image viewer |
| click in the list (`i`) | Show that diagram |
| `s` | Toggle the diagram source |
| `o` | Open the image in your default viewer |
| `y` | Copy the image path |
| `r` | Follow the newest diagram again |
| `t` | Resume scroll sync after manual navigation, or turn it off and on |
| `q` | Close the viewer |

The viewer asks the terminal for mouse reports (like vim or htop do); herdr passes them to the
pane. Zoom and pan only move the image, so they stay smooth even for large diagrams.

New diagrams take over the viewer until you move away from the newest; after that the
header counts them (`+2 new (r)`) instead.

**Scroll sync** (`⇅` in the header): about once a second the viewer reads the text visible
in the agent's pane. It looks for the `[diagram: <title>]` line the skill asks agents to
write next to each diagram, or for the diagram's own source lines when the agent printed
the diagram in its answer. The bottom-most match wins. Navigating yourself (`j`, `k`, `g`, the
list) pauses sync (`⇅ paused`) until you press `t` or `r`.

### Export

`e` in the viewer, or `herdr-diagram export` from a shell, writes each diagram as PNG, SVG
and its source file (`.mmd`, `.puml`, `.dsl`, `.d2`, `.dot`), in the light theme, to
`diagrams/` in the agent's working directory:

```sh
herdr-diagram export                     # newest diagram of this pane
herdr-diagram export --all --svg         # every diagram, SVG only
herdr-diagram export -n 2 -d docs/img    # second newest, into docs/img
herdr-diagram export --all --archived    # include diagrams of earlier sessions
```

Existing files with the same content are left alone; a different file with the same name
gets a `-2` suffix. Export never writes through a symlink, and image items export as PNG
only (their path comes from the agent, so the original file is never copied).

### Cleanup

Diagrams are archived, not deleted. `gc` (also run when herdr starts) deletes diagrams,
archives and cached images older than 7 days:

| When | What happens |
|---|---|
| A new agent session starts in a pane | Diagrams of earlier sessions in that pane are archived; the viewer shows the new session only |
| A pane closes | Its viewer closes; its diagrams are archived |
| A pane moves to another tab or space | Its diagrams move with it |
| herdr starts (plugin startup) | Diagrams of panes that no longer exist are archived; `gc` runs (7 days) |

### Commands

```
herdr-diagram show [FILE|-]      queue a diagram or image for the viewer beside this pane
herdr-diagram list               diagrams shown from this pane
herdr-diagram render FILE -o X   render to a PNG file, no viewer
herdr-diagram export             write PNG, SVG and source files (see Export)
herdr-diagram open               open the viewer beside this pane
herdr-diagram doctor             check herdr, graphics, renderers and links
herdr-diagram install-skill      link skill and CLI (--status, --uninstall)
herdr-diagram setup-keys         herdr keybinding for the viewer (default prefix+i)
herdr-diagram install-hook claude  automatic Stop hook for Claude Code
herdr-diagram allow claude         permission rules for Claude Code (no prompts, sandbox)
herdr-diagram gc                 delete diagrams, archives and images older than 7 days
```

## Configure

Files live in the plugin config dir (`herdr plugin config-dir herdr-diagrams`):

- `config.toml`:
  - `theme = "dark"` (default) or `"light"`. `HERDR_DIAGRAMS_THEME` overrides it.
  - `scroll_sync = true` (default) or `false`.
  - `export_dir = "{cwd}/diagrams"` (default); `{cwd}` is the agent's working directory,
    `{home}` your home directory.
  - `export_theme = "light"` (default) or `"dark"`.
  - `images = "auto"` (default), `"on"` or `"off"`: override the terminal detection.
- `renderers.toml`: override a bundled renderer or add one. Example, a self-hosted
  [Kroki](https://kroki.io) for BPMN:

  ```toml
  [bpmn]
  detect = ["bpmn"]
  argv = ["curl", "-sf", "--data-binary", "@{in}", "http://localhost:8000/bpmn/png", "-o", "{out}"]
  in_ext = "bpmn"
  out = "png"
  ```

State lives in `~/.local/state/herdr-diagrams` (`HERDR_DIAGRAMS_HOME` overrides it):
diagrams per herdr session and pane under `spool/<session>/<pane>/`, archived ones under
`archive/`, rendered images in `cache/`, the last 50 herdr events in `events.log`.

## Security

Diagram sources come from agents, so they are treated as untrusted input:

- Renderers run as argv lists, never through a shell.
- PlantUML runs with `PLANTUML_SECURITY_PROFILE=SANDBOX`: no file includes, no URL fetches.
- Structurizr sources using `!script`, `!plugin` or a remote `!include`, and D2 sources with
  remote icons or images, are refused (`reject` in `renderers.toml`).
- Mermaid's headless Chromium keeps its sandbox and has all network traffic sent to a
  dead proxy.
- Nothing is sent to an online renderer. Add one yourself only if you trust it with your
  diagrams.
- Limits: 1 MiB source, 20 MiB image, 30 to 90 s render time; on timeout the renderer's
  whole process group (Chromium, Java) is killed.
- Titles, sources and renderer errors are stripped of terminal control characters before
  they are drawn.
- `install-hook` edits the target of a symlinked `settings.json`, keeps its file mode and
  writes a backup.

## Troubleshooting

`herdr-diagram doctor` checks everything below.

- **The viewer shows nothing where the image should be.** Your terminal does not speak
  the Kitty graphics protocol, or `kitty_graphics` is off in herdr's config. Press `o` to
  open the image externally.
- **`renderer not installed: plantuml`.** Install the tool from the table above.
- **Mermaid fails with "could not start its sandbox" (Ubuntu 23.10+).** Ubuntu restricts the
  user namespaces Chromium's sandbox needs: `sudo sysctl -w
  kernel.apparmor_restrict_unprivileged_userns=0` (persist it in `/etc/sysctl.d`), or set
  `PUPPETEER_EXECUTABLE_PATH` to an installed Chrome or Chromium.
- **Mermaid fails with a browser error.** Run `npx puppeteer browsers install
  chrome-headless-shell` in the plugin directory, or install Chromium; the plugin falls
  back to a system Chromium or Chrome.
- **The agent does not use the skill.** Check `herdr-diagram install-skill --status`,
  then restart the agent. For Claude Code, `install-hook claude` works without the skill.

## Design

- [Specification](docs/spec.md)
- [Architecture decision records](docs/adr/)

## Development

```sh
npm install                       # mermaid-cli
uv sync                           # pytest, ruff, import-linter
uv run pytest -q
uv run ruff check src tests
PYTHONPATH=src uv run lint-imports
herdr plugin link "$PWD"
```

The runtime uses the Python standard library only.

## Related

- [hx-w/herdr-visuals](https://github.com/hx-w/herdr-visuals): Mermaid and LaTeX previews
  for Codex sessions.
- [haretoke/herdr-image-viewer](https://github.com/haretoke/herdr-image-viewer): the images
  an agent reads, with thumbnails.

## License

MIT
