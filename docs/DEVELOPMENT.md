# Development

What a development host needs, the checks a change runs, and the dev loop. Product behavior is in the rest of `docs/`. The task queue is [`draft2/STATUS.md`](../draft2/STATUS.md).

## Host tools

These versions were verified on the development host, Ubuntu 26.04.1 LTS on amd64, on 2026-11-11. Newer releases are fine. The "From" column is the first task that needs the tool.

| Tool | Verified | Used for | From |
|---|---|---|---|
| git | 2.53.0 | Version control. Commits are signed off with `git commit -s` (D2-022). | T00 |
| GitHub CLI (`gh`) | 2.102.0 | CI status, GitHub Releases, and the newest release of each pinned action (`release.py check`). Log in with the `repo` and `workflow` scopes (`gh auth status`). | T01 |
| uv | 0.13.7 | Python and every Python command (`uv sync`, `uv run`). It installs the pinned CPython, 3.15.2, so the app never uses the system Python. | T01 |
| python3 | 3.14.4 (system) | Only `scripts/release.py`, which needs Python 3.11 or newer and the standard library. | T00 |
| cloc | 2.06 | The line count in release notes (`RELEASING.md`). | T00 |
| Docker | 29.8.2, rootful | The dev container, `FROM ubuntu:26.04`. Rootless Docker or rootless Podman also work (D2-015). | T01 |
| Node.js and npm | 26.13.1 and 11.20.0 | Building and testing `web/`. The version is `web/.node-version`, the newest LTS release (D2-023). npm refuses another major (`engine-strict`), so put this Node first on `PATH` when the host's default is a different one. | T04 |
| nginx | 1.28.3 | The mount tests, which run it without root on loopback ports with the `deploy/nginx/` files. They need 1.25.1 or newer. The dev container installs its own. | T02 |
| openssl | 3.5.5 | The mount tests' certificate. | T02 |
| dpkg-deb | 1.23.7 | Building the `.deb`. | T12 |

Python-side tools come from `uv.lock`, not the host: ruff, ty, pytest, and httpx2 (T01). httpx2 is the transport of the FastAPI test client. Starlette deprecates plain httpx there. `websockets` (T06) is a dependency of segl itself, the WebSocket protocol uvicorn serves `/collab` with (D2-027), and the tests that need a real socket use its client. Web-side tools come from `web/package-lock.json`: Vite, TypeScript, Vitest, Playwright, and Prettier (T04).

Do not use pip, poetry, pnpm, yarn, a virtualenv made by hand, or a Playwright installed system-wide.

## Browsers for the tests

`@playwright/test` drives Chromium. `npx playwright install chromium`, run in `web/`, fetches the browser into the user's cache. Where Chromium's system libraries are missing on the host, run the browser from the Playwright image and point the tests at it, as Sunstone does:

```console
$ docker run --rm --network host --init mcr.microsoft.com/playwright:v<version>-noble \
    /bin/sh -c "cd /tmp && npx -y playwright@<version> run-server --port 3124 --host 127.0.0.1" &
$ PW_WS_ENDPOINT=ws://127.0.0.1:3124/ npm --prefix web run e2e
```

`<version>` must equal the `@playwright/test` version in `versions.toml`, 1.65.0 today. `web/playwright.config.ts` reads `PW_WS_ENDPOINT`. The container shares the host's network, so its browser reaches the test servers on `127.0.0.1`. The tests pass the browser no launch arguments, which that server would drop unless started with `--unsafe`.

CI installs the browser with `npx playwright install --with-deps chromium`, which also installs its system libraries.

## What the browser tests start

`npm --prefix web run e2e` runs `web/e2e/` against the production build, so build first. Playwright starts two things and stops them afterwards:

- `uv run segl --config <temporary TOML>` on `127.0.0.1:18950`, with its database and its uploaded files in a fresh folder under the system's temporary directory and `web_dir` pointing at `web/dist`.
- `uv run python tests/e2e_nginx.py`, which puts nginx in front of that server with the `deploy/nginx/` files, through the same harness as the mount tests. Each site example gets an nginx of its own: segl at `/board/` on port 18951, and segl at a host root on port 18952.

Every spec but one runs three times, as the projects `direct` (Python alone), `root` (nginx at a host root), and `board` (nginx at `/board/`). The specs open paths relative to the project's base URL, so the same test covers each mount. `SEGL_E2E_PORT` moves the ports.

The one spec apart is `web/e2e/durability.spec.ts`, the `restart` project. Its tests kill segl and start it again (T-006, and the restart of T-007), which cannot be done to the server the other tests share. Each of them starts a segl of its own with `uv run segl --config`, on port 18953 and in a new folder under the system's temporary directory (`web/e2e/server.ts`), ends it with SIGKILL, starts it again over the same folder, and removes the folder afterwards.

The tests run one at a time (`workers: 1`). The three projects share the one server, and its slots are shared by design: a room keeps what was drawn on its slot until the server stops, and counts every connection. So a test asserts on what it drew itself, by element id, and never on a slot being empty. `SLOTS` in `web/e2e/pages.ts` says which slot each kind of test may change. Slots 1 and 9 are never drawn on, for the tests about an empty slot. The title test puts `Workspace 4` back when it ends, and slot 4 is where the image tests place their images, each project in a color and at a place of its own. The run takes between four and five minutes.

`web/e2e/history.spec.ts` is T-011 in two browsers, on slot 3, which the presence tests share and do not draw on. The server keeps at most one revision a second while people draw, so a test that needs two revisions waits a second before each drawing. It finds the revision from before a restore as a person does, as the row under the restore's. One of its tests opens the list at 390 pixels and checks that the page gained no sideways scroll.

`web/e2e/saving.spec.ts` holds T-005 and the bar's `Saving…` and `Saved`. It reads the stored head over HTTP to see that "saved" means the disk. `web/e2e/images.spec.ts` is T-007 up to the restart. A test places an image by dropping a PNG it made itself on the canvas (`png` and `dropImage` in `web/e2e/pages.ts`): the editor's own file dialog is the browser's file picker, which Playwright cannot drive. "The image renders" is checked on the canvas: the test reads the pixel in the middle of the image and expects the PNG's color (`expectPainted`). An image without its file is a gray placeholder. The editor stores its own encoding of an image, so the stored bytes are a PNG and not the dropped file byte for byte.

"Two browsers" in `TEST-PLAN.md` is two browser contexts against that server. The `person` fixture makes one: a page in a context of its own, with a display name already stored. `web/e2e/collab.spec.ts` holds T-001 to T-004, the broadcast of T-014, T-015, and T-016, and in the `board` project those tests are the WebSocket half of T-013, over `wss://…/board/collab`. T-004 takes the network away with `page.routeWebSocket`, which closes the page's socket and refuses the ones it tries next until the test restores it.

The browser reaches nginx by address, as `https://127.0.0.1:18951/board/`, and does not check the test certificate, which names the example sites. The mount tests in `tests/test_mount.py` cover the site names and verify the certificate.

`web/e2e/mount.spec.ts` is the page half of T-013 and T-010. It refuses every request to another origin, as with outbound network blocked, and fails if the page attempted one, asked for a path outside its mount, got an error status, or was sent a cookie.

A test's browser starts with a display name already in `localStorage` (`Tester`), as a returning visitor's does, and asks the server for none. segl gives one address 30 names a minute, and every browser test comes from `127.0.0.1`. The specs import `test` from `web/e2e/pages.ts`, which stores that name. The few tests about a new visitor opt out with `test.use({ storedName: null })`, and take 18 names in a run. The test server's word file is `Guest` and `Staff`.

The canvas is pixels, so the specs read the scene through `window.SEGL_CANVAS.document()`, a read-only handle the canvas adapter publishes (`web/src/canvas/handle.ts`). It returns the scene document as the editor serializes it for storage, which leaves deleted elements out. The head segl stores keeps them (D2-029). `peers()` returns the other connections the editor is drawing cursors for. `images()` returns the images on the canvas, each with the type of its file, or null while the canvas does not hold the file. `reconcile(local, remote)` runs the editor's own `reconcileElements` beside the canvas, and `web/e2e/reconcile.spec.ts` holds it to `tests/reconcile_cases.json`, the table the server's rule is held to.

## The empty scene

`src/segl/empty_scene.json` is the scene a new slot starts with (`DATA-MODEL.md`). `web/e2e/fixture.spec.ts` compares it with what the pinned editor produces for an empty canvas. When a new Excalidraw release changes that document, the test fails. Capture it again, and review the difference before committing it:

```bash
SEGL_UPDATE_FIXTURE=1 npm --prefix web run e2e -- fixture.spec.ts --project direct
```

## Checks

Python, from T01:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

`uv run pytest` covers `tests/` and `tools/md2html`. The page tests (`tests/test_web.py`) use a small stand-in for `web/dist`, so pytest needs no web build. One of them holds the stand-in to the real build when `web/dist` exists, and skips when it does not. Some tests start a real `segl` process on a free loopback port. The mount tests (`tests/test_mount.py`) also start nginx in front of it, from a temporary copy of the `deploy/nginx/` files (`tests/harness.py`), and so does the display-name limit's test (`tests/test_names.py`). A test server's word file is `Guest` and `Staff`. On a host without nginx or openssl they skip, and the summary line says why. With `SEGL_REQUIRE_NGINX=1` they fail instead. The dev container and CI set it. The release script's tests use fakes for the network, `gh`, and `git push`, and real `git` in a temporary repository. One test builds the wheel with `uv build` to confirm it carries `versions.toml` and the SQL migrations, so it needs the network the first time. The repository and slot tests each use a SQLite file in pytest's temporary folder. The room tests (`tests/test_room.py`) need no socket: a test's browser is a list of the messages the room delivered. The socket tests (`tests/test_collab.py`) use the FastAPI test client entered as a context manager, so that every socket of a test shares one event loop as in the server, then a real `segl` process, and then nginx in front of one, with the `websockets` client. The saver's tests (`tests/test_saver.py`) run a room over a real database with flush intervals of a hundredth of a second, or of an hour where only a leave or a stop may be the reason for a write, and with a clock the test moves for the history interval. `tests/test_durability.py` is T-005, T-006, and T-007 at the socket: it kills a `segl` process with SIGKILL, or stops it with SIGTERM, and starts another over the same folder. `tests/test_assets.py` covers the file store and its two routes, through nginx too. `tests/test_history.py` is the revision routes and restore: T-011 and the history part of T-008 at the socket, the 51st revision as the list route shows it, a restore across two kills of a `segl` process, and both through nginx. How a restore takes its turn with the head flushes is in `tests/test_saver.py`, where a test holds a write open in its worker thread. `tests/reconcile_cases.json` is one table of which copy of an element is kept. pytest, Vitest, and a browser test all read it. ruff's settings are in `pyproject.toml`: 100-character lines, Markdown left alone, and `scripts/` kept to Python 3.11 syntax because the host's `python3` runs them.

The dev container runs the same suite while it builds, from the repository root:

```bash
docker build -f deploy/Containerfile .    # or: podman build -f deploy/Containerfile .
```

Web, from T04:

```bash
npm --prefix web ci --ignore-scripts   # the locked packages, into web/node_modules
npm --prefix web run check             # tsc --noEmit
npm --prefix web test                  # Vitest
npm --prefix web run format:check      # Prettier
npm --prefix web run build             # web/dist, which Python serves
npm --prefix web run e2e               # Playwright, against Python serving that build
```

`npm --prefix web run format` rewrites the files Prettier would complain about. Vitest covers the modules that need no browser: how the page finds segl's root, slot parsing and the last slot, display names, slot titles, the canvas adapter's reading of a stored scene, the collaboration session (against a socket, a canvas, and a file server the test supplies, with a clock it moves), the messages of the socket, the files of images (`web/src/collab/files.ts`, and the `data:` URL codec beside it), and the build scripts. `tests/display_name_cases.json` is one table of typed names and what segl shows for each. Vitest and pytest both read it, so the browser's title case and the server's cannot drift apart. A test (`tests/test_pins.py`) holds `web/package.json`, `web/package-lock.json`, and `web/.node-version` to `versions.toml`.

CI runs the same commands (`.github/workflows/ci.yml`). It installs nginx and Chromium, sets `SEGL_REQUIRE_NGINX=1`, and builds `web/` before pytest. The dev container runs them too, except the browser tests, which join in T11.

## Dev loop

Two processes, each in its own terminal:

```bash
uv run segl                 # Python on 127.0.0.1:8888, development defaults, data in var/
npm --prefix web run dev    # Vite on 127.0.0.1:5173, with hot reload
```

Open `http://127.0.0.1:5173/s/1`. Vite proxies `/api` and `/collab` (the WebSocket) to Python with `changeOrigin: false`, so the Origin check still matches. Two browser windows on that address collaborate as they do in production. `SEGL_API_URL` names a Python on another address. The dev server serves the editor's canvas fonts from the npm package at `/fonts/`, where the build puts a copy.

The dev server serves the page itself, at the host root, with no `SEGL_CONFIG`. The app then takes the host root as segl's root and asks `api/v1/config` whether an edit token is needed (`ARCHITECTURE.md`). Mounting under a path such as `/board/` is tested through nginx and the production build, not the dev server (`TEST-PLAN.md` T-013).

Python serves the production build as well. After `npm --prefix web run build`, `uv run segl` serves it at `http://127.0.0.1:8888/s/1`, from `web/dist` (`web_dir` in `DEPLOY.md`). Without a build it says `no web application in web/dist` and serves the API alone, which is all the dev server needs. Python reads the build when it starts, so restart it after building again.

Everything that touches Excalidraw is in `web/src/canvas/`. The rest of the application imports that folder and never the package. The collaboration code in `web/src/collab/` knows the canvas only as `SceneEditor`, six methods that `web/src/canvas/editor.ts` implements. In development React constructs the editor twice and mounts one, so `Canvas.tsx` waits for the editor's first change before it hands the editor on. The application version in the segl bar comes from `versions.toml` at build time (`web/scripts/app-version.ts`).

## Documentation site

Every Markdown file in the repository is published as HTML at <https://robert-patrick-texas.github.io/segl/> (D2-024). `README.md` is the index page. Every page carries the same left-hand index of all pages, and that index opens with the project name linking to the GitHub repository. `.md` links become links between pages.

```bash
python3 scripts/build_docs.py          # build _site/ and check every link, anchor, and image
python3 scripts/build_docs.py /tmp/x   # build somewhere else
```

Open `_site/index.html` in a browser to review it.

The script runs `tools/md2html`, copied from vakr, with segl's settings:

- the project name and repository from `versions.toml`
- the repository entry at the top of the index (`--repo-in-index`)
- `.github/` left out
- `--check`

It also copies `images/` into the site whole, and fails on a raw HTML `<img>` whose file is missing, which md2html does not check itself.

`.github/workflows/pages.yml` runs the same script on every push to `main` and deploys `_site/`. A broken link stops the deploy.

`tools/md2html` stays portable. It imports nothing from segl and hard-codes nothing about it, so it can go back to vakr unchanged. `uv run pytest` runs its tests with the rest of the suite. Its two packages are the `docs` dependency group, at the `[python.docs]` pins in `versions.toml`, and its inline script metadata mirrors them.

## Images

Pictures for any page go in `images/` at the repository root. The site build copies the folder whole, so one relative path works on GitHub and on the published site, from Markdown and from HTML.

From a file at the root, such as `README.md`:

```markdown
![Two slots open side by side](images/two-slots.png)
```

From a file one folder down, in `docs/`, `draft2/`, or `journal/`:

```markdown
![Two slots open side by side](../images/two-slots.png)
```

```html
<img src="../images/two-slots.png" alt="Two slots open side by side" width="1600" height="900">
```

- Use PNG, JPEG, GIF, SVG, or WebP, with lowercase hyphenated file names.
- Give every picture alt text. In HTML, `width` and `height` (the file's size in pixels) let the page reserve the space before the picture loads.
- Keep files small. Git keeps every version of every picture.

## Releases

`RELEASING.md`.
