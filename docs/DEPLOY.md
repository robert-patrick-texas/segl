# Deployment

## Configuration

`/opt/segl/etc/segl.toml` on the server. `deploy/segl.toml.example` is that file as the `.deb` installs it, with a comment on each key:

```toml
bind = "127.0.0.1:8888"
trusted_proxies = ["127.0.0.1", "::1"]
edit_token = ""
database = "/opt/segl/var/segl.sqlite"
assets_dir = "/opt/segl/var/assets"
display_names = "/opt/segl/etc/display-names.txt"
web_dir = "/opt/segl/app/web/dist"
max_asset_bytes = 10485760
max_scene_bytes = 52428800
history_limit = 50
history_interval_seconds = 1
head_flush_seconds = 0.2
```

There is no base-path setting. segl serves at its root, and nginx strips the path it mounts segl under (`ARCHITECTURE.md`, mount and navigation).

`trusted_proxies` lists the addresses whose `X-Forwarded-For` and `X-Forwarded-Proto` headers segl believes. An entry is an IP address or a network such as `10.0.0.0/8`. Keep it to the nginx host. An empty list believes nobody. `*` is refused, because it would let any client choose the address segl records for it.

`web_dir` is the folder that holds the built web application: `index.html`, Vite's `assets/`, the editor's `fonts/`, and the favicon. segl reads it once, when it starts, so a new build takes a restart. When the folder has no `index.html`, segl serves the API and no page, and says so on its first line of output. An `index.html` that is not a build of `web/` stops it with exit status 1.

`bind` is `host:port`. Write an IPv6 host in brackets, as in `[::1]:8888`. When the file `--config` names does not exist, segl starts with the defaults above.

segl checks the file when it starts. A key it does not know, such as a misspelled `edit_token` or the removed `base_path`, or a value it cannot use, stops it with exit status 2 and a message that names the key. The message never repeats the token. The sizes and `history_limit` are whole numbers, 1 or more. The two intervals are seconds above 0.

`max_scene_bytes` is the most the elements of one slot may come to, as JSON, and also the largest message the collaboration WebSocket takes. A longer message closes that connection, and an edit that would take a slot over is refused (`API.md`, WebSocket). It is the largest file an import takes too. An exported file holds its images as base64 text, a third larger than their bytes, and each image in it may be up to `max_asset_bytes`. The database can hold up to `history_limit` + 1 copies of each slot's scene.

`head_flush_seconds` is how long after an edit segl writes the slot's head, and so how much a crash can lose. `history_interval_seconds` is the least time between two history rows of one slot while people draw (`DATA-MODEL.md`, flush rules). segl also writes when the last browser leaves a slot and when it is stopped with SIGTERM, which is how systemd stops it.

`assets_dir` holds the bytes of the images on the canvases, one file to an image, each at most `max_asset_bytes`. segl makes the folder when it starts, and a folder it cannot write in stops it with exit status 1 and one line that names the folder. Nothing removes a file from it. Back up `database` and `assets_dir` together: a scene names its images by the files in that folder.

Without `--config`, segl runs with development defaults: the values above, except `database = "var/segl.sqlite"`, `assets_dir = "var/assets"`, `display_names = "deploy/display-names.txt"`, and `web_dir = "web/dist"`, relative to the working directory. Git ignores `var/`. Without `--config`, segl also reads `segl.toml` from the working directory when that file exists, so a local file, which git ignores too, can override any of them. With `--config`, only the named file is read. Tests point `database`, `assets_dir`, and `display_names` at temporary paths and may shorten the flush interval.

`display_names` is the word file new visitors are named from (`ARCHITECTURE.md`, display names): one word of 1–10 ASCII letters on a line, with blank lines and `#` comments skipped. segl reads it once, when it starts, so a changed file takes a restart. A file that is missing, has a line that is not such a word, or has no words stops segl with exit status 1 and one line that names the file, and the line number when a line is at fault.

After the settings, segl opens `database`, before it listens. It creates the file, and its folder, when they are missing, applies the migrations the file lacks, and adds the nine slots (`DATA-MODEL.md`). A database it cannot open, or one written by a newer segl, stops it with exit status 1 and one line that names the file.

The example file ships with `edit_token = ""`. Operators who set a token restrict the file to mode `0640`, owner `root`, group `segl`.

## Process layout

| Path | Contents |
|---|---|
| `/opt/segl/python` | CPython installed by `uv python install` during package build, at the exact `runtime.python` in `versions.toml`. `.python-version` mirrors that pin. |
| `/opt/segl/venv` | Virtualenv created from `uv.lock` using that interpreter. The installed `segl` package carries a copy of `versions.toml`, which `segl --version` reads. |
| `/opt/segl/app` | Application source and `web/dist`. |
| `/opt/segl/share/nginx` | The files from `deploy/nginx/`. |
| `/opt/segl/etc/segl.toml` | Site config. |
| `/opt/segl/etc/display-names.txt` | Copy of `deploy/display-names.txt`. Sites edit this copy. |
| `/opt/segl/var` | SQLite database, asset directory, writable by user `segl`. |

The `.deb` creates system user `segl`, shell `nologin`, home `/opt/segl`. The unit runs as that user. The interpreter and virtualenv are owned by root and are not writable by `segl`.

```ini
[Service]
User=segl
Group=segl
ExecStart=/opt/segl/venv/bin/segl --config /opt/segl/etc/segl.toml
Restart=on-failure
NoNewPrivileges=true
TimeoutStopSec=20
```

`TimeoutStopSec` gives the process time to flush dirty heads on SIGTERM.

## nginx

`deploy/nginx/` holds the files a site includes. The examples mount segl at `/board/`, as in `https://dev.example.com/board/s/1`.

| File | Install as | Context | Contents |
|---|---|---|---|
| `segl-http.conf` | `/etc/nginx/conf.d/segl.conf` | `http` | The `segl` upstream (`127.0.0.1:8888`, with keepalive) and the `$segl_connection` WebSocket map. Changes nothing on its own. |
| `segl-proxy.conf` | `/etc/nginx/snippets/segl-proxy.conf` | `location` | Proxy settings: strip the location's prefix, forwarded headers, WebSocket upgrade, body limit, timeouts, and gzip. |
| `segl-board.conf` | `/etc/nginx/snippets/segl-board.conf` | `server` | The `/board` to `/board/` redirect, and `location ^~ /board/` including `segl-proxy.conf`. |
| `site-board.example.conf` | `/etc/nginx/sites-available/` | | A complete TLS site with segl at `/board/`. |
| `site-root.example.conf` | `/etc/nginx/sites-available/` | | A complete TLS site that gives segl a host name of its own. |

To add segl at `/board/` to an existing site (from a checkout, the same files are in `deploy/nginx/`):

```bash
sudo install -m 644 /opt/segl/share/nginx/segl-http.conf  /etc/nginx/conf.d/segl.conf
sudo install -m 644 /opt/segl/share/nginx/segl-proxy.conf /etc/nginx/snippets/segl-proxy.conf
sudo install -m 644 /opt/segl/share/nginx/segl-board.conf /etc/nginx/snippets/segl-board.conf
# then, inside the site's server { } block:  include snippets/segl-board.conf;
sudo nginx -t && sudo systemctl reload nginx
```

What the proxy settings do:

- `proxy_pass http://segl/;` has a trailing slash, which strips `/board`. Under `location /` it changes nothing.
- `Host $http_host` keeps the port, so segl's Origin check matches a site on a port other than 443.
- `X-Forwarded-For $remote_addr` replaces any value the client sent. segl believes it only from `trusted_proxies`, so a client cannot choose the address the display-name rate limit counts.
- `Upgrade` and `Connection $segl_connection` carry the WebSocket at `/collab`, and keep the upstream connection alive for everything else.
- `client_max_body_size 52m` sits above `max_scene_bytes` (50 MiB) and `max_asset_bytes` (10 MiB), so segl's own `payload_too_large` answers first. Raise it if you raise those.
- `proxy_read_timeout 120s` is well above segl's 20-second WebSocket ping.
- `gzip` covers CSS, JavaScript, JSON, and SVG. Ubuntu's `nginx.conf` turns gzip off.
- There is no `add_header`. One in a location would discard the server block's headers, HSTS included.
- `segl-board.conf` has commented `allow`/`deny` and `auth_basic` lines for a site that wants to narrow who reaches the slots. Neither uses cookies.

To mount segl at another path, change `/board` in the three places in `segl-board.conf`. segl needs no change. TLS certificates are the site's. The examples include Ubuntu's `snippets/snakeoil.conf` as a placeholder.

T00 checked these files with nginx 1.28.3 on 2026-11-11. `nginx -t` passed for both site examples. A run in front of a stub backend showed the prefix stripped, the port kept in `Host`, a client-sent `X-Forwarded-For` replaced, the upgrade headers passed through, a 51 MiB body accepted and a 53 MiB body refused with 413, and the server block's HSTS header kept.

The test suite repeats the check against segl itself on every run (`tests/test_mount.py`, T02). It copies these files into a temporary folder laid out like `/etc/nginx`, and runs nginx there in front of a real segl process. The copies differ from the shipped files only in the upstream port, the listening ports, and a test certificate in place of snakeoil. The tests run `nginx -t` on each site example, then check the `/board` redirect, the health and config routes under `/board/` and at a host root, the path and client address segl sees, and that no response sets a cookie.

## Dev container

`deploy/Containerfile` is based on Ubuntu 26.04 and installs uv, Node for the web build, nginx for the mount tests, and the browser Playwright needs. It does not install the production `.deb` layout. Tests run with `uv sync` and `uv run` inside the container, using the project's pinned Python. Rootful Docker, rootless Docker, or rootless Podman can build and run it (D2-015). T01 created the file with uv alone, pinned by image digest, and its build runs `uv run pytest` as the image's unprivileged `ubuntu` account. T02 added nginx and openssl, and set `SEGL_REQUIRE_NGINX=1`, so the tests through nginx fail there instead of skipping. T04 added Node, at the version in `web/.node-version` and pinned by image digest, and the build now also runs `npm ci`, the web typecheck, Vitest, Prettier, and `vite build` before pytest. T11 adds the browser, and is the first task that must pass the browser suite inside it. The host tools are in `DEVELOPMENT.md`.

## Production container

Not part of the MVP. After the gate, L-005 adds an image that runs the same `/opt/segl` layout. Do not add it in T12.

## Operator notes to ship in T12

Write `deploy/OPERATOR.md` from this page, covering: install the `.deb`, install the nginx files and add the include line, leave or set `edit_token`, replace `display-names.txt`, and restart the unit. State that slots are shared and that protected inventory is not available on them.
