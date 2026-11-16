// Native Herdr-App GPUI diagram viewer for herdr-diagrams (Mermaid, Structurizr C4, PlantUML, D2, Graphviz).
import { View, div, svg, image } from "gpui-kit";
import { v_flex, h_flex, Editor, EditorState } from "gpui-base";
import {
  spaces,
  panes,
  focused,
  exec,
  run,
  theme,
  settings,
  props,
  appHome,
  watchFolder,
  nextCommand,
  notify,
} from "herdr";
import * as fs from "fs/promises";

const B64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const B64_LOOKUP = new Uint8Array(256);
for (let i = 0; i < B64_CHARS.length; i++) B64_LOOKUP[B64_CHARS.charCodeAt(i)] = i;

function decodeBase64(b64) {
  const clean = b64.replace(/[\r\n\s]/g, "");
  const len = clean.length;
  if (!len) return new Uint8Array(0);
  const pad = clean.endsWith("==") ? 2 : clean.endsWith("=") ? 1 : 0;
  const out = new Uint8Array(((len * 3) >> 2) - pad);
  let p = 0;
  for (let i = 0; i < len; i += 4) {
    const a = B64_LOOKUP[clean.charCodeAt(i)];
    const b = B64_LOOKUP[clean.charCodeAt(i + 1)];
    const c = B64_LOOKUP[clean.charCodeAt(i + 2)];
    const d = B64_LOOKUP[clean.charCodeAt(i + 3)];
    const triple = (a << 18) | (b << 12) | (c << 6) | d;
    if (p < out.length) out[p++] = (triple >> 16) & 0xff;
    if (p < out.length) out[p++] = (triple >> 8) & 0xff;
    if (p < out.length) out[p++] = triple & 0xff;
  }
  return out;
}

function splitTarget(raw, fallbackMachine) {
  if (!raw) return { pane: null, on: fallbackMachine ?? null };
  const s = String(raw);
  if (s.includes("/")) {
    const idx = s.indexOf("/");
    return { on: s.slice(0, idx) || null, pane: s.slice(idx + 1) || null };
  }
  return { on: fallbackMachine ?? null, pane: s };
}

function resolveTarget(followFocus, manualBind, lastTarget) {
  const activeSpace = spaces().find((s) => s.active);
  const defaultMachine = activeSpace?.machine ?? null;
  const bound = manualBind ?? props()?.bind;
  if (!followFocus && bound) {
    return splitTarget(bound, defaultMachine);
  }
  const f = focused();
  const allPanes = panes();
  const activeTab = f?.tab || activeSpace?.tabs?.find((tb) => tb.active)?.id || null;
  const focusedTermPane = f?.pane ? allPanes.find((p) => p.pane === f.pane && p.terminal) : null;
  const tabTermPane = activeTab ? allPanes.find((p) => p.tab === activeTab && p.terminal) : null;
  const rawTerm =
    focusedTermPane?.terminal ||
    f?.terminal ||
    tabTermPane?.terminal ||
    (lastTarget?.pane
      ? lastTarget.on
        ? `${lastTarget.on}/${lastTarget.pane}`
        : lastTarget.pane
      : null) ||
    f?.agent ||
    bound ||
    null;
  return splitTarget(rawTerm, defaultMachine);
}

function formatTime(epochSec) {
  if (!epochSec) return "";
  const d = new Date(epochSec * 1000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export default class Diagrams extends View {
  init(_props, cx) {
    this.handle = cx.focus_handle();
    this.size = { width: 640, height: 480 };
    this.items = [];
    this.pane = null;
    this.on = null;
    this.lastTarget = null;
    this.panes = [];
    this.index = 0;
    this.selectedId = null;
    this.lastSyncIndex = null;
    this.viewIndex = 0;
    this.zoom = 1.0;
    this.panX = 0;
    this.panY = 0;
    this.drag = null;
    this.showSource = false;
    this.showList = false;
    this.followSync = true;
    this.followFocus = !props()?.bind;
    this.manualBind = props()?.bind ?? null;
    this.loading = false;
    this.error = null;
    this.watchedSpool = null;
    this.cachedSet = new Set();
    this.sourceEditor = null;
    this.sourceItemId = null;

    cx.spawn(async (cx) => {
      for (;;) {
        const cmd = await nextCommand();
        if (cmd === "focus") {
          this.handle.focus();
          cx.notify();
        } else if (cmd === "refresh") {
          this.refresh(cx);
        }
      }
    });

    this.refresh(cx);
    cx.timer.every(1500, (cx) => this.refresh(cx));
  }

  watchLocalSpool(spoolDir, cx) {
    if (!spoolDir || this.on || this.watchedSpool === spoolDir) return;
    this.watchedSpool = spoolDir;
    cx.spawn(async (cx) => {
      try {
        while (this.watchedSpool === spoolDir && !this.on) {
          await watchFolder(spoolDir);
          this.refresh(cx);
        }
      } catch {
        if (this.watchedSpool === spoolDir) this.watchedSpool = null;
      }
    });
  }

  async ensureRemoteArtifacts(item, on, cx) {
    if (!item || !item.artifacts?.length) return;
    const cacheDir = `${appHome()}/data/diagrams-cache`;
    let changed = false;
    for (const art of item.artifacts) {
      if (!art?.name || this.cachedSet.has(art.name)) continue;
      const localPath = `${cacheDir}/${art.name}`;
      if (await fs.exists(localPath).catch(() => false)) {
        this.cachedSet.add(art.name);
        continue;
      }
      if (!on) continue;
      const res = await exec("herdr-diagram", ["app-artifact", art.name], { on }).catch(() => null);
      if (res?.code === 0 && res.stdout) {
        await fs.mkdir(cacheDir, { recursive: true }).catch(() => {});
        const bytes = decodeBase64(res.stdout);
        if (bytes.length > 0) {
          await fs.writeFile(localPath, bytes).catch(() => {});
          this.cachedSet.add(art.name);
          changed = true;
        }
      }
    }
    if (changed) cx.notify();
  }

  refresh(cx) {
    if (this.loading) return;
    const target = resolveTarget(this.followFocus, this.manualBind, this.lastTarget);
    if (target.pane) this.lastTarget = target;
    const wantTheme = settings()?.dark === false ? "light" : "dark";
    const args = ["app-state", "--theme", wantTheme];
    if (target.pane) args.push("--pane", target.pane);
    if (!target.on) args.push("--sync-cache");

    this.loading = true;
    cx.spawn(async (cx) => {
      try {
        const res = await exec("herdr-diagram", args, { on: target.on });
        if (res.code !== 0) {
          this.error = (res.stderr || res.stdout || "herdr-diagram app-state failed").trim();
          return;
        }
        const state = JSON.parse(res.stdout || "{}");
        const prevCount = this.items.length;
        const prevLastId = prevCount ? this.items[prevCount - 1]?.id : null;
        this.items = Array.isArray(state.items) ? state.items : [];
        this.pane = state.pane ?? target.pane;
        this.on = target.on;
        this.panes = Array.isArray(state.panes) ? state.panes : [];
        this.error = null;

        if (this.items.length === 0) {
          this.index = 0;
          this.selectedId = null;
          this.viewIndex = 0;
        } else {
          const newLastId = this.items[this.items.length - 1]?.id ?? null;
          const hasNewItem = prevCount === 0 || (newLastId && newLastId !== prevLastId);
          const validSync =
            typeof state.sync_index === "number" &&
            state.sync_index >= 0 &&
            state.sync_index < this.items.length;
          const syncChanged = validSync && state.sync_index !== this.lastSyncIndex;
          if (validSync) this.lastSyncIndex = state.sync_index;

          if (this.followSync && (hasNewItem || syncChanged)) {
            const nextIdx = validSync ? state.sync_index : this.items.length - 1;
            if (nextIdx !== this.index || prevCount === 0) {
              this.index = nextIdx;
              this.selectedId = this.items[this.index]?.id ?? null;
              this.viewIndex = 0;
            }
          } else {
            const idxById = this.selectedId
              ? this.items.findIndex((it) => it.id === this.selectedId)
              : -1;
            if (idxById >= 0) {
              this.index = idxById;
            } else if (this.index >= this.items.length) {
              this.index = Math.max(0, this.items.length - 1);
              this.viewIndex = 0;
            }
            this.selectedId = this.items[this.index]?.id ?? null;
          }
        }

        const current = this.items[this.index];
        if (current) {
          const maxViews = Math.max(1, current.artifacts?.length ?? 1);
          if (this.viewIndex >= maxViews) this.viewIndex = 0;
          await this.ensureRemoteArtifacts(current, target.on, cx);
        }
        if (state.spool_dir && !target.on) {
          this.watchLocalSpool(state.spool_dir, cx);
        }
      } catch (e) {
        this.error = String(e);
      } finally {
        this.loading = false;
        cx.notify();
      }
    });
  }

  selectItem(nextIndex, manual, cx) {
    if (!this.items.length) return;
    const clamped = Math.max(0, Math.min(this.items.length - 1, nextIndex));
    if (clamped !== this.index) {
      this.panX = 0;
      this.panY = 0;
      this.drag = null;
    }
    this.index = clamped;
    this.selectedId = this.items[this.index]?.id ?? null;
    this.viewIndex = 0;
    if (manual) this.followSync = false;
    const current = this.items[this.index];
    if (current) {
      cx.spawn(async (cx) => {
        await this.ensureRemoteArtifacts(current, this.on, cx);
      });
    }
    cx.notify();
  }

  selectView(delta, cx) {
    const current = this.items[this.index];
    const count = current?.artifacts?.length ?? 0;
    if (count <= 1) return;
    this.viewIndex = (this.viewIndex + delta + count) % count;
    this.panX = 0;
    this.panY = 0;
    this.drag = null;
    cx.notify();
  }

  adjustZoom(factor, reset, cx, focalOffset) {
    if (reset) {
      this.zoom = 1.0;
      this.panX = 0;
      this.panY = 0;
      this.drag = null;
    } else {
      const prevZoom = this.zoom;
      const nextZoom = Math.max(0.25, Math.min(6.0, Math.round(prevZoom * factor * 100) / 100));
      const ratio = nextZoom / prevZoom;
      const vx = focalOffset?.x ?? 0;
      const vy = focalOffset?.y ?? 0;
      this.panX = Math.round(vx - (vx - this.panX) * ratio);
      this.panY = Math.round(vy - (vy - this.panY) * ratio);
      this.zoom = nextZoom;
    }
    cx.notify();
  }

  panBy(dx, dy, cx) {
    this.panX = Math.round(this.panX + dx);
    this.panY = Math.round(this.panY + dy);
    cx.notify();
  }

  startDrag(e, cx) {
    cx.stop_propagation();
    this.handle.focus();
    if (e.button === "left" && (e.click_count ?? 1) >= 2) {
      this.adjustZoom(1.0, true, cx);
      return;
    }
    this.drag = {
      startX: e.position.x,
      startY: e.position.y,
      origPanX: this.panX,
      origPanY: this.panY,
    };
    cx.notify();
  }

  moveDrag(e, cx) {
    if (!this.drag) return;
    const dx = e.position.x - this.drag.startX;
    const dy = e.position.y - this.drag.startY;
    this.panX = Math.round(this.drag.origPanX + dx);
    this.panY = Math.round(this.drag.origPanY + dy);
    cx.notify();
  }

  endDrag(_e, cx) {
    if (!this.drag) return;
    this.drag = null;
    cx.notify();
  }

  exportCurrent(cx) {
    const current = this.items[this.index];
    if (!current) return;
    const nFromNewest = this.items.length - this.index;
    const args = ["export", "-n", String(nFromNewest)];
    if (this.pane) args.push("--pane", this.pane);
    cx.spawn(async (cx) => {
      const res = await exec("herdr-diagram", args, { cwd: current.cwd || undefined, on: this.on }).catch(
        (e) => ({ code: 1, stdout: "", stderr: String(e) })
      );
      if (res.code === 0) {
        const files = res.stdout.trim().split("\n").filter(Boolean);
        notify({
          title: "Diagram exported",
          body: files[0] || current.title,
          level: "success",
        });
      } else {
        notify({
          title: "Export failed",
          body: (res.stderr || res.stdout || "Could not export diagram").trim(),
          level: "error",
        });
      }
      cx.notify();
    });
  }

  handleKey(e, cx) {
    const k = typeof e.key === "string" ? e.key : e.keystroke?.key ?? e.keystroke;
    const ch = e.key_char;
    const shift = Boolean(e.modifiers?.shift);
    const panStep = 64;

    if (shift && (k === "left" || k === "h" || k === "H")) {
      this.panBy(panStep, 0, cx);
    } else if (shift && (k === "right" || k === "l" || k === "L")) {
      this.panBy(-panStep, 0, cx);
    } else if (shift && (k === "up" || k === "k" || k === "K")) {
      this.panBy(0, panStep, cx);
    } else if (shift && (k === "down" || k === "j" || k === "J")) {
      this.panBy(0, -panStep, cx);
    } else if (k === "j" || k === "down") {
      this.selectItem(this.index + 1, true, cx);
    } else if (k === "k" || k === "up") {
      this.selectItem(this.index - 1, true, cx);
    } else if (k === "h" || k === "left") {
      this.selectView(-1, cx);
    } else if (k === "l" || k === "right") {
      this.selectView(1, cx);
    } else if (k === "+" || k === "=" || ch === "+" || ch === "=") {
      this.adjustZoom(1.25, false, cx);
    } else if (k === "-" || ch === "-") {
      this.adjustZoom(0.8, false, cx);
    } else if (k === "0" || ch === "0") {
      this.adjustZoom(1.0, true, cx);
    } else if (k === "c") {
      this.panX = 0;
      this.panY = 0;
      this.drag = null;
      cx.notify();
    } else if (k === "s") {
      this.showSource = !this.showSource;
      cx.notify();
    } else if (k === "i") {
      this.showList = !this.showList;
      cx.notify();
    } else if (k === "t" || k === "r" || (shift && k === "g") || ch === "G") {
      this.followSync = true;
      this.selectItem(this.items.length - 1, false, cx);
      this.refresh(cx);
    } else if (k === "g") {
      this.selectItem(0, true, cx);
    } else if (k === "e") {
      this.exportCurrent(cx);
    }
  }

  ensureEditor(item, t) {
    if (!item?.source) return null;
    if (this.sourceItemId !== item.id || !this.sourceEditor) {
      this.sourceItemId = item.id;
      this.sourceEditor = EditorState.new({
        language: item.format === "structurizr" ? "yaml" : "markdown",
        value: item.source,
        readonly: true,
        font_family: settings()?.font ?? "JetBrains Mono",
        syntax: {
          keyword: t.ansi5,
          string: t.ansi2,
          comment: t.dim,
          number: t.ansi3,
          type: t.ansi4,
          function: t.ansi6,
        },
      });
    }
    return this.sourceEditor;
  }

  render() {
    const t = theme();
    const stop = (_e, cx) => cx.stop_propagation();
    const current = this.items[this.index] ?? null;
    const views = current?.artifacts ?? [];
    const activeArt = views[this.viewIndex] ?? views[0] ?? null;
    const paneBadge = this.on ? `${this.on}/${this.pane ?? "_"}` : this.pane ?? "auto";

    const btn = (id, label, active, onClick) =>
      div()
        .id(id)
        .h(24)
        .px(7)
        .flex_none()
        .flex()
        .items_center()
        .justify_center()
        .rounded(5)
        .text_size(11.5)
        .bg(active ? t.selected : t.raised)
        .border(1)
        .border_color(active ? t.accent : t.border)
        .text_color(active ? t.foreground : t.muted)
        .hover((s) => s.bg(t.hover).text_color(t.foreground))
        .on_mouse_down("left", stop)
        .on_click(onClick)
        .child(label);

    const header = h_flex()
      .h(36)
      .w_full()
      .px(10)
      .gap(6)
      .items_center()
      .justify_between()
      .bg(t.chrome)
      .border_b(1)
      .border_color(t.border)
      .child(
        h_flex()
          .gap(7)
          .items_center()
          .min_w(0)
          .flex_1()
          .child(svg("mods/diagrams/diagram.svg").size(14).flex_none().text_color(t.accent))
          .child(
            div()
              .font_semibold()
              .text_size(12.5)
              .text_color(t.foreground)
              .truncate()
              .child(current ? current.title : "Diagrams")
          )
          .when(Boolean(current), (el) =>
            el.child(
              div()
                .px(5)
                .py(1)
                .rounded(4)
                .bg(t.raised)
                .text_size(10.5)
                .text_color(t.dim)
                .flex_none()
                .child(`${current.format} · ${this.index + 1}/${this.items.length}`)
            )
          )
      )
      .child(
        h_flex()
          .gap(4)
          .items_center()
          .flex_none()
          .when(this.items.length > 1, (el) =>
            el
              .child(btn("prev-item", "‹", false, (_e, cx) => this.selectItem(this.index - 1, true, cx)))
              .child(btn("next-item", "›", false, (_e, cx) => this.selectItem(this.index + 1, true, cx)))
          )
          .child(
            btn("toggle-sync", this.followSync ? "Sync ●" : "Sync ○", this.followSync, (_e, cx) => {
              this.followSync = !this.followSync;
              if (this.followSync) this.refresh(cx);
              else cx.notify();
            })
          )
          .child(
            btn("toggle-list", `List (${this.items.length})`, this.showList, (_e, cx) => {
              this.showList = !this.showList;
              cx.notify();
            })
          )
          .child(
            btn("toggle-src", "Source", this.showSource, (_e, cx) => {
              this.showSource = !this.showSource;
              cx.notify();
            })
          )
          .when(Boolean(current), (el) =>
            el.child(btn("export-item", "Export", false, (_e, cx) => this.exportCurrent(cx)))
          )
      );

    const subbar = h_flex()
      .h(28)
      .w_full()
      .px(10)
      .gap(6)
      .items_center()
      .justify_between()
      .bg(t.surface)
      .border_b(1)
      .border_color(t.border)
      .text_size(11)
      .child(
        h_flex()
          .gap(6)
          .items_center()
          .child(
            div()
              .id("toggle-follow-focus")
              .px(6)
              .py(1)
              .rounded(4)
              .bg(this.followFocus ? t.selected : t.raised)
              .text_color(this.followFocus ? t.foreground : t.muted)
              .hover((s) => s.bg(t.hover))
              .on_click((_e, cx) => {
                this.followFocus = !this.followFocus;
                this.refresh(cx);
              })
              .child(`Pane: ${paneBadge}${this.followFocus ? " (follow)" : ""}`)
          )
          .when(views.length > 1, (el) =>
            el.child(
              h_flex()
                .gap(4)
                .items_center()
                .child(btn("prev-view", "◀", false, (_e, cx) => this.selectView(-1, cx)))
                .child(
                  div()
                    .px(6)
                    .text_color(t.foreground)
                    .child(`View ${this.viewIndex + 1}/${views.length}`)
                )
                .child(btn("next-view", "▶", false, (_e, cx) => this.selectView(1, cx)))
            )
          )
      )
      .child(
        h_flex()
          .gap(4)
          .items_center()
          .when(this.panX !== 0 || this.panY !== 0, (el) =>
            el.child(
              btn("pan-center", "Center", false, (_e, cx) => {
                this.panX = 0;
                this.panY = 0;
                this.drag = null;
                cx.notify();
              })
            )
          )
          .child(btn("zoom-out", "−", false, (_e, cx) => this.adjustZoom(0.8, false, cx)))
          .child(
            btn(
              "zoom-reset",
              `${Math.round(this.zoom * 100)}%`,
              this.zoom !== 1.0 || this.panX !== 0 || this.panY !== 0,
              (_e, cx) => this.adjustZoom(1.0, true, cx)
            )
          )
          .child(btn("zoom-in", "+", false, (_e, cx) => this.adjustZoom(1.25, false, cx)))
      );

    const viewW = Math.max(200, (this.size?.width ?? 640) - (this.showList ? 210 : 0));
    const viewH = Math.max(160, (this.size?.height ?? 480) - 64);
    const fitW = Math.max(160, viewW - 32);
    const fitH = Math.max(120, viewH - 32);

    let bodyContent;
    if (this.error && !current) {
      bodyContent = v_flex()
        .size_full()
        .p(20)
        .gap(8)
        .items_center()
        .justify_center()
        .child(div().font_semibold().text_color(t.blocked).child("Could not load diagrams"))
        .child(div().text_size(12).text_color(t.muted).child(this.error));
    } else if (!current) {
      bodyContent = v_flex()
        .size_full()
        .p(24)
        .gap(8)
        .items_center()
        .justify_center()
        .child(svg("mods/diagrams/diagram.svg").size(28).text_color(t.dim))
        .child(div().font_semibold().text_size(13).text_color(t.foreground).child("No diagrams queued yet"))
        .child(
          div()
            .text_size(12)
            .text_color(t.muted)
            .child("Ask an agent for a diagram or run `herdr-diagram show <file>` in a terminal.")
        );
    } else if (!current.ok) {
      bodyContent = v_flex()
        .size_full()
        .p(16)
        .gap(8)
        .overflow_y_scrollbar()
        .child(
          div()
            .font_semibold()
            .text_color(t.blocked)
            .child(`${current.format} render error: ${current.error || "failed"}`)
        )
        .when(Boolean(current.detail), (el) =>
          el.child(
            div()
              .p(10)
              .rounded(6)
              .bg(t.raised)
              .border(1)
              .border_color(t.border)
              .text_size(12)
              .text_color(t.foreground)
              .child(current.detail)
          )
        );
    } else if (this.showSource && current.source) {
      const editorState = this.ensureEditor(current, t);
      bodyContent = div()
        .size_full()
        .p(8)
        .child(
          editorState
            ? Editor.new(editorState).size_full()
            : div().size_full().overflow_y_scrollbar().text_size(12).child(current.source)
        );
    } else if (activeArt) {
      const artW = Math.max(1, activeArt.width || 1200);
      const artH = Math.max(1, activeArt.height || 800);
      const scale = Math.min(fitW / artW, fitH / artH) * this.zoom;
      const drawW = Math.max(48, Math.round(artW * scale));
      const drawH = Math.max(48, Math.round(artH * scale));
      const cardW = drawW + 18;
      const cardH = drawH + 18;
      const cardLeft = Math.round((viewW - cardW) / 2 + this.panX);
      const cardTop = Math.round((viewH - cardH) / 2 + this.panY);
      const startDrag = (e, cx) => this.startDrag(e, cx);
      const moveDrag = (e, cx) => this.moveDrag(e, cx);
      const endDrag = (e, cx) => this.endDrag(e, cx);
      bodyContent = div()
        .id("diagram-canvas")
        .relative()
        .size_full()
        .overflow_hidden()
        .when(Boolean(this.drag), (el) => el.cursor_grabbing())
        .when(!this.drag, (el) => el.cursor_grab())
        .on_mouse_down("left", startDrag)
        .on_mouse_down("middle", startDrag)
        .on_mouse_move(moveDrag)
        .on_mouse_up("left", endDrag)
        .on_mouse_up("middle", endDrag)
        .on_scroll_wheel((e, cx) => {
          const dx = e.delta?.x ?? 0;
          const dy = e.delta?.y ?? 0;
          if (e.modifiers?.shift) {
            this.panBy(dy !== 0 ? dy : dx, 0, cx);
            return;
          }
          if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) >= 1) {
            this.panBy(dx, 0, cx);
            return;
          }
          if (Math.abs(dy) >= 1) {
            const focal = e.local_position
              ? {
                  x: e.local_position.x - viewW / 2,
                  y: e.local_position.y - viewH / 2,
                }
              : null;
            this.adjustZoom(dy > 0 ? 1.12 : 0.89, false, cx, focal);
          }
        })
        .child(
          div()
            .id("diagram-card")
            .absolute()
            .left(cardLeft)
            .top(cardTop)
            .rounded(8)
            .p(8)
            .bg(t.background)
            .border(1)
            .border_color(t.border)
            .on_mouse_down("left", startDrag)
            .on_mouse_down("middle", startDrag)
            .on_mouse_move(moveDrag)
            .on_mouse_up("left", endDrag)
            .on_mouse_up("middle", endDrag)
            .child(image(activeArt.mod_path).w(drawW).h(drawH))
        );
    } else {
      bodyContent = v_flex()
        .size_full()
        .items_center()
        .justify_center()
        .child(div().text_color(t.muted).child("Rendering diagram…"));
    }

    const listDrawer = this.showList
      ? v_flex()
          .id("diagram-list-drawer")
          .w(210)
          .h_full()
          .flex_none()
          .bg(t.chrome)
          .border_r(1)
          .border_color(t.border)
          .p(6)
          .gap(4)
          .overflow_y_scrollbar()
          .children(
            this.items
              .map((it, idx) => ({ it, idx }))
              .reverse()
              .map(({ it, idx }) => {
                const selected = idx === this.index;
                return v_flex()
                  .id(`item-row-${it.id}`)
                  .w_full()
                  .p(7)
                  .gap(2)
                  .rounded(6)
                  .bg(selected ? t.selected : t.chrome)
                  .border(1)
                  .border_color(selected ? t.accent : t.chrome)
                  .hover((s) => s.bg(t.hover))
                  .on_click((_e, cx) => this.selectItem(idx, true, cx))
                  .child(
                    div()
                      .text_size(12)
                      .font_semibold()
                      .text_color(selected ? t.foreground : t.muted)
                      .truncate()
                      .child(it.title)
                  )
                  .child(
                    h_flex()
                      .justify_between()
                      .text_size(10.5)
                      .text_color(t.dim)
                      .child(div().child(it.format))
                      .child(div().child(formatTime(it.created)))
                  );
              })
          )
      : null;

    return v_flex()
      .id("diagrams-root")
      .size_full()
      .bg(t.background)
      .text_color(t.foreground)
      .track_focus(this.handle)
      .on_key_down((e, cx) => this.handleKey(e, cx))
      .on_mouse_move((e, cx) => this.moveDrag(e, cx))
      .on_mouse_up("left", (e, cx) => this.endDrag(e, cx))
      .on_mouse_up("middle", (e, cx) => this.endDrag(e, cx))
      .on_hover((hovered, cx) => {
        if (!hovered && this.drag) {
          this.drag = null;
          cx.notify();
        }
      })
      .on_size_change((size, cx) => {
        if (
          Math.abs((this.size?.width ?? 0) - size.width) > 2 ||
          Math.abs((this.size?.height ?? 0) - size.height) > 2
        ) {
          this.size = size;
          cx.notify();
        }
      })
      .child(header)
      .child(subbar)
      .child(
        h_flex()
          .flex_1()
          .w_full()
          .min_h(0)
          .when(Boolean(listDrawer), (el) => el.child(listDrawer))
          .child(div().flex_1().h_full().min_w(0).child(bodyContent))
      );
  }
}
