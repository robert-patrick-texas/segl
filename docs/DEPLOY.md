# Deployment

## Configuration

`/opt/segl/etc/segl.toml` on the server. In development, `deploy/segl.toml.example` and a local `segl.toml` ignored by git.

```toml
base_path = "/"
bind = "127.0.0.1:8000"
edit_token = ""
database = "/opt/segl/var/segl.sqlite"
assets_dir = "/opt/segl/var/assets"
display_names = "/opt/segl/etc/display-names.txt"
max_asset_bytes = 10485760
max_scene_bytes = 52428800
history_limit = 50
history_interval_seconds = 1
head_flush_seconds = 0.2
```

`base_path` is `/` or a prefix like `/whiteboard`. The process refuses to start when `base_path` is missing a leading slash, has a trailing slash, or contains a host. Tests may point `database` and `display_names` at temporary paths and may shorten the flush interval.

The example file ships with `edit_token = ""`. Operators who set a token restrict the file to mode `0640`, owner `root`, group `segl`.

## Process layout

| Path | Contents |
|---|---|
| `/opt/segl/python` | CPython installed by `uv python install` during package build, using the minor in `versions.toml`. `.python-version` mirrors that pin. |
| `/opt/segl/venv` | Virtualenv created from `uv.lock` using that interpreter. |
| `/opt/segl/app` | Application source and `web/dist`. |
| `/opt/segl/etc/segl.toml` | Site config. |
| `/opt/segl/etc/display-names.txt` | Copy of `draft2/display-names.txt`. Sites edit this copy. |
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

Proxy the URI unchanged so a prefix in the location is still present when Python sees it. `base_path` in TOML equals that prefix.

Host-root site (`base_path = "/"`):

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
}
```

Prefixed site (`base_path = "/whiteboard"`):

```nginx
location /whiteboard/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
}
```

Both site files include this map in the `http` block:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

The prefixed site also contains `location = /whiteboard { return 301 /whiteboard/; }` so a visit without the trailing slash reaches the app. TLS certificates are the site's; the examples use the host's existing certificate directives rather than inventing a CA.

## Dev container

`deploy/Containerfile` is based on Ubuntu 26.04 and installs uv, plus Node for the web build, plus the browser Playwright needs. It does not install the production `.deb` layout. Tests run with `uv sync` and `uv run` inside the container, using the project's pinned Python. Either rootless Podman or Docker can build it. T01 creates the file; T11 is the first task that must pass the full browser suite inside it.

## Production container

Not part of the MVP. After the gate, L-005 adds an image that runs the same `/opt/segl` layout. Do not add it in T12.

## Operator notes to ship in T12

Write `deploy/OPERATOR.md` from this page, covering: install the `.deb`, set `base_path`, leave or set `edit_token`, replace `display-names.txt`, restart the unit, and the two nginx examples. State that slots are shared and that protected inventory is not available on them.
