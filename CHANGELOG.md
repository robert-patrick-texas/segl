# Changelog

Summarized history of changes to source and documents. Newest release first. The release script turns `Unreleased` into the next release note. Keep the one-to-three sentence summary, then only the topic headings that have bullets: New, Changed, Fixed, Additional Notes.

## Unreleased

The project is specified, licensed, and public on GitHub. Application code has started with a Python service that reads its settings and serves a health and a config route. CI and a dev container check it, including through nginx at `/board/`.

### New

- Apache License 2.0 and the nine-slot MVP specification.
- One version manifest (`versions.toml`), a release script, this changelog, and `journal/` for the project narrative.
- The public repository <https://github.com/robert-patrick-texas/segl>, with GitHub private vulnerability reporting.
- nginx files in `deploy/nginx/`. They hold an upstream and WebSocket map, proxy settings (forwarded client address, a body limit above segl's own, timeouts, gzip), a `/board/` mount, and two example sites.
- `docs/DEVELOPMENT.md` lists the development host's tools, the checks, and the dev loop.
- The documentation site at <https://robert-patrick-texas.github.io/segl/>: every Markdown file as a page, with an index of all pages that opens with a link to the repository. `scripts/build_docs.py` builds it with `tools/md2html`, copied from vakr. Pictures go in `images/`. A broken link, anchor, or image stops the publish (D2-024).
- The Python project: package `segl` under `src/segl`, built with hatchling, with FastAPI and uvicorn. `uv run segl` serves `GET /api/v1/health` on `bind` (default `127.0.0.1:8000`), and `segl --version` prints the application version from `versions.toml`, a copy of which the wheel carries.
- The checks: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run ty check`. Tests hold `pyproject.toml`, `.python-version`, and md2html's inline metadata to `versions.toml`, and check every source file for the license header.
- The release command (`scripts/release.py`, `docs/RELEASING.md`): `check --gate` covers Python, every direct dependency, and the pinned GitHub Actions. `upgrade` moves one component at a time and holds one that fails the suite. `cut` writes the version and the changelog section. `publish` runs its preflight, tags, and creates the GitHub Release.
- CI (`.github/workflows/ci.yml`) runs those checks on pushes to `main` and on pull requests.
- The dev container, `deploy/Containerfile`: Ubuntu 26.04 and uv, running the suite with uv's Python.
- Every setting in `docs/DEPLOY.md`, with `deploy/segl.toml.example` as the file the package will install. Without `--config`, segl uses the development defaults and reads a local `segl.toml` when one exists. A key segl does not know, or a value it cannot use, stops it at startup with a message that names the key.
- `GET /api/v1/config` returns `{ "editRequired" }`.
- segl believes `X-Forwarded-For` and `X-Forwarded-Proto` only from `trusted_proxies`, which takes addresses and networks. It sends no redirect of its own, so a trailing slash on an API path is a `404`.
- Mount tests: `uv run pytest` runs nginx with the `deploy/nginx/` files in front of a real segl process, at `/board/` and at a host root (`tests/test_mount.py`, `tests/harness.py`). They skip without nginx or openssl. The dev container and CI install nginx and set `SEGL_REQUIRE_NGINX=1`, which turns the skip into a failure.

### Changed

- The Python pin is exactly 3.15.2 and follows the newest stable CPython uv offers. GitHub Releases are the publish destination. PyPI stays off until there is a demoable build.
- The contributor manual lives in `docs/`. `draft1/` and `draft2/` stay in the repository: frozen history, and the agent workbook.
- segl no longer has a `base_path` setting. It serves at its own root and works under any path nginx strips, such as `/board/` (D2-007).
- The web package uses npm, the newest Node LTS release, Vitest, Playwright Test, and Prettier (D2-023).
- Releases follow vakr's and Sunstone's policy. Every component moves to its newest release, a release that fails the tests is held with the reason, and currency is checked again at publish (D2-020). The release command is now task T01b.
- Development containers may run under rootful Docker (D2-015, S-017).
- The WebSocket carries title changes and newly placed images. Uploaded files are served at `/api/v1/assets/{hash}`. `trusted_proxies` decides whose `X-Forwarded-For` segl believes.
- The default display names no longer include Bush, Clinton, Obama, Trump, or Biden.
- The test client's transport is httpx2, not httpx, which Starlette deprecates there. `versions.toml` gains `[python.build]` for the build backend.
- The license header moved from the agent rules to `CONTRIBUTING.md`. The rule to comment out superseded code was removed.
