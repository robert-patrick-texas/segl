# Releasing

`versions.toml` at the repository root is the only list of versions. It holds the application version, the exact Python version, the Node version used to build the frontend, and the direct dependency versions. Lockfiles hold the transitive closure. Application code that displays or checks a version reads `versions.toml`. `.python-version`, `pyproject.toml`, `web/.node-version`, `web/package.json`, and the inline metadata of `tools/md2html/md2html.py` mirror the matching entries. A change that adds or upgrades a direct dependency updates `versions.toml` in the same change.

`0.0.0` means unpublished. Do not publish it.

## Policy

segl releases the way vakr and Sunstone do:

- Every component moves to its newest stable release: Python (patch or minor, from what `uv python list` offers), each direct Python and web dependency, Node's newest LTS release, and the GitHub Actions the workflows pin. A release's age is never a reason to wait. One published an hour ago counts.
- Pre-releases (`a`, `b`, `rc`, `dev`, and SemVer suffixes such as `-beta.1`) never count as the newest release.
- A component is held back only after its newest release fails the tests and the fix is not a straightforward correction in this repository. The hold is a `[held.<name>]` entry in `versions.toml` (the version kept, the version skipped, the reason, the date) and an Additional Notes bullet in the release notes. Other components still move.
- A hold lasts until the component publishes a release newer than the one that failed. Then it is tried again.
- Currency is checked again when a release is published, not only when it was prepared.

## Commands

```bash
python3 scripts/release.py check          # each component beside its newest release; changes nothing
python3 scripts/release.py check --gate   # exit 1 unless every component is current or held
python3 scripts/release.py upgrade        # move components one at a time, test each, hold failures
python3 scripts/release.py notes          # print the release-note body
python3 scripts/release.py cut            # gate and suite, then the version bump and changelog section
python3 scripts/release.py publish        # preflight, tag, and GitHub Release
```

The script needs only the host's `python3` (3.11 or newer). It runs `uv`, `gh`, `git`, and `cloc`, and `npm` once `web/` exists.

- `check` lists every pinned component beside its newest stable release:
  - Python, from `uv python list`.
  - Each direct Python dependency in `versions.toml`, from PyPI. A release whose files are all yanked does not count.
  - Node's newest LTS release from nodejs.org, and each direct web dependency from npm, once `runtime.node` and the `[web.*]` tables are filled.
  - Each action the workflows in `.github/workflows/` pin, from `gh api`. A tag pin such as `actions/checkout@v7` is current while 7.y.z is the newest series. A commit pin is compared by the version in its trailing comment (`# v10.3.3`). A branch pin, or a commit pin without that comment, cannot be checked.
- `check --gate` exits 1 when a component has a newer release and no hold, when a component could not be checked, or when a hold is stale because a release newer than the skipped one exists.
- `upgrade` first runs the suite as the tree stands, and changes nothing if that fails. Then it moves each outdated component on its own, runs the suite, and keeps the move when the suite passes. When the suite fails it restores the files it changed and records `[held.<name>]` with `version`, `skipped`, `reason` (the first failing test, or the check that failed), and `since`. It updates `versions.toml` and the mirrors, including md2html's inline metadata for a `[python.docs]` package and the commit and comment of a commit-pinned action. When the Python minor moves, `requires-python` and the ruff and ty targets move with it. A hold is removed when its component moves or is current again. It leaves the changes uncommitted, and it exits 1 when a component could not be checked.
- The suite is what CI runs: `uv sync`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, and `uv run pytest`. Once `web/package.json` exists it also runs `npm install`, `check`, `test`, and `format:check` in `web/`.
- `notes` prints the notes for `Unreleased`, or for the current version's section when `Unreleased` is empty after a cut. Each hold adds an Additional Notes bullet.
- `cut` requires a summary of one to three sentences, at least one bullet, `check --gate`, and the suite. Then it writes the new application version into `versions.toml` and `pyproject.toml`, runs `uv lock`, turns `Unreleased` into `## <version> — <date>`, and opens a fresh `Unreleased`. It leaves those files unchanged when a check fails. Commit and push the result, and CI runs on it.
- `publish` runs a preflight and stops at the first failure. The tree must be clean, `HEAD` must be on `main`, `CHANGELOG.md` must have the version's section, the version must not be `0.0.0`, tag `v<version>` must exist neither locally nor on `origin`, every GitHub check run for `HEAD` must have passed, and `check --gate` must pass now. Then it tags `v<version>`, pushes the tag, and runs `gh release create v<version> --verify-tag` with the notes and, once T12 builds one, the `.deb` from `dist/`. It uploads to PyPI, with `uv build` and `uv publish`, only when `publish.pypi` is true.

Before `1.0.0`, a release that contains New or Changed increments the minor number. A release that contains only Fixed increments the patch number.

Publish destinations are `[publish]` in `versions.toml`. GitHub Releases are enabled, to `publish.github_repo`. PyPI is off until there is a build worth demonstrating. A container registry waits for L-005. The script reads credentials from the environment (`GH_TOKEN` or an authenticated `gh`, and a PyPI token only after that destination is enabled). It does not store tokens in the repository.

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
  --exclude-dir=node_modules,.venv,venv,dist,build,vendor,third_party,site-packages,_site \
  --not-match-f='(uv\.lock|package-lock\.json|pnpm-lock\.yaml)'
```

`cloc` is installed on the development host (`DEVELOPMENT.md`). Documentation, the journal, deploy files, and application source all count. `node_modules`, virtualenvs, build output, the generated documentation site (`_site/`), and an embedded copy of upstream Excalidraw do not.

## Changelog and journal

`CHANGELOG.md` is the running summary. Add a bullet when source or documents change in a way a contributor or operator needs to know. `journal/YYYY-MM-DD-short-title.md` is the narrative: why a choice was made, what failed, what to remember. A task does not require a journal entry. A surprising outcome does.

## GitHub Actions

T01 adds `.github/workflows/ci.yml` to run ruff, ty, and pytest, and T04 adds the web checks. `publish` requires those checks to pass for the release commit. CI does not publish.
