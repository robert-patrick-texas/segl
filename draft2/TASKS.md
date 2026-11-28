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

- Status: done
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
- As first built, the page did not know when its pass ends: it was told at its next edit, and what was drawn in that moment stayed on that one canvas. Changed the same day, at the user's request and after the task: `welcome` carries `editEndsIn`, the seconds the pass has left, and the page stops taking edits a second before that.
- The page's modules are `web/src/pass.ts`, `usePass.ts`, `access.ts`, and `AccessPage.tsx`. `editToken.ts`, `useEditToken.ts`, and the session's `onGate` are gone. The browser spec is `web/e2e/access.spec.ts` in the projects `access-direct`, `access-root`, and `access-board`, and the pass that ends is `web/e2e/expiry.spec.ts`, in the `restart` project. The table of what a header carries is `tests/header_value_cases.json`.
- The bar wraps at any width. The new link showed that between 721 and about 1,100 pixels the notice had been squeezed into a column a word wide.

Acceptance: T-008 as reworded, the new rows, and T-012 with the new route. ruff, ty, and the web checks pass.

## T11 — P0 browser matrix in the dev container

- Status: done
- Requires: T10b
- Requirements: S-017 and the browser rows of `docs/TEST-PLAN.md`
- Read: `docs/TEST-PLAN.md`, `docs/DEVELOPMENT.md` (browsers)

Make T-001 through T-016, T-019, and T-020 runnable as one command inside the dev container, under rootful Docker and under rootless Docker or Podman. If Chromium cannot run in the Ubuntu 26.04 container, use the Playwright image through `PW_WS_ENDPOINT` and record why. Try a 10-editor stretch once, record the observation in `STATUS.md`, and do not block on it. Run the 1,000-element load once and record it the same way.

As built, where the text above left a choice open:

- The command is the image's own: `docker run --rm --init segl-dev` runs `scripts/testplan.py`. It runs pytest and the browser tests whole and prints one line for each row. `tests/testplan.toml` names the tests of each row, and `tests/test_testplan.py` holds that table to the test plan and to the tests' names.
- A row passes when every test it names ran and passed, in each Playwright project it belongs to. A skipped test fails its row. The script judges T-018 itself, in the dev container alone.
- Chromium runs in the Ubuntu 26.04 image, installed by the pinned `@playwright/test`. The Playwright image and `PW_WS_ENDPOINT` were not needed there.
- The build still runs the web checks, the web build, and pytest. The run runs pytest again, with the browser tests.
- Rootful Docker and rootless Docker ran it. The rootless daemon was started by hand and removed afterwards. Podman was not tried: the host has none.
- The two sizes are `npm --prefix web run stretch`, in a config of its own, as Sunstone's `bench` is. The elements are 1,024: one rectangle, doubled ten times in the editor, so no element is hand-made.
- Found, and not changed in the task: a browser that loads a large slot sometimes sends the whole scene back before the server's `scene` arrives (`draft2/STATUS.md`, T11). Changed the same day, at the user's request and after the task: the page's list of what the server holds starts with the scene it loaded.

Acceptance: that container command exits 0 on T-001 through T-016, T-019, and T-020. Evidence goes into the STATUS log.

## T12 — Debian package and systemd

- Status: done
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

As built, where the text above left a choice open (D2-034):

- The files are in `deploy/debian/`, with the unit in `deploy/systemd/segl.service`. `build-deb.sh` builds, and `package-test.sh` is T-017, in an `ubuntu:26.04` container booted with systemd.
- The package owns the program alone. postinst makes `/opt/segl/etc` and `/opt/segl/var`, and copies the example TOML (mode `0640`, group `segl`) and the display-name file there only when they are missing. Neither is a dpkg conffile.
- A first install enables and starts nothing, as Sunstone's does. An upgrade restarts segl if it was running. Remove keeps the settings and the boards. Purge removes the settings and keeps the boards.
- `/opt/segl/app` holds `web/dist` alone. The server's code is the `segl` wheel in the virtualenv.
- The package documentation path is `/usr/share/doc/segl`: `OPERATOR.md`, `LICENSE`, `NOTICE`, the copyright file, and the license texts of the bundled parts.
- The unit adds to the manual's sketch: the system is read-only to segl but `/opt/segl/var`, exit status 2 gets no restart, and five starts in a minute is the limit.
- `uv.lock` holds the build backend too, as the `build` dependency group, so the wheel is built with hashed tools.
- nfpm is 2.49.0, pinned in `deploy/debian/Containerfile` with its Go image. It is not in `versions.toml`, and `release.py check` does not see it.
- The license texts: every npm package in the web build and every font gets its text in the package, and one without a text fails the build. `web/licenses/` keeps the texts for what ships none. Liberation Sans in the editor is version 1.05, under the GPL version 2 with a font exception. Changed the same day, at the user's request and after the task: the build ships Liberation Sans 2.1.5, under the Open Font License, in its place (`web/fonts/`, D2-026).
- `scripts/release.py publish` runs `package-test.sh` as its last preflight step and attaches the package it built.
- CI builds and installs the package as a second job.
- Changed the same day, at the user's request and after the task (D2-035): the package also carries `segl update`, its timer, and the release signers. Its `postinst` adds a new version's settings to `segl.toml` and merges nginx changes into the site's files. `package-test.sh` is T-021 too.

Acceptance: T-017 on Ubuntu 26.04, on a host or in an `ubuntu:26.04` container booted with systemd. That machine runs nginx with the `deploy/nginx/` files and `site-board.example.conf`, using Ubuntu's snakeoil certificate. If neither is available, log what was checked and leave a follow-up line on T13.

Out of scope: the production container image (L-005).

## T13 — MVP gate

- Status: done
- Requires: T12
- Requirements: all S-001–S-019
- Read: `docs/TEST-PLAN.md` evidence section

Re-run T-001 through T-021. Append the evidence block to `STATUS.md`. On full pass, set Next task to `NONE` and Completed to T00–T13. On a failure, set Next task to the task that owns the defect and do not open P1.

This task does not add features.

As run, on 2026-11-13 and on commit `00ea07f`:

- The dev container ran T-001 through T-016, T-018, T-019, and T-020, once under rootful Docker and once under rootless Docker. `deploy/debian/package-test.sh` ran T-017 and T-021.
- Every row passed. `STATUS.md` has the evidence.
- The gate changed no code and no test. It corrected the gate line of `docs/ROADMAP.md`, which still said T-020.

## T14 — Send a scene once

- Status: done
- Requires: T13
- Requirements: S-002, S-013
- Read: `docs/ROADMAP.md` (after the gate, send a scene once), `docs/API.md` (the scene route and the WebSocket), `docs/ARCHITECTURE.md` (collaboration), `docs/DECISIONS.md` D2-025, `src/segl/room.py`, `src/segl/saver.py`, `web/src/collab/session.ts`, and the STATUS entries of T11 and of 2026-11-13 on the roadmap entry

Added on 2026-11-16 at the user's request, after release 0.3.0. It is the roadmap entry "send a scene once". It is not part of P0. Today a page that opens a slot gets the scene twice: the stored head over HTTP, then the room's scene over the socket, after `welcome`. After this task the socket sends only what changed since the HTTP copy. For a quiet slot that is nothing. For a slot of 1,024 elements each copy was about 431,000 bytes (STATUS, the roadmap entry of 2026-11-13). Keep this task small.

The mark:

- A mark names a point in one room's changes: a value the server picks when it starts, the epoch, and the room's count of changes. One way to write it: `<start>.<epoch>.<count>`, as one ASCII string. The page does not read it. It hands it back.
- The room counts every change it takes: an `elements` batch with a winner, a `files` message with a new file, and a restore or an import. It notes the count at each element's and each file's last change. The count only goes up while the process runs. All of it lives in memory. Nothing joins the database.
- The changes since a mark are the elements whose count is higher than the mark's, deleted ones included, in drawing order. With them go the files they name, and every file the slot took since the mark.

The rule: a mark never says that a copy holds more than it does. A copy that holds more than its mark says costs a few elements sent twice. A mark that says more than its copy holds loses a drawing.

The server:

- The scene route's answer carries `mark`, the mark of the head it returns. A flush writes the head in a worker thread, so the head can be one flush behind the room. The mark is therefore that of the last head write that finished, taken before the head is read. A slot with no room yet has count 0, and its room starts from the head at count 0. A restore or an import writes the head, then gives the room its scene. A mark taken between the two names the old epoch, so it gets a whole scene.
- `hello` takes an optional `mark`: a string of at most 64 characters, or `null`. Anything else is `bad_message`.
- After `welcome`, the server sends `scene` as today. It gains two fields: `whole`, and `mark`, the room's count when it was sent. With a mark of this start, this epoch, and a count the room has reached, `scene` holds only the changes since the mark, with `whole` false. For a quiet slot that is no element. With no mark, or any other mark, it holds the whole scene, with `whole` true. That happens after a restart, a restore, or an import.
- Every other `scene` is whole, as today: after an epoch mismatch, and to every connection after a restore or an import.

The page:

- The HTTP copy stays. It paints the canvas when the socket is slow or never opens. The page still reconciles what it is sent (D2-025).
- The page keeps a base: the stamps (`id`, `version`, `versionNonce`) and files of the newest scene the server sent, with its mark. At first that is the HTTP copy. `hello` carries the base's mark, so a page that reconnects asks only for what changed since its last `scene`. A whole `scene` replaces the base. One that is not whole is laid over it.
- After each `scene`, `known`, the list of what the server holds, becomes the base, and never what the page itself sent. Today `sendPending` notes a batch as known when it sends it, and the whole scene a reconnect brings puts that right. A batch the socket lost before the server took it must still go again after a `scene` that is not whole. This is the task's risk: try it first.
- The file list works the same way: the base's files, with a partial `scene`'s files added to them.

Tests:

- pytest: in `tests/test_room.py`, the count, the changes since a mark, each reason for a whole scene, a mark of the wrong type, and a quiet slot. The scene route's mark while a flush's write is held open in its worker thread, as `tests/test_saver.py` holds one, and between a restore's head write and the room's new epoch. A real process: a mark from before a restart gets the whole scene. Once through nginx.
- Vitest: the base, `known` after each kind of `scene`, and a lost batch sent again after a `scene` that is not whole.
- The browser: a page that reloads a quiet slot gets a socket `scene` with no element. A page whose socket drops while another edits comes back, and both end with the same scene. A batch held back with `routeWebSocket` and lost with its socket reaches the other page after the reconnect. The last test joins T-004's row in `tests/testplan.toml`.
- The size run's slot of 1,024 elements prints how many characters the late browser's socket `scene` held.

Documents: `docs/API.md` (the scene route's `mark`, `hello`'s `mark`, `scene`'s `whole` and `mark`, and the rule), `docs/ARCHITECTURE.md` (collaboration), `docs/DEVELOPMENT.md` (the tests), a new decision D2-037, `docs/ROADMAP.md` (the entry becomes a line saying it was built, and keeps "Not planned"), and `CHANGELOG.md`.

Acceptance: T-001 through T-004, T-007, T-009, and T-011 pass, in the dev container or by `scripts/e2e.py`, and so do the new tests. The size run shows the late browser's socket `scene` for the 1,024-element slot under 1,000 characters, where it was about 431,000. ruff, ty, and the web checks pass.

Out of scope: a browser that keeps a slot's scene between visits (`docs/ROADMAP.md`, not planned).

As built, where the text above left a choice open or the build went past it (D2-037):

- The route's mark names the epoch of the head it returns. When the newest finished write was of another epoch, its count is 0. The text had a mark taken during a restore name the old epoch. Then a page could get a scene that is not whole for an epoch it is not on. Count 0 of the new epoch says no more than the head holds: every element of an epoch has the count of the change that started it. A `hello` with it gets every element of the new epoch once the room has it, and the whole scene before.
- Each slot has a start of its own, picked when segl starts, so a mark handed to another slot names no scene there.
- A file named while a restore or an import was being written gets a count after the one that started the epoch, since the head lacks it. An import's own files go with the elements that name them, and get no count of their own.
- `scene` carries `whole` and `mark` ahead of `elements`. The page takes a `scene` with no `whole` as whole, and a mark that is not text of at most 64 characters as none. The page always sends `mark` in `hello`, `null` when it has none.
- A `scene` that is not whole and names another epoch than the page's is not taken: the page drops its mark and reconnects for the whole scene. The server does not send one.
- The tests of the route, the socket, a real process, and nginx are `tests/test_marks.py`. `MarkOf` in `tests/harness.py` matches a mark whose start the test cannot know. The browser tests stand between the page and the server with `tapSockets` in `web/e2e/pages.ts`. The size run fails when the new browser's socket `scene` is 1,000 characters or more.

## T15 — Network devices and typed links

- Status: done
- Requires: T14
- Requirements: L-001 (draft1 N-001 to N-005). N-006, named interfaces, waits.
- Read: `docs/ROADMAP.md` (P1, and what is carried forward from draft1), `draft1/REQUIREMENTS.md` (N-001 to N-006, the initial symbol types), `draft1/ARCHITECTURE.md` (semantic-to-visual mapping, typed links), `draft1/DATA-MODEL.md` (enumerations, modeling rules), `docs/ARCHITECTURE.md` (the canvas adapter, collaboration), `web/src/canvas/`, `web/src/collab/session.ts`, and the STATUS entry of 2026-11-16 that queued this task

Added on 2026-11-16 at the user's request: the first task of P1. The user answered one batch of questions: devices and links in one task, symbols drawn by hand, the editor's library with a small segl panel, and a link's kind shown by its line. Then: a state shows as a letter tag and never as a color, a connector has a dot at each end, and "other" replaces "unknown". Keep the task to that.

What a person can do after it:

- Open the editor's library panel and find segl's network library: 12 devices and 5 links. Place any of them on a slot.
- Select a device or a link and see segl's panel: its kind, its name, and its state. Set the state. Set a link's kind.
- Draw a link from one device to another. Its ends stay on the devices as they move.
- See each object's state at a glance, in every browser on the slot, and after a reload, a restore, an export, and an import.

The devices, 12 kinds: router, switch, firewall, Wi-Fi AP (`wireless_ap`), server, workstation, printer, VoIP phone (`voip_phone`), mobile, host, cloud (provider transport), and other. Other is a device of none of the other kinds. It replaces draft1's "unknown device", at the user's word.

The links, 5 kinds, each a line style:

| Kind | Line |
|---|---|
| cable | solid, thin |
| circuit | solid, bold |
| neighbor | dashed |
| relationship | dotted |
| connector | thin, a dot at each end (the editor's `circle` end) |

The other four have no end marks.

The states: Existing, Planned, and To remove (`existing`, `planned`, `remove`). draft1 called them observed, planned, and retired_proposed. Nothing here is observed: a person draws what exists. P2's imported records will be the observed ones. A state never changes a real network.

Color is the team's:

- segl never sets or changes a color. The library draws in the editor's default ink. The team colors links by speed or other signs, and devices by owner or vendor. Red means trouble to them.
- A state change touches only the tag. A kind change on a link sets its line style, its width, and its ends, and nothing else.
- What a person changes by hand in the editor's style menu stays. It does not change the kind or the state, which are data.

The tag:

- Existing shows no tag. Planned shows `P`, and To remove shows `R`, in the object's ink.
- On a device, the tag is a small text element in the device's group, at its top right, so it moves with the device.
- On a link, the tag starts the link's label, before any words the team writes there: `P 10G`. Setting the state rewrites only that letter and its space. A label the person edits by hand stays as they wrote it.

The record:

- Each device and each link carries `customData.segl` on one element: the device's body shape, or the link's line. It is `{ "schemaVersion": 1, "objectId", "objectType", "state" }`. `objectId` is a random UUID the page makes when the object is placed. It is not an element id. A device's tag carries `{ "schemaVersion": 1, "objectId", "part": "tag" }`.
- A device's name is its body's own text label, edited on the canvas as any label is. The panel shows it. No second copy is kept.
- A link's ends are the editor's bindings, each to a device's body. The record keeps no copy of them. A link with an end on nothing is legal.
- The record rides in the scene. Live sync, saving, history, restore, export, and import carry it as they carry a color. No table, route, or service is added. The server already keeps `customData` as sent, and checks nothing new: a record is the drawing's own. A server check is a later ask.
- The page reads a record strictly. An element whose record it cannot read is drawn as it is, as freeform. Freeform shapes and arrows stay legal beside network objects.

Copies:

- A placed copy gets a new `objectId`: from the library, a paste, the editor's duplicate, and Alt-drag. A cut and a paste keeps it, since the first copy is gone.
- Only this browser's own changes get a new id. An element that came over the socket keeps the id it came with.

The library and the panel:

- The canvas adapter gives the editor segl's library at load, merged with what the person has. `web/src/network/` describes the symbols as plain shapes and does not import the editor. The adapter turns them into the editor's elements.
- The panel shows for one selected network object. The bar gains nothing. At 390 px wide the panel covers none of the editor's tools: measure it.
- A viewer sees the tags and changes nothing.

The risk, to try first: the editor keeps `customData` through each way an element is placed or copied: a library item, a paste, duplicate, Alt-drag, and an update from another browser. A link's binding holds when the device's group moves. If the pinned editor drops `customData` in one of these, say how the page puts it back before anything else is built.

Tests:

- Vitest: reading a record (a good one, each bad shape, none), the 12 symbols and the 5 line styles, the tag of each state on a device and in a label, the label rewrite (`10G`, `P 10G`, `R 10G`, `10G`), a new id for each kind of copy, and none for an element from the socket.
- The browser: each of the 12 devices and 5 links placed from the library, each with its own `objectId`. A state set in the panel shows its tag in a second browser. A link between two devices keeps both ends when one moves. A copy gets a new id. A color the person set survives a state change. After a reload, a restore, and an export and import, the records and the tags are the same. A viewer sees the tags and changes nothing. A new row, T-022 in `docs/TEST-PLAN.md`, with its row in `tests/testplan.toml`.
- A screenshot of a mixed diagram: physical, logical, and planned, which is the gate draft1 set for this phase. Show it to the user in the recap.

Documents: `docs/REQUIREMENTS.md` (L-001 becomes N-001 to N-005 under P1, with "other" in place of "unknown", and N-006 stays later), `docs/TEST-PLAN.md` (T-022), `docs/ARCHITECTURE.md` (network objects), `docs/DATA-MODEL.md` (the record in `customData`), a new decision D2-038 with the user's answers, `docs/ROADMAP.md` (P1), the status in `README.md`, and `CHANGELOG.md`.

Acceptance: T-022 passes, and T-001 through T-011 still pass by `scripts/e2e.py`. ruff, ty, and the web checks pass. The screenshot shows all 12 devices, all 5 links, and a tag of each state.

Out of scope: a named interface at a link's end (N-006); inventory, device import, and search (P2); a device that changes kind once placed (place another); a server check of the record; scenarios; a symbol manifest file; and keeping a person's own library between visits.

As built (2026-11-16):

- The risk did not happen. The pinned editor keeps `customData` on every copy: from the library, a paste, its duplicate, Alt-drag, a cut and a paste, and the socket. So each copy kept its source's `objectId`. The editor's own `onDuplicate`, which it calls for the library, a paste, its duplicate, and Alt-drag, gives each copy its new id before the copy reaches the canvas, in the same undo step. An element from the socket never passes through it. A link's binding held when a device's group moved, in both browsers.
- A device is a card: a rounded rectangle with the name as its label, at the bottom, and a glyph above it. The editor binds a link's end to a shape with no fill only near its outline, and never to a line, so the glyph is all lines. The label makes the card's inside a place to click.
- The tag is drawn under the card. The editor binds a link's end to the topmost shape near it, and a text outside a container is one.
- Cable is the editor's width 1, and circuit its widest, 4. The editor draws every line at 2 unless told, so "bold" at 2 would be every freeform arrow.
- The library draws with the editor's Architect lines and its Normal font. Neither is a color.
- The items are in the library panel's "Personal library", as the person's own. Published items would show under "Excalidraw library".
- The panel sits at the top right of a wide page, left of the library while it is open, and on the left under the editor's top row in its narrow layout. A test measures it at 1280, 800, and 390 pixels.
- A click on the empty middle of a device that is already selected clears the selection. The editor treats a click inside a selected group that misses its lines as a click on nothing. A second click selects it again. The pinned editor is not changed (rule 6).
- T-022 uses slot 6, with the deleting tests. The viewer's test is in `web/e2e/access.spec.ts`, the only spec that runs against the server with a code.

## T16 — History that lasts, and clearing a slot

- Status: done
- Requires: T15
- Requirements: S-005, and a new row for clearing a slot
- Read: `docs/DATA-MODEL.md` (flush and revision rules), `docs/DECISIONS.md` D2-011, D2-030, and D2-031, `docs/API.md` (the revision routes), `src/segl/repository.py`, `src/segl/saver.py`, `src/segl/migrations/`, `web/src/history.ts`, `tests/test_history.py`, `web/e2e/history.spec.ts`, and the STATUS entry of 2026-11-26

Added on 2026-11-26 at the user's request: the first of three tasks the user put before the rest of P1. segl keeps the newest 50 revisions of a slot and writes at most one a second while people draw. So under a minute of steady drawing replaces every older revision. If someone clears a board by mistake and the call draws on for a minute, the board cannot come back. ExcaliDash always keeps a snapshot before a save that drops more than a tenth of a board, and limits its history by age as well as count. This task does the same, in segl's way.

What a person can do after it:

- Open History after a long call and find the board as it was in each minute of the last hour, each hour of the last day, and each day of the last week.
- Get a board back after someone deleted most of it, even after an hour more of drawing.
- Get back what a restore or an import replaced, for a week.
- Clear a slot for good from the command line, when what it holds was saved elsewhere or is too heavy to keep.

Which revisions stay (one week, at the user's word of 2026-11-26):

- The newest `history_limit` (50), as today.
- Older than those: the newest revision of each minute for the last hour, of each hour for the last day, and of each day for the last 7 days. Clock minutes, hours, and days, in UTC. The rest go.
- A kept revision stays a week, whatever the count. At most 20 per slot: the 21st drops the oldest kept one.

What is kept:

- The scene before a big delete. When a flush would leave fewer than 90% of the live elements (those not deleted) that the head holds, the saver first writes the head as a revision, whatever the age of the newest one, unless the newest holds it already. It marks that revision kept. The flush that deletes then writes its own revision, whatever the age.
- The scene a restore or an import replaced. D2-030 and D2-031 already write it. Mark it kept.

Storage:

- Revision scenes are stored compressed with zstd, from Python's own library (`compression.zstd`, in the pinned 3.15.2). No new dependency. The head stays plain JSON.
- A migration, `0003`, compresses the revisions that exist and adds the mark. A database from 0.5.0 opens and reads back the same scenes.
- Measure one slot of 1,024 elements with a full history, before and after: the database's size and the time a flush takes.

The History control:

- A kept revision says why, in a short phrase: `Before delete`, `Before restore`, or `Before import`.
- The revision list's answer names the reason (`docs/API.md`).

Clearing a slot, added at the user's word of 2026-11-26. A one-day workshop saved its drawing outside segl, or a board holds too many images, and the slot can now be wiped:

- `segl slot clear N` empties slot N for good: its scene, its title (back to `Workspace N`), its whole history, and its rows in `slot_file`. It deletes the image bytes under `assets_dir` that no other slot names. It takes one or more slot numbers.
- It says what it will remove (elements, revisions, files, and bytes) and asks for the slot number to be typed back, unless `--yes` is given.
- A running segl holds each open slot's scene in memory and would write it back. So the command stops segl's unit first and starts it after, as `segl update` does, and says each step. On a host without the unit, it refuses while segl answers on its port.
- The clear raises the slot's epoch, as a restore does. A browser that was open on the slot then takes the empty board when it reconnects, and does not send its old one back (`takeScene` in `web/src/collab/session.ts`).
- A clear cannot be undone. segl's log records it.

Tests:

- pytest, with a clock the test sets: a slot written once a second for two hours keeps the newest 50 and exactly the revisions the tiers name. A drop below 90% keeps the scene before it, which outlasts two more hours of drawing and is gone after a week. A drop that leaves 90% or more keeps nothing extra. A restore and an import keep the scene they replaced. The 21st kept revision drops the oldest kept one. A database from 0.5.0 migrates and reads back the same. A clear removes the scene, the title, the revisions, and the file rows, keeps the bytes another slot names, and raises the epoch. It refuses a slot outside 1–9, waits for the typed number unless `--yes` is given, and refuses while segl answers on its port without the unit.
- Vitest: the History list's phrases.
- Browser: delete most of a board, draw until 50 newer revisions exist, find `Before delete` in History, restore it, and see the board return in both browsers. A browser stays open on a slot while segl stops, the slot is cleared, and segl starts: the browser shows the empty board, and the board stays empty after a reload.
- T-011's last rule changes ("The 51st revision drops the oldest"). A new row, T-023, in `docs/TEST-PLAN.md`, for the history and the clear, with its row in `tests/testplan.toml`.

Documents: `docs/REQUIREMENTS.md` (S-005, and a row for the clear), `docs/TEST-PLAN.md` (T-011, T-023), `docs/DATA-MODEL.md` (flush and revision rules, the migration, what a clear removes), `docs/API.md` (the reason), `docs/DEPLOY.md` and `deploy/OPERATOR.md` (the command), a dated amendment on D2-011 for the tiers, the kept revisions, and the clear, the status in `README.md`, and `CHANGELOG.md`.

Acceptance: T-011 and T-023 pass, and T-001 through T-022 still pass by `scripts/e2e.py`. ruff, ty, and the web checks pass.

Out of scope: a setting for the tiers, a revision a person keeps by hand, a compressed head, a clear from the browser or on a timer, and Diagram mode's history (T17 and after).

As built (2026-11-26), where the text above left a choice:

- The saver works out a big delete from the room's elements, and keeps a count of the head's live elements. Counting from the JSON in the flush cost about 6 ms a flush on a slot of 1,024 elements, where the whole flush took 1 to 2 ms. The repository takes the answer as `before_delete`.
- Clock minutes, hours, and days count back from the current one: the last 60 minutes are the current minute and the 59 before it. Newest means the highest revision number.
- A kept revision is protected while it is less than a week old and one of the slot's 20 newest marked ones. Its mark stays when that ends, and History still shows it while another rule keeps the row.
- The mark for a restore or an import is set in `replace_head`'s transaction, the second write, not in the flush before it. So a restore that fails after the flush marks nothing. `flush_head` takes `before_delete` alone.
- The rules run at each write that adds or marks a revision. A slot nobody draws on keeps what it had.
- The row kept before a delete has the time of the flush, as the delete's row does, and the head's own label.
- The revision list and the single revision carry `kept`: `delete`, `restore`, `import`, or null. A page reads a reason it does not know as none.
- `0003` renames the old table and makes the new one under its own name, so its `CREATE` text stays as `docs/DATA-MODEL.md` lists it. It calls `segl_zstd()`, a function segl gives the connection that runs the migrations. It does not `VACUUM`: SQLite uses the freed pages again.
- `segl slot clear` uses the unit only with the package's settings, `/opt/segl/etc/segl.toml`, while `segl.service` runs. Otherwise it refuses while anything takes a connection on segl's port. So a test or a checkout never stops an installed segl. It needs root to stop the unit.
- It reads the counts before it stops segl, asks for every number before it clears any, clears in number order, and stops and starts segl once. After the stop it runs the migrations, as a start does.
- After a clear the slot's revision numbers start again from 1.
- "segl's log" is the system log under the identifier `segl`, the unit's own (`journalctl -t segl`). `journalctl -u segl` does not show a line from the command, which runs outside the unit.
- The browser test of `Before delete` runs a server of its own that keeps 5 revisions, not 50, in the `restart` project only. Drawing 50 revisions a second apart would add about a minute to the test.
- The install test clears a slot on the package, as root, and checks that every file beside the database is still segl's and that segl writes it again.

## T17 — Diagram mode on slot 9

- Status: done
- Requires: T16
- Requirements: S-001 and S-003 (slot 9), and new rows for Diagram mode (D2-039)
- Read: `docs/DECISIONS.md` D2-007, D2-017, D2-026, D2-037, and D2-039, `docs/ARCHITECTURE.md` (collaboration, the canvas adapter), `docs/API.md` (the WebSocket), `src/segl/room.py`, `src/segl/saver.py`, `web/src/SlotPage.tsx`, `web/src/collab/session.ts`, `web/e2e/pages.ts`, `deploy/debian/`, `scripts/release.py`, drawio's embed page (<https://www.drawio.com/doc/faq/embed-mode>), and the STATUS entry of 2026-11-26

Added on 2026-11-26 at the user's request. Slot 9 becomes Diagram mode: drawio's editor, for formal diagrams and planning, beside the Excalidraw whiteboards on slots 1–8. The user wants to see drawio early, and how people work together in it. Collaboration comes first. So this task puts drawio on slot 9 with two ways to work together, live co-editing and the pen. It measures how well co-editing works and records the result in a decision. The next Diagram mode task is written from that decision.

What a person can do after it:

- Open slot 9 and draw in drawio's editor under the segl bar, with its shape libraries, the network and Cisco sets among them. The bar says `Diagram mode`.
- Work on one diagram with other people at the same time, and see their changes as they make them.
- Take the pen to edit alone while the others watch, and give it back.
- Close the browser, or restart segl, and find the diagram as they left it.

drawio itself:

- Pin drawio in `versions.toml`: 32.7.7, the newest release on 2026-11-25. `scripts/release.py check` learns where its releases are (`jgraph/drawio` on GitHub).
- The build fetches the release's `draw.war`, checks its SHA-256 (`e84ac13ee1e6c2bded36b6e920a2e8abfa37df277a6d9697ae8dc28f7bbeb9f1` for 32.7.7), and unpacks its web files, unmodified, beside segl's web build. Not `WEB-INF`: segl runs none of drawio's Java. Git does not hold them. The war is 50.4 MiB. Its web files, without `WEB-INF` and `META-INF`, are 3,115 files and 121 MiB.
- drawio ships two settings files for a site to replace, `js/PreConfig.js` and `js/PostConfig.js`. segl may lay its own over them. No other file changes.
- segl serves drawio from its own origin, under the same mount (D2-007): at a host root and at `/board/`. The page loads nothing from another host (D2-026, S-014). drawio's `stealth=1` and `lockdown=1` turn off its cloud storage links and its logging: find which segl needs by a run. Do not pass `offline=1`, which turns on drawio's service worker. `pwa=0` keeps it off.
- drawio keeps its settings in `localStorage`, on segl's origin. Check that it sets no cookie (rule 8), and that none of its keys is one of segl's.
- Licenses: drawio's code is Apache-2.0, and the release carries no copy of that text, so segl ships one. The icon sets and stencils carry drawio's terms (no use in Atlassian products), which segl meets. `js/libavoid-js/` is under the LGPL 2.1. Say what it does in drawio and whether drawio works without it, and put the choice to the user before the package ships it, as the font was (D2-026).
- The name: segl does not use drawio's name or logo for the mode. The documents credit draw.io, under its trademark rules.

The page:

- Slot 9 opens drawio's editor in a frame below the bar, in embed mode (`embed=1&proto=json`), and loads the diagram with `autosave` and `diffSync` on. Every message to and from the frame goes through one adapter, `web/src/diagram/` (rule 5). The adapter takes a message only from its own frame.
- A viewer's frame loads read-only. drawio says read-only "is a view mode, not access control", so the server refuses a viewer's changes with `view_only`.
- The bar works as on other slots: the title, who is here, the connection state, and saving and saved. History and Import stay hidden on slot 9 until the next Diagram mode task. The editor's own menu exports `.drawio`, PNG, and SVG. PDF goes through the browser's print dialog.

Live co-editing, the design to build first:

- An edit comes out of drawio as a patch and a checksum (its diff sync). The page sends the patch on the same `/collab` socket, with the number of the last patch it applied.
- The server numbers each patch it takes, in the order it takes them, and sends it to every other browser on slot 9. Each browser applies the patches in that order, with the embed's `patch` action.
- The server cannot read a patch: drawio's own code applies them. So a browser also sends the whole diagram, its XML, with the number of the last patch it holds. The server keeps a copy only when its sender held every patch before it. That copy is slot 9's head, and the saver writes it and its revisions by T16's rules.
- After a patch, a checksum that does not match means a browser has drifted. Its page loads the head and the patches after it.
- A page that opens slot 9 gets the head and the patches since, as D2-037 does for other slots.
- The edit gate, the Origin check, `internal_networks`, and `max_scene_bytes` hold as for other slots. Name the new messages in `docs/API.md`.

The pen, built as well, at the user's word of 2026-11-26:

- Slot 9 starts in co-editing. A person who may edit can take the pen. While someone holds it, only the holder changes the diagram, and everyone else watches it change live. Their frames go read-only, and come back when the pen is free.
- The bar shows who holds the pen. Anyone who may edit can take it at any time, even from the holder: the users are honest, and a pen nobody else can take would strand a slot. The pen is free again when its holder gives it back or leaves slot 9. No timer frees it.
- While the pen is held, the server takes diagram changes only from the holder. It refuses the others with a new error, `pen_held`. A viewer never gets the pen.
- The pen sets who edits, not where anyone looks. A watcher's view stays where they put it, so a change the holder makes out of sight, or on another page of the diagram, shows only when the watcher looks there. T18 adds following the holder's view.
- If the measures show co-editing loses or garbles edits that the design cannot fix, the pen is the only way to edit slot 9 until a fix. Say why in the decision.

The old slot 9: a migration drops slot 9's Excalidraw scene, its revisions, and its rows in `slot_file`. Bytes another slot still names stay. The user accepted the break, since no site holds data to keep. `segl slot clear 9` (T16) clears the diagram, its history, and its pen. The tests that name slot 9 as a whiteboard move: the browser tests' `empty` slot (`web/e2e/pages.ts`), and the slot lists in `tests/test_slots.py` and `tests/test_repository.py`.

The risk, to try first: drawio's embed mode runs from segl's own origin with nothing else reachable, at both mounts, and a patch made in one frame applies in another. drawio's page says embed mode "is only supported on https://embed.diagrams.net". If it does not run from segl, stop, set Blocked, and record what failed.

Measures, for the STATUS entry and the decision:

- Two browsers, then four, draw on slot 9 at once for five minutes, each a known number of shapes. Count what each browser and the head end with, the checksums that did not match, and how often the server got a copy it could keep.
- The time from an edit in one browser to its showing in another, on one host.
- The size of a patch and of a whole copy, for a diagram of 500 shapes.
- The time from a take of the pen, and from its return, to every browser's frame changing mode.
- The `.deb`'s size before and after.

Tests:

- pytest: the diagram messages at the socket: numbering and order, the copy rule, the gate, the size limit, a restart that keeps the head, and the migration. The pen: a take, a take from the holder, `pen_held` for anyone else, a viewer refused, and the pen free again when its holder gives it back or leaves.
- Vitest: the adapter takes messages only from its frame, applies patches in order, and loads the head after a checksum that does not match. It sets its frame read-only while someone else holds the pen, and back after.
- Browser: two browsers on slot 9 see each other's shapes. Each draws a shape at the same time, and both remain in both. A reload and a restart keep the diagram. A viewer sees changes and makes none. One browser takes the pen: the other sees its changes and cannot edit, then takes the pen in turn. The holder leaves, and the pen is free. No request leaves the origin, at both mounts.
- A new row, T-024, in `docs/TEST-PLAN.md`, with its row in `tests/testplan.toml`.
- A screenshot of two browsers on one diagram. Show it to the user in the recap.

Documents: `docs/REQUIREMENTS.md` (S-001, S-003, and rows for Diagram mode), `docs/TEST-PLAN.md` (T-024), `docs/ARCHITECTURE.md` (Diagram mode, its adapter, and its collaboration), `docs/API.md` (the diagram messages, the pen, `pen_held`, and slot 9's head), `docs/DATA-MODEL.md` (slot 9's head and revisions), `docs/DEPLOY.md` and `deploy/OPERATOR.md` (what the package carries), a new decision D2-040 with how co-editing and the pen work and the measures, D2-039 amended as built, `docs/ROADMAP.md`, the status in `README.md`, and `CHANGELOG.md`.

Acceptance: T-024 passes, and T-001 through T-023 still pass by `scripts/e2e.py`. T-017 and T-021 pass with drawio in the package. ruff, ty, and the web checks pass.

Out of scope, for the next Diagram mode task or later: History and restore on slot 9, Import of `.drawio` files, segl's 12 device kinds and 5 link kinds in drawio's library, cursors, follow mode in Diagram mode (T18), a pen that frees itself after a time, a whiteboard sketch carried into a diagram, and a second diagram slot.

As built (2026-11-27):

- The risk did not happen. drawio 32.7.7's embed mode ran from a scratch server's own origin, at its root and under `/board/`, with every other origin refused, and a patch made in one frame applied in another. One thing had to change: a frame given an empty `xml` makes a page with an id of its own, so another frame's patch named a page it lacked. Every browser loads the same text, and slot 9's empty diagram has one page with the fixed id `segl-page-1`.
- Loading and drawing asked no other host with or without `stealth=1` and `lockdown=1`. Either one makes drawio's `isOffline()` true, which drops Help's search, support, desktop, and video links, File's Embed formats, and Import from URL. `lockdown` also stops drawio's real-time cache. drawio's logging runs only on drawio's own hosts. The page passes both, with `pwa=0`, `noSaveBtn=1`, `noExitBtn=1`, and `saveAndExit=0`.
- drawio keeps one `localStorage` key, `.drawio-config`, and sets no cookie. No service worker is registered.
- Slot 9's head is `{"diagram": xml}`. The room is `DiagramRoom` (`src/segl/diagram.py`), a `Room` that numbers patches and keeps a copy, so the saver writes it unchanged.
- A patch message carries the page's whole diagram, as drawio's `autosave` hands it over, so the server holds the newest copy it may keep without asking. A patch is `exact` when every patch after its `base` is the sender's own. When it is not, the sender sends a `copy` once its own patch comes back, and `saved` waits for a kept copy that holds the patch. A `copy` that holds every patch is kept even with no new patch: drawio sends one for a change outside the pages.
- A page knows its own patches by an id it makes (`pid`), not by its connection, so a patch that comes back after a reconnect is still its own. The ones the server never took are sent again at the next join, applied again after a whole diagram.
- The checksum is compared only after an `exact` patch, while the page holds every patch before it and waits on none of its own. Otherwise it is the sender's alone.
- Drift: two people who draw at once leave the new shapes in another order in each browser, since drawio's insert names the shape it goes after. A page then loads the whole diagram. Found while measuring: a load resets the view and ends a label being typed, losing the text. So segl's `PostConfig.js` tells the page when a label editor opens and closes and where the diagram is scrolled, and the page asks for the whole diagram only once no label is being edited, then loads it with the same scale and the same point at the top left. A load still shows the first page of a diagram with several pages: drawio's embed messages cannot select another.
- segl's `PostConfig.js` also tells the page when drawio's read-only view turns on or off, by segl or by drawio's View menu, so the page turns it back where it should be. `PreConfig.js` shows drawio's Network and Cisco sets at first. Both keep what drawio's own files set.
- The pen: `pen {take}`. Taking it twice tells nobody again. A give-back from anyone but the holder is ignored. A viewer's take is `view_only`. A refused change makes the page load the whole diagram, so it never keeps what the server did not take.
- Restore and import answer `409` with `diagram_mode` on slot 9. The single-revision and history routes still answer for slot 9.
- Migration `0004` deletes rows and writes the head. It removes no file under `assets_dir`. It calls `segl_empty_diagram()`, a second function of segl's own beside `segl_zstd`.
- drawio's files are served with `Cache-Control: no-cache`: their names carry no hash.
- The build keeps the war and its unpacked files in `~/.cache/segl/drawio` (`SEGL_DRAWIO_CACHE`), and the package build in the docker volume `segl-drawio-cache`.
- Licenses: the war's `templates/LICENSE` is the Creative Commons Attribution 4.0 license, not the Atlassian terms of `img/`, `shapes/`, and `stencils/`. libavoid's compiled code is in `js/extensions.min.js`, which drawio loads at every start, and in `js/integrate.min.js` and `js/libavoid-js/libavoid.min.js`, which nothing loads. The owner chose on 2026-11-27 to ship it with a notice. segl ships drawio's Apache License from its repository at the tag.
- The browser tests' empty slot is slot 1, which no test draws on. Slot 9 is `SLOTS.diagram`. The restart test is in `durability.spec.ts` and the viewer's in `access.spec.ts`, beside their kind.

## T18 — Follow mode, and cursors in Diagram mode

- Status: done
- Requires: T17
- Requirements: S-002 (cursors on slot 9), S-010, and a new row for follow mode
- Read: `docs/DECISIONS.md` D2-013, D2-025, D2-027, and D2-039, `docs/API.md` (the WebSocket, `presence`), `src/segl/room.py`, `web/src/bar/`, `web/src/canvas/`, `web/src/diagram/`, `web/src/collab/session.ts`, `web/drawio/js/PostConfig.js`, the pinned editor's follow types (`onUserFollow`, `userToFollow`, `followedBy`), its `maybeUnfollowRemoteUser`, and its `getClientColor`, drawio's embed page (the `viewbox` action and `zoomEvents`), drawio's `js/diagramly/P2PCollab.js` (`sendCursor` and `updateCursor`), and the STATUS entries of 2026-11-26 and 2026-11-27

Added on 2026-11-26 at the user's request. On a troubleshooting call one person leads, and the rest need to see what the leader sees. After this task a person clicks a name in the bar's list of who is here and follows that person's view, on every slot. In Diagram mode, whoever takes the pen is followed by default. It is not a presentation mode: anyone can look away at any time. Added to on 2026-11-27 at the user's request: on slot 9 each person sees the others' cursors, as on the whiteboards.

What a person can do after it:

- Click a name in who is here and follow that person: the canvas scrolls and zooms as theirs does. On slot 9 it also turns to the page of the diagram they are on.
- See that they follow, and stop with one click.
- Stop by looking away. Following ends when they scroll, zoom, or click on the canvas themselves, as the pinned editor does, so starting to draw ends it. It also ends when they click the name again, or the person leaves. Following never locks anyone.
- On slot 9, follow whoever takes the pen without a click. Step away by scrolling, zooming, or clicking, and click the holder's name to follow again.
- On slot 9, see where each other person's pointer is on the diagram, with their name beside it, as on the whiteboards.

The design:

- The pinned editor 0.18.1 has the hooks: `onUserFollow` reports a follow and an unfollow, and its state holds `userToFollow` and `followedBy`. It ends a follow on the follower's own scroll, zoom, or click on the canvas (`maybeUnfollowRemoteUser`). Use its own follow display. All of it goes through the canvas adapter (rule 5).
- Two new messages on the socket. `follow` names the connection to follow, or `null` to stop. The server tells a connection how many follow it. Only while someone follows it does a page send `view`: its visible area, in canvas coordinates, at most a few times a second, and on slot 9 its page of the diagram. The server sends `view` only to that connection's followers.
- The follower's canvas fits the leader's visible area, whatever the two screens' sizes.
- A viewer may follow and be followed. Neither changes the scene, so the edit gate does not apply.

In Diagram mode, at the user's word of 2026-11-26:

- drawio's embed sets a view with its `viewbox` action. With `zoomEvents` on, it reports a change of zoom, with the scale and the page, but not a scroll. segl's own `js/PostConfig.js` (rule 6) reports the frame's scroll to the adapter, `web/src/diagram/`. The same report tells the page when a watcher scrolls or zooms on their own, and a click in the frame tells it they clicked. Each ends their follow, as on the whiteboards.
- A page that learns of a new pen holder sends `follow` for the holder, unless it is the holder. So each take of the pen starts every other browser on slot 9 following the new holder, once. One who steps away stays away until they click the holder's name, or the pen moves again. When the pen is given back, the follow ends.
- The risk, to try first: what drawio's own code lets `js/PostConfig.js` see of the frame's scroll. If it sees none, stop and say what it does see before the rest is built.

Cursors in Diagram mode, at the user's word of 2026-11-27:

- Why: on slots 1–8 the pinned editor draws the others' cursors from `presence`. Slot 9 shows none (`web/src/diagram/session.ts`), so S-002 holds there for edits only. drawio's embed messages have no cursor action. drawio draws the others' cursors only in its own real-time sessions (`js/diagramly/P2PCollab.js`), which go through drawio's relay server. segl runs no such server, and the page asks no other host (D-002).
- segl's `js/PostConfig.js` reports this browser's pointer to the adapter: the point on the diagram and the id of the page it is on, worked out from the view's scale and translate and the frame's scroll, as `P2PCollab.js`'s `sendCursor` does. The page sends it as `presence`, at most once every 50 ms, as on the whiteboards.
- On slot 9 a cursor also names its page: `{ "x", "y", "page" }`. The server checks the page id as it checks `x` and `y`, and passes it on. Slots 1–8 keep `{ "x", "y" }`.
- The adapter hands the others' cursors to the frame. `js/PostConfig.js` takes them only from its parent page, on segl's origin, and draws each in drawio's graph container, placed as `P2PCollab.js`'s `updateCursor` places one. So a cursor stays on its point of the diagram as this browser scrolls and zooms, and shows only on the page it names. Each has its person's display name beside it, and the color the pinned editor gives that connection on the whiteboards, worked out from the connection id (its `getClientColor`, which the package does not export). The protocol still carries no color (D2-027), and segl still sets no color on the diagram.
- A cursor stays where its person last moved it, as on the whiteboards, and goes when they leave slot 9. A viewer's cursor shows too, as on the whiteboards. The pen changes no cursor: it sets who edits, not who is seen.
- The risk, to try with the scroll's: that `js/PostConfig.js` can see drawio's pointer and draw in its graph container. If it cannot, stop and say what it does see before the rest is built.

Tests:

- pytest: `follow` and its count, `view` only to followers, a follow that ends when the leader leaves, and a `follow` of a connection not on the slot refused. On slot 9, a cursor with its page reaches the others, and one whose page is not a short string is refused with `bad_message`.
- Vitest: the adapter's follow and the fit, on both canvases. A follow ends on the follower's own scroll, zoom, or click. A new pen holder starts a follow, except in the holder's own page. On slot 9, the adapter sends the frame's pointer as `presence` at most once every 50 ms, hands the others' cursors to the frame with their names and colors, shows a cursor only on its own page, and drops it when its person leaves.
- Browser: one browser follows another on a whiteboard. The leader scrolls and zooms, and the follower's view matches within a small margin. The follower scrolls, and the follow ends. Stop works. The leader leaves, and the follow ends. On slot 9, a take of the pen starts the other browser following. The holder scrolls, zooms, and turns the page, and the watcher's view matches. The watcher scrolls away and stays away, and a click on the holder's name follows again. On slot 9, each browser shows the other's cursor with its name, on the point of the diagram under the other's pointer within a small margin, while the two are scrolled and zoomed differently. A cursor on another page does not show. The other leaves, and its cursor goes.
- Two new rows in `docs/TEST-PLAN.md`, each with its row in `tests/testplan.toml`: T-025 for follow mode, and T-026 for S-002's cursors on slot 9.

Documents: `docs/REQUIREMENTS.md` (a new row, and S-002 as built), `docs/TEST-PLAN.md` (T-025 and T-026), `docs/API.md` (`follow`, `view`, the count, and a cursor's page on slot 9), `docs/ARCHITECTURE.md` (collaboration, and Diagram mode's `js/PostConfig.js` and cursors), a new decision D2-041 for the messages, D2-039 amended as built, the status in `README.md`, and `CHANGELOG.md`.

Acceptance: T-025 and T-026 pass, and T-001 through T-024 still pass by `scripts/e2e.py`. ruff, ty, and the web checks pass.

Out of scope: a presentation mode that locks screens to the leader, a leader who brings everyone to their view at once, and the others' selections in Diagram mode, which drawio's own sessions outline.

As built (2026-11-27):

- The risk did not happen. A run on a scratch server showed segl's `js/PostConfig.js` taking drawio's scroll, scale, and page, and the pointer as a point on the diagram, applying another view, and drawing a cursor in drawio's scrolling container, at the right place before and after a zoom. drawio answered none of segl's own messages with `unknownMessage`.
- The messages: `follow {connectionId}`, `view {view}` with `{ x, y, width, height }`, `followers {count}` to the one followed, and `view {connectionId, view}` to its followers alone. The server keeps no view: a page sends its view at once when one more follows it, then as it changes, at most five times a second (200 ms).
- A new error, `cannot_follow`, for a follow of a connection not on the slot, of the sender, or of one that follows the sender, however many steps away. Found while writing the rules: two pages that follow each other fit each other's view in turn, and with screens of two sizes zoom out without end. The follow there was stays, and the page sends `follow` with null to end it too.
- The follower fits the leader's area with segl's own function (`web/src/canvas/fit.ts`), at the editor's zoom limits of 0.1 and 30. The editor's `zoomToFitBounds` floors the zoom to steps of 0.1. The view is set straight into the editor's state, which ends no follow.
- The pinned editor's `onUserFollow` prop is typed but not wired in 0.18.1: the page listens with its API's `onUserFollow`. The editor reports segl's own changes too, so the session ignores the end of a follow it has already left. The editor's avatar row stays hidden. A name in the bar's list is a button, and the list says `following` beside the one followed.
- In Diagram mode `js/PostConfig.js` reports the frame's whole view, with its page, on a scroll, a zoom, a resize, or a page turn, so the page uses no `zoomEvents`. It shows a view itself, not with drawio's `viewbox` action, which rounds the scale to steps of 0.05 and keeps a 10-pixel border. It turns to the view's page with `selectPage(page, true)`: no undo step, and drawio's autosave skips a page change, so following sends no patch. A view whose page comes in a patch after it, as when the holder adds a page, is turned to on drawio's `embedLoaded` after that patch, and forgotten when the follow ends.
- The person's own look in the frame is a wheel, a press anywhere in the frame, or a key with Ctrl, Cmd, or Alt. A plain key or a pointer move ends no follow, as on the whiteboards.
- segl's messages to the frame are objects with a `segl` field. `js/PostConfig.js` adds its listener before drawio's and stops them there.
- The pen, where the task was silent: a page that comes while the pen is held follows the holder. A page that takes the pen ends its own follow first, or the others' follows of it would be refused as a loop. A follow the person chose stays when the pen comes back.
- A follow ends with either socket, and is not taken up again after a reconnect.
- Slot 9's bar says `Following` and the name, with a stop. The count of followers is used only to decide when to send the view: the bar does not show it.
- The cursors: `js/PostConfig.js` draws each as the whiteboards' editor does, its arrow outlined in white and the name in a box. The color rule is a copy of the editor's `getClientColor` in `web/src/diagram/cursors.ts`, which the package does not export, and a Vitest test reads the rule from the editor's build and holds the copy to it for 503 ids. A page id may be 1 to 128 characters, or null. `web/scripts/drawio.test.ts` held segl's drawio files to no color at all: it now holds them to no color on drawio's shapes.
- One throttle (`web/src/collab/throttle.ts`) sends the cursors on both canvases and the views, in place of the whiteboard session's own cursor timer.
- For the browser tests, `window.SEGL_CANVAS.view()` gives the canvas's `width` and `height`, and `window.SEGL_DIAGRAM.view()` the area the frame shows. The whiteboard tests use slot 2, `SLOTS.follow`, and draw nothing.

## T19 — Diagram mode's polish, and the update notice

- Status: next
- Requires: T18
- Requirements: D-001 (History on slot 9), D-003 (a load keeps the page and waits for a press), D-005 and S-005 (slot 9's history and a big delete there), S-002 and S-021 (the gaps T18 left), a new row for the others' selections on slot 9, and a new row for the update notice
- Read: `docs/DECISIONS.md` D2-011, D2-030, D2-039, D2-040, and D2-041, `docs/API.md` (`welcome`, `presence`, the restore route, and Diagram mode), `docs/DATA-MODEL.md` (the flush rules and restore), `src/segl/diagram.py`, `src/segl/saver.py`, `src/segl/collab.py` (`restore`), `src/segl/app.py` (the restore route), `web/src/diagram/`, `web/src/bar/` (`SeglBar.tsx` and `HistoryControl.tsx`), `web/drawio/js/PostConfig.js`, drawio's `js/diagramly/EditorUi.js` (the embed `load` action, `createLoadMessage`, and `getFileData`), `js/diagramly/P2PCollab.js` (`selectionChangeListener` and its `selectionChange` case), `Graph.prototype.highlightCell` in `js/diagramly/Editor.js`, and the STATUS entries of T17 and T18

Added on 2026-11-27 at the user's request, while the production network team tests slot 9. It takes up what T17 and T18 left (D2-040, D2-041) and the roadmap's History on slot 9. After it, a load that puts a drifted browser right keeps the person's page and waits for their drag. Slot 9 has History and restore. Each person sees what the others have selected. A page left open across an update says to reload.

What a person can do after it:

- Keep working on page 3 of a diagram when their browser drifts and loads the whole diagram again. They stay on page 3, at the same scale and scroll, with the same shapes selected.
- Finish a drag. A load waits until the mouse button is up.
- Open History on slot 9, see the diagram's revisions with their marks, and restore one for everyone. The diagram before a big delete is kept, as on the whiteboards.
- See which shapes and links each other person has selected, outlined in that person's cursor color, on the page they are on.
- See that segl was updated while the page was open, and reload with one press.
- See why a follow did not start, when it would close a loop.

The page across a load (D2-040):

- Today: drawio's `load` action takes a scale and a scroll, and no page (`EditorUi.js`, `data.action == 'load'`), so a load opens the first page. The answer to `export`, which the page reads for the view, names the page by its index (`createLoadMessage`'s `currentPage`), not by its id.
- segl's `js/PostConfig.js` adds the current page's id to that answer, as it adds the scroll. Before a repair's load, the page tells the frame which page and view to come back to. After the load, on drawio's `embedLoaded`, `js/PostConfig.js` turns to that page quietly with `selectPage(page, true)`, as follow mode does: no undo step, and no patch. It then sets the scale and the scroll on that page. When another browser has deleted the page, the person stays on the first page.
- A follow shows the leader's view after a load, as now.
- The risk, to try first: a turn and a view set after `embedLoaded` leave no undo step and send no patch, and the scale and scroll land on the turned page, not the first. If drawio cannot do it, stop and say what it does.

A press across a load (D2-040; T17 did not measure it):

- Measure first. In a browser, start a drag of a shape, have a load come while the button is down, then end the drag. Record what happens to the shape and the drag. Run T17's labelled measure again (four browsers, labels on about half the shapes), and count the inserts whose label editor did not open: 25 of 208 in T17. Find the cause. T17's reading, that a load cleared the selection, was not checked.
- `js/PostConfig.js` tells the page when a press starts and ends in the frame. drawio's graph sets `isMouseDown` on a press and clears it on the release (`mxGraph.prototype.isEventIgnored`, which `fireMouseEvent` calls). The page asks for the whole diagram only when no label is being typed and no press is held, as `idle()` now waits for a label. While it waits, the others' patches wait too, as they do for a label today.
- After the load, `js/PostConfig.js` selects again, by id, the cells that were selected and are still there. A selection is not part of the diagram, so this sends no patch.
- D2-040 records the measures and the cause.

History and restore on slot 9 (D-001, D-005, S-005):

- Today: slot 9 keeps revisions by S-005's rules, and the history routes answer for it. The bar hides History on slot 9, and the restore route answers `409` with `diagram_mode`. `DiagramRoom` has no elements, so the saver keeps no revision before a big delete there.
- The bar shows History on slot 9, as on the whiteboards. Import stays hidden (T20 or later).
- A restore on slot 9 works as one on a whiteboard (D2-030). It keeps the diagram that goes, marked `restore`, starts a new epoch with the revision's diagram, and writes a revision of it. Every browser on slot 9 loads the restored diagram, and keeps its view and its page when that page is still there. A patch of the old epoch is refused, as a whiteboard change is after a restore.
- The pen: while someone holds it, only the holder restores. The others' History shows no Restore, and the server refuses a restore from anyone else with `pen_held`. The restore request names its connection, so the server can tell who sent it.
- A big delete on slot 9: the server counts the shapes and links in the copy it keeps, drawio's cells with `vertex="1"` or `edge="1"` on every page. The saver's 90% rule then keeps the diagram before a big delete, marked `delete`, as on the whiteboards. drawio's `autosave` writes pages plain: `getFileData` compresses only when `Editor.defaultCompressed` is set, and segl does not set it. Check that with a diagram imported through drawio's own menu. The XML comes from a browser: count it without expanding entities, off the event loop. A diagram the server cannot count gets no `delete` row, and is still saved.

The others' selections on slot 9 (a new row):

- drawio's own sessions show them (`P2PCollab.js`). When the selection changes, they wait 300 ms, then send the page's id and the selected cells' ids, or no ids when more than 50 cells are selected. The receiver outlines each cell with `graph.highlightCell(cell, color, 60000, 70, 3)`, which fades out after a minute. That code runs only through drawio's relay server, which segl does not run (D-002).
- segl's `js/PostConfig.js` reports this browser's selection when it changes: the page's id, and the selected cells' ids, or none when more than 50 are selected, as drawio's sessions do. The page sends it on the socket at most a few times a second. Whether it rides in `presence` or in a message of its own is this task's call, written in `docs/API.md`. The server checks it as it checks a cursor (a page id, and at most 50 cell ids, each text of 1 to 128 characters) and passes it to the others. The server keeps each connection's newest selection, so a browser that comes later sees the selections already made.
- The frame outlines each cell the others have selected, in that person's cursor color, and only on its page. It uses drawio's `mxCellHighlight`, as `highlightCell` does, but the outline lasts as long as the cell stays selected. It follows the cell when the cell moves. It goes when the cell is deleted, when its person selects something else, or when that person leaves slot 9. When a patch or a load replaces the cells, the frame draws the outlines again.
- A selection is presence, not drawing, as a cursor is. It goes in no patch and changes no diagram, and segl still sets no color on the diagram (D2-038, D2-039).
- The As built list says whether drawio's read-only view lets a viewer, or a watcher while another holds the pen, select, and what the others then see.

The gaps T18 left (S-002, S-021):

- A browser test of a viewer's cursor on slot 9, shown in an editor's frame.
- A browser test that the cursors stay on their points across a whole-diagram load.
- A follow refused with `cannot_follow` now ends without a word, on every slot. The bar says why, in a short phrase such as `Can't follow: they follow you`, for a few seconds.

The update notice (a new row):

- Today a page left open across `segl update` reconnects and runs its old code. By reading the code, and not run: a page of 0.6.0 open on slot 9 across the update to 0.7.0 would have each change it made answered `unknown_type`, with no word, until a reload (0.7.0's publish entry).
- `welcome` carries the server's version, `version`, as `segl --version` prints it from `versions.toml`. The page compares it with the version it was built with (`__SEGL_VERSION__`). When the two differ, the bar says `segl updated`, with a `Reload` button. The page does not reload by itself: a person may be typing.
- Only a page built with this task knows the field. A page of 0.8.0 shows nothing at the update to the release that carries T19. The notice first shows at the update after that.

Tests:

- pytest: `welcome` carries `version`. A restore on slot 9 starts a new epoch, keeps the diagram that went marked `restore`, and sends every connection the restored diagram. A patch of the old epoch is then refused. While another holds the pen, a restore from someone else is refused with `pen_held`. A big delete on slot 9 keeps a `delete` row, and a diagram the server cannot count is still saved. A selection reaches the others, a browser that joins gets the selections already made, a selection whose page or cell ids are not short text is refused with `bad_message`, and a selection goes when its person leaves.
- Vitest: a repair's load waits for a press to end, as for a label, and tells the frame the page to come back to. The bar shows History on slot 9, and no Restore while another holds the pen. A selection goes out at most a few times a second, and the others' reach the frame with their colors. The update notice shows only when the versions differ. A refused follow shows its phrase.
- Browser: on a diagram with three pages, a browser on page 3 drifts, loads, and stays on page 3 at the same view, with its selection kept. A load that comes during a drag waits for the release, and every browser keeps the drag's move. A restore from History on slot 9 reaches both browsers, each on its own page. Each browser sees the other's selection outlined on its page and not on another page. The outline follows a moved shape, and goes when the other selects nothing. A viewer's cursor shows in an editor's frame, and the cursors stay on their points across a load. A page whose `welcome` names another version shows the notice, and `Reload` loads the page again (Playwright's `routeWebSocket` can change the message).
- Four new rows in `docs/TEST-PLAN.md`, each with its row in `tests/testplan.toml`: T-027 for a load that keeps the page and waits for a press, T-028 for History and restore on slot 9, T-029 for the others' selections on slot 9, and T-030 for the update notice. T-025 and T-026 gain the gaps above.

Documents: `docs/REQUIREMENTS.md` (D-001 and D-003 as built, and two new rows), `docs/TEST-PLAN.md` (T-025 to T-030), `tests/testplan.toml`, `docs/API.md` (`version` in `welcome`, the selection, and the restore route on slot 9 with `pen_held`), `docs/DATA-MODEL.md` (a big delete on slot 9), `docs/ARCHITECTURE.md` (Diagram mode's loads, selections, and `js/PostConfig.js`), D2-040 with the measures, D2-041 amended as built, the status in `README.md`, and `CHANGELOG.md`.

Acceptance: T-027 to T-030 pass, and T-001 through T-026 still pass by `scripts/e2e.py`. ruff, ty, and the web checks pass.

Out of scope, for T20 or later at the user's word of 2026-11-27:

- segl's 12 device kinds and 5 link kinds in drawio's library, with no color set by segl. The recommendation: each object's record as drawio's own data on its shape, edited in drawio's Edit Data dialog, in place of a segl panel in the frame.
- Import of `.drawio` files on slot 9. The team already imports through drawio's own menu. segl's Import would replace the whole diagram for everyone and keep the old one in History.
- A pen that frees itself after a time, and a second diagram slot.
- A smaller package: drawio files that nothing loads (`js/integrate.min.js`, `js/libavoid-js/`), against D2-039's rule that segl serves drawio as released.
- Noted while writing this task: the others' selections on the whiteboards. The pinned editor's `Collaborator` type has `selectedElementIds`, and segl does not send it.

As built (2026-11-28):

- The risk did not happen. In a real browser, a load of a three-page diagram with a view on page 3 came back to page 3, at scale 1.5 and the same point, with the same two cells selected, no autosave, and no undo step. `js/PostConfig.js` wraps the load function drawio hands `installMessageHandler`, and turns with `selectPage(page, true)` right after drawio puts the loaded diagram in place. That is before drawio's autosave baseline and before it applies the load's scale and scroll, so drawio sets the view on the turned page itself. A first try that turned at `embedLoaded` sent an autosave: the first time a page is shown after a load, drawio writes that page's settings into the diagram. A follow's turn after a patch still does that (D2-041).
- Measured first, on the code before the task (D2-040). A load during a drag ended the drag every time, 12 of 12, and the shape stayed where it was everywhere. T17's 25 label editors that did not open came from drawio's insert animation, not from a cleared selection: drawio selects a new shape only when its pop animation ends, and once a load during that animation left the selection holding a replaced cell. `js/PostConfig.js` now swaps such a cell for the diagram's own cell of that id. The measure also found that it said a label editor was open when drawio had opened none, and it now reports drawio's real state.
- Every load in the frame waits until no label is edited and no press is held, a join's too. The press: capture listeners on the window for `pointerdown`, `pointerup`, and `pointercancel`, counted per pointer. A move with no button down and the window's `blur` also end one, so a release outside the frame cannot hold loads. The end of a press is told from a timer after the release, so drawio's own change of a drag or a drop is posted first, and reaches the server before the page asks for the whole diagram. Told at once, the page asked first, and a shape dropped from the panel came back unselected (the measure after the fix, 2 of 2). Each press has a number, so a late release ends only its own press.
- The session waits for the frame before reading the view, for every whole diagram that is not a join. After a load it applies again its own patches the server has not numbered: an edit made just before a load is not in the diagram that came back.
- A restore on slot 9 goes through `DiagramRoom.replace`: a new epoch, the restored diagram, no patches, nothing waiting, and the pen as it was. It counts as one change for the mark. The route checks the pen before it reads the revision: a restore from anyone but the holder is `pen_held` even for a revision that does not exist. The pen is checked once, at the start. A `connectionId` that is not text never matches the holder. A restore leaves everyone's selection as it was.
- The count for a big delete is `live_cells` in `src/segl/diagram.py`, with Python's expat. A DOCTYPE, a compressed page, XML that does not parse, or half a surrogate pair makes a diagram uncountable. The saver counts the head in the next write's worker thread, at start and after a restore or an import. When either side cannot be counted, no `delete` row is written, and the save goes ahead.
- A selection: the frame drops cell ids that are not 1 to 128 characters and repeats, and makes a page id the server would refuse null. It reports once per task, and only on a change. The server reads a selection with no `page` as null, drops other keys, allows repeats, and refuses a message with no `selection` field. A page sends its selection again at each `welcome` when it has one.
- The outlines are drawio's `mxCellHighlight` as `highlightCell` builds one, at opacity 70, with no fade, in drawio's overlay pane, drawn only on their own page, and drawn again after each patch, load, page turn, and model change. drawio's read-only view cannot select, so a viewer, and a watcher while another holds the pen, sends none, and still sees the others'.
- While this browser follows someone, a load turns to the followed page, not its own.
- The bar on slot 9 shows the pen, History, and the follow, in that order. While another holds the pen, History says `Restoring needs the pen.`, and a `pen_held` refusal says the same. The confirm question still says `Replace the canvas for everyone?` on slot 9.
- The refusal of a follow shows only while the refused follow is still the one the page shows: the loop. A follow refused because its leader just left shows nothing. The update notice reads `version` from each `welcome`, and an empty or missing one shows nothing.
- `web/src/bar/SeglBar.test.ts` is the project's first test that renders a React component, with `react-dom/server` and a `MemoryRouter`.
- Three more browser tests came from the fault list of `js/PostConfig.js`: an empty page keeps its view across a load, a shape drawn just as a load comes still takes its label, and a press that ends in a cancel, a lost focus, or a move with no button lets a load come.
