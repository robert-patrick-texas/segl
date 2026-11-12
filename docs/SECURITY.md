# Security (MVP)

The network perimeter is the access boundary for reading a slot. nginx listens on the addresses the site chooses. The Python process listens on `127.0.0.1` only. Slots are shared whiteboards: anyone who can open the URL can watch live, and can edit when no edit token is configured. They are not a place for protected network inventory. That data has no tables and no routes in this phase.

## Required controls

- TLS at nginx for any shared deployment. The application generates relative URLs so it does not terminate TLS itself.
- `edit_token` compared with a constant-time compare. Wrong and missing tokens both yield a view-only connection.
- Token storage on the client is `localStorage` under the `basePath` key. A shared link uses the `#e=` fragment, which the page strips after copying it into `localStorage`.
- No `Set-Cookie` on any response. No session middleware. No credentialed CORS.
- Reject a mutating request whose `Origin` header is present and does not match its `Host` header, host and port, with `403` and `bad_origin`. nginx passes the browser's `Host` with its port (`deploy/nginx/segl-proxy.conf`). WebSocket upgrades follow the same check, and are refused in the handshake. The check is middleware in front of every route (`src/segl/origin.py`): any method but `GET`, `HEAD`, and `OPTIONS` is a mutation, on any path. A port left out is the scheme's own, 80 or 443. An origin that is not `http` or `https`, such as the `null` of a sandboxed page, matches nothing. A request without `Origin`, such as one from `curl`, is not a browser's cross-site request and passes. Reads are not checked, and segl sends no CORS header, so a page on another site cannot read an answer.
- The collaboration socket: a connection is in no room until its `hello`, and has 10 seconds to send it. A message is at most `max_scene_bytes`. The server reads `id`, `version`, `versionNonce`, and `index` of an element and relays the rest as data, and each browser's editor checks an element before it holds it. A browser that stops reading is disconnected once 1024 messages or 16 MiB wait for it. The number of connections is not limited: the network perimeter is the limit.
- Body limits: `max_asset_bytes` default 10485760, `max_scene_bytes` default 52428800. nginx allows 52 MiB, so segl's own limits answer first.
- Display-name allocation: at most 30 allocations per client address in any 60 seconds, counted in memory, so a restart forgets the count. A call counts when it is admitted, whether or not the allocation then succeeds. The call after the 30th gets `429` with `rate_limited`, takes no name, and is not counted, so a client that keeps asking is admitted again once its oldest counted call is a minute old. An address whose counted calls are all a minute old is dropped from the table at its next sweep, which runs once a minute while names are being asked for. The client address is the `X-Forwarded-For` value when the connection comes from an address in `trusted_proxies` (default `127.0.0.1` and `::1`), and the connection's own address otherwise. uvicorn applies that rule (`proxy_headers`, with `trusted_proxies` as its allowed addresses), so the access log shows the same address. nginx overwrites that header with the address it sees, so a client cannot choose it.
- Uploaded-file reads (`/api/v1/assets/{hash}`) use a SHA-256 hex name under `assets_dir`. Reject any other path shape.
- SQL parameters only. Slot numbers are integers 1–9.
- Logs may include slot, epoch, revision, status, and byte size. Logs omit the edit token, cookies, authorization headers, and scene bodies. A WebSocket's log line is its path, `/collab?slot=N`. Display names and elements are not logged.
- Secrets live in `/opt/segl/etc/segl.toml`. When a token is set, that file is mode `0640` and group `segl`. The service user cannot write the Python install or the virtualenv.
- The packaged word list is read as text. It is not executed and it is not imported as code.
- Runtime does not call a SaaS API. Fonts and the editor bundle are served by this process.
- CSV and JSON formula injection matters later, at L-002. There is no import of those formats in P0. Scene JSON is stored and returned as data, not rendered as HTML.

## Deferred with the later phases

Login, bearer tokens, protected workspaces, inventory credentials, encryption at rest, and SSO are L-004 and L-006. Do not add stub user tables or a login route in P0.

A pilot that passes these controls is still an open shared whiteboard. Operators who need to keep a diagram private either rely on network controls or set `edit_token` and treat the URL as untrusted for writes. Viewers of a token-protected slot can still see the drawing.
