#!/bin/sh
# Build step run by `herdr plugin install`: mermaid-cli and its headless browser.
set -eu
case "$(uname -s)" in
  Linux|Darwin) ;;
  *) echo "herdr-diagrams supports Linux and macOS; $(uname -s) is not supported yet." >&2; exit 1 ;;
esac
npm ci --no-audit --no-fund
# npm may skip puppeteer's postinstall; fetch the browser explicitly. If that
# fails, rendering falls back to a system Chromium/Chrome (see render.py).
npx --yes puppeteer browsers install chrome-headless-shell >/dev/null 2>&1 || \
  echo "herdr-diagrams: could not download chrome-headless-shell; will use system Chromium" >&2

echo "herdr-diagrams installed. Checking this machine:"
python3 bin/herdr-diagram doctor --brief || true
python3 bin/herdr-diagram doctor --notify >/dev/null 2>&1 || true  # visible toast in herdr
