# Changelog

Summarized history of changes to source and documents. Newest release first. The release script turns `Unreleased` into the next release note. Keep the one-to-three sentence summary, then only the topic headings that have bullets: New, Changed, Fixed, Additional Notes.

## Unreleased

The project is specified, licensed, and public on GitHub. A Python service reads its settings, keeps nine slots in SQLite, and serves them, and a browser application shows each slot as an Excalidraw canvas under the segl bar, where each browser has a display name. Nothing drawn is saved or shared yet. CI and a dev container check both, including through nginx at `/board/`.

### New

- Apache License 2.0 and the nine-slot MVP specification.
- One version manifest (`versions.toml`), a release script, this changelog, and `journal/` for the project narrative.
- The public repository <https://github.com/robert-patrick-texas/segl>, with GitHub private vulnerability reporting.
- nginx files in `deploy/nginx/`. They hold an upstream and WebSocket map, proxy settings (forwarded client address, a body limit above segl's own, timeouts, gzip), a `/board/` mount, and two example sites.
- `docs/DEVELOPMENT.md` lists the development host's tools, the checks, and the dev loop.
- The documentation site at <https://robert-patrick-texas.github.io/segl/>: every Markdown file as a page, with an index of all pages that opens with a link to the repository. `scripts/build_docs.py` builds it with `tools/md2html`, copied from vakr. Pictures go in `images/`. A broken link, anchor, or image stops the publish (D2-024).
- The Python project: package `segl` under `src/segl`, built with hatchling, with FastAPI and uvicorn. `uv run segl` serves `GET /api/v1/health` on `bind` (default `127.0.0.1:8888`), and `segl --version` prints the application version from `versions.toml`, a copy of which the wheel carries.
- The checks: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run ty check`. Tests hold `pyproject.toml`, `.python-version`, and md2html's inline metadata to `versions.toml`, and check every source file for the license header.
- The release command (`scripts/release.py`, `docs/RELEASING.md`): `check --gate` covers Python, every direct dependency, and the pinned GitHub Actions. `upgrade` moves one component at a time and holds one that fails the suite. `cut` writes the version and the changelog section. `publish` runs its preflight, tags, and creates the GitHub Release.
- CI (`.github/workflows/ci.yml`) runs those checks on pushes to `main` and on pull requests.
- The dev container, `deploy/Containerfile`: Ubuntu 26.04 and uv, running the suite with uv's Python.
- Every setting in `docs/DEPLOY.md`, with `deploy/segl.toml.example` as the file the package will install. Without `--config`, segl uses the development defaults and reads a local `segl.toml` when one exists. A key segl does not know, or a value it cannot use, stops it at startup with a message that names the key.
- `GET /api/v1/config` returns `{ "editRequired" }`.
- segl believes `X-Forwarded-For` and `X-Forwarded-Proto` only from `trusted_proxies`, which takes addresses and networks. It sends no redirect of its own, so a trailing slash on an API path is a `404`.
- Mount tests: `uv run pytest` runs nginx with the `deploy/nginx/` files in front of a real segl process, at `/board/` and at a host root (`tests/test_mount.py`, `tests/harness.py`). They skip without nginx or openssl. The dev container and CI install nginx and set `SEGL_REQUIRE_NGINX=1`, which turns the skip into a failure.
- SQLite storage (`src/segl/repository.py`, `docs/DATA-MODEL.md`). segl creates the `database` file at startup, in WAL mode, applies the numbered SQL files in `src/segl/migrations/`, and adds slots 1–9 as `Workspace 1` to `Workspace 9`. A database it cannot open, or one from a newer segl, stops it with exit status 1.
- `GET /api/v1/slots`, `GET /api/v1/slots/{n}`, and `GET /api/v1/slots/{n}/scene`. Anything but `1` to `9` for `{n}` is a `404` with `invalid_slot`.
- A new slot's scene is the editor's own empty scene, `src/segl/empty_scene.json`, captured from the running editor. A browser test compares the file with what the pinned editor produces. A head that still holds the earlier placeholder `{"elements":[]}` gets the empty scene at startup.
- Every error has the `{ "error", "message" }` shape, including an unknown path (`not_found`), a method a path does not take (`method_not_allowed`), and a failure inside segl (`internal_error`).
- The web application, `web/`: Vite, React, TypeScript, and React Router, embedding `@excalidraw/excalidraw` 0.18.1 unmodified (D2-025). The segl bar sits above the canvas with slot buttons 1–9, the slot's title, room for the presence count, the notice that the workspace is shared, and the application version from `versions.toml`. Only `web/src/canvas/` imports Excalidraw.
- Navigation: segl's root opens the last slot this browser used, kept in `localStorage` under a key that carries the mount path, or slot 1. `s/N` opens slot N, and any other `s/...` goes to slot 1.
- Python serves the build. `web_dir` is a new setting: `/opt/segl/app/web/dist` in production, `web/dist` in a checkout. `/` and `/s/{n}` return the page with file URLs relative to that page and `window.SEGL_CONFIG = { root, editRequired }`, so one build works at a host root and under `/board/`. Without a build, segl serves the API alone and says so when it starts.
- The page asks for nothing outside segl (S-014, D2-026). The build copies the editor's canvas fonts into `web/dist/fonts/`, and the page points the editor at them in place of its public CDN.
- Web checks: `npm --prefix web run check` (`tsc --noEmit`), `test` (Vitest), `format:check` (Prettier), `build`, and `e2e` (Playwright). The browser tests run against Python serving the build, directly and behind nginx with the `deploy/nginx/` files, at a host root and at `/board/`. They refuse every request to another origin and fail if the page attempted one. `PW_WS_ENDPOINT` uses a browser running elsewhere.
- CI runs the web checks, the build, and the browser tests. The dev container has Node and runs the web checks and the build. `scripts/release.py upgrade` and `cut` run them too.
- `versions.toml` lists Node 26.13.1 and every direct web dependency. `web/package.json`, `web/package-lock.json`, and `web/.node-version` mirror it, and a test holds them to it. `scripts/release.py check` covers them.
- Display names (S-009). `deploy/display-names.txt` is the packaged word list, 190 words. `POST /api/v1/display-name` returns the next name, such as `Alpha1`, then `Bravo2`, from the word file and a counter in SQLite that never repeats. One client address gets 30 names a minute. The next call is a `429` with `rate_limited` and `Retry-After`.
- segl reads the `display_names` file when it starts. A file that is missing, has a line that is not a word of 1–10 letters, or has no words stops it with exit status 1.
- The segl bar shows this browser's name after `You:`. A new browser asks the server once and keeps the answer in `localStorage`, across reloads, slots, and tabs. The name is a button: a typed name is title-cased (`john smith` becomes `John Smith`), kept the same way, and shown only in that browser until live collaboration exists.
- `tests/display_name_cases.json` holds the browser's title case and the server's to one table of cases.

### Changed

- The Python pin is exactly 3.15.2 and follows the newest stable CPython uv offers. GitHub Releases are the publish destination. PyPI stays off until there is a demoable build.
- The contributor manual lives in `docs/`. `draft1/` and `draft2/` stay in the repository: frozen history, and the agent workbook.
- segl no longer has a `base_path` setting. It serves at its own root and works under any path nginx strips, such as `/board/` (D2-007).
- The web package uses npm, the newest Node LTS release, Vitest, Playwright Test, and Prettier (D2-023).
- Releases follow vakr's and Sunstone's policy. Every component moves to its newest release, a release that fails the tests is held with the reason, and currency is checked again at publish (D2-020). The release command is now task T01b.
- Development containers may run under rootful Docker (D2-015, S-017).
- The WebSocket carries title changes and newly placed images. Uploaded files are served at `/api/v1/assets/{hash}`. `trusted_proxies` decides whose `X-Forwarded-For` segl believes.
- segl's default address is `127.0.0.1:8888`, not port 8000, which other development servers commonly use. The upstream in `deploy/nginx/segl-http.conf`, `deploy/segl.toml.example`, and the Vite dev server's proxy follow. The mount tests take the upstream to replace from the default, so the nginx file cannot fall out of step with it.
- The default display names no longer include Bush, Clinton, Obama, Trump, or Biden.
- The test client's transport is httpx2, not httpx, which Starlette deprecates there. `versions.toml` gains `[python.build]` for the build backend.
- The license header moved from the agent rules to `CONTRIBUTING.md`. The rule to comment out superseded code was removed.
