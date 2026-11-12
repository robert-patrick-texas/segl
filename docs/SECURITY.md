# Security (MVP)

The network perimeter is the access boundary for reading a slot. nginx listens on the addresses the site chooses. The Python process listens on `127.0.0.1` only. Slots are shared whiteboards: anyone who can open the URL can watch live, and can edit when no edit token is configured. They are not a place for protected network inventory. That data has no tables and no routes in this phase.

## Required controls

- TLS at nginx for any shared deployment. The application generates relative URLs so it does not terminate TLS itself.
- `edit_token` compared with a constant-time compare. Wrong and missing tokens both yield a view-only connection.
- Token storage on the client is `localStorage` under the base-path key. A shared link uses the `#e=` fragment, which the page strips after copying it into `localStorage`.
- No `Set-Cookie` on any response. No session middleware. No credentialed CORS.
- Reject mutating requests whose `Origin` is present and is not this host. WebSocket upgrades follow the same origin check.
- Body limits: `max_asset_bytes` default 10485760, `max_scene_bytes` default 52428800.
- Display-name allocation: at most 30 successful or attempted allocations per minute per client address, in memory.
- Asset reads use a SHA-256 hex name under `assets_dir`. Reject any other path shape.
- SQL parameters only. Slot numbers are integers 1–9.
- Logs may include slot, epoch, revision, status, and byte size. Logs omit the edit token, cookies, authorization headers, and scene bodies.
- Secrets live in `/opt/segl/etc/segl.toml`. When a token is set, that file is mode `0640` and group `segl`. The service user cannot write the Python install or the virtualenv.
- The packaged word list is read as text. It is not executed and it is not imported as code.
- Runtime does not call a SaaS API. Fonts and the editor bundle are served by this process.
- CSV and JSON formula injection matters later, at L-002. There is no import of those formats in P0. Scene JSON is stored and returned as data, not rendered as HTML.

## Deferred with the later phases

Login, bearer tokens, protected workspaces, inventory credentials, encryption at rest, and SSO are L-004 and L-006. Do not add stub user tables or a login route in P0.

A pilot that passes these controls is still an open shared whiteboard. Operators who need to keep a diagram private either rely on network controls or set `edit_token` and treat the URL as untrusted for writes. Viewers of a token-protected slot can still see the drawing.
