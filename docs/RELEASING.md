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
python3 scripts/release.py upgrade        # move components, test what each can break, hold failures
python3 scripts/release.py notes          # print the release-note body
python3 scripts/release.py cut            # gate and suite, then the version bump and changelog section
python3 scripts/release.py publish        # preflight, tag, and GitHub Release
```

The script needs only the host's `python3` (3.11 or newer). It runs `uv`, `gh`, `git`, `cloc`, `ssh-keygen`, and `npm`, with the Node of `web/.node-version` first on `PATH`.

- `check` lists every pinned component beside its newest stable release:
  - Python, from `uv python list`.
  - Each direct Python dependency in `versions.toml`, from PyPI. A release whose files are all yanked does not count.
  - Node's newest LTS release from nodejs.org, and each direct web dependency from npm, once `runtime.node` and the `[web.*]` tables are filled.
  - Each action the workflows in `.github/workflows/` pin, from `gh api`. A tag pin such as `actions/checkout@v7` is current while 7.y.z is the newest series. A commit pin is compared by the version in its trailing comment (`# v10.3.3`). A branch pin, or a commit pin without that comment, cannot be checked.
- `check --gate` exits 1 when a component has a newer release and no hold, when a component could not be checked, or when a hold is stale because a release newer than the skipped one exists.
- `upgrade` moves every outdated component and holds the one that fails. It does not run the whole suite for each:
  - The components that can break anything move together, and the suite runs once. A pass keeps them all. That is the usual case, and it costs one run.
  - When that run fails, `upgrade` restores the files and runs the suite on the tree as it stands. If that fails too, the tree is at fault: it changes nothing and exits 1. If it passes, it moves each of those components alone and runs the suite for each. One component alone is not run again: it is held with the failure already seen.
  - A tool that can only break its own check gets that check, which takes seconds: ruff (`ruff check`, `ruff format --check`), ty (`ty check`), pytest, httpx2, and md2html's two packages (`pytest`), Prettier (`format:check`), and TypeScript and the `@types` packages (`check`). When no run of the suite has shown the tree to be good, the check runs before the move too, and a tool whose check already fails is not tried.
  - A GitHub Action is moved without a run. Nothing on the machine runs it, and CI on the push is its test.
  - Everything else gets the whole suite, Vitest among it: `vite.config.ts` takes its `defineConfig` from Vitest, so the build does too.
- A move that fails is undone, and `upgrade` records `[held.<name>]` with `version`, `skipped`, `reason` (the first failing test, or the check that failed), and `since`. It updates `versions.toml` and the mirrors, including md2html's inline metadata for a `[python.docs]` package and the commit and comment of a commit-pinned action. When the Python minor moves, `requires-python` and the ruff and ty targets move with it. A hold is removed when its component moves or is current again. It leaves the changes uncommitted, and it exits 1 when a component could not be checked.
- The suite is what CI runs, in CI's order: `uv sync` and `npm install` in `web/`, which bring both environments to the pins; `uv run ruff check .`, `uv run ruff format --check .`, and `uv run ty check`; `check`, `test`, `format:check`, and `build` in `web/`; `uv run pytest`; and the browser tests, through `scripts/e2e.py`, which runs them in as many groups at once as the machine has room for (`DEVELOPMENT.md`, the browser tests in groups). pytest comes after `npm install` because it holds the web lockfile to `versions.toml`, and after the build because it compares its stand-in for the build with the real one. The browser tests need a browser of the pinned `@playwright/test` version (`DEVELOPMENT.md`, browsers for the tests). A move of `@playwright/test` needs the browser of the new version: install it, or start the browser server at that version, before `upgrade`, or the move fails the suite and is held.
- `notes` prints the notes for `Unreleased`, or for the current version's section when `Unreleased` is empty after a cut. Each hold adds an Additional Notes bullet.
- `cut` requires a summary of one to three sentences, at least one bullet, `check --gate`, and the suite. Then it writes the new application version into `versions.toml` and `pyproject.toml`, runs `uv lock`, turns `Unreleased` into `## <version> — <date>`, and opens a fresh `Unreleased`. It leaves those files unchanged when a check fails. Commit and push the result, and CI runs on it.
- `publish` runs a preflight and stops at the first failure. The tree must be clean, `HEAD` must be on `main`, `CHANGELOG.md` must have the version's section, the version must not be `0.0.0`, tag `v<version>` must exist neither locally nor on `origin`, every GitHub check run for `HEAD` must have passed, and `check --gate` must pass now. `deploy/release-signers` must list a key, and the release key must be where `publish` looks for it (the release key, below). Last, `deploy/debian/package-test.sh` must pass: it builds `dist/segl_<version>_amd64.deb`, installs it in a container that booted with systemd, and updates it there with `segl update` (`TEST-PLAN.md` T-017 and T-021), which needs Docker, `ssh-keygen`, and `openssl`. Then `publish` writes `dist/SHA256SUMS` for that package, signs it with the release key, which asks for the key's passphrase, and checks the signature against `deploy/release-signers` as a server will. A signature that does not verify stops it, with nothing tagged. Then it tags `v<version>`, pushes the tag, and runs `gh release create v<version> --verify-tag` with the notes and three files: that `.deb`, `SHA256SUMS`, and `SHA256SUMS.sig`. It attaches no other file from `dist/`. It uploads to PyPI, with `uv build` and `uv publish`, only when `publish.pypi` is true.

Before `1.0.0`, a release that contains New or Changed increments the minor number. A release that contains only Fixed increments the patch number.

Publish destinations are `[publish]` in `versions.toml`. GitHub Releases are enabled, to `publish.github_repo`. PyPI is off until there is a build worth demonstrating. A container registry waits for L-005. The script reads credentials from the environment (`GH_TOKEN` or an authenticated `gh`, and a PyPI token only after that destination is enabled). It does not store tokens in the repository.

## The release key

A server installs a release only when `SHA256SUMS` carries a signature from a key its installed package lists (`DEPLOY.md`, updates). So every release is signed, and the key outlives any one release.

- **The private half** is on the maintainer's development host, at `~/.config/segl-release/release_ed25519`, beside the release keys of vakr and Sunstone. It has a passphrase. It is never in the repository, in CI, or on GitHub. `SEGL_RELEASE_KEY` names another path.
- **The public half** is a line in `deploy/release-signers`, in ssh-keygen's allowed-signers form. The package installs that file as `/opt/segl/share/release-signers`. The principal and the namespace are both `segl-release`.

To make the key, once:

```bash
mkdir -p ~/.config/segl-release && chmod 700 ~/.config/segl-release
ssh-keygen -t ed25519 -C segl-release -f ~/.config/segl-release/release_ed25519
printf 'segl-release namespaces="segl-release" %s\n' \
    "$(cut -d' ' -f1,2 ~/.config/segl-release/release_ed25519.pub)" >>deploy/release-signers
ssh-keygen -lf ~/.config/segl-release/release_ed25519.pub   # the fingerprint, for the file's comment
```

Commit `deploy/release-signers` with the key's date and fingerprint in a comment. Keep a copy of the private key somewhere safe: a server that runs a release signed with it installs no release signed with another.

Until the file lists a key, `publish` stops at `deploy/release-signers lists a key`, and a package built from the tree refuses every update.

To change the key, add the new one to `deploy/release-signers` and publish that release signed with the old key. Servers that install it trust both. Sign later releases with the new key, and take the old key out in a release after that. A server that skipped the release with both keys must be upgraded by hand, with `apt install`.

The install test does not use the release key. It makes a throwaway key, and its test releases trust that one (`deploy/debian/package-test.sh`).

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

`.github/workflows/ci.yml` runs ruff, ty, and pytest (T01), and the web typecheck, Vitest, Prettier, the build, and the browser tests (T04). `publish` requires those checks to pass for the release commit. CI does not publish.
