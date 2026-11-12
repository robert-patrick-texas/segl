# Releasing

`versions.toml` at the repository root is the only list of versions. It holds the application version, the Python version, the Node version used to build the frontend, and the direct dependency versions. Lockfiles hold the transitive closure. Application code that displays or checks a version reads `versions.toml`. `.python-version`, `pyproject.toml`, and the web manifest mirror the matching entries. A task that adds or upgrades a direct dependency updates `versions.toml` in the same change.

`0.0.0` means unpublished. Do not publish it.

## Command

```bash
python3 scripts/release.py check          # report newer versions, change nothing
python3 scripts/release.py notes          # print the release-note body
python3 scripts/release.py cut            # upgrade, test, hold failures, rewrite the changelog
python3 scripts/release.py cut --publish  # cut, then the destinations enabled in versions.toml
```

`check` and `notes` work before any application code exists. `cut` changes nothing until `pyproject.toml` and the test suite exist. T01 finishes `cut` so that it then does the rest of this contract: move each direct dependency to its newest release, move Python to the newest patch of the minor already pinned in `versions.toml` (a 3.15 pin stays on 3.15), and run the test suite. When a newer component fails and the fix is not a straightforward correction in this repository, restore that component's known-good version, record a `[held.*]` entry, and add an Additional Notes bullet. Other components still move forward. A new minor of Python is reported and left pinned.

Publish destinations are `[publish]` in `versions.toml`. GitHub Releases are enabled. PyPI is off until there is a build worth demonstrating; the script uploads to PyPI only when `pypi = true`. The `.deb`, once T12 builds it, is uploaded as a GitHub Release asset. A container registry waits for L-005. The script reads credentials from the environment (`GH_TOKEN` or an authenticated `gh`, and a PyPI token only after that destination is enabled). It does not store tokens in the repository.

Before `1.0.0`, a release that contains New or Changed increments the minor number. A release that contains only Fixed increments the patch number. `cut` writes the new application version into `versions.toml` and opens a fresh `Unreleased` section.

## Release note shape

The summary is one to three sentences. Then only the headings that have bullets, in this order: New, Changed, Fixed, Additional Notes. After those headings, one table. The first row is the project line count. The following rows are the application, runtimes, and direct dependencies from `versions.toml`. Transitive dependencies, when a lockfile exists, follow the table inside a collapsed details block.

```markdown
## 0.1.0 — 2026-11-11

Two or three sentences on what this release is for.

### New

- A user-visible addition.

### Additional Notes

- Kept example-package at 1.2.3. Version 1.3.0 failed tests/test_scene.py. Deferred to a later release of that package.

| Item | Value |
|---|---|
| Project lines of code | 1200 |
| Python | 3.15.2 |
| segl | 0.1.0 |
| fastapi | 0.115.6 |

<details>
<summary>Python sub-dependencies (40)</summary>

| Package | Version |
|---|---|
| starlette | 0.41.0 |

</details>
```

A Fixed-only release omits New, Changed, and Additional Notes. A release with no held packages omits Additional Notes unless some other note belongs there.

## Line count

The line count is `cloc`'s code column for files written in this repository. That is the work covered by `LICENSE`. The count excludes dependency and vendor trees and generated lockfiles:

```bash
cloc . --json --quiet --fullpath \
  --exclude-dir=node_modules,.venv,venv,dist,build,vendor,third_party,site-packages \
  --not-match-f='(uv\.lock|package-lock\.json|pnpm-lock\.yaml)'
```

`cloc` is installed on the development host. Documentation, the journal, deploy files, and application source all count. `node_modules`, virtualenvs, build output, and an embedded copy of upstream Excalidraw do not.

## Changelog and journal

`CHANGELOG.md` is the running summary. Add a bullet when source or documents change in a way a contributor or operator needs to know. `journal/YYYY-MM-DD-short-title.md` is the narrative: why a choice was made, what failed, what to remember. A task does not require a journal entry. A surprising outcome does.

## GitHub Actions

T01 adds `.github/workflows/ci.yml` to run ruff, ty, and pytest. The release script is the publisher. CI does not publish.
