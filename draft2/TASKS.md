# Task queue

Do the task named in `STATUS.md`. Status values are `pending`, `next`, or `done`.

When a task is done, set it to `done` here and follow `AGENTS.md` to update `STATUS.md`.

## T01 — Python skeleton and dev container

- Status: next
- Requires: none
- Requirements: S-017 (container starts), tooling from D2-016
- Read: `AGENTS.md`, `docs/DEPLOY.md` (dev container), `docs/RELEASING.md`, `docs/DECISIONS.md` D2-015, D2-016, D2-019, D2-020, and D2-021

Create the uv project at the repository root with package `segl` under `src/segl`. Read the Python pin and the application version from `versions.toml`. Write the same Python pin to `.python-version`. Set the project license field to `Apache-2.0` and the project version to the `versions.toml` application version. Depend on FastAPI and uvicorn. Dev-depend on pytest, httpx, ruff, and ty. Record those direct versions back into `versions.toml`. Configure ruff and ty for the pinned Python in `pyproject.toml`. Add a console script `segl` whose `--version` prints the application version from `versions.toml`. Keep the existing root `LICENSE`. New Python modules use the header in `AGENTS.md`.

Finish `scripts/release.py cut` so it performs the upgrade, test, hold, changelog, and `--publish` steps in `docs/RELEASING.md`. `cut` must leave `versions.toml` and `CHANGELOG.md` unchanged when the suite fails. Add `.github/workflows/ci.yml` to run ruff, ty, and pytest. CI does not publish.

The process serves `GET /api/v1/health` → `{ "status": "ok" }` on the configured bind address, default `127.0.0.1:8000`. Load a TOML path from `--config` if the flag is present; for this task a missing file still serves health.

Add `deploy/Containerfile` from Ubuntu 26.04 that installs uv and can run `uv sync` and `uv run pytest` for this health test. The container uses uv's Python, not a hand-made venv.

Acceptance:

- `uv run pytest` passes the health test.
- `uv run segl --version` prints the application version from `versions.toml`.
- `.python-version` matches `versions.toml` `runtime.python`, and every direct Python dependency in `pyproject.toml` is listed in `versions.toml`.
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- `uv run ty check` passes.
- `python3 scripts/release.py notes` prints a body whose first table row is the project line count.
- The container build runs that pytest. If the Ubuntu 26.04 base image cannot be pulled, log the exact error in `STATUS.md` and set Blocked.

Out of scope: React, Excalidraw, SQLite, nginx, the `.deb`.

## T02 — Config, base path, nginx examples

- Status: pending
- Requires: T01
- Requirements: S-006, S-007
- Read: `docs/DEPLOY.md`, `docs/API.md` (config route), `docs/SECURITY.md`

Implement the TOML keys from `docs/DEPLOY.md` with those defaults. Refuse a bad `base_path`. Mount health and `GET /api/v1/config` under `base_path`. Inject nothing yet; the config route is the contract test.

Write `deploy/nginx/whiteboard-root.conf` and `deploy/nginx/whiteboard-prefix.conf` plus the upgrade map, matching `docs/DEPLOY.md`. Add the redirect from `/whiteboard` to `/whiteboard/`.

Acceptance: pytest covers both base paths (T-013) and asserts those responses have no `Set-Cookie` (start of T-012). ruff and ty pass.

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
- Read: `docs/ARCHITECTURE.md` (mount and navigation)

Create `web/` with Vite, React, TypeScript, and React Router. Pin `@excalidraw/excalidraw` and record that version in `versions.toml`. Record the reconcile choice in `docs/DECISIONS.md`. Isolate imports in `web/src/canvas/`. The about line or an equivalent status in the segl bar shows the application version read from `versions.toml`.

The segl bar sits outside the canvas: slot buttons 1–9, the shared title, room for the later presence count, and the notice that the workspace is shared. `{base}/` honors `localStorage` last-slot. `{base}/s/N` saves last-slot and loads that head. Invalid slot URLs go to slot 1.

Python serves `web/dist` in production mode and injects `window.SEGL_CONFIG`. Document the dev loop: the Vite dev server proxies `{base}/api` and `{base}/collab` to Python. The dev default `base_path` is `/`. Prefix mounts are tested through the Python production build, not by rebuilding the frontend.

Capture the editor's real empty `initialData`, store it as the bootstrap fixture, and migrate existing empty heads to it if their JSON is the T03 placeholder.

Bundle fonts and other editor assets so T-010 can pass with outbound network disabled. Record how in `docs/DECISIONS.md`.

Acceptance: production build served by Python renders a slot under both base paths; the empty scene loads; the shared notice is visible; T-010 passes for the slot page; `web` typecheck passes; ruff and ty pass.

## T05 — Display names

- Status: pending
- Requires: T04
- Requirements: S-009
- Read: `docs/ARCHITECTURE.md` (display names), `draft2/display-names.txt`

Copy `draft2/display-names.txt` to `deploy/display-names.txt`. Implement allocation, the 30/minute limit, and `POST /api/v1/display-name`. The bar shows the current label and accepts a rename, title-cased, broadcast only locally until T06 carries it on the socket (store it in `localStorage` now; T06 must not allocate again).

Acceptance: T-014 against a temp word file; a test that the packaged file has at least 100 unique `^[A-Za-z]{1,10}$` entries; the browser keeps a label across reload. ruff, ty, and the web typecheck pass.

## T06 — Live collaboration

- Status: pending
- Requires: T05
- Requirements: S-002, S-008, S-010, S-013
- Read: `docs/ARCHITECTURE.md` (collaboration, edit gate), `docs/API.md` (WebSocket)

Implement the room, the WebSocket messages, reconcile, presence, and the view-only gate. The menu count and the participant list use this room. Show connecting, live, and disconnected. `saved` can light up in T07; for this task, show live once `welcome` arrives.

If the pinned package exports a reconcile helper, use it in the client and match it in the server unit test. Otherwise use version, then versionNonce. Record the choice in `docs/DECISIONS.md`.

Acceptance: T-001, T-002, T-003, T-008, T-015, and the reconnect half of T-004. Two browsers means two Playwright contexts (or the test runner's equivalent) against one server. ruff, ty, and the web typecheck pass.

## T07 — Durability, history rows, images

- Status: pending
- Requires: T06
- Requirements: S-004, S-005 (storage, not the panel), S-012, S-013
- Read: `docs/DATA-MODEL.md` (flush rules)

Flush the head, append revisions, honor the caps and intervals from config (tests use short intervals), flush on last disconnect and on SIGTERM. Emit `saved`. Persist an embedded image using the editor's file model.

Acceptance: T-005, T-006, T-007, and a unit test that the 51st revision drops the oldest. The UI shows saving and then saved. ruff, ty, and the web typecheck pass.

## T08 — History panel and restore

- Status: pending
- Requires: T07
- Requirements: S-005
- Read: `docs/API.md` restore routes, epoch rules in `docs/ARCHITECTURE.md`

Add the revision list and restore control in the bar. Restore is view-only blocked when a token is set. Connected clients follow the new epoch.

Acceptance: T-011. ruff, ty, and the web typecheck pass.

## T09 — JSON export and import

- Status: pending
- Requires: T08
- Requirements: S-011
- Read: `docs/API.md` import route

Use the editor's Excalidraw JSON export. Import posts to the import route, which follows the restore epoch rules. Reject an oversized body with `payload_too_large`.

Acceptance: T-009. ruff, ty, and the web typecheck pass.

## T10 — Edit-token browser flow and cookie sweep

- Status: pending
- Requires: T09
- Requirements: S-007, S-008, S-016
- Read: `docs/SECURITY.md`, `docs/ARCHITECTURE.md` (edit gate)

Store `#e=` into the base-path `localStorage` key and strip the fragment. Put the editor into view mode when this client must not edit, and say so in the bar. Send the token only as the HTTP header and inside WebSocket messages.

Acceptance: T-008 in the browser, including the fragment link; T-012 across the routes that now exist, including a WebSocket handshake. ruff, ty, and the web typecheck pass.

## T11 — P0 browser matrix in the dev container

- Status: pending
- Requires: T10
- Requirements: S-017 and the browser rows of `docs/TEST-PLAN.md`
- Read: `docs/TEST-PLAN.md`

Make T-001 through T-016 runnable as one command inside the dev container. Try a 10-editor stretch once, record the observation in `STATUS.md`, and do not block on it. Run the 1,000-element load once and record it the same way.

Acceptance: that container command exits 0 on T-001 through T-016. Evidence goes into the STATUS log.

## T12 — Debian package and systemd

- Status: pending
- Requires: T11
- Requirements: S-015
- Read: `docs/DEPLOY.md`

Build a `.deb` that installs the uv-pinned CPython under `/opt/segl/python`, a virtualenv from `uv.lock`, `web/dist`, the example TOML, the display-name file, the systemd unit, `deploy/OPERATOR.md`, and `LICENSE` under the package documentation path. The package copyright file names Apache-2.0. Create user `segl`. The unit's stop flushes heads (covered by T07's SIGTERM test).

Acceptance: T-017 on Ubuntu 26.04. If this session cannot reach an Ubuntu 26.04 host, build the package here, install it in the Ubuntu 26.04 dev container, run the slot page through the unit's `ExecStart` with a test TOML, and log that nginx TLS was checked by reviewing the example configs rather than a public certificate. Do not mark T-017 fully passed without a TLS proxy; say so in the log and leave a follow-up line on T13.

Out of scope: the production container image (L-005).

## T13 — MVP gate

- Status: pending
- Requires: T12
- Requirements: all S-001–S-017
- Read: `docs/TEST-PLAN.md` evidence section

Re-run T-001 through T-018. Append the evidence block to `STATUS.md`. On full pass, set Next task to `NONE` and Completed to T01–T13. On a failure, set Next task to the task that owns the defect and do not open P1.

This task does not add features.
