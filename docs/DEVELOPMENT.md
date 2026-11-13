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
| Docker | 29.8.2, rootful and rootless | The dev container, `FROM ubuntu:26.04`. T11 ran it under both. Rootless Podman is allowed too (D2-015) and was not tried. | T01 |
| Node.js and npm | 26.13.1 and 11.20.0 | Building and testing `web/`. The version is `web/.node-version`, the newest LTS release (D2-023). npm refuses another major (`engine-strict`), so put this Node first on `PATH` when the host's default is a different one. | T04 |
| nginx | 1.28.3 | The mount tests, which run it without root on loopback ports with the `deploy/nginx/` files. They need 1.25.1 or newer. The dev container installs its own. | T02 |
| openssl | 3.5.5 | The mount tests' certificate. | T02 |
| Docker, again | 29.8.2, rootful | Building the `.deb` and installing it in a container that boots systemd, which needs a privileged container. nfpm, lintian, and `dpkg-deb` are in the build's image, not on the host. | T12 |

Python-side tools come from `uv.lock`, not the host: ruff, ty, pytest, and httpx2 (T01). httpx2 is the transport of the FastAPI test client. Starlette deprecates plain httpx there. `websockets` (T06) is a dependency of segl itself, the WebSocket protocol uvicorn serves `/collab` with (D2-027), and the tests that need a real socket use its client. Web-side tools come from `web/package-lock.json`: Vite, TypeScript, Vitest, Playwright, and Prettier (T04).

Do not use pip, poetry, pnpm, yarn, a virtualenv made by hand, or a Playwright installed system-wide.

## Browsers for the tests

`@playwright/test` drives Chromium. `npx playwright install chromium`, run in `web/`, fetches the browser into the user's cache. Where Chromium's system libraries are missing on the host, run the browser from the Playwright image and point the tests at it, as Sunstone does:

```console
$ docker run --rm --network host --init mcr.microsoft.com/playwright:v<version>-noble \
    /bin/sh -c "cd /tmp && npx -y playwright@<version> run-server --port 3124 --host 127.0.0.1" &
$ PW_WS_ENDPOINT=ws://127.0.0.1:3124/ npm --prefix web run e2e
```

`<version>` is the `@playwright/test` version in `versions.toml`, 1.65.1 today. The browser server refuses a client of another minor release. A patch apart works: on 2026-11-13 the 1.65.1 tests ran against the 1.65.0 image. `web/playwright.config.ts` reads `PW_WS_ENDPOINT`. The container shares the host's network, so its browser reaches the test servers on `127.0.0.1`. The tests pass the browser no launch arguments, which that server would drop unless started with `--unsafe`.

CI installs the browser with `npx playwright install --with-deps chromium`, which also installs its system libraries. The dev container's image has both, installed the same way, so the browser tests run in it with no second container.

## What the browser tests start

`npm --prefix web run e2e` runs `web/e2e/` against the production build, so build first. Playwright starts four things and stops them afterwards:

- `uv run segl --config <temporary TOML>` on `127.0.0.1:18950`, with its database and its uploaded files in a fresh folder under the system's temporary directory and `web_dir` pointing at `web/dist`.
- `uv run python tests/e2e_nginx.py`, which puts nginx in front of that server with the `deploy/nginx/` files, through the same harness as the mount tests. Each site example gets an nginx of its own: segl at `/board/` on port 18951, and segl at a host root on port 18952.
- A second segl on port 18954, the same but for `access_codes` and `access_secret` in its TOML, with a folder of its own beside the first one's.
- A second `tests/e2e_nginx.py` in front of that one: `/board/` on port 18955, and a host root on port 18956.

`web/e2e/sites.ts` has the ports, each project's base URL, and the access code, for the config and the specs alike. `SEGL_E2E_PORT` moves the ports.

Every spec but three runs three times, as the projects `direct` (Python alone), `root` (nginx at a host root), and `board` (nginx at `/board/`). The specs open paths relative to the project's base URL, so the same test covers each mount.

`web/e2e/access.spec.ts` is one of the three apart. It runs three times against the segl that has an access code, as `access-direct`, `access-root`, and `access-board`, and is T-008 and T-019 in a browser. A test's own page there has no pass: a viewer. An editor is a second context with a pass already stored, `person(name, { editor: true })`, which buys one from the server as the access page does, or a page on which a code is entered. The spec shows what a viewer sees and cannot do, on the canvas, the title, the history, the import, and an upload, and that a script on a viewer's page is answered `view_only`. It follows the bar's link to the access page, enters the code, and edits on the slot it came from, also from another tab and after a wrong code. It shows that an address ending in `#e=` is an address like any other. It also reads every address both browsers asked for, and fails if one carries a code or a pass or if any answer set a cookie (T-012). Five wrong codes in a row make an address wait fifteen minutes, and every test comes from `127.0.0.1`, so a test that enters a wrong code enters a right one afterwards, and the wait itself is shown with an answer the test puts in the server's place.

The other two are the `restart` project. Each of their tests starts a segl of its own with `uv run segl --config`, on port 18953 and in a new folder under the system's temporary directory (`web/e2e/server.ts`), and removes the folder afterwards. The tests of `web/e2e/durability.spec.ts` kill segl and start it again (T-006, and the restart of T-007), which cannot be done to the server the other tests share: they end it with SIGKILL and start it again over the same folder. `web/e2e/expiry.spec.ts` runs a segl whose passes last 14.4 seconds. It shows the page stopping by itself before its pass ends, with nothing drawn afterwards and no refusal from the server, and a code entered again (T-019). It reads the frames of the page's socket, each with its time.

The tests run one at a time (`workers: 1`). The three projects share the one server, and its slots are shared by design: a room keeps what was drawn on its slot until the server stops, and counts every connection. So a test asserts on what it drew itself, by element id, and never on a slot being empty. `SLOTS` in `web/e2e/pages.ts` says which slot each kind of test may change. Slots 1 and 9 are never drawn on, for the tests about an empty slot. The title test puts `Workspace 4` back when it ends, and slot 4 is where the image tests place their images, each project in a color and at a place of its own. The run takes about nine minutes.

`web/e2e/fonts.spec.ts` is about the one font file that is not the editor's own, Liberation Sans (`web/licenses/README.md`). A page fetches that file only when some text uses the face, so the test asks the page to load it, and checks that the browser took it as a font and that its bytes are the file in `web/fonts/`.

`web/e2e/history.spec.ts` is T-011 in two browsers, on slot 3, which the presence tests share and do not draw on. The server keeps at most one revision a second while people draw, so a test that needs two revisions waits a second before each drawing. It finds the revision from before a restore as a person does, as the row under the restore's. One of its tests opens the list at 390 pixels and checks that the page gained no sideways scroll.

`web/e2e/import.spec.ts` is T-009 in two browsers, on slot 8, which the tests about names share and do not draw on. It exports through the editor's own menu. Chromium has a save dialog of its own there, which Playwright cannot drive, so the test takes that dialog away before the page loads (`withoutFilePickers` in `web/e2e/pages.ts`). The editor then saves the file as a download, as it does in Firefox and Safari, and the test reads it. The import goes through the bar's Import button and the browser's file dialog, which Playwright answers. One test drops a scene file on the canvas (`dropFile`), and one checks that the editor's own Open is gone.

`web/e2e/saving.spec.ts` holds T-005 and the bar's `Saving…` and `Saved`. It reads the stored head over HTTP to see that "saved" means the disk. `web/e2e/images.spec.ts` is T-007 up to the restart. A test places an image by dropping a PNG it made itself on the canvas (`png` and `dropImage` in `web/e2e/pages.ts`): the editor's own file dialog is the browser's file picker, which Playwright cannot drive. "The image renders" is checked on the canvas: the test reads the pixel in the middle of the image and expects the PNG's color (`expectPainted`). An image without its file is a gray placeholder. The editor stores its own encoding of an image, so the stored bytes are a PNG and not the dropped file byte for byte.

"Two browsers" in `TEST-PLAN.md` is two browser contexts against that server. The `person` fixture makes one: a page in a context of its own, with a display name already stored. `web/e2e/collab.spec.ts` holds T-001 to T-004, the broadcast of T-014, T-015, and T-016, and in the `board` project those tests are the WebSocket half of T-013, over `wss://…/board/collab`. T-004 takes the network away with `page.routeWebSocket`, which closes the page's socket and refuses the ones it tries next until the test restores it. One test holds the server's `scene` back for a second the same way, and fails if the page sends any of the drawing it loaded.

The browser reaches nginx by address, as `https://127.0.0.1:18951/board/`, and does not check the test certificate, which names the example sites. The mount tests in `tests/test_mount.py` cover the site names and verify the certificate.

`web/e2e/origin.spec.ts` is the Origin check of T-012 in a real browser, which writes the `Origin` header itself. The three projects reach one segl at three origins, so a page of one is a page of another site to the next. Such a page posts an import and asks for a display name, with requests a browser sends without asking leave, and each is answered `403` and changes nothing. It tries a `PATCH`, which the browser asks leave for first and never sends. It tries to read a slot, and to open the collaboration socket, which is refused in the handshake while the same address opens from the site's own page. A browser keeps the body of such an answer from the page and from the test, so the test reads the status off the wire, and reads the error code by sending the same request itself with the same `Origin`.

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

`uv run pytest` covers `tests/` and `tools/md2html`. The page tests (`tests/test_web.py`) use a small stand-in for `web/dist`, so pytest needs no web build. One of them holds the stand-in to the real build when `web/dist` exists, and skips when it does not. Some tests start a real `segl` process on a free loopback port. The mount tests (`tests/test_mount.py`) also start nginx in front of it, from a temporary copy of the `deploy/nginx/` files (`tests/harness.py`), and so does the display-name limit's test (`tests/test_names.py`). A test server's word file is `Guest` and `Staff`. On a host without nginx or openssl they skip, and the summary line says why. With `SEGL_REQUIRE_NGINX=1` they fail instead. The dev container and CI set it. The harness's own client is held at TLS 1.2 (`running_mount`). Under TLS 1.3 its WebSocket client, the `websockets` package, sometimes lost its request on a busy machine, and a test then failed with a handshake that was not answered. nginx runs the shipped files either way and still offers TLS 1.3, which the browser tests use. `uv run python tests/handshake_loop.py 3000 --busy 8` repeats the measurement, and with `--tls13` it runs without the hold, which is how to find out whether a newer `websockets` lets it go (`ROADMAP.md`, held until a dependency moves). When a server keeps a test waiting, the harness says what the server had written. A WebSocket handshake that is not answered in ten seconds fails the test with the last 40 lines of segl's log, and through nginx also of nginx's `error.log` and `access.log`, where the client's bare timeout used to be. Through nginx that failure comes when the connection ends, which may be later than the ten seconds: the client waits for nginx to let go. A server that has not stopped ten seconds after SIGTERM is killed, as before, and is now named in a warning in pytest's summary with the end of its log. `tests/test_harness.py` holds both, with a segl that is stopped where it stands (SIGSTOP) to stand in for a host that stalls. The release script's tests use fakes for the network, `gh`, and `git push`, and real `git` in a temporary repository. One test builds the wheel with `uv build` to confirm it carries `versions.toml` and the SQL migrations, so it needs the network the first time. The repository and slot tests each use a SQLite file in pytest's temporary folder. The room tests (`tests/test_room.py`) need no socket: a test's browser is a list of the messages the room delivered. The socket tests (`tests/test_collab.py`) use the FastAPI test client entered as a context manager, so that every socket of a test shares one event loop as in the server, then a real `segl` process, and then nginx in front of one, with the `websockets` client. The saver's tests (`tests/test_saver.py`) run a room over a real database with flush intervals of a hundredth of a second, or of an hour where only a leave or a stop may be the reason for a write, and with a clock the test moves for the history interval. `tests/test_durability.py` is T-005, T-006, and T-007 at the socket: it kills a `segl` process with SIGKILL, or stops it with SIGTERM, and starts another over the same folder. `tests/test_assets.py` covers the file store and its two routes, through nginx too. `tests/test_history.py` is the revision routes and restore: T-011 and the history part of T-008 at the socket, the 51st revision as the list route shows it, a restore across two kills of a `segl` process, and both through nginx. How a restore takes its turn with the head flushes is in `tests/test_saver.py`, where a test holds a write open in its worker thread. `tests/test_sweep.py` is T-012 as one walk: a table of one request for every route, asked as segl's own page asks, as a page of another site asks, and as a browser without a pass asks, in process and through nginx in front of a real process that has access codes. No answer may set a cookie or carry a CORS header, a refusal among them. One of its tests compares the table with the routes the application registers, so a new route has to join the walk. `tests/reconcile_cases.json` is one table of which copy of an element is kept. pytest, Vitest, and a browser test all read it. `tests/test_access.py` is the access codes: a code's normal form, the pass and each reason to refuse one with a clock the test moves, the count of wrong codes, the route, and each gate, then a real process with codes in its TOML, and nginx in front of one. `tests/test_networks.py` is `internal_networks`: in process, where the test says which address the client has, and against a real process that is sent `X-Forwarded-For`. `tests/harness.py` has a code, a secret, and `issue_pass` for the tests of the other routes. `tests/header_value_cases.json` is one table of what a page can, and cannot, send in a request header, which Vitest holds the page's stored pass to and pytest holds an issued pass to. ruff's settings are in `pyproject.toml`: 100-character lines, Markdown left alone, and `scripts/` kept to Python 3.11 syntax because the host's `python3` runs them.

The dev container runs the same suite while it builds (below).

Web, from T04:

```bash
npm --prefix web ci --ignore-scripts   # the locked packages, into web/node_modules
npm --prefix web run check             # tsc --noEmit
npm --prefix web test                  # Vitest
npm --prefix web run format:check      # Prettier
npm --prefix web run build             # web/dist, which Python serves
npm --prefix web run e2e               # Playwright, against Python serving that build
```

`npm --prefix web run format` rewrites the files Prettier would complain about. Vitest covers the modules that need no browser: how the page finds segl's root, slot parsing and the last slot, display names, slot titles, the canvas adapter's reading of a stored scene, the collaboration session (against a socket, a canvas, and a file server the test supplies, with a clock it moves), the messages of the socket, the files of images (`web/src/collab/files.ts`, and the `data:` URL codec beside it), the stored pass (`web/src/pass.ts`), the access page's logic (`web/src/access.ts`: what the server's answer to a code means, and the words for it), the notice in the bar, and the build scripts. `tests/display_name_cases.json` is one table of typed names and what segl shows for each. Vitest and pytest both read it, so the browser's title case and the server's cannot drift apart. A test (`tests/test_pins.py`) holds `web/package.json`, `web/package-lock.json`, and `web/.node-version` to `versions.toml`.

CI runs the same commands (`.github/workflows/ci.yml`). It installs nginx and Chromium, sets `SEGL_REQUIRE_NGINX=1`, and builds `web/` before pytest.

## The dev container

The dev container is Ubuntu 26.04 with uv, Node, nginx, and Chromium (`deploy/Containerfile`). It needs Docker from the host and nothing else. From the repository root:

```bash
docker build -f deploy/Containerfile -t segl-dev .   # the web checks, the web build, and pytest
docker run --rm --init segl-dev                      # the test plan's rows, one line each
```

The build stops at the first check that fails. The run is `scripts/testplan.py` (next section): pytest again, then the browser tests, about ten minutes in all. It exits 0 when every row passed. `--init` gives the container a first process that cleans up after the processes the tests end.

Chromium runs in the Ubuntu 26.04 image itself. Playwright lists that Ubuntu, `playwright install-deps chromium` installs the libraries, and Playwright starts Chromium with `--no-sandbox` and `--disable-dev-shm-usage`, so `docker run` needs no extra flag. The Playwright image and `PW_WS_ENDPOINT` are for a host without the libraries, not for the container.

The tests run as the image's `ubuntu` account, on uv's Python. The image has no system Python for them to fall back on, and `UV_PYTHON_PREFERENCE=only-managed` would refuse one.

Rootless Docker takes the same two commands. T11 ran both under rootful Docker 29.8.2 and under rootless Docker 29.8.2. The rootless daemon was started by hand with `dockerd-rootless.sh`, on rootlesskit's own network driver. Podman reads the same file and was not tried: the development host has none.

## The test plan as one command

```bash
uv run python scripts/testplan.py
```

It runs pytest whole, then the browser tests whole, and prints one line for each row of `TEST-PLAN.md`:

```text
  T-001  pass  2 pytest, 3 browser
  T-002  pass  1 pytest, 3 browser
```

`tests/testplan.toml` names the tests that run each row. A row passes when every test it names ran and passed. A skipped test fails its row. So does a browser test that missed one of its projects: the three mounts, the three `access-` projects, or `restart`. A failed row lists what failed under it. The command exits 0 when every row passed and both suites did.

Above the rows it prints what an evidence block needs (`TEST-PLAN.md`, evidence): the revision, the Python and where it came from, Node, nginx, Excalidraw, Playwright, and Chromium.

It needs what `npm --prefix web run e2e` needs: the build and a browser. T-017 is not run here: `deploy/debian/package-test.sh` installs the `.deb` (the package, below). T-018 is judged in the dev container alone, where it passes when the other rows did, on uv's Python.

`tests/test_testplan.py` holds the table to the test plan's rows and to the tests' names. A test that is renamed fails pytest until the table follows. It holds the judging to made-up reports, and the command to stand-ins for the two suites.

## Size runs

```bash
npm --prefix web run stretch
```

It runs the two sizes of `TEST-PLAN.md`: ten editors on one slot, and a slot of 1,024 elements. `web/stretch/sizes.stretch.ts` has both, and `web/playwright.stretch.config.ts` runs them against Python alone and through nginx at `/board/`. Each test prints what it measured, on lines that start with `stretch:`.

- Ten editors: ten browser contexts join one slot. All draw at once, three times, then all move a rectangle twenty steps at once. Every browser must end with the same scene, and the stored scene must have every rectangle.
- 1,024 elements: one rectangle, doubled ten times with select-all and duplicate, while a second browser watches. A third browser then loads the slot, draws one more rectangle, and the second moves all 1,025 at once. All three must end with the same scene.

The runs are not part of the gate and hold no time to a limit. They fail only when the browsers end with different scenes. They use the browser tests' servers and ports, so run one or the other. In the dev container: `docker run --rm --init segl-dev npm --prefix web run stretch`. The times are those of the machine and of a browser that draws without a GPU. `draft2/STATUS.md` has the numbers of T11's run.

## The package

```bash
deploy/debian/build-deb.sh        # dist/segl_<version>_amd64.deb
deploy/debian/package-test.sh     # builds it, then installs it (TEST-PLAN.md T-017)
deploy/debian/package-test.sh dist/segl_<version>_amd64.deb   # installs one already built
```

`build-deb.sh` builds the package in a clean `ubuntu:26.04` container, from the two lockfiles (`DEPLOY.md`, the package). It hands the container every tracked file and every untracked file git does not ignore, so work in progress builds too. The files in the package carry the last commit's time. The build ends with lintian, and a lintian error fails it. On the development host a build took 47 seconds, and 50 without the download caches (`SEGL_UV_CACHE=` and `SEGL_NPM_CACHE=`), once the builder image existed. Building that image the first time took 69 seconds. Three builds of one tree gave the same file, byte for byte.

`package-test.sh` is T-017. It boots an `ubuntu:26.04` container with systemd as PID 1 (`deploy/debian/Containerfile.systemd`), with nginx, Ubuntu's `ssl-cert`, and curl, and no Python. The container's host name is `dev.example.com`, the name in `site-board.example.conf`, so the snakeoil certificate Ubuntu makes there is for that name. Then `deploy/debian/systemd-test.sh` runs in it and prints one `PASS` or `FAIL` line for each check:

- The package installs with apt. The interpreter is under `/opt/segl/python` at the pin, the virtualenv runs it, and `segl --version` reads the packaged `versions.toml`. The settings are mode `0640` for root and segl's group, and user `segl` can write nothing but `/opt/segl/var`.
- Nothing starts on install. `systemctl enable --now segl` starts the unit, as user `segl`, on loopback alone.
- nginx gets the `deploy/nginx/` files and `site-board.example.conf`, with the commands `deploy/OPERATOR.md` gives. A TLS request, checked against the snakeoil certificate, gets the slot page, its script, and a font through `/board/`.
- The package's own Python draws an element over the WebSocket through nginx (`deploy/debian/socket_check.py`). The element is still there after a restart.
- A setting segl cannot use stops the unit, the journal names the key, and systemd does not start it again.
- With access codes in the file, a code buys a pass, and the journal has neither the code nor the secret.
- An upgrade keeps the settings and the board and restarts segl. A stop is clean and leaves no write-ahead log. Remove keeps the settings and the board. Purge removes the settings, keeps the board, and says so.

The upgrade is the same package under a higher version number, which the script makes by repacking it. Set `SEGL_KEEP_CONTAINER=1` to leave the container running afterwards and look around in it.

The container is privileged, because systemd as PID 1 needs a cgroup tree of its own. The test was run under rootful Docker.

`tests/test_package.py` reads the same files without building anything: the unit, the nfpm spec, the maintainer scripts, the copyright file, and the operator notes. It also runs `web/scripts/collect-licenses.ts` against the real web build, when there is one, so a bundled package or a font without a license text fails pytest.

## Dev loop

Two processes, each in its own terminal:

```bash
uv run segl                 # Python on 127.0.0.1:8888, development defaults, data in var/
npm --prefix web run dev    # Vite on 127.0.0.1:5173, with hot reload
```

Open `http://127.0.0.1:5173/s/1`. Vite proxies `/api` and `/collab` (the WebSocket) to Python with `changeOrigin: false`, so the Origin check still matches. Two browser windows on that address collaborate as they do in production. `SEGL_API_URL` names a Python on another address. The dev server serves the editor's canvas fonts from the npm package at `/fonts/`, where the build puts a copy.

The dev server serves the page itself, at the host root, with no `SEGL_CONFIG`. The app then takes the host root as segl's root and asks `api/v1/config` whether an access code is needed (`ARCHITECTURE.md`). Mounting under a path such as `/board/` is tested through nginx and the production build, not the dev server (`TEST-PLAN.md` T-013).

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
