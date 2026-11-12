# Locked decisions

Decisions below are approved. Implement them. A change needs a new dated entry, or a dated amendment on the row, and a user request.

`draft1/` assumed authenticated board CRUD, cookies, PostgreSQL from the first release, and a separate Node collaboration service. Those assumptions are withdrawn for the MVP.

| ID | Decision |
|---|---|
| D2-001 | Working title remains `segl`. |
| D2-002 | MVP is nine fixed collaborative Excalidraw slots. Network objects, inventory import, login, and protected workspaces come later (`ROADMAP.md`). |
| D2-003 | One Python process serves the built web app, the HTTP API, and the collaboration WebSocket. Nginx is the TLS reverse proxy. There is no Node process in production. |
| D2-004 | The browser app is React + TypeScript, built with Vite, embedding `@excalidraw/excalidraw`. The web tooling is D2-023. |
| D2-005 | Slots are numbered 1–9, created at first startup, and never created or deleted by users. Each slot has one shared scene and one shared title. The default title is `Workspace N`. |
| D2-006 | First visit opens slot 1. A later visit to segl's root opens the last slot stored in `localStorage`. A link to `s/N` always opens slot N. |
| D2-007 | One frontend build serves every mount point, and segl has no setting for the path it is mounted under. segl serves at its own root. A reverse proxy gives it a host name of its own (`https://board.example.com/s/1`) or a path on an existing site that the proxy strips (`https://dev.example.com/board/s/1`, the example path in `deploy/nginx/`). The page asks for its assets, the API, and the WebSocket relative to itself. Amended 2026-11-11 (T00): replaces `base_path` in TOML, following Sunstone. |
| D2-008 | The web interface uses no cookies in any phase. Later login will use an `Authorization` bearer token stored in `localStorage`. |
| D2-009 | Anyone who can open the URL can view a slot and see live updates. A site-wide `edit_token` in TOML gates mutations. An empty token means every viewer may also edit. |
| D2-010 | Persistence is SQLite behind a repository interface. PostgreSQL is a later swap, not an MVP dependency. App configuration is TOML. CSV, JSON, and TOML inventory import is later. |
| D2-011 | The head scene is flushed within 200 ms of a change, on last disconnect, and on shutdown. A user-visible revision is recorded at most about once a second, on last disconnect, and on restore or import. The latest 50 revisions per slot are kept. |
| D2-012 | Display labels are assigned from `display-names.txt` round-robin, plus a server-wide counter that never repeats (`Alpha1`, `Bravo2`). The browser keeps the label in `localStorage`. A manual rename replaces the whole label and is title-cased. Automatic names use the file's spelling verbatim. |
| D2-013 | The menu shows the number of live WebSocket connections on the current slot. Activating it lists those participants. |
| D2-014 | Future protected boards use `/{team}/{project}/{board-slug}`. The MVP does not implement that tree. The first path segment `s` stays reserved for slots. |
| D2-015 | Development and automated tests run in a container under rootful Docker, rootless Docker, or rootless Podman. The MVP production install is a `.deb` that places a uv-pinned CPython and a virtualenv under `/opt/segl`, supervised by systemd, behind host nginx. A production container image is a second install method after the MVP gate. Amended 2026-11-11 (T00): rootful Docker allowed for development. |
| D2-016 | Python tooling is uv, ruff, and ty. The Python pin is the exact `runtime.python` value in `versions.toml` (3.15.2). `.python-version` mirrors it. The pin follows the newest stable CPython that uv can install, patch or minor, under the release policy in D2-020. Amended 2026-11-11 (T00): exact patch pin, kept current through uv. |
| D2-017 | Collaboration is a segl WebSocket protocol. The server reconciles Excalidraw elements by id and version and checkpoints the scene. It does not speak the upstream `excalidraw-room` socket.io protocol unless a spike shows the embed requires it, and even then the process remains the one Python service. |
| D2-018 | JSON export and import are in the MVP. Import is an edit: it bumps the scene epoch, requires the edit token when one is set, and writes a revision. PNG and SVG export are whatever the embedded editor already shows. No custom image-export task. |
| D2-019 | The project license is Apache License 2.0. The text is `LICENSE` at the repository root. New source files carry the header in `CONTRIBUTING.md`, with `Copyright 2026 segl contributors`. Excalidraw and other dependencies stay under their own licenses. Attribution those licenses require goes in `NOTICE` when the dependency is added. |
| D2-020 | `versions.toml` is the only version list: application, Python, Node, and direct dependencies. The program reads it to display or check a version. Every component moves to its newest stable release, however recently it was published. One is held back only after it fails the tests, as a `[held.*]` entry with the reason, and is tried again when a newer release appears. `scripts/release.py` checks currency again when a release is published, and publishes only from a clean `main` whose CI passed. Release notes use the shape in `RELEASING.md`, including a first-party `cloc` count ahead of the version table and a collapsed list of lockfile sub-dependencies. `CHANGELOG.md` is the summary history. `journal/YYYY-MM-DD-short-title.md` is the narrative. GitHub Releases, including the `.deb` asset, are on from the first publishable release. PyPI stays off until `publish.pypi` is set true, which waits for a build worth demonstrating. Amended 2026-11-11 (T00): the vakr and Sunstone release policy. |
| D2-021 | The GitHub repository contains the whole project except gitignored secrets and build output. `draft1/` is frozen history. `draft2/` is the agent workbook: status, tasks, and agent rules. `docs/` is the contributor and operator manual. Neither draft folder is gitignored. |
| D2-022 | The repository is public at `https://github.com/robert-patrick-texas/segl`, default branch `main`. Commits carry a `Signed-off-by` line (`git commit -s`). Vulnerability reports go through GitHub private vulnerability reporting. Added 2026-11-11 (T00). |
| D2-023 | The web package uses npm: exact versions in `web/package.json`, `web/package-lock.json`, and `web/.npmrc` with `engine-strict=true`. Node is the LTS release named in `web/.node-version` and mirrored in `versions.toml` `runtime.node`. Vitest runs unit tests. `@playwright/test` runs browser tests against Python serving the production build. `tsc --noEmit` type-checks, and Prettier formats. This matches Sunstone. Added 2026-11-11 (T00). |

## Open, and not blocking T01

- **Exact Excalidraw pin and reconcile helper.** Choose the newest stable `@excalidraw/excalidraw` at T04, record the version in `versions.toml`, and confirm the reconcile API at T06. Adjust the adapter, not the decisions above.
- **Image file model.** Confirm at T07 how the pinned editor names and loads binary files, and map that onto the `files` message and `/api/v1/assets/{hash}` in `API.md`.

## Decision protocol

When a task discovers that a locked decision cannot be implemented as written, set `Blocked: yes` in `draft2/STATUS.md` and append the evidence. Do not silently substitute PostgreSQL, cookies, a Node room server, free-form board CRUD, mandatory login, or a base-path setting.
