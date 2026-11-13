# Security (MVP)

The network perimeter is the access boundary for reading a slot. nginx listens on the addresses the site chooses. The Python process listens on `127.0.0.1` only. Slots are shared whiteboards: anyone who can open the URL can watch live, and can edit when no access codes are set. They are not a place for protected network inventory. That data has no tables and no routes in this phase.

This MVP is for an internal network. Do not put it on the open internet except as a prototype or a demo with no real-world data. Nobody is authenticated in this phase: access codes (D2-033) keep honest people from changing a board by mistake, and they do not tell one person from another.

## Required controls

- TLS at nginx for any shared deployment. The application generates relative URLs so it does not terminate TLS itself.
- Access codes, when the site sets them (S-008, D2-033). A code is a word or a phrase with at least 8 ASCII letters and digits, compared in a normal form, in constant time, against every code in the list. A wrong code and a missing pass both leave a view-only browser. segl does not start with a shorter code, with one code twice, or with codes and no `access_secret`, and its message gives an entry's place in the list and never its text (`DEPLOY.md`).
- A right code buys a pass: the second of its issue, and an HMAC-SHA-256 over that second and the code under `access_secret`, cut to 18 bytes. The pass holds neither the code nor the secret, and the secret is what keeps a pass from being a way to test guesses at the code offline. That is why `access_secret` has at least 32 characters. The server keeps no list of passes, and takes one by its signature, its age, and the two times the site may set (`ARCHITECTURE.md`, edit gate).
- What ends a pass: `access_pass_hours` after its issue, 12 by default. A code taken out of the list, which ends the passes it bought. A new `access_passes_after`, which ends every pass issued before it. A new `access_secret`, which ends them all. Each takes a restart. Nothing takes one pass back by itself.
- Wrong codes are counted per client address, in memory, so a restart forgets the count. After five in a row, every code from that address, the right one too, gets `429` with `rate_limited` for fifteen minutes from the last wrong one, before its body is read. A right code starts the count again, and so does fifteen minutes without a wrong one. The address is the one the display-name limit counts by (below). An address that starts to wait is logged, once, without what it sent. Behind one proxy address, or one NAT, people share a count: five wrong codes from any of them keep all of them waiting.
- A code travels in the body of `POST api/v1/access`. A pass travels in the `X-Segl-Edit-Token` header and in the socket's `hello`. Neither is in a URL the browser asks for, so neither is in an access log, of segl or of nginx, or in a `Referer`. Nothing hands a pass from one browser to another: an earlier build's link with a token in its fragment is gone, and the page reads no fragment.
- Pass storage on the client is `localStorage` under the `basePath` key. A script that runs in segl's origin could read it there, which is one reason an uploaded file is never served as a page (below). Anyone who can use the browser's profile can use its pass until it ends. A page sends in the header only what a header carries whole, 1 to 256 printable ASCII characters with no space at either end, which a pass is: a browser cannot send another character in a header at all.
- This is not authentication. A pass says that someone knew a code, and a code is shared. The name on an edit is still the display name a browser chose.
- `internal_networks`, when the site sets it (S-018). A request or a WebSocket handshake from an address outside those networks is `403` with `outside_network`, before the Origin check and before any route: the pages and the health route among them. Loopback is always inside, and an IPv4 address written as IPv6 is read as IPv4. Text that is not an address is outside. The address is the one segl believes (below): through a proxy that is not in `trusted_proxies`, every client has the proxy's address, and is inside or outside as the proxy is. A firewall, or nginx's `allow` and `deny`, can do the same. This is the second check, and it is no replacement for the first: segl still listens on loopback only.
- The page stops taking edits a second before its pass ends, from the length `welcome` gave it. That is for the person, so that nothing is drawn which only they would see. It is not the gate: the server refuses an edit after the end whatever a page does.
- The view mode of the page is not the gate. The server refuses a viewer's elements, title, restore, import, and upload whatever the page does. The page keeps a viewer's own canvas from changing: the editor's view mode, and a drop on the canvas that the canvas adapter stops, because the editor's drop handler ignores view mode (`ARCHITECTURE.md`, edit gate).
- No `Set-Cookie` on any response. No session middleware. No credentialed CORS.
- Reject a mutating request whose `Origin` header is present and does not match its `Host` header, host and port, with `403` and `bad_origin`. nginx passes the browser's `Host` with its port (`deploy/nginx/segl-proxy.conf`). WebSocket upgrades follow the same check, and are refused in the handshake. The check is middleware in front of every route (`src/segl/origin.py`): any method but `GET`, `HEAD`, and `OPTIONS` is a mutation, on any path. A port left out is the scheme's own, 80 or 443. An origin that is not `http` or `https`, such as the `null` of a sandboxed page, matches nothing. A request without `Origin`, such as one from `curl`, is not a browser's cross-site request and passes. Reads are not checked, and segl sends no CORS header, so a page on another site cannot read an answer.
- The collaboration socket: a connection is in no room until its `hello`, and has 10 seconds to send it. A message is at most `max_scene_bytes`. The server reads `id`, `version`, `versionNonce`, and `index` of an element and relays the rest as data, and each browser's editor checks an element before it holds it. A message it could not write back as JSON is refused whole: `NaN`, `Infinity`, and a number too large to hold, such as `1e999`, which would otherwise be stored and leave the slot's scene unreadable to every browser. A browser that stops reading is disconnected once 1024 messages or 16 MiB wait for it. The number of connections is not limited: the network perimeter is the limit.
- Body limits: `max_asset_bytes` default 10485760, `max_scene_bytes` default 52428800. nginx allows 52 MiB, so segl's own limits answer first.
- Display-name allocation: at most 30 allocations per client address in any 60 seconds, counted in memory, so a restart forgets the count. A call counts when it is admitted, whether or not the allocation then succeeds. The call after the 30th gets `429` with `rate_limited`, takes no name, and is not counted, so a client that keeps asking is admitted again once its oldest counted call is a minute old. An address whose counted calls are all a minute old is dropped from the table at its next sweep, which runs once a minute while names are being asked for. The client address is the `X-Forwarded-For` value when the connection comes from an address in `trusted_proxies` (default `127.0.0.1` and `::1`), and the connection's own address otherwise. uvicorn applies that rule (`proxy_headers`, with `trusted_proxies` as its allowed addresses), so the access log shows the same address. nginx overwrites that header with the address it sees, so a client cannot choose it.
- Uploaded files (D2-028). An upload is a mutation: it needs a pass when codes are set, and passes the Origin check. Its `Content-Type` must be one of the editor's nine image types, and its body at most `max_asset_bytes`. segl does not look inside the bytes, so a file is whatever a browser sent. It is therefore served as `application/octet-stream` with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'; sandbox`, and never under an image or page type: an uploaded SVG with a script in it, opened by its URL, is a download that runs nothing and cannot read the pass in `localStorage`. The page fetches the bytes, builds a `data:` URL, and the editor shows it in an image element, where a script does not run.
- Uploaded-file reads (`/api/v1/assets/{hash}`) use a SHA-256 hex name under `assets_dir`. A name that is not 64 lowercase hex digits is a `404` before any path is built, so no text a browser sends is joined to the folder. Reading needs no pass, as viewing a slot needs none. No route lists, replaces, or deletes a file.
- A `files` message, which says that a file id means some uploaded bytes, is refused unless segl has those bytes, and a file id keeps the bytes it was first given. So nobody can point an image that is already on a slot at other bytes.
- The number of uploads is not limited, and nothing removes a file once no scene names it. A slot's elements are limited to `max_scene_bytes` together (`scene_too_large`). The network perimeter and the access codes are the limit on who can fill the disk.
- The history. Anyone who can open the URL can read a slot's revisions, as anyone can view the slot: the latest `history_limit` scenes (50), which include what has since been deleted from the canvas. Deleting something does not take it out of the history, and nothing but newer revisions pushes a revision out. A restore is a mutation: it needs a pass when codes are set, and passes the Origin check. The name on a revision is the display name a browser sent, which nobody has verified, as with every label in this phase.
- JSON import (D2-031). An import is a mutation: it needs a pass when codes are set, checked before the body is read, and passes the Origin check. Its body is at most `max_scene_bytes`. The document is data from a browser, and is read strictly. segl keeps its elements, of which it reads `id`, `version`, `versionNonce`, `index`, and `fileId`, and the files those elements name. It reads nothing else in it. A file's bytes are taken out of the document and stored and served as an upload's are, under the same types and the same size limit, so an SVG inside an imported file is no more a page of this site than an uploaded one. A file id the slot already has keeps its bytes. A number JSON cannot write, such as `1e999`, refuses the document: the server would otherwise hand every browser a scene it could not parse. A refusal's message says where the document is wrong and repeats nothing from it. The name on the import's revision comes from the `X-Segl-Display-Name` header, and is as unverified as every label. The editor's own way to open a file is off (`ARCHITECTURE.md`, export and import), so that a file cannot reach the shared scene past the gate's one question.
- SQL parameters only. Slot numbers are integers 1–9. A revision number in a path is 1 to 16 digits, and in a restore's body a whole number in the same range, before it reaches a query.
- Logs may include slot, epoch, revision, status, and byte size. Logs omit access codes, the secret, passes, cookies, authorization headers, and scene bodies. An address that has to wait after five wrong codes is logged, with nothing of what it sent. A WebSocket's log line is its path, `/collab?slot=N`. Display names and elements are not logged. A head flush that fails is logged with the slot's number and the database's error. An upload's log line is its path, and a read's has the hash. An import's log line is its path: not the file's name, its elements, or who imported.
- Secrets live in `/opt/segl/etc/segl.toml`: the access codes and `access_secret`. When they are set, that file is mode `0640` and group `segl`. The service user cannot write the Python install or the virtualenv.
- The packaged word list is read as text. It is not executed and it is not imported as code.
- Runtime does not call a SaaS API. Fonts and the editor bundle are served by this process.
- CSV and JSON formula injection matters later, at L-002. There is no inventory import in P0. Scene JSON, drawn or imported, is stored and returned as data, not rendered as HTML.

## Hardening nginx

TLS, the ports that answer, and the headers a browser is sent with every page are nginx's, outside the application. They are in the hands of the site's server administrators and the site's policy. segl listens on loopback, speaks plain HTTP to nginx, and depends on none of what follows. The packaged site examples, `deploy/nginx/site-board.example.conf` and `site-root.example.conf`, carry a strong configuration to start from:

```nginx
# Plain HTTP only sends the browser on to HTTPS.
server {
    listen 80;
    listen [::]:80;
    server_name dev.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name dev.example.com;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:segl_tls:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    server_tokens off;

    add_header Strict-Transport-Security "max-age=31536000" always;
    proxy_hide_header X-Content-Type-Options;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "same-origin" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    include snippets/segl-board.conf;
}
```

- **Ports.** Whether the site answers on port 80 at all, and on which port it serves HTTPS, is the site's choice. The example answers plain HTTP only to send the browser on to HTTPS. A site that wants nothing on port 80 removes that block.
- **HSTS.** `Strict-Transport-Security` tells a browser that has been to the site once to ask for HTTPS only, for a year. It is also what stands behind segl's Origin check. The check compares the host and the port and not the scheme, so it takes a page served over plain http under the site's own name for the site's page. A browser that has been to the site once does not load such a page while the header's year lasts. Add `includeSubDomains` when every name under the site's is served over HTTPS.
- **TLS.** TLS 1.2 and 1.3 only. Under 1.2, only ciphers with forward secrecy and authenticated encryption. No session tickets, whose key nginx would keep until it restarts. A site with a TLS policy of its own puts that in place of these lines.
- **Headers.** `nosniff` holds a file to the type the server gave it. segl sends that header itself with an uploaded file, so `proxy_hide_header` drops segl's copy and the browser gets the site's, once. `Referrer-Policy: same-origin` tells no other site which page a link was followed from. `X-Frame-Options: SAMEORIGIN` keeps another site from showing segl's pages in a frame of its own: remove it to embed a board in another site's page. `server_tokens off` leaves the nginx version out of its answers. They are set in the server block, with `always`, so nginx's own error pages carry them too. `segl-proxy.conf` adds no header, because one in a location would discard all of these.
- **Who can reach it.** `segl-board.conf` has commented lines for `allow` and `deny` by network, and for a password. A firewall in front of nginx does the same. `internal_networks` in segl itself is a second check behind both (D2-033, S-018).
- **Not in the example.** A `Content-Security-Policy` is not set. None has been tried against the embedded editor, and one that is too tight would break it. OCSP stapling and the certificate are the site's.

`tests/test_mount.py` runs nginx with these files and holds them to what this section says: the four headers on what segl answers and on what nginx answers itself, no nginx version, a refusal of a cipher outside the list, no session ticket, and both TLS versions.

## Deferred with the later phases

Login, bearer tokens, protected workspaces, inventory credentials, encryption at rest, and SSO are L-004 and L-006. Do not add stub user tables or a login route in P0. The access page is not a login: it takes a code, knows no user, and keeps no account (D2-033). Real user authentication follows later, with RADIUS as one option and SAML or other methods after it.

A pilot that passes these controls is still an open shared whiteboard. Operators who need to keep a diagram private rely on network controls, with `internal_networks` as a second check. Access codes limit who changes a slot, not who sees it: viewers of a slot that asks for a code can still see the drawing.
