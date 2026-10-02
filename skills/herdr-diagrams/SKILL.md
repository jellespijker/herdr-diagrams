---
name: herdr-diagrams
description: Render diagrams as real images in a herdr side pane. Use this whenever you are about to write a Mermaid, PlantUML, Structurizr, D2 or Graphviz diagram in an answer, or when explaining architecture, flows, sequences, state machines, data models or dependencies, and the environment has HERDR_ENV=1 (you run inside herdr). Instead of leaving the diagram as a text code block, pass it to `herdr-diagram show` so the user sees the picture next to the conversation. Also shows PNG, SVG and JPEG files.
---

# herdr-diagrams

The user runs you inside herdr, in a terminal that can show images. Text diagrams in your
answer stay text. To show a real image, pass the diagram to `herdr-diagram show`. It
renders the diagram and displays it in a viewer pane next to yours. The viewer opens by
itself the first time.

Check that you are inside herdr first: `test "$HERDR_ENV" = 1`. If you are not, skip this
skill. Use `herdr-diagram render FILE -o out.png` only if the user asks for an image file.

## Show a diagram

Pass the source on stdin with a heredoc and always give a short title:

```bash
herdr-diagram show --title "Login flow" - <<'EOF'
sequenceDiagram
    participant U as User
    participant A as App
    participant S as Auth server
    U->>A: open app
    A->>S: authorize (PKCE)
    S-->>A: tokens
EOF
```

You can also show a file. The format comes from the extension, or from `--format`:

```bash
herdr-diagram show --title "Container view" docs/architecture.dsl
herdr-diagram show --title "Screenshot" /tmp/screenshot.png
```

Successful output looks like this:
`mermaid: Login flow — shown in the viewer beside pane w1:p3`.

If rendering fails, the command exits with status 1 and prints the renderer's error,
for example a Mermaid parse error with a line number. Nothing is queued. Fix the source
and run `show` again; do not tell the user it was shown.

## Choose a format

| Need | Format | Example first line |
|---|---|---|
| Most diagrams: flow, sequence, class, state, ER, gantt, mindmap | Mermaid (default) | `flowchart LR` |
| UML in detail, complex sequence or activity diagrams | PlantUML | `@startuml` |
| C4 architecture model with several views from one model | Structurizr DSL | `workspace "Name" {` |
| Clean architecture or infrastructure overview | D2 | `direction: right` |
| Large or generated dependency graphs | Graphviz | `digraph G {` |

Rules of thumb:

- Keep each diagram small enough to read in a side pane: about 15 nodes. Split a big
  picture into several `show` calls.
- Prefer left-to-right layouts (`flowchart LR`, `rankdir=LR`, `direction: right`). The pane is
  often tall and narrow; then use top-down instead.
- Do not set colours or themes. The plugin renders for the user's terminal theme.
- A Structurizr workspace with several views shows each view; the user switches with `h`/`l`.

## Tell the user

After a successful `show`, put a marker line in your answer where the diagram belongs, with
the exact title you passed to `--title`:

```
[diagram: Login flow]
```

The viewer uses these markers to follow the chat: when the user scrolls back to an earlier
answer, the viewer switches to the diagram whose marker is on screen. Write one marker per
diagram, on its own line, next to the text that explains it.

In the viewer the user presses `j`/`k` to switch diagrams, `h`/`l` to switch views of one
Structurizr workspace, `+`/`-` to zoom and `o` to open the image. Do not paste the diagram
source into your answer as well, unless the user asked for the source. Do not print image
paths.

## Troubleshooting

- `command not found: herdr-diagram`: the plugin is not linked yet. Tell the user to run
  the herdr action "Diagrams: install skill and CLI for all agents".
- `renderer not installed: plantuml` (or d2, dot, structurizr-cli): use Mermaid instead,
  or tell the user which tool is missing.
- Shown, but the user sees nothing: ask the user to run `herdr-diagram doctor` and check
  that their terminal supports the Kitty graphics protocol (Ghostty, kitty, WezTerm).

When the user asks to save, commit or embed a diagram you showed, use `export` instead of
writing the files by hand; it renders in a light theme suitable for documents.

## Other commands

```bash
herdr-diagram list            # diagrams shown from this pane, newest first
herdr-diagram export --all    # save them as PNG, SVG and source into ./diagrams
herdr-diagram export -n 1 -d docs/img --svg   # newest one as SVG into docs/img
herdr-diagram open            # open the viewer pane again if the user closed it
herdr-diagram doctor          # check herdr, graphics support and renderers
```
