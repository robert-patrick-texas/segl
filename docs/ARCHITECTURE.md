# Architecture

How the MVP processes run together. Contracts are in `API.md` and `DATA-MODEL.md`. Host paths and units are in `DEPLOY.md`.

## Processes

| Piece | Role |
|---|---|
| Browser | React application. Excalidraw is the canvas. A segl bar handles slots, title, presence, history, and the shared-workspace notice. |
| nginx | TLS termination and reverse proxy. Gives segl a host name of its own or a path on an existing site, such as `/board/`, which it strips before forwarding (`deploy/nginx/`). |
| `segl` Python process | FastAPI on `127.0.0.1`. Serves the built web assets, REST, and the WebSocket at its own root. Owns SQLite, uploaded files, and the display-name file. |
| SQLite | Head scene, revisions, name counter. One file, WAL mode. |
| Display-name file | Plain text list on disk. Sites replace the file to change future labels. |

Node runs in the build environment and in the dev container's frontend build. systemd does not start Node.

In-memory room state (who is connected, cursors, dirty heads waiting to flush) lives in the one Python process. A restart drops presence and reloads each slot from its head row.

## Mount and navigation

segl serves at its own root and has no setting for the path it is mounted under (D2-007). nginx can give it a host name of its own (`https://board.example.com/s/1`) or a path on an existing site (`https://dev.example.com/board/s/1`). In the second case nginx strips `/board` and segl sees `/s/1`. Every URL the page uses is relative to the page, so the browser stays under `/board/`. This follows Sunstone.

Routes at segl's root:

- `/` serves the app, which opens the last slot in `localStorage`, or `s/1` when none is stored.
- `/s/1` … `/s/9` are the slots. The app sends any other `/s/...` value to slot 1.
- `/api/v1/...` is HTTP.
- `/collab` is the WebSocket.
- `/assets/...`, the editor's fonts, and the favicon are the Vite build output.

Vite builds with `base: './'`, so the built `index.html` names its files `./assets/...` and code-split chunks find each other relative to themselves. Python serves `index.html` for `/` and for `/s/{n}`. A slot page is one level down, so for it Python rewrites those `./` URLs to `../`. Both pages get:

```html
<script>window.SEGL_CONFIG = { "root": "../", "editRequired": false };</script>
```

`root` is the path from this page to segl's root: `./` on `/`, `../` on `/s/N`. A later, deeper route gets the matching number of `../`. The app resolves it once, `new URL(SEGL_CONFIG.root, location.href)`, to get its root URL, such as `https://dev.example.com/board/`. Everything else comes from that URL:

- `basePath` is its path: `/board/`, or `/` at a host root. It is the React Router basename.
- API calls are `new URL("api/v1/...", root)`.
- The WebSocket is `new URL("collab?slot=N", root)` with `ws:` or `wss:` to match the page, so TLS follows the page.
- `window.EXCALIDRAW_ASSET_PATH` is the root URL, so the editor loads its fonts from segl.

`editRequired` is true when `edit_token` is non-empty. The token value is never injected. In the Vite dev server, which serves the page itself at the host root, a missing `SEGL_CONFIG` means `root` is the host root, and `editRequired` comes from `GET api/v1/config`.

segl's own redirects are relative. nginx's `/board` to `/board/` redirect is in `deploy/nginx/segl-board.conf`.

`localStorage` keys include `basePath` so two mounts on one origin stay separate:

- `segl:{basePath}:lastSlot`, such as `segl:/board/:lastSlot`
- `segl:{basePath}:displayName`
- `segl:{basePath}:editToken`
- `segl:{basePath}:clientId`

## Request path

1. The browser requests `https://dev.example.com/board/s/1`.
2. nginx terminates TLS, strips `/board`, and proxies `/s/1` to `127.0.0.1:8000`, with the client's address in `X-Forwarded-For`.
3. Python returns `index.html` with `../` asset URLs and `SEGL_CONFIG`.
4. The app stores last-slot `1`, loads the head scene from `api/v1/slots/1/scene` under its root, and mounts Excalidraw.
5. If `displayName` is missing, the app asks the server for the next label and stores it.
6. The app opens the WebSocket and sends `hello` with `clientId`, the display name, and the edit token when the browser has one.
7. The server joins the connection to the in-memory room for slot 1 and sends the current head epoch, the title, and the current participant list.
8. An edit in the canvas sends the changed elements. The server reconciles them into the room scene, broadcasts the winners, and schedules a head flush.
9. Other browsers on slot 1 apply those elements. Slot 2 is a different room and a different SQLite head.

## Collaboration

segl owns the wire protocol. The canvas adapter is the only module that imports Excalidraw.

- Element messages carry the element records the editor produces (`id`, `version`, and the deletion flag the pinned package uses).
- The server keeps the element with the greater `version`. On a tie, it keeps the greater `versionNonce` unless the pinned package exports a reconcile helper, in which case the server-side unit test and the client both follow that helper.
- Deleted elements stay in the scene as tombstones so an older copy cannot resurrect them.
- A full-scene replace happens on join (load the head) and when the epoch changes (restore or import).
- Each head has an integer `epoch`, starting at 1. Ordinary element messages must name the current epoch. A stale epoch gets the current scene back so the client can reconcile, and the stale elements are not applied.
- Restore and JSON import increment the epoch, replace the scene, append a revision, and broadcast the new scene to the room.
- A title change (`PATCH` on the slot) is broadcast to the room as a `slot` message, so every open bar shows the new title.
- Images are files, not elements. The browser that places one uploads the bytes (`POST api/v1/slots/{n}/assets`), then announces the file id and its hash in a `files` message. The server records the mapping with the head and relays it. Other browsers fetch `api/v1/assets/{hash}` and add the file to their editor, and a new load gets the mapping with the scene. T07 settles the details against the pinned editor's file model.
- Cursors and the participant list are presence. They are not written to SQLite and they are not part of the scene.
- The client shows one of: connecting, live, saving, saved, disconnected. `saved` means the head flush that includes that edit has finished.
- On reconnect the client sends any elements it still holds that the server may have missed, then applies the server reconcile result. It does not replace the server head with a blind full-scene upload.
- While the socket is down the canvas stays usable. Those edits are queued and reconciled when the socket returns.

The acknowledged-save boundary is the head flush. A crash can lose edits that were broadcast to peers but not flushed. Peers that are still open resend on reconnect. The flush interval default is 200 ms, and a flush also runs when the last client leaves the slot and on process shutdown. History rows are a coarser sample of that head (default 1 second, plus last-leave, restore, and import), capped at 50 per slot.

## Edit gate

Viewing, cursors, and receiving elements require no token.

When `edit_token` is empty, every connection may mutate the scene, the title, the history (restore), and uploaded files.

When `edit_token` is set:

- Mutations include the token from `localStorage` (HTTP header `X-Segl-Edit-Token`, and the same value inside the WebSocket `hello` / later mutation messages).
- A missing or wrong token joins as view-only. The server drops scene, title, restore, and file mutations. Presence and rename still work.
- The comparison is constant-time. Logs record the slot and the byte size, not the token and not the scene body.
- A shared link may carry the token in the URL fragment `#e=...`. The page writes it to `localStorage` and removes the fragment with `history.replaceState`. The fragment is not sent on the HTTP request.

The editor runs in its view mode when this client is view-only. The segl bar always states that the slot is a shared unauthenticated workspace. A view-only client also states that editing is locked.

## Display names

The packaged list is `draft2/display-names.txt`. T05 copies it to `deploy/display-names.txt` and the `.deb` installs it at `/opt/segl/etc/display-names.txt`. A site may replace that file. Lines that are blank or start with `#` are ignored. Every remaining line is 1–10 ASCII letters. Startup fails if the filtered list is empty.

The counter is one row in SQLite. It starts at 1 and survives restarts. Assignment is a single transaction: read `next_value`, increment it, commit, then choose `word = lines[(value - 1) % len(lines)]` and return `f"{word}{value}"`. The first three packaged assignments are `Alpha1`, `Bravo2`, `Charlie3`.

The browser calls assignment only when it has no stored label, then stores the result. A person may replace the label. The client and the server title-case a manual name: split on whitespace, uppercase the first character of each word, lowercase the rest (`john smith` becomes `John Smith`, and `NASA` becomes `Nasa`). Automatic names skip that transform so file spellings such as `McKinley` stay as written. Manual names are 1–40 characters after trimming. Duplicate manual names are allowed. The menu count is connections, so two tabs can show the same label twice.

## Data the MVP stores

SQLite holds slots, the head scene, revisions, and the name counter. The scene document is whatever the pinned editor needs in order to restore elements and embedded images, up to `max_scene_bytes`. If the editor's image model is binary files outside the scene JSON, those bytes go under `assets_dir` named by SHA-256. Either way, an image placed on the canvas is still there after a process restart and a browser reload. Details are in `DATA-MODEL.md`.

## What is intentionally absent

No second collaboration process, no Redis, no PostgreSQL, no cookie session, no user accounts, no board create/delete, no inventory tables, no base-path setting, and no route under `/{team}/{project}/{board}`. The repository interface is the seam those later stores will implement. Slot handlers do not call a protected-data function, because that function does not exist in this phase.
