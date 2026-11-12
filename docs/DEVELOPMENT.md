# Development

What a development host needs, the checks a change runs, and the dev loop. Product behavior is in the rest of `docs/`. The task queue is [`draft2/STATUS.md`](../draft2/STATUS.md).

## Host tools

These versions were verified on the development host, Ubuntu 26.04.1 LTS on amd64, on 2026-11-11. Newer releases are fine. The "From" column is the first task that needs the tool.

| Tool | Verified | Used for | From |
|---|---|---|---|
| git | 2.53.0 | Version control. Commits are signed off with `git commit -s` (D2-022). | T00 |
| GitHub CLI (`gh`) | 2.102.0 | CI status and GitHub Releases. Log in with the `repo` and `workflow` scopes (`gh auth status`). | T01 |
| uv | 0.13.7 | Python and every Python command (`uv sync`, `uv run`). It installs the pinned CPython, 3.15.2, so the app never uses the system Python. | T01 |
| python3 | 3.14.4 (system) | Only `scripts/release.py`, which needs Python 3.11 or newer and the standard library. | T00 |
| cloc | 2.06 | The line count in release notes (`RELEASING.md`). | T00 |
| Docker | 29.8.2, rootful | The dev container, `FROM ubuntu:26.04`. Rootless Docker or rootless Podman also work (D2-015). | T01 |
| Node.js and npm | 24.22.1 and 11.19.1 | Building and testing `web/`. The project's Node version is `web/.node-version` (D2-023). | T04 |
| nginx | 1.28.3 | Trying the `deploy/nginx/` files on the host. The dev container installs its own for the mount tests. | T02 |
| dpkg-deb | 1.23.7 | Building the `.deb`. | T12 |

Python-side tools come from `uv.lock`, not the host: ruff, ty, pytest, and httpx (T01). Web-side tools come from `web/package-lock.json`: Vite, TypeScript, Vitest, Playwright, and Prettier (T04).

Do not use pip, poetry, pnpm, yarn, a virtualenv made by hand, or a Playwright installed system-wide.

## Browsers for the tests

`@playwright/test` drives Chromium. `npx playwright install chromium`, run in `web/`, fetches the browser into the user's cache. Where Chromium's system libraries are missing on the host, run the browser from the Playwright image and point the tests at it, as Sunstone does:

```console
$ docker run --rm --network host --init mcr.microsoft.com/playwright:v<version>-noble \
    /bin/sh -c "cd /tmp && npx -y playwright@<version> run-server --port 3124 --host 127.0.0.1" &
$ PW_WS_ENDPOINT=ws://127.0.0.1:3124/ npm --prefix web run e2e
```

`<version>` must equal the `@playwright/test` version in `versions.toml`. T04 wires `PW_WS_ENDPOINT` into `web/playwright.config.ts`.

## Checks

Python, from T01:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

Web, from T04:

```bash
npm --prefix web run check          # tsc --noEmit
npm --prefix web test               # Vitest
npm --prefix web run format:check   # Prettier
npm --prefix web run e2e            # Playwright, against Python serving the production build
```

CI runs the same commands (`.github/workflows/ci.yml`, from T01).

## Dev loop

From T04: run Python on `127.0.0.1:8000` with `uv run segl`, which uses the development defaults in `DEPLOY.md`, and the Vite dev server on `127.0.0.1:5173`. Vite proxies `/api` and `/collab` (the WebSocket) to Python with `changeOrigin: false`, so the Origin check still matches. Open `http://127.0.0.1:5173/s/1`.

The dev server serves the page at the host root. Mounting under a path such as `/board/` is tested through nginx and the production build, not the dev server (`TEST-PLAN.md` T-013).

## Releases

`RELEASING.md`.
