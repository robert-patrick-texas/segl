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

The process serves `GET /api/v1/health` → `{ "status": "ok" }` on the configured bind address, default `127.0.0.1:8888`. Load a TOML path from `--config` if the flag is present. For this task a missing file still serves health.

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

- Status: done
- Requires: T01
- Requirements: S-006, S-007
- Read: `docs/DEPLOY.md`, `docs/ARCHITECTURE.md` (mount and navigation), `docs/API.md` (config route), `docs/SECURITY.md`

Implement the TOML keys from `docs/DEPLOY.md` with those defaults, and the development defaults when `--config` is absent, with a `segl.toml` in the working directory read over them. Refuse a key segl does not know, and a value it cannot use, at startup. Write `deploy/segl.toml.example` with the production paths. Serve health and `GET /api/v1/config` at segl's root. Run uvicorn with proxy headers believed only from `trusted_proxies`. Every redirect segl sends is relative. The framework's trailing-slash redirect is absolute, so it is off, and segl sends no redirect yet. Inject nothing into pages yet; the config route is the contract test.

Add nginx and openssl to the dev container, and install nginx in CI. Add a pytest harness (`tests/harness.py`, used by `tests/test_mount.py`) that runs the real segl server on a free loopback port, and nginx in front of it with the `deploy/nginx/` files. Copy those files to a temporary prefix, point the upstream at the test port, and use a test certificate in place of snakeoil. Do not edit the shipped files for the test.

Acceptance:

- pytest covers the HTTP half of T-013 through the harness: `/board` redirects to `/board/`, and `/board/api/v1/health` and `/board/api/v1/config` reach segl. The same requests work at a host root.
- Those responses have no `Set-Cookie` (start of T-012).
- `nginx -t` passes for both site examples.
- The harness skips with a clear message when nginx is not installed, or is older than 1.25.1, or openssl is missing. It does not skip in the dev container or in CI: `SEGL_REQUIRE_NGINX=1` turns the skip into a failure there.
- ruff and ty pass.

## T03 — SQLite slots

- Status: done
- Requires: T02
- Requirements: S-003
- Read: `docs/DATA-MODEL.md`

Add migrations and the repository methods. Startup bootstraps nine slots. Use a temporary empty scene document `{ "elements": [] }` until T04 replaces it with a fixture captured from the editor. Expose `GET /api/v1/slots`, `GET /api/v1/slots/{n}`, and `GET /api/v1/slots/{n}/scene`.

The repository is `src/segl/repository.py`, opened by the `segl` command before it serves and passed to `create_app`. Every error segl sends has the `{ "error", "message" }` shape, including an unknown path.

Acceptance: a test boots a temp database, reads nine titles `Workspace 1`–`Workspace 9`, checks isolated scenes, and checks that slot 0 and slot 10 return `invalid_slot`. ruff and ty pass.

## T04 — Excalidraw shell

- Status: done
- Requires: T03
- Requirements: S-001, S-003, S-006, S-014, S-016
- Read: `docs/ARCHITECTURE.md` (mount and navigation), `docs/DECISIONS.md` D2-004, D2-007, and D2-023, `docs/DEVELOPMENT.md`

Create `web/` with Vite, React, TypeScript, and React Router, using npm (D2-023). Put exact versions in `web/package.json`, commit `web/package-lock.json`, set `engine-strict=true` in `web/.npmrc`, and name the newest Node LTS release in `web/.node-version`. Record Node and every direct web dependency in `versions.toml`. Pin `@excalidraw/excalidraw` at its newest stable release and add its notice to `NOTICE`. Record the reconcile choice in `docs/DECISIONS.md`. Isolate imports in `web/src/canvas/`. The about line, or an equivalent status in the segl bar, shows the application version read from `versions.toml`.

Add the npm scripts `build`, `check` (`tsc --noEmit`), `test` (Vitest), `format:check` (Prettier), and `e2e` (Playwright). Add the web checks, the build, and the browser tests to CI, and the web checks and the build to the dev container. The release suite in `scripts/release_upgrade.py` runs them too.

The segl bar sits outside the canvas. It holds slot buttons 1–9, the shared title, room for the later presence count, and the notice that the workspace is shared. Visiting segl's root honors the `localStorage` last slot. `s/N` saves the last slot and loads that head. Invalid slot URLs go to slot 1.

Build with Vite `base: './'`. Python serves the build in `web_dir`, a setting whose value is `web/dist` in a checkout and `/opt/segl/app/web/dist` in production. It serves `index.html` for `/` and `/s/{n}` with asset URLs relative to that page, and injects `window.SEGL_CONFIG` with `root` and `editRequired` (`docs/ARCHITECTURE.md`). Without a build it serves the API alone. The app derives `basePath`, API URLs, the WebSocket URL, the router basename, and `EXCALIDRAW_ASSET_PATH` from `root`. Document the dev loop in `docs/DEVELOPMENT.md`. The Vite dev server proxies `/api` and `/collab` to Python with `changeOrigin: false`.

Set up `@playwright/test` with a `webServer` that runs `uv run segl --config <temporary TOML>` serving the production build. Put nginx in front of it with the `deploy/nginx/` files as T02's harness does (`tests/e2e_nginx.py`), one nginx for each site example, each on its own loopback port, and support `PW_WS_ENDPOINT` (`docs/DEVELOPMENT.md`). Every spec runs against Python directly, at a host root behind nginx, and at `/board/`.

Capture the editor's real empty `initialData`, store it as the bootstrap fixture (`src/segl/empty_scene.json`), and migrate existing empty heads to it if their JSON is the T03 placeholder. A browser test holds the fixture to the editor.

Bundle fonts and other editor assets so T-010 can pass with outbound network disabled. Record how in `docs/DECISIONS.md`.

Acceptance:

- Playwright, against the production build, renders a slot at a host root and through nginx at `/board/`, and the page asks for nothing outside `/board/` (the page half of T-013).
- The empty scene loads, and the shared notice is visible.
- T-010 passes for the slot page.
- `npm run check`, `npm test`, and `npm run format:check` pass in `web/`.
- ruff and ty pass.

## T05 — Display names

- Status: done
- Requires: T04
- Requirements: S-009
- Read: `docs/ARCHITECTURE.md` (display names), `docs/SECURITY.md` (client address), `draft2/display-names.txt`

Copy `draft2/display-names.txt` to `deploy/display-names.txt`. From then on `deploy/display-names.txt` is the packaged list. Implement allocation, the 30/minute limit per client address, and `POST /api/v1/display-name`. The bar shows the current label and accepts a rename, title-cased. Until T06 carries it on the socket, the rename is only shown locally: store it in `localStorage` now, and T06 must not allocate again.

The server reads the word file at startup and stops when it has no usable words (`src/segl/names.py`). The title case is written on both sides now, `title_case_name` in Python and `titleCaseName` in `web/src/names.ts`, and both are held to `tests/display_name_cases.json`. T06 calls the Python one for the `rename` message. The browser tests start with a stored name, because of the limit (`docs/DEVELOPMENT.md`).

Acceptance:

- T-014 runs against a temp word file, including its rate-limit case through the nginx harness. Its broadcast of the rename is T06's.
- A test checks that the packaged file has at least 100 unique `^[A-Za-z]{1,10}$` entries.
- The browser keeps a label across reload.
- ruff, ty, and the web checks pass.

## T06 — Live collaboration and titles

- Status: done
- Requires: T05
- Requirements: S-002, S-003 (titles), S-008, S-010, S-013
- Read: `docs/ARCHITECTURE.md` (collaboration, edit gate), `docs/API.md` (WebSocket, slot route), `docs/SECURITY.md` (Origin)

Implement the room, the WebSocket messages, reconcile, presence, and the view-only gate. The menu count and the participant list use this room. Show connecting, live, and disconnected. `saved` can light up in T07. For this task, show live once `welcome` arrives.

Implement title editing in the bar and `PATCH /api/v1/slots/{n}`, broadcast to the room as a `slot` message. Refuse a WebSocket upgrade or a mutation whose `Origin` does not match `Host` (`docs/SECURITY.md`).

If the pinned package exports a reconcile helper, use it in the client and match it in the server unit test. Otherwise use version, then versionNonce. Record the choice in `docs/DECISIONS.md`.

The package exports `reconcileElements`, and D2-025 records the choice. The room keeps its scene in memory, and T07 writes it to the head. The server gates on the token in `hello` and on the `X-Segl-Edit-Token` header, and the page already sends a stored token both ways. T-008 is tested at the socket and the route here, with real processes. T10 adds the `#e=` link and tests T-008 in the browser. `websockets` is a new dependency, and a participant has no color (D2-027).

Acceptance: T-001, T-002, T-003, T-008, T-015, T-016, the reconnect half of T-004, and the WebSocket half of T-013 (two contexts sync over `/board/collab` through nginx). Two browsers means two Playwright contexts against one server. ruff, ty, and the web checks pass.

## T07 — Durability, history rows, images

- Status: done
- Requires: T06
- Requirements: S-004, S-005 (storage, not the panel), S-012, S-013
- Read: `docs/DATA-MODEL.md` (flush rules), `docs/API.md` (uploaded files, `files` message)

Flush the head, append revisions, honor the caps and intervals from config (tests use short intervals), and flush on last disconnect and on SIGTERM. Emit `saved`. Persist an embedded image using the editor's file model: upload the bytes to `POST /api/v1/slots/{n}/assets`, announce them with a `files` message, record the file list with the head, and serve `GET /api/v1/assets/{hash}`.

The editor keeps an image's bytes outside the scene, under a file id, so the bytes are files under `assets_dir` and the file list is a table of its own, `slot_file` (D2-028). `saved` answers a `seq` number the browser gives its messages, a stored head keeps its deleted elements, and a slot's elements are limited to `max_scene_bytes` (D2-029). T-006 and the restart of T-007 run against a segl the test starts and kills itself, in pytest and in the `restart` project of the browser tests. T08 adds the routes that list and restore the revisions this task writes.

Acceptance: T-005, T-006, T-007, and a unit test that the 51st revision drops the oldest. The UI shows saving and then saved. ruff, ty, and the web checks pass.

## T08 — History panel and restore

- Status: done
- Requires: T07
- Requirements: S-005
- Read: `docs/API.md` restore routes, epoch rules in `docs/ARCHITECTURE.md`

Add the revision list and restore control in the bar. Restore is view-only blocked when a token is set. Connected clients follow the new epoch.

The three routes are the revision list, one revision, and restore. A restore first keeps the scene it replaces as a revision, so it can be undone, and takes `displayName` for the name on its own revision (D2-030). The slot's saver does both writes under the lock its flushes take. The History control marks a row a restore wrote from its epoch, reads the list when it is opened and when the epoch moves, and restores in two presses. T-011 runs in `web/e2e/history.spec.ts` on slot 3 and in `tests/test_history.py`, which also holds the history part of T-008 and the 51st revision. T09's import replaces a scene through the same saver method, `Saver.replace`. T10 tests the viewer's list in a browser.

Acceptance: T-011. ruff, ty, and the web checks pass.

## T09 — JSON export and import

- Status: done
- Requires: T08
- Requirements: S-011
- Read: `docs/API.md` import route

Use the editor's Excalidraw JSON export. Import posts to the import route, which follows the restore epoch rules. Reject an oversized body with `payload_too_large`.

The export is the editor's own menu entry, and segl names the file after the slot's title. The editor's own ways to open a scene file are off, because each fills one browser's canvas and not the slot: the bar's Import control posts the file to the route instead, after a second press, and so does a scene file dropped on the canvas (D2-031). The route takes the document's elements and the files they name, stores the files as uploads, and leaves `appState`. Who imported comes in the `X-Segl-Display-Name` header. The slot's saver does the import as it does a restore, through `Saver.put`. The History control's mark on the first row of an epoch reads `replacement`, for a restore or an import. T-009 runs in `web/e2e/import.spec.ts` on slot 8 and in `tests/test_import.py`, which also holds the import part of T-008. T10 tests the viewer's Import control in a browser.

Acceptance: T-009. ruff, ty, and the web checks pass.

## T10 — Edit-token browser flow, cookie and Origin sweep

- Status: done
- Requires: T09
- Requirements: S-007, S-008, S-016
- Read: `docs/SECURITY.md`, `docs/ARCHITECTURE.md` (edit gate)

Store `#e=` into the `basePath` `localStorage` key and strip the fragment. Put the editor into view mode when this client must not edit, and say so in the bar. Send the token only as the HTTP header and inside WebSocket messages.

The page takes the fragment out of the address at once and stores the token only once the server has taken it, so a link with a wrong token cannot displace a stored one (D2-032). A token is what a request header carries whole, and segl does not start with another. The notice in the bar has a sentence for each state of the gate. A viewer's canvas takes no drop, which the editor's view mode does not cover. T-008 runs in `web/e2e/token.spec.ts`, against a second test server with a token, directly and through nginx at both mounts. T-012 is `tests/test_sweep.py`, a walk over every route in process and through nginx, and `web/e2e/origin.spec.ts`, a page of another site in a real browser.

Acceptance: T-008 in the browser, including the fragment link. T-012 across the routes that now exist, including a WebSocket handshake and the Origin refusals. ruff, ty, and the web checks pass.

## T10b — Access codes, passes, and internal networks

- Status: pending
- Requires: T10
- Requirements: S-008 (which this task rewords), S-007, S-016, and a new S-018 for `internal_networks`
- Read: `docs/DECISIONS.md` D2-033, D2-032, and D2-027, `docs/SECURITY.md`, `docs/ARCHITECTURE.md` (edit gate), and texas2step's `docs/access.md` and `src/texas2step/access.py` in `/home/netops/code/texas2step`, whose access codes this follows in their simplest form

Added on 2026-11-12 at the user's request, after T10. It replaces the one static `edit_token` with access codes that buy a pass (D2-033). The aim is to keep honest people on an internal network from changing or deleting a board by mistake while segl is introduced. It is not authentication: there are no users and no accounts, and a pass says only that someone knew a code. Real authentication comes in a later phase, with RADIUS as one option and SAML or other methods after it (`docs/ROADMAP.md`). Keep this task small.

Settings, each in `docs/DEPLOY.md` and `deploy/segl.toml.example`:

- `access_codes`: a list of codes, words, or phrases, `[]` by default. Empty means everyone edits, as an empty `edit_token` does today. With one or more, editing needs a pass, and `GET api/v1/config` says `editRequired` true.
- `access_secret`: the server's secret, which signs a pass. segl does not start with codes and no secret. It is never in a log, a page, or an answer, and stays out of the `Settings` repr, as the token does today.
- `access_pass_hours`: how long a pass can be used from the moment it was issued, 12 by default, and `0` for no limit.
- `access_passes_after`: an optional time. A pass issued before it is refused. Setting it and restarting ends every pass issued so far, while the codes still work.
- `internal_networks`: a list of IPv4 and IPv6 networks in CIDR form, `[]` by default.
- `edit_token` goes: no release shipped with it. A file that still has it stops segl by the unknown-key rule, and the message should point at `access_codes`.

A code is compared as texas2step compares one (`normalize` there): lowercase letters and digits, with any run of other characters as one separator, so `Maple River 42` and `maple.river.42` are one code. The comparison is constant-time, against every code in the list. A code with fewer than 8 letters and digits, or one that is in the list twice, stops segl at startup, and the message gives the entry's place in the list and not its text.

A pass is texas2step's: the time it was issued, and a signature over it under `access_secret`, as `<issued>.<signature>`. The code it was bought with goes into what is signed, so taking a code out of the list ends the passes that code bought. Anything else the pass needs to carry goes in the same way, signed. It is printable ASCII and far under 256 characters, so T10's rule for what a page can send in a header still holds for it. The server keeps no list of passes. It takes a pass when the signature fits one of the codes, compared in constant time, when the pass was issued at or after `access_passes_after`, when it is not from more than five minutes ahead of the server's clock, and when it is younger than `access_pass_hours` as that is set now.

The server:

- `POST api/v1/access` takes `{ "code" }`, a JSON object of at most 4096 bytes, and answers `{ "pass", "expiresAt" }` with `Cache-Control: no-store`. `expiresAt` is null when there is no limit. A wrong code is `403` with a new code such as `wrong_code`. It sets no cookie, and it is a mutation for the Origin check.
- Wrong codes are counted per client address, in memory, as the display-name limit counts: after five in a row, every code from that address is `429` with `rate_limited` and `Retry-After` for fifteen minutes, and a right code starts the count again. texas2step counts by network and keeps a file. That is more than this needs.
- The gate checks a pass wherever `may_edit` compares the token today: in `hello`, and in the header of a title change, a restore, an import, and an upload. The header and the field keep their names, `X-Segl-Edit-Token` and `editToken`, and carry the pass.
- A pass can end while a socket is open. The connection keeps the time its pass ends, from `hello`, and an `elements` or `files` message after that time is answered `view_only`, as any viewer's is. The page already turns view-only when it is told so.
- With `internal_networks` set, segl answers nobody outside it. Every request and every WebSocket handshake from another address is `403` with a new code such as `outside_network`, before any route and before the Origin check, the health route and the pages among them. The address is the one segl already believes, `X-Forwarded-For` from `trusted_proxies` (`docs/SECURITY.md`). Loopback counts as inside, as in texas2step's `is_internal`, and an IPv4 address written as IPv6 is read as IPv4. An entry that is not a network stops segl at startup. `docs/DEPLOY.md` has to say that a proxy missing from `trusted_proxies` makes every client look like the proxy. A firewall can do the same job. This is the second check.

The page:

- A browser that may not edit has a button in the bar, by the notice, such as `Enter access code`. It opens the access page, `access` under segl's root, which Python serves as it serves `/`. Add `access` to the reserved first segments in `docs/API.md`. The page has one field. A right code stores the pass under the `basePath` key, where the token is today, and goes back to the slot the person came from, where the page says `hello` again and may edit. A wrong code is answered in words, and so is a browser that has to wait.
- It is called the access page, not a login: a login has a user, and that name is kept for the later phase.
- T10's notice keeps its states. Its `refused` state now also means a pass that has ended, and its words say so and point at the button.
- The `#e=` link of T10 goes, at the user's word: where a site limits editing to access codes, an editor provides an access code. Nothing hands a pass from one browser to another. Take out what only the link needed: reading and stripping the fragment in `web/src/main.tsx` and `web/src/editToken.ts`, the `hashchange` listener, and the state for a token that is still to be proven, with the session's `onGate` if nothing else uses it. A pass comes from the access route alone, so the page stores it as soon as it is issued. The page no longer reads a fragment: an old link opens the slot as any address does, and the token in it opens nothing.
- What stays from T10: the pass in `localStorage` under the `basePath` key, a pass another tab stored reaching this one (`storage`), a new `hello` when the pass changes, the notice, the viewer's canvas that takes no drop, and the rule for what a page can send in a header.
- No cookie (S-007). The pass lives in `localStorage` and goes to the server in the header and in `hello`, and in no URL.

Tests:

- pytest: codes and their normal form, the pass and each of the four reasons to refuse one, with a clock the test moves, the route, the count of wrong codes, and each gate. A real process with codes in its TOML, and the access route through nginx. `tests/test_sweep.py` takes the new route into its walk, and the `outside_network` answer sets no cookie either.
- `internal_networks` in process, and against a real process that trusts `127.0.0.1` and is sent `X-Forwarded-For`, as `tests/test_names.py` does for the name limit. The test nginx overwrites that header with `127.0.0.1`, so through it every client is inside.
- The browser: the server of the `token-` projects gets `access_codes` in place of `edit_token`, and `web/e2e/token.spec.ts` has a viewer press the button, enter the code, and edit. Its link tests go, and so does the link test in `web/e2e/slot.spec.ts`. One test opens an address that ends in `#e=` and something, and shows that it is an address like any other: the browser stays a viewer and nothing is stored. A pass that ends needs a server of its own with a short `access_pass_hours`, as `web/e2e/server.ts` starts one for the restart tests.

Documents: reword S-008 and T-008 from the token to codes and a pass. Add S-018, and test-plan rows after T-018 for codes and passes and for `internal_networks`. Take the new rows into T11's and T13's ranges and into the gate line of `docs/ROADMAP.md`. Update `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/DEPLOY.md` (its operator notes name `edit_token`, and it says how to write a link), `docs/DEVELOPMENT.md`, rule 9 of `draft2/AGENTS.md`, `README.md` (its status names the link), and `CHANGELOG.md`. Each of them describes the link today.

As built, where the text above left a choice open:

- `access_secret` has at least 32 characters. The pass is left in a browser's storage, and without a strong secret it would be a way to test guesses at a code offline.
- A code is ASCII, and at most 256 characters as written. A letter outside ASCII would count as a separator, and the code would not be the one that was written.
- `access_passes_after` is a TOML time with its offset, and `""` for none. A time more than five minutes ahead of the server's clock is said on a line of output at startup, and segl still starts.
- A count of wrong codes is forgotten fifteen minutes after its last one. A body that is not a code is `bad_request` and is not counted. An address that starts to wait is logged, once, without what it sent.
- On a segl without codes the access route is `404` with `no_access_codes`, and the access page says that everyone can edit.
- The refusals' codes are `wrong_code` and `outside_network`. A client with no address, or with text that is not one, is outside.
- The bar's way to the access page is a link, `Enter access code`, which takes the slot along in the router's history entry. Opened by its address, the page goes back to the last slot the browser used. The field is plain text, not a password field.
- The page does not know when its pass ends. It is told at its next edit, and what was drawn in that moment stays on that one canvas until the slot is loaded again.
- The page's modules are `web/src/pass.ts`, `usePass.ts`, `access.ts`, and `AccessPage.tsx`. `editToken.ts`, `useEditToken.ts`, and the session's `onGate` are gone. The browser spec is `web/e2e/access.spec.ts` in the projects `access-direct`, `access-root`, and `access-board`, and the pass that ends is `web/e2e/expiry.spec.ts`, in the `restart` project. The table of what a header carries is `tests/header_value_cases.json`.
- The bar wraps at any width. The new link showed that between 721 and about 1,100 pixels the notice had been squeezed into a column a word wide.

Acceptance: T-008 as reworded, the new rows, and T-012 with the new route. ruff, ty, and the web checks pass.

## T11 — P0 browser matrix in the dev container

- Status: pending
- Requires: T10b
- Requirements: S-017 and the browser rows of `docs/TEST-PLAN.md`
- Read: `docs/TEST-PLAN.md`, `docs/DEVELOPMENT.md` (browsers)

Make T-001 through T-016, T-019, and T-020 runnable as one command inside the dev container, under rootful Docker and under rootless Docker or Podman. If Chromium cannot run in the Ubuntu 26.04 container, use the Playwright image through `PW_WS_ENDPOINT` and record why. Try a 10-editor stretch once, record the observation in `STATUS.md`, and do not block on it. Run the 1,000-element load once and record it the same way.

Acceptance: that container command exits 0 on T-001 through T-016, T-019, and T-020. Evidence goes into the STATUS log.

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

Re-run T-001 through T-020. Append the evidence block to `STATUS.md`. On full pass, set Next task to `NONE` and Completed to T00–T13. On a failure, set Next task to the task that owns the defect and do not open P1.

This task does not add features.
