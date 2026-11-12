# Task queue

Do the task named in `STATUS.md`. Status values are `pending`, `next`, or `done`.

When a task is done, set it to `done` here and follow `AGENTS.md` to update `STATUS.md`.

## T00 — Repository and pre-build decisions

- Status: done
- Requires: none
- Requirements: D2-007, D2-015, D2-016, D2-020, D2-022, D2-023

The steps that had to happen before T01. Done 2026-11-11:

1. A git repository on `main`: one commit of the specification as received, then this task's commit, both signed off.
2. The public GitHub repository `robert-patrick-texas/segl`, pushed, with private vulnerability reporting on (D2-022).
3. The Python pin is exactly 3.15.2 and follows uv's newest stable CPython under the release policy (D2-016, D2-020). `scripts/release.py check` reads an exact pin and reports a newer patch or minor.
4. The web toolchain is npm, the newest Node LTS release, Vitest, Playwright Test, and Prettier, as in Sunstone (D2-023).
5. segl serves at its own root and works under any path nginx strips. `base_path` is gone (D2-007). `deploy/nginx/` holds the files a site includes, with `/board/` as the example path.
6. Rootful Docker is allowed for development (D2-015, S-017).
7. Contract gaps closed:
   - The WebSocket carries title changes (`slot`) and new image files (`files`).
   - Uploaded files moved to `/api/v1/assets/{hash}`, clear of Vite's `assets/`.
   - `trusted_proxies` and the Origin rule are defined.
   - The WebSocket message size and ping interval are stated.
   - The development defaults and the `versions.toml` lookup are specified.
   - Title editing belongs to T06.
   - T01's release work is its own task, T01b.
8. `docs/DEVELOPMENT.md` lists the development tools. The license header moved to `CONTRIBUTING.md`. The agent rule about commenting out superseded code is gone.
9. The default display names drop Bush, Clinton, Obama, Trump, and Biden.

Acceptance (evidence in `STATUS.md`): `git log` shows both signed-off commits on `main`, and `origin` is the public GitHub repository. `nginx -t` passes for both site examples in `deploy/nginx/`. `python3 scripts/release.py check` reports the 3.15.2 pin. `python3 scripts/release.py notes` prints the line count as the first table row.

## T00b — Documentation site

- Status: done
- Requires: T00
- Requirements: D2-024

Done 2026-11-11 at the user's request:

1. `tools/md2html`, copied from vakr at `99f62e3`, with one added option, `--repo-in-index`, and a test for it.
2. `scripts/build_docs.py`, which builds `_site/` from every Markdown file except `.github/`, copies `images/`, and checks raw HTML `<img>` paths.
3. `.github/workflows/pages.yml`, which deploys `_site/` to GitHub Pages on every push to `main`.
4. `images/` for pictures on any page (`docs/DEVELOPMENT.md`).
5. md2html's two packages in `versions.toml` `[python.docs]`, moved to their newest releases. `NOTICE` names md2html and the Octicons mark.

Acceptance (evidence in `STATUS.md`): md2html's tests pass. `python3 scripts/build_docs.py` exits 0 with no broken links. The Pages workflow deploys, and the site answers at its URL.

## T01 — Python skeleton, CI, and dev container

- Status: done
- Requires: T00
- Requirements: S-017 (container starts), tooling from D2-016
- Read: `AGENTS.md`, `CONTRIBUTING.md` (license header), `docs/DEVELOPMENT.md`, `docs/DEPLOY.md` (dev container, configuration), `docs/DECISIONS.md` D2-015, D2-016, D2-019, D2-020, D2-021, and D2-022

Create the uv project at the repository root with package `segl` under `src/segl`. Read the Python pin (`runtime.python`, an exact version such as `3.15.2`) and the application version from `versions.toml`. Write the same pin to `.python-version`. Set `requires-python` to the pin's minor (`>=3.15,<3.16`). Set the project license field to `Apache-2.0` and the project version to the `versions.toml` application version.

Depend on FastAPI and uvicorn. Dev-depend on pytest, httpx2 (the test client's transport; Starlette deprecates plain httpx there), ruff, and ty. Take the newest stable release of each, pin it exactly (`==`) in `pyproject.toml`, and record the same versions in `versions.toml`. Configure ruff and ty for the pin's minor in `pyproject.toml`. Add a `docs` dependency group holding md2html's two packages at the `[python.docs]` pins, and point pytest and ty at `tools/md2html` as vakr's `pyproject.toml` does, so `uv run pytest` and `uv run ty check` cover it. md2html keeps its inline metadata for `uv run`.

Add a console script `segl` whose `--version` prints the application version from `versions.toml`. The installed package carries a copy of `versions.toml` that the build puts inside it. A checkout reads the file at the repository root. Tests cover both lookups.

The process serves `GET /api/v1/health` → `{ "status": "ok" }` on the configured bind address, default `127.0.0.1:8000`. Load a TOML path from `--config` if the flag is present. For this task a missing file still serves health.

Add a test that every first-party source file under `src/`, `tests/`, and `scripts/`, and under `web/src/` once it exists, starts with the license header in `CONTRIBUTING.md`. New modules carry that header.

Add `.github/workflows/ci.yml`. It runs on pushes to `main` and on pull requests: `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, and `uv run pytest`. Pin actions as Sunstone's workflow does (`astral-sh/setup-uv` by commit). CI does not publish.

Add `deploy/Containerfile` from `ubuntu:26.04`. It installs uv and runs `uv sync` and `uv run pytest` for this health test, using uv's Python, not a hand-made venv. It builds under rootful Docker, rootless Docker, or rootless Podman.

Acceptance:

- `uv run pytest` passes the health, version-lookup, and license-header tests, and md2html's tests.
- `uv run segl --version` prints the application version from `versions.toml`.
- `.python-version` matches `versions.toml` `runtime.python`. Every direct Python dependency in `pyproject.toml` is listed in `versions.toml` at the same version, and a test checks this.
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- `uv run ty check` passes.
- `python3 scripts/release.py notes` prints a body whose first table row is the project line count.
- `docker build -f deploy/Containerfile .` (or the Podman equivalent) runs that pytest.
- The CI workflow passes on GitHub for the pushed commit (`gh run list`).

Out of scope: the release command (T01b), React, Excalidraw, SQLite, nginx, the `.deb`.

## T01b — Release command

- Status: done
- Requires: T01
- Requirements: D2-020
- Read: `docs/RELEASING.md`, `docs/DECISIONS.md` D2-016, D2-020, and D2-022

Finish `scripts/release.py` to the contract in `docs/RELEASING.md`:

- `check` lists every pinned component beside its newest stable release: Python through `uv python list`, each direct Python dependency through PyPI, Node and each direct web dependency through npm once `web/` exists, and the GitHub Actions pins in `.github/workflows/`. `check --gate` exits 1 when a component has a newer release and no hold, when a component could not be checked, or when a hold is stale because a release newer than the skipped one exists.
- `upgrade` moves each outdated component on its own and runs the suite. It keeps the move when the suite passes. Otherwise it restores the previous version and records `[held.<name>]` with `version`, `skipped`, `reason` (the first failing test), and `since`. A move of a `[python.docs]` package also updates `tools/md2html/md2html.py`'s inline metadata.
- `cut` and `publish` behave as `docs/RELEASING.md` describes, including the preflight order.

Tests replace the network, `gh`, and `git push` with fakes, and use a temporary git repository with a local bare remote, as Sunstone's `tools/release` tests do.

Acceptance: `uv run pytest` covers these cases:

- The gate fails for an unheld newer release, passes for a held one, and fails again once a release newer than the held one appears.
- `upgrade` holds a component whose move fails the suite and keeps the others.
- `cut` leaves `versions.toml` and `CHANGELOG.md` unchanged when the gate or the suite fails.
- A successful `cut` writes the version and the changelog section.
- `publish` stops at each preflight failure and never publishes `0.0.0`.
- A successful `publish` creates the tag and calls `gh release create` with the notes.

ruff and ty pass.

## T02 — Config, relative mount, nginx harness

- Status: next
- Requires: T01
- Requirements: S-006, S-007
- Read: `docs/DEPLOY.md`, `docs/ARCHITECTURE.md` (mount and navigation), `docs/API.md` (config route), `docs/SECURITY.md`

Implement the TOML keys from `docs/DEPLOY.md` with those defaults, and the development defaults when `--config` is absent. Write `deploy/segl.toml.example` with the production paths. Serve health and `GET /api/v1/config` at segl's root. Run uvicorn with proxy headers believed only from `trusted_proxies`. Every redirect segl sends is relative. Inject nothing into pages yet; the config route is the contract test.

Add nginx to the dev container. Add a pytest harness that runs the real segl server on a free loopback port, and nginx in front of it with the `deploy/nginx/` files. Copy those files to a temporary prefix, point the upstream at the test port, and use a test certificate in place of snakeoil. Do not edit the shipped files for the test.

Acceptance:

- pytest covers the HTTP half of T-013 through the harness: `/board` redirects to `/board/`, and `/board/api/v1/health` and `/board/api/v1/config` reach segl. The same requests work at a host root.
- Those responses have no `Set-Cookie` (start of T-012).
- `nginx -t` passes for both site examples.
- The harness skips with a clear message when nginx is not installed, and it does not skip in the dev container.
- ruff and ty pass.

## T03 — SQLite slots

- Status: pending
- Requires: T02
- Requirements: S-003
- Read: `docs/DATA-MODEL.md`

Add migrations and the repository methods. Startup bootstraps nine slots. Use a temporary empty scene document `{ "elements": [] }` until T04 replaces it with a fixture captured from the editor. Expose `GET /api/v1/slots`, `GET /api/v1/slots/{n}`, and `GET /api/v1/slots/{n}/scene`.

Acceptance: a test boots a temp database, reads nine titles `Workspace 1`–`Workspace 9`, checks isolated scenes, and checks that slot 0 and slot 10 return `invalid_slot`. ruff and ty pass.

## T04 — Excalidraw shell

- Status: pending
- Requires: T03
- Requirements: S-001, S-003, S-006, S-014, S-016
- Read: `docs/ARCHITECTURE.md` (mount and navigation), `docs/DECISIONS.md` D2-004, D2-007, and D2-023, `docs/DEVELOPMENT.md`

Create `web/` with Vite, React, TypeScript, and React Router, using npm (D2-023). Put exact versions in `web/package.json`, commit `web/package-lock.json`, set `engine-strict=true` in `web/.npmrc`, and name the newest Node LTS release in `web/.node-version`. Record Node and every direct web dependency in `versions.toml`. Pin `@excalidraw/excalidraw` at its newest stable release and add its notice to `NOTICE`. Record the reconcile choice in `docs/DECISIONS.md`. Isolate imports in `web/src/canvas/`. The about line, or an equivalent status in the segl bar, shows the application version read from `versions.toml`.

Add the npm scripts `build`, `check` (`tsc --noEmit`), `test` (Vitest), `format:check` (Prettier), and `e2e` (Playwright). Add the web checks to CI.

The segl bar sits outside the canvas. It holds slot buttons 1–9, the shared title, room for the later presence count, and the notice that the workspace is shared. Visiting segl's root honors the `localStorage` last slot. `s/N` saves the last slot and loads that head. Invalid slot URLs go to slot 1.

Build with Vite `base: './'`. In production mode Python serves `web/dist`. It serves `index.html` for `/` and `/s/{n}` with asset URLs relative to that page, and injects `window.SEGL_CONFIG` with `root` and `editRequired` (`docs/ARCHITECTURE.md`). The app derives `basePath`, API URLs, the WebSocket URL, the router basename, and `EXCALIDRAW_ASSET_PATH` from `root`. Document the dev loop in `docs/DEVELOPMENT.md`. The Vite dev server proxies `/api` and `/collab` to Python with `changeOrigin: false`.

Set up `@playwright/test` with a `webServer` that runs `uv run segl --config <temporary TOML>` serving the production build. Put nginx in front of it with the `deploy/nginx/` files as T02's harness does, and support `PW_WS_ENDPOINT` (`docs/DEVELOPMENT.md`).

Capture the editor's real empty `initialData`, store it as the bootstrap fixture, and migrate existing empty heads to it if their JSON is the T03 placeholder.

Bundle fonts and other editor assets so T-010 can pass with outbound network disabled. Record how in `docs/DECISIONS.md`.

Acceptance:

- Playwright, against the production build, renders a slot at a host root and through nginx at `/board/`, and the page asks for nothing outside `/board/` (the page half of T-013).
- The empty scene loads, and the shared notice is visible.
- T-010 passes for the slot page.
- `npm run check`, `npm test`, and `npm run format:check` pass in `web/`.
- ruff and ty pass.

## T05 — Display names

- Status: pending
- Requires: T04
- Requirements: S-009
- Read: `docs/ARCHITECTURE.md` (display names), `docs/SECURITY.md` (client address), `draft2/display-names.txt`

Copy `draft2/display-names.txt` to `deploy/display-names.txt`. From then on `deploy/display-names.txt` is the packaged list. Implement allocation, the 30/minute limit per client address, and `POST /api/v1/display-name`. The bar shows the current label and accepts a rename, title-cased. Until T06 carries it on the socket, the rename is only shown locally: store it in `localStorage` now, and T06 must not allocate again.

Acceptance:

- T-014 runs against a temp word file, including its rate-limit case through the nginx harness.
- A test checks that the packaged file has at least 100 unique `^[A-Za-z]{1,10}$` entries.
- The browser keeps a label across reload.
- ruff, ty, and the web checks pass.

## T06 — Live collaboration and titles

- Status: pending
- Requires: T05
- Requirements: S-002, S-003 (titles), S-008, S-010, S-013
- Read: `docs/ARCHITECTURE.md` (collaboration, edit gate), `docs/API.md` (WebSocket, slot route), `docs/SECURITY.md` (Origin)

Implement the room, the WebSocket messages, reconcile, presence, and the view-only gate. The menu count and the participant list use this room. Show connecting, live, and disconnected. `saved` can light up in T07. For this task, show live once `welcome` arrives.

Implement title editing in the bar and `PATCH /api/v1/slots/{n}`, broadcast to the room as a `slot` message. Refuse a WebSocket upgrade or a mutation whose `Origin` does not match `Host` (`docs/SECURITY.md`).

If the pinned package exports a reconcile helper, use it in the client and match it in the server unit test. Otherwise use version, then versionNonce. Record the choice in `docs/DECISIONS.md`.

Acceptance: T-001, T-002, T-003, T-008, T-015, T-016, the reconnect half of T-004, and the WebSocket half of T-013 (two contexts sync over `/board/collab` through nginx). Two browsers means two Playwright contexts against one server. ruff, ty, and the web checks pass.

## T07 — Durability, history rows, images

- Status: pending
- Requires: T06
- Requirements: S-004, S-005 (storage, not the panel), S-012, S-013
- Read: `docs/DATA-MODEL.md` (flush rules), `docs/API.md` (uploaded files, `files` message)

Flush the head, append revisions, honor the caps and intervals from config (tests use short intervals), and flush on last disconnect and on SIGTERM. Emit `saved`. Persist an embedded image using the editor's file model: upload the bytes to `POST /api/v1/slots/{n}/assets`, announce them with a `files` message, record the file list with the head, and serve `GET /api/v1/assets/{hash}`.

Acceptance: T-005, T-006, T-007, and a unit test that the 51st revision drops the oldest. The UI shows saving and then saved. ruff, ty, and the web checks pass.

## T08 — History panel and restore

- Status: pending
- Requires: T07
- Requirements: S-005
- Read: `docs/API.md` restore routes, epoch rules in `docs/ARCHITECTURE.md`

Add the revision list and restore control in the bar. Restore is view-only blocked when a token is set. Connected clients follow the new epoch.

Acceptance: T-011. ruff, ty, and the web checks pass.

## T09 — JSON export and import

- Status: pending
- Requires: T08
- Requirements: S-011
- Read: `docs/API.md` import route

Use the editor's Excalidraw JSON export. Import posts to the import route, which follows the restore epoch rules. Reject an oversized body with `payload_too_large`.

Acceptance: T-009. ruff, ty, and the web checks pass.

## T10 — Edit-token browser flow, cookie and Origin sweep

- Status: pending
- Requires: T09
- Requirements: S-007, S-008, S-016
- Read: `docs/SECURITY.md`, `docs/ARCHITECTURE.md` (edit gate)

Store `#e=` into the `basePath` `localStorage` key and strip the fragment. Put the editor into view mode when this client must not edit, and say so in the bar. Send the token only as the HTTP header and inside WebSocket messages.

Acceptance: T-008 in the browser, including the fragment link. T-012 across the routes that now exist, including a WebSocket handshake and the Origin refusals. ruff, ty, and the web checks pass.

## T11 — P0 browser matrix in the dev container

- Status: pending
- Requires: T10
- Requirements: S-017 and the browser rows of `docs/TEST-PLAN.md`
- Read: `docs/TEST-PLAN.md`, `docs/DEVELOPMENT.md` (browsers)

Make T-001 through T-016 runnable as one command inside the dev container, under rootful Docker and under rootless Docker or Podman. If Chromium cannot run in the Ubuntu 26.04 container, use the Playwright image through `PW_WS_ENDPOINT` and record why. Try a 10-editor stretch once, record the observation in `STATUS.md`, and do not block on it. Run the 1,000-element load once and record it the same way.

Acceptance: that container command exits 0 on T-001 through T-016. Evidence goes into the STATUS log.

## T12 — Debian package and systemd

- Status: pending
- Requires: T11
- Requirements: S-015
- Read: `docs/DEPLOY.md`

Build a `.deb` that installs these:

- the uv-pinned CPython under `/opt/segl/python`
- a virtualenv from `uv.lock`, whose `segl` package carries `versions.toml`
- `web/dist`
- the example TOML and the display-name file
- the `deploy/nginx/` files under `/opt/segl/share/nginx/`
- the systemd unit
- `deploy/OPERATOR.md`, and `LICENSE` and `NOTICE` under the package documentation path

The package copyright file names Apache-2.0. Create user `segl`. The unit's stop flushes heads (covered by T07's SIGTERM test). Build it the way Sunstone does: nfpm, in a clean `ubuntu:26.04` container, from the lockfiles.

Acceptance: T-017 on Ubuntu 26.04, on a host or in an `ubuntu:26.04` container booted with systemd. That machine runs nginx with the `deploy/nginx/` files and `site-board.example.conf`, using Ubuntu's snakeoil certificate. If neither is available, log what was checked and leave a follow-up line on T13.

Out of scope: the production container image (L-005).

## T13 — MVP gate

- Status: pending
- Requires: T12
- Requirements: all S-001–S-017
- Read: `docs/TEST-PLAN.md` evidence section

Re-run T-001 through T-018. Append the evidence block to `STATUS.md`. On full pass, set Next task to `NONE` and Completed to T00–T13. On a failure, set Next task to the task that owns the defect and do not open P1.

This task does not add features.
