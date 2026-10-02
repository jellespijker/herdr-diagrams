# ADR-0004: Display with Kitty graphics in a herdr pane, not inline

- Status: Accepted
- Date: 2026-10-02

## Context

The preferred experience would be images inline in the agent's conversation. That is not
achievable from outside the harness:

- Claude Code, agy and similar TUIs redraw their whole screen. They do not emit graphics
  escape sequences from model output, and anything drawn from outside is overwritten on the
  next redraw or scroll.
- Kitty Unicode placeholders would survive redraws, but need placeholder characters with a
  foreground colour encoding the image ID inside the harness's own output. No harness
  renderer produces that.

What does work, on the target setup (Ghostty 1.3.1, herdr 0.9.3):

- herdr has `[terminal] kitty_graphics` (on by default) and forwards Kitty graphics from a
  pane to a capable outer terminal. herdr 0.9.2 removed the pane graphics API, so a pane
  draws by writing escapes to its own stdout.
- Prior plugins (haretoke/herdr-image-viewer, hx-w/herdr-visuals) use this approach.

## Decision

- The viewer runs in a herdr split pane beside the source pane and draws with the Kitty
  graphics protocol on its own stdout.
- An "open externally" key (`xdg-open`, macOS `open`) is always available.
- No sixel and no block-character fallback in v1. When graphics are unavailable the viewer
  shows source text and the open hint.
- The display is a function `show(png_path, cols, rows)`, not an interface. A second real
  backend is the trigger to introduce one.

## Consequences

- Works with every harness unchanged; the image sits beside the conversation, not in it.
- Requires a Kitty-graphics terminal (Ghostty, kitty, WezTerm). Other terminals get the
  external-open path only.
- Forwarding by herdr is not yet verified on this machine; milestone 2 starts with that
  check. If it fails, the fallback is a Hyprland window running the same viewer, without
  changes to ingest or render.
- If a harness ever supports images in its own output, an inline display can be added
  without touching the spool or renderers.

## Amendment (2026-10-02, after implementation)

- Forwarding is verified: on Ghostty 1.3.1 with herdr 0.9.3 the viewer pane shows images,
  and herdr reports the cell size in pixels through `TIOCGWINSZ`.
- Re-placing an already uploaded image after deleting its placement did not show reliably
  through herdr. The viewer therefore deletes and re-transmits the image on every draw.
  Artifacts are tens to hundreds of kilobytes, so the cost is small.

## Amendment (2026-10-02, 0.1.3)

Re-placing an uploaded image with a new size or source rectangle works through herdr, as
long as the screen is not cleared in between (tested: same id, `p=1`, new `c`/`r` and
`x,y,w,h`; also delete-placement then place). Only a full redraw (screen clear) re-transmits.
Zoom and pan, from keys or the mouse, now send a placement only, which keeps mouse wheel zoom
and drag panning responsive.
