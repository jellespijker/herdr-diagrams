#!/usr/bin/env python3
"""Release guards for herdr-diagrams (see RELEASING.md).

    release_check.py                    consistency only (every CI run)
    release_check.py --release X.Y.Z    everything a release needs (release workflow)

Checks:
- the version is the same in herdr-plugin.toml, pyproject.toml, package.json and
  package-lock.json;
- CHANGELOG.md has a non-empty `## X.Y.Z (YYYY-MM-DD)` entry for that version;
with --release also:
- X.Y.Z is the version in the files, and is higher than the latest release tag;
- tag vX.Y.Z does not exist yet, locally or on origin;
- the "Unreleased" section of the changelog is empty (everything went into X.Y.Z);
- origin/release is an ancestor of HEAD, so the release branch can fast-forward.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def versions() -> dict[str, str]:
    lock = json.loads((ROOT / "package-lock.json").read_text())
    return {
        "herdr-plugin.toml": tomllib.loads((ROOT / "herdr-plugin.toml").read_text())["version"],
        "pyproject.toml": tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"],
        "package.json": json.loads((ROOT / "package.json").read_text())["version"],
        "package-lock.json": lock["version"],
        "package-lock.json packages[\"\"]": lock["packages"][""]["version"],
    }


def changelog_sections() -> dict[str, str]:
    """Heading key ("Unreleased" or "X.Y.Z") -> body text."""
    text = (ROOT / "CHANGELOG.md").read_text()
    sections = {}
    for match in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL):
        heading = match.group(1).strip()
        key = "Unreleased" if heading.lower() == "unreleased" else heading.split()[0]
        sections[key] = match.group(2).strip()
    return sections


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def latest_tag() -> tuple[int, ...] | None:
    tags = [t.strip()[1:] for t in git("tag", "--list", "v*").stdout.splitlines()]
    parsed = [tuple(map(int, m.groups())) for t in tags if (m := SEMVER.match(t))]
    return max(parsed) if parsed else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", metavar="X.Y.Z", help="check everything needed to release this version")
    args = parser.parse_args()
    errors = []

    found = versions()
    distinct = set(found.values())
    if len(distinct) != 1:
        errors.append("versions differ: " + ", ".join(f"{f}={v}" for f, v in found.items()))
    version = next(iter(distinct)) if len(distinct) == 1 else None
    if version and not SEMVER.match(version):
        errors.append(f"version {version!r} is not X.Y.Z")

    sections = changelog_sections()
    if version and not sections.get(version):
        errors.append(f"CHANGELOG.md has no (or an empty) '## {version} (date)' entry")
    if version and version in sections:
        heading = re.search(rf"^## {re.escape(version)} \((\d{{4}}-\d{{2}}-\d{{2}})\)$",
                            (ROOT / "CHANGELOG.md").read_text(), re.MULTILINE)
        if not heading:
            errors.append(f"CHANGELOG.md heading for {version} must be '## {version} (YYYY-MM-DD)'")

    if args.release:
        wanted = args.release.removeprefix("v")
        if not SEMVER.match(wanted):
            errors.append(f"release version {wanted!r} is not X.Y.Z")
        if version and wanted != version:
            errors.append(f"release {wanted} but the files say {version}: run scripts/bump_version.py {wanted}")
        if (last := latest_tag()) and SEMVER.match(wanted) and tuple(map(int, wanted.split("."))) <= last:
            errors.append(f"release {wanted} is not higher than the latest tag v{'.'.join(map(str, last))}")
        if git("rev-parse", "-q", "--verify", f"refs/tags/v{wanted}").returncode == 0 or \
                git("ls-remote", "--tags", "origin", f"refs/tags/v{wanted}").stdout.strip():
            errors.append(f"tag v{wanted} already exists")
        if sections.get("Unreleased"):
            errors.append("CHANGELOG.md 'Unreleased' is not empty: move its entries into the release")
        git("fetch", "-q", "origin", "release")
        if git("rev-parse", "-q", "--verify", "origin/release").returncode == 0 and \
                git("merge-base", "--is-ancestor", "origin/release", "HEAD").returncode != 0:
            errors.append("origin/release is not an ancestor of HEAD: release cannot fast-forward "
                          "(was something committed to release directly?)")

    for error in errors:
        print(f"::error::{error}" if "GITHUB_ACTIONS" in os.environ else f"error: {error}")
    if not errors:
        print(f"ok: version {version}" + (f", ready to release v{args.release.removeprefix('v')}"
                                          if args.release else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
