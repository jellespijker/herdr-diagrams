#!/bin/sh
# Build step run by `herdr plugin install`: mermaid-cli and its headless browser.
set -eu
npm ci --no-audit --no-fund
# npm may skip puppeteer's postinstall; fetch the browser explicitly. If that
# fails, rendering falls back to a system Chromium/Chrome (see render.py).
npx --yes puppeteer browsers install chrome-headless-shell >/dev/null 2>&1 || \
  echo "herdr-diagrams: could not download chrome-headless-shell; will use system Chromium" >&2
