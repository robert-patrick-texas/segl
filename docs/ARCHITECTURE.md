# Architecture

How the MVP processes run together. Contracts are in `API.md` and `DATA-MODEL.md`. Host paths and units are in `DEPLOY.md`.

## Processes

| Piece | Role |
|---|---|
| Browser | React application. Excalidraw is the canvas. A segl bar handles slots, title, presence, history, and the shared-workspace notice. |
| nginx | TLS termination and reverse proxy. Gives segl a host name of its own or a path on an existing site, such as `/board/`, which it strips before forwarding (`deploy/nginx/`). |
| `segl` Python process | FastAPI on `127.0.0.1`. Serves the built web assets, REST, and the WebSocket at its own root. Owns SQLite, uploaded files, and the display-name file. |
| SQLite | Head scene, revisions, each slot's file list, name counter. One file, WAL mode. |
| Uploaded files | The bytes of the images on the canvases, one file to a SHA-256 under `assets_dir`. |
| Display-name file | Plain text list on disk. Sites replace the file to change future labels. |

Node runs in the build environment and in the dev container's frontend build. systemd does not start Node.

In-memory room state (who is connected, cursors, the scene as edited, dirty heads waiting to flush) lives in the one Python process. A stop writes every dirty head first. A restart drops presence and reloads each slot from its head row.

## Mount and navigation

segl serves at its own root and has no setting for the path it is mounted under (D2-007). nginx can give it a host name of its own (`https://board.example.com/s/1`) or a path on an existing site (`https://dev.example.com/board/s/1`). In the second case nginx strips `/board` and segl sees `/s/1`. Every URL the page uses is relative to the page, so the browser stays under `/board/`. This follows Sunstone.

Routes at segl's root:

- `/` serves the app, which opens the last slot in `localStorage`, or `s/1` when none is stored.
- `/s/1` … `/s/9` are the slots. The app sends any other `/s/...` value to slot 1.
- `/api/v1/...` is HTTP.
- `/collab` is the WebSocket.
- `/assets/...`, `/fonts/...` (the editor's canvas fonts), and `/favicon.svg` are the Vite build output.

Python reads the build from `web_dir` (`DEPLOY.md`) when it starts: `web/dist` in a checkout. Vite builds with `base: './'`, so the built `index.html` names its files `./assets/...` and code-split chunks find each other relative to themselves. Python serves `index.html` for `/` and for `/s/{n}`. A slot page is one level down, so for it Python rewrites those `./` URLs to `../`. Any one segment after `/s/` gets the slot page, and so does `/s/` itself, because sending a wrong slot to slot 1 is the app's job. `/s` gets the root page. Pages are sent with `Cache-Control: no-cache`, since they name the other files by content hash. After the page routes, Python registers only the folders and files the build holds, so a build cannot shadow `/api`, `/s`, or `/collab`. Without a build, segl serves the API alone and says so when it starts.

Both pages get, at the end of `<head>`:

```html
<script>window.SEGL_CONFIG = { "root": "../", "editRequired": false };</script>
```

`root` is the path from this page to segl's root: `./` on `/`, `../` on `/s/N`. A later, deeper route gets the matching number of `../`. The app resolves it once, `new URL(SEGL_CONFIG.root, location.href)`, to get its root URL, such as `https://dev.example.com/board/`. Everything else comes from that URL:

- `basePath` is its path: `/board/`, or `/` at a host root. It is the React Router basename.
- API calls are `new URL("api/v1/...", root)`.
- The WebSocket is `new URL("collab?slot=N", root)` with `ws:` or `wss:` to match the page, so TLS follows the page.
- `window.EXCALIDRAW_ASSET_PATH` is the root URL, so the editor loads its fonts from `fonts/` under segl's root and not from a public CDN (D2-026).

`editRequired` is true when `edit_token` is non-empty. The token value is never injected. In the Vite dev server, which serves the page itself at the host root, a missing `SEGL_CONFIG` means `root` is the host root, and `editRequired` comes from `GET api/v1/config`.

segl's own redirects are relative. It sends none today: the framework's trailing-slash redirect is absolute and is turned off, so `/api/v1/health/` is a `404`. nginx's `/board` to `/board/` redirect is in `deploy/nginx/segl-board.conf`, and is relative too.

`localStorage` keys include `basePath` so two mounts on one origin stay separate:

- `segl:{basePath}:lastSlot`, such as `segl:/board/:lastSlot`
- `segl:{basePath}:displayName`
- `segl:{basePath}:editToken`
- `segl:{basePath}:clientId`

## Request path

1. The browser requests `https://dev.example.com/board/s/1`.
2. nginx terminates TLS, strips `/board`, and proxies `/s/1` to `127.0.0.1:8888`, with the client's address in `X-Forwarded-For`.
3. Python returns `index.html` with `../` asset URLs and `SEGL_CONFIG`.
4. The app stores last-slot `1`, loads the head scene from `api/v1/slots/1/scene` under its root, and mounts Excalidraw. The scene comes with its file list, and the app fetches the file of each image from `api/v1/assets/{hash}`.
5. If `displayName` is missing, the app asks the server for the next label (`POST api/v1/display-name`) and stores it.
6. Once the canvas is mounted with that scene, the app opens the WebSocket and sends `hello` with `clientId`, the display name, and the edit token when the browser has one.
7. The server joins the connection to the in-memory room for slot 1 and sends `welcome`, with the epoch, the title, and the participant list, and then `scene`, the room's elements. The app merges them into the canvas.
8. An edit in the canvas sends the changed elements, with a number. The server reconciles them into the room scene, broadcasts the winners, and writes the head within `head_flush_seconds`. It then answers `saved` with that number, and the bar goes from `Saving…` to `Saved`.
9. Other browsers on slot 1 apply those elements. Slot 2 is a different room and a different SQLite head.

## Collaboration

segl owns the wire protocol (`API.md`, WebSocket). The canvas adapter, `web/src/canvas/`, is the only module that imports Excalidraw.

The server side is five modules. `src/segl/reconcile.py` is the rule for which copy of an element is kept. `src/segl/room.py` is one slot's room: its connections and its scene, with no I/O. `src/segl/collab.py` is the socket around a room. `src/segl/saver.py` writes a room's scene to its head (`DATA-MODEL.md`, flush rules), and puts a restored scene in the room's place. `src/segl/assets.py` is the store of uploaded files. A room is made from the slot's head and file list the first time someone opens the slot, and stays for the life of the process. Everything a room does runs on the event loop. The repository and the file store block, and are called from worker threads: a flush turns the scene into JSON there too, from a list of elements that nothing changes afterwards.

- Element messages carry the element records the editor produces (`id`, `version`, `versionNonce`, and `isDeleted`, the deletion flag the pinned package uses). The server reads those fields and `index`, and stores and sends the rest as it arrived.
- The server keeps the element with the greater `version`. On a tie, it keeps the lower `versionNonce`. That is the rule of `reconcileElements`, the helper the pinned package exports, which the client calls (D2-025). One table of cases, `tests/reconcile_cases.json`, holds the server's rule (pytest), the editor's helper (a browser test), and the client's own rule for what to send (Vitest) to the same answers.
- The editor's helper also keeps this browser's copy of an element it is editing, resizing, or creating, whatever arrives. Only the client can know that.
- Deleted elements stay in the scene as tombstones so an older copy cannot resurrect them. A deletion made at the same moment as another edit is settled by the same rule as any two edits.
- The scene is ordered by each element's fractional `index`, as text, and then by `id`, which is the editor's order.
- A full-scene replace happens when the epoch changes (restore or import). On join the client is sent the room's scene and merges it into the canvas, which holds the head it loaded over HTTP.
- Each head has an integer `epoch`, starting at 1. Ordinary element messages must name the current epoch. A stale epoch gets the current scene back, which the client puts in place of its own, and the stale elements are not applied.
- A restore (`POST api/v1/slots/{n}/restore`) puts one of the slot's revisions in place of its scene (D2-030). The slot's saver does it, under the lock its head flushes take, so a flush and a restore never cross: the slot is written by one of them at a time, and no flush names an epoch the slot has left. In order: the room's scene is written to the head and kept as a revision, so that the restore can be undone. The revision's scene becomes the head at the next epoch, with a revision of its own. The room takes that scene and that epoch, and every connection is sent `scene`. The revision is read before anything is written, because keeping the scene that is going may drop the oldest revision, which may be the one being restored. JSON import (T09) follows the same steps.
- A browser puts a `scene` of another epoch in place of its canvas, empties its undo history, and stops waiting for `saved`. What it drew for the old scene and had not sent goes with it. An `elements` message that names the old epoch is answered with the scene and is not applied. A browser that was away over a restore learns the new epoch when it reconnects, and replaces its canvas the same way. An edit that reaches the server during the few milliseconds a restore is being written is dropped with the scene it was made on.
- A title change (`PATCH` on the slot) is broadcast to the room as a `slot` message, so every open bar shows the new title. Two changes at once are stored and sent in one order.
- Images are files, not elements (D2-028). The editor keeps an image's bytes under a file id of its own, which the image element names. The element goes to the room as soon as it is placed, like any element. The browser that placed it uploads the bytes (`POST api/v1/slots/{n}/assets`), then says which hash that file id means in a `files` message. The server checks that it has those bytes, keeps the pair in the slot's file list, writes it with the next head flush, and tells the other connections. Each of them fetches `api/v1/assets/{hash}` and hands the file to its editor, which until then draws a placeholder. A new load gets the file list with the scene, over HTTP and again in `scene`. The browser side is `web/src/collab/files.ts`: whatever the canvas holds that the list lacks is uploaded, and whatever the list names that the canvas lacks is fetched, each once, and again after five seconds when a transfer fails. A file uploaded while the socket was down is named when the scene is back.
- Cursors and the participant list are presence. They are not written to SQLite and they are not part of the scene. The editor draws each cursor, with its label, in a color it derives from the connection id, so the protocol carries no color. The editor's own row of avatars is hidden, because pressing one follows that person's view, which segl does not carry.
- The client shows one of: connecting, live, saving, saved, disconnected. It is live once `welcome` arrives. It numbers each `elements` and `files` message it sends, and the server answers `saved` with the number of the newest one that is in the head on its disk (D2-029). The bar says `Saving…` from the moment the canvas holds an edit the server has not seen, before the edit is even sent, until that answer covers everything sent, the file of a placed image included. Then it says `Saved`, until the next edit. A viewer is never saving. After a reconnect, a browser that never heard `saved` for something it sent asks again, with an empty numbered batch.
- The client keeps no queue of edits. It keeps the copy of each element the server is known to hold, and whatever the canvas holds that beats that copy is what it sends, at most once every 30 ms. Cursor messages go at most once every 50 ms.
- While the socket is down the canvas stays usable, and the client tries again after 0.5, 1, 2, and then every 5 seconds. On reconnect it says `hello` again, merges the scene it is sent, and sends the elements it holds that beat the server's copies: the edits made while it was down. It does not replace the server head with a blind full-scene upload, and an element the server holds a newer copy of is not sent.
- A broadcast never waits for a slow browser. Each connection has an outbox, and a browser that stops reading is disconnected (`API.md`, limits).

A room's scene is in memory, and its head on the disk follows it. `GET api/v1/slots/{n}/scene` returns the head, and a browser that loads it then joins the room and is sent what the room holds, which may be one flush interval newer.

The acknowledged-save boundary is the head flush. A crash can lose edits that were broadcast to peers but not flushed. Peers that are still open resend on reconnect. The flush interval default is 200 ms, and a flush also runs when the last client leaves the slot and on process shutdown. History rows are a coarser sample of that head (default 1 second, plus last-leave, shutdown, restore, and import), capped at 50 per slot. A stored head keeps its deleted elements, so a browser that was away across a restart cannot bring one back.

The appearance of the canvas that the editor keeps outside the elements, such as the background color and the grid, is not shared live. Upstream's own collaboration does not share it either.

## History

The server keeps the latest `history_limit` revisions of each slot (`DATA-MODEL.md`, flush and revision rules). The bar's History control lists them, newest first: when each was made, the display name behind it, and a `restore` mark on a row that a restore wrote. The mark is worked out in the browser: a restore writes the first revision of a new epoch, so a row whose epoch is higher than that of the row under it is one.

The control reads `api/v1/slots/{n}/revisions` each time it is opened, after a restore of its own, and when the epoch of the canvas moves, which is how a list open in another browser follows a restore. It is not live otherwise: a row made while the list is open shows at the next opening.

Restore takes two presses, because it replaces the canvas of everyone on the slot. The page sends the revision's number and this browser's display name, and changes nothing itself: the restored scene arrives on the socket, as it does in every other browser. The buttons wait while the page is not in the slot's room, where it would not see the result. A view-only browser sees the list without them.

`web/src/history.ts` is the rows and their words. `web/src/bar/HistoryControl.tsx` is the control. `web/src/bar/inView.ts` keeps the list inside the page: it hangs from its button, and moves left where the button is too far right for that, on a narrow screen or after a long title.

## Edit gate

Viewing, cursors, and receiving elements require no token.

When `edit_token` is empty, every connection may mutate the scene, the title, the history (restore), and uploaded files.

When `edit_token` is set:

- Mutations include the token from `localStorage`: the HTTP header `X-Segl-Edit-Token`, and the same value in the WebSocket `hello`, which settles the connection as an editor or a viewer until it closes.
- A missing or wrong token joins as view-only. The server drops scene, title, restore, and file mutations: `elements` gets an `error` with `view_only`, and a `PATCH`, a restore, or an upload gets `403` with `view_only`. Presence and rename still work, and so does reading the history.
- The comparison is constant-time. Logs record the slot and the byte size, not the token and not the scene body.
- A shared link may carry the token in the URL fragment `#e=...`. The page writes it to `localStorage` and removes the fragment with `history.replaceState`. The fragment is not sent on the HTTP request.

The editor runs in its view mode when this client is view-only, the title in the bar is text, not a button, and the history list has no restore buttons. The server says which in `welcome`. Until it has, a browser may edit unless a token is configured. The segl bar always states that the slot is a shared unauthenticated workspace. A view-only client also states that editing is locked. T10 adds the `#e=` link and the browser test of this flow.

## Display names

The packaged list is `deploy/display-names.txt`, copied in T05 from `draft2/display-names.txt`. The `.deb` installs it at `/opt/segl/etc/display-names.txt`. A site may replace that file. Lines that are blank or start with `#` are ignored, and so are spaces around a word. Every remaining line is 1–10 ASCII letters. segl reads the file once, when it starts, so a changed file takes a restart. Startup fails, with exit status 1 and a message that names the file, if the file is missing, has a line that is not such a word, or has no words left.

The counter is one row in SQLite. It starts at 1 and survives restarts. Assignment is a single transaction: read `next_value`, increment it, commit, then choose `word = lines[(value - 1) % len(lines)]` and return `f"{word}{value}"`. The first three packaged assignments are `Alpha1`, `Bravo2`, `Charlie3`.

The browser calls assignment (`POST api/v1/display-name`) only when it has no stored label, then stores the result under `segl:{basePath}:displayName`. A reload, another slot, and another tab of the same browser all show the stored label and do not ask again. One client address is given at most 30 names a minute (`SECURITY.md`). A browser that is refused, or cannot reach the server, shows `Set your name` in place of a label, stays usable, and asks again later: after the `Retry-After` time of a refusal, and otherwise after half a minute.

A person may replace the label: the label in the segl bar is a button that opens a field. Enter, or leaving the field, keeps the new name. Escape keeps the old one. The client and the server title-case a manual name: split on whitespace, join the words with one space, uppercase the first character of each word, lowercase the rest (`john smith` becomes `John Smith`, and `NASA` becomes `Nasa`). Where the uppercase of that first character is more than one character, only the first of them stays uppercase (`ßeta` becomes `Sseta`), so title-casing a name twice gives the same name. Automatic names skip that transform so file spellings such as `McKinley` stay as written, and a field that is closed without a change renames nothing. Manual names are 1–40 characters after that transform. One that is not is refused, and the field says so. Duplicate manual names are allowed. The menu count is connections, so two tabs can show the same label twice.

The label reaches the other browsers on the socket. `hello` carries the stored label, which the server takes as written, so a name from the word file keeps its spelling. A name the person types afterwards goes as `rename`, from the tab it was typed in and from every other tab of that browser, which hear of it through `localStorage`. The server title-cases it again and sends it to everyone on the slot. A browser that had no label when its socket opened says `hello` again, on a new socket, once the server has assigned one, because `rename` would title-case it. The socket never allocates a name. The two implementations of the title case, `src/segl/names.py` and `web/src/names.ts`, are held to one table of cases, `tests/display_name_cases.json`.

## Data the MVP stores

SQLite holds slots, the head scene, revisions, each slot's file list, and the name counter. The scene document is the editor's own, with every element, up to `max_scene_bytes` of elements. The editor's image model is binary files outside the scene JSON, so those bytes go under `assets_dir` named by SHA-256, each at most `max_asset_bytes`. An image placed on the canvas is still there after a process restart and a browser reload. Details are in `DATA-MODEL.md`.

## What is intentionally absent

No second collaboration process, no Redis, no PostgreSQL, no cookie session, no user accounts, no board create/delete, no inventory tables, no base-path setting, and no route under `/{team}/{project}/{board}`. The repository interface is the seam those later stores will implement. Slot handlers do not call a protected-data function, because that function does not exist in this phase.
