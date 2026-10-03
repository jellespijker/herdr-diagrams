#!/usr/bin/env python3
"""Set the version everywhere and turn the changelog's "Unreleased" section into it.

    scripts/bump_version.py 0.2.0

Updates herdr-plugin.toml, pyproject.toml, package.json, package-lock.json and uv.lock,
renames `## Unreleased` to `## 0.2.0 (today)` and opens a new empty `## Unreleased`.
Commit the result on a branch, open a pull request to main; see RELEASING.md.
"""

from __future__ import annotations

import datetime
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text()
    new, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        sys.exit(f"bump_version: pattern not found in {path.name}: {pattern}")
    path.write_text(new)


def main() -> int:
    if len(sys.argv) != 2 or not SEMVER.match(sys.argv[1].removeprefix("v")):
        sys.exit(__doc__)
    version = sys.argv[1].removeprefix("v")
    replace_once(ROOT / "herdr-plugin.toml", r'^version = "[^"]+"', f'version = "{version}"')
    replace_once(ROOT / "pyproject.toml", r'^version = "[^"]+"', f'version = "{version}"')
    replace_once(ROOT / "package.json", r'^  "version": "[^"]+"', f'  "version": "{version}"')
    subprocess.run(["npm", "install", "--package-lock-only", "--no-audit", "--no-fund", "--ignore-scripts"],
                   cwd=ROOT, check=True, capture_output=True)
    subprocess.run(["uv", "lock", "-q"], cwd=ROOT, check=True)

    changelog = ROOT / "CHANGELOG.md"
    text = changelog.read_text()
    match = re.search(r"^## Unreleased\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match or not match.group(1).strip():
        sys.exit("bump_version: CHANGELOG.md needs a non-empty '## Unreleased' section")
    today = datetime.date.today().isoformat()
    text = text.replace(match.group(0), f"## Unreleased\n\n## {version} ({today})\n{match.group(1)}", 1)
    changelog.write_text(text)
    print(f"version {version}; review CHANGELOG.md and commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
