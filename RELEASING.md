# Releasing

## Branches

| Branch | Purpose | Who updates it |
|---|---|---|
| `release` | Default branch. What `herdr plugin install jellespijker/herdr-diagrams` and the herdr marketplace use | Only the release workflow, by fast-forward |
| `main` | Development | Pull requests with green CI |
| `v*` tags | One per release | Only the release workflow |

GitHub rulesets enforce this: no force pushes or deletions on `main`, `release` and `v*` tags;
`main` takes changes through pull requests with the `checks` and `test` jobs passing and a
linear history; `release` and the tags can only be written by GitHub Actions. A pull request
into `release` fails the `pr-guard` check unless it comes from `main`.

## Day to day

1. Branch from `main`, change, add a line under `## Unreleased` in `CHANGELOG.md`.
2. Open a pull request to `main`. CI runs `checks` (version consistency, changelog, lint,
   import contracts) and `test` on Linux and macOS. Merge when green.

## Cutting a release

1. On a branch from `main`: `scripts/bump_version.py X.Y.Z`. It sets the version in
   `herdr-plugin.toml`, `pyproject.toml`, `package.json` and the lock files, and turns
   `## Unreleased` into `## X.Y.Z (date)`. Review the changelog, commit, open a pull
   request to `main`, merge it.
2. Start the release: Actions → release → Run workflow on `main` with version `X.Y.Z`, or
   `gh workflow run release --ref main -f version=X.Y.Z`. Tick `dry_run` to only check.
3. The workflow:
   - `verify`: the version matches the files, the changelog has the entry and `Unreleased`
     is empty, the version is higher than the last tag, the tag does not exist, and
     `release` can fast-forward to this commit;
   - `ci`: the full CI on Linux and macOS;
   - `publish` (waits for your approval in the `release` environment): fast-forwards
     `release`, creates tag `vX.Y.Z` and the GitHub release with the changelog entry.
4. Users get it with `herdr plugin install --yes jellespijker/herdr-diagrams`.

## Fixing a bad release

Releases are never rewritten. Fix it on `main` and release the next patch version. A tag
can only be removed by an admin after temporarily disabling the tag ruleset.

## Versions

Semantic versioning. Patch: fixes and small additions. Minor: new features or new
configuration. Major: breaking changes to the Item contract (ADR-0002), the CLI or the
config files.
