# HTTP and WebSocket (MVP)

Paths below are relative to segl's root. A proxy that mounts segl under a path, such as `/board/`, strips that path first (`ARCHITECTURE.md`, mount and navigation). The service binds `127.0.0.1`. Errors are JSON: `{ "error": "<code>", "message": "<human text>" }`. Clients branch on `error`. The message is for a person and may change.

Mutation routes need a pass when `access_codes` has one or more codes (S-008, D2-033). A browser is issued a pass by `POST /api/v1/access`, for an access code, and sends it in the `X-Segl-Edit-Token` header. The header's name is from an earlier build, in which it carried a token. A call without a pass the server takes gets `403` and `error: view_only`. With no codes, the header is ignored and the write is allowed.

With `internal_networks` set, a request or a WebSocket handshake from an address outside those networks gets `403` and `error: outside_network`, whatever its path and before anything else is looked at (`SECURITY.md`, S-018).

A mutation, or a WebSocket upgrade, whose `Origin` header is present and does not match the request's `Host` (host and port) gets `403` and `error: bad_origin` (`SECURITY.md`). A mutation is a request with any method but `GET`, `HEAD`, and `OPTIONS`, whatever its path. A request without `Origin` is not checked.

## HTTP

| Method | Path | Function |
|---|---|---|
| GET | `/api/v1/health` | `{ "status": "ok" }` |
| GET | `/api/v1/version` | `{ "version" }`, the release that is serving, as `segl --version` prints it. `segl update` waits for the new version here after it starts segl. |
| GET | `/api/v1/config` | `{ "editRequired" }`, true when `access_codes` has a code. Same fact as the injected script. No pass, and no code is ever in the response. |
| POST | `/api/v1/access` | Body `{ "code" }`, a JSON object of at most 4096 bytes. Issues a pass for an access code and returns `{ "pass", "expiresAt" }`. No pass is needed to call it. A wrong code is `403` with `wrong_code`. After five wrong codes in a row from one client address, every code from it gets `429` with `rate_limited` for fifteen minutes. |
| GET | `/api/v1/slots` | `{ "slots": [ ... ] }` with nine entries in number order: number, title, epoch, savedAt. |
| GET | `/api/v1/slots/{n}` | One slot's metadata, the same object as its entry in the list. |
| PATCH | `/api/v1/slots/{n}` | Body `{ "title" }`, a JSON object of at most 4096 bytes. The title is trimmed, and is 1–80 characters on one line. Returns the slot's metadata with the title as stored. A pass when codes are set. Sends a `slot` message to the slot's room. |
| GET | `/api/v1/slots/{n}/scene` | Head scene, epoch, savedAt, editorLabel, and the head's file list (`id`, `hash`, `mimeType`): the files its images name. |
| GET | `/api/v1/slots/{n}/revisions` | `{ "revisions": [ ... ] }`, the slot's history, newest first, at most `history_limit` entries (50): revision, epoch, authorLabel, createdAt. Scene bodies stay on the single-revision route. No pass. |
| GET | `/api/v1/slots/{n}/revisions/{revision}` | One revision: the same four fields, its stored scene, and the scene's file list. No pass. |
| POST | `/api/v1/slots/{n}/restore` | Body `{ "revision", "displayName" }`, a JSON object of at most 4096 bytes. Records the scene being replaced, puts the revision's scene in the head at the next epoch, appends a revision for it, and sends `scene` to the slot's room. Returns `{ "revision", "epoch", "savedAt" }`. A pass when codes are set. |
| POST | `/api/v1/slots/{n}/import` | The body is an Excalidraw scene document, the file the editor's export writes, of at most `max_scene_bytes`. Records the scene being replaced, puts the document's elements in the head at the next epoch, with the files of its images, appends a revision for it, and sends `scene` to the slot's room. Returns `{ "revision", "epoch", "savedAt" }`. A pass when codes are set. |
| POST | `/api/v1/display-name` | Allocates the next `WordN` and returns `{ "displayName" }`. No body and no pass. At most 30 names per minute per client address (`SECURITY.md`). The next call gets `429` with `rate_limited` and a `Retry-After` header. |

Paths are exact. A trailing slash, as in `/api/v1/health/`, is a `404` and is not redirected.

`{n}` is one digit, `1` to `9`. Anything else in its place, such as `0`, `10`, `01`, or `abc`, returns `404` with `invalid_slot`. The app sends those URLs to slot 1 before calling the API.

Errors that no route names:

| Status | `error` | When |
|---|---|---|
| 400 | `bad_request` | The body of a mutation is not a JSON object. |
| 403 | `bad_origin` | A mutation, or a WebSocket handshake, with an `Origin` that does not match `Host`. Nothing was changed. |
| 403 | `outside_network` | Any request, or a WebSocket handshake, from an address outside `internal_networks`, when that is set. Nothing else was looked at. |
| 403 | `view_only` | A mutation without a pass, or with one the server does not take, when `access_codes` has a code. |
| 403 | `wrong_code` | `POST /api/v1/access` with text that is not one of the access codes. |
| 404 | `no_access_codes` | `POST /api/v1/access` on a segl without access codes. Everyone can edit there, and there is no pass to issue. |
| 404 | `not_found` | No route has this path. |
| 404 | `revision_not_found` | The slot has no revision with that number. It was never made, or it was the oldest and has been dropped. |
| 405 | `method_not_allowed` | The path exists and does not take this method. The `Allow` header lists the ones it takes. Slots have no create or delete route. |
| 413 | `payload_too_large` | The body is larger than the route takes. For an import, also elements that come to more than `max_scene_bytes` as segl stores them, or a file inside the document over `max_asset_bytes`. |
| 415 | `unsupported_media_type` | An upload whose `Content-Type` is not one of the image types. |
| 422 | `invalid_title` | A slot title that is not text, is empty once trimmed, is longer than 80 characters, or has a control character, such as a line break. |
| 422 | `invalid_revision` | A restore whose `revision` is not a whole number, 1 or more. |
| 422 | `invalid_document` | An import whose body is a JSON object and is not a scene document as the editor writes one. The message says what is wrong, and repeats nothing from the body. |
| 429 | `rate_limited` | This client address has been given 30 display names in the last minute, or has sent five wrong access codes in a row. `Retry-After` is the whole seconds until it may ask again. The refused call takes no name, and its code is not read. |
| 500 | `internal_error` | segl failed, for example because it could not read the database. The cause is in the server log, not in the response. |

A slot's metadata, from `/api/v1/slots/4`:

```json
{ "number": 4, "title": "Workspace 4", "epoch": 1, "savedAt": "2026-11-12T09:00:00.000Z" }
```

A slot's scene, from `/api/v1/slots/4/scene`:

```json
{
  "scene": { "elements": [] },
  "epoch": 1,
  "savedAt": "2026-11-12T09:00:00.000Z",
  "editorLabel": "System",
  "files": []
}
```

`scene` is the stored document, returned as it was saved. Its elements include the deleted ones, each with `isDeleted` true, which the editor keeps and does not draw. `savedAt` is when the head was last written, in UTC to the millisecond. `editorLabel` is `System` until a connection has saved the slot. `files` says which bytes the scene's images mean:

```json
{ "id": "5925e98057f8775cdcb89135e0a309eb07424d6f", "hash": "6df4c4fc942d7e02…", "mimeType": "image/png" }
```

`id` is the editor's file id, which an image element names in `fileId`. `hash` is the 64 hex digits the bytes are fetched by. The head is the room's scene as of the last flush, at most `head_flush_seconds` behind what the browsers on the slot see (`DATA-MODEL.md`, flush rules). The response is ASCII: a character outside it is a `\u` escape.

A slot's history, from `/api/v1/slots/4/revisions`:

```json
{
  "revisions": [
    { "revision": 3, "epoch": 2, "authorLabel": "Bravo2", "createdAt": "2026-11-12T09:05:00.000Z" },
    { "revision": 2, "epoch": 1, "authorLabel": "Alpha1", "createdAt": "2026-11-12T09:04:59.990Z" },
    { "revision": 1, "epoch": 1, "authorLabel": "Alpha1", "createdAt": "2026-11-12T09:00:01.000Z" }
  ]
}
```

A revision is the slot's scene as it was at one moment (`DATA-MODEL.md`, flush and revision rules). `revision` counts up per slot from 1 and is not reused. `authorLabel` is the display name behind the newest change in that scene, or `System`. `epoch` is the epoch the scene belonged to. A restore and an import each start a new epoch, so a revision whose epoch is higher than that of the one before it was written by one of them: revision 3 above. Nothing stored says which of the two. A slot nobody has changed has an empty list.

One revision, from `/api/v1/slots/4/revisions/2`, is the same object with `scene` and `files` as the scene route gives them. A `{revision}` is a whole number from 1, written without a sign or a leading zero. Anything else in its place, or a number the slot does not have, is a `404` with `revision_not_found`.

A restore, `POST /api/v1/slots/4/restore` with `{ "revision": 1, "displayName": "Bravo2" }`, answers:

```json
{ "revision": 3, "epoch": 2, "savedAt": "2026-11-12T09:05:00.000Z" }
```

`revision` is the new revision the restore wrote, and `epoch` the slot's new epoch. Before the route answers, in this order:

1. The scene the slot's room holds is written to the head, and kept as a revision unless the newest revision already holds it. A restore can therefore be undone by restoring that revision: 2 above.
2. The chosen revision's scene becomes the head, the epoch goes up by one, and a revision records it, in one transaction.
3. Every connection on the slot, viewers included, is sent `scene` with the new epoch, and puts it in place of its canvas.

`displayName` is who restored, for `authorLabel`: the label the browser stores, taken as written, as `hello` takes it. Left out, or not 1 to 40 characters of text, it is `System`. The pass is checked before the body is read. A restore the server cannot write leaves the slot on its scene and its epoch, and is a `500`. An edit that reaches the server while it is writing a restore was made on the scene that is going, and is dropped with it.

An import, `POST /api/v1/slots/4/import`, takes as its body the file the editor's export writes (S-011, D2-031):

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "segl",
  "elements": [
    { "id": "Hq3…", "type": "image", "fileId": "5925e980…", "index": "a0", "version": 3, "versionNonce": 81 }
  ],
  "appState": { "viewBackgroundColor": "#ffffff" },
  "files": {
    "5925e980…": { "mimeType": "image/png", "id": "5925e980…", "dataURL": "data:image/png;base64,iVBORw0…" }
  }
}
```

It answers as a restore does, with `{ "revision", "epoch", "savedAt" }`, after the same three steps: the scene the slot's room holds is kept as a revision, the imported scene becomes the head at the next epoch with a revision of its own, and every connection on the slot is sent `scene`. So an import is undone by restoring the revision under its own. What segl takes from the document:

- `type`, which is `excalidraw`. A library file, or any other JSON object, is `invalid_document`.
- `elements`, or none when the key is absent or `null`. Each is an object with a text `id`, and no two share one. A missing `version` or `versionNonce` becomes 1 or 0, which is what the editor does with an element from an older file. They are stored in drawing order: by `index`, and then those without one, as they came. An empty list empties the slot.
- Of `files`, the entries the elements name in `fileId`, deleted elements included. An entry is `mimeType`, one of the image types an upload may have, and `dataURL`, a `data:` URL that holds the bytes, at most `max_asset_bytes` of them. segl stores the bytes as it stores an upload, under their SHA-256, and adds the file id to the slot's file list in the write that starts the epoch. A file id the slot already has keeps the bytes it had. An image whose file the document lacks is taken as it is: the slot may hold the file already, and if not, the editor draws a placeholder. An entry no element names is not read.
- Nothing else. `appState` holds the canvas's background and grid, which a slot does not share (`ARCHITECTURE.md`, collaboration), and `version` and `source` are the exporting editor's. The stored scene is the slot's own document with the imported elements.

Who imported, for `authorLabel`, comes in the `X-Segl-Display-Name` header, because the body is the document: the label the browser stores, percent-encoded as UTF-8, since a header is ASCII. Left out, or not 1 to 40 characters once decoded, it is `System`.

A refused import changes nothing and stores no file. The pass is checked before the body is read. A body over `max_scene_bytes` is a `413` with `payload_too_large`, refused from its `Content-Length` before it is read. So is a document whose elements come to more than `max_scene_bytes` as segl stores them, which is ASCII, with an escape for every other character, and one with a named file over `max_asset_bytes`. A body that is not a JSON object is a `400` with `bad_request`. A JSON object that is not a scene document is a `422` with `invalid_document`: an element without an id, two elements with one id, a named file that is not an image in a `data:` URL, or a number JSON cannot write, such as `1e999`.

A display name, from `POST /api/v1/display-name`:

```json
{ "displayName": "Alpha1" }
```

Every call takes the next number, so the response is sent with `Cache-Control: no-store`, and a browser calls the route only when it has no stored label (`ARCHITECTURE.md`, display names).

A pass, from `POST /api/v1/access` with `{ "code": "Maple River 42" }`:

```json
{ "pass": "1800000000.q0h3JYzXb1cR5tUv7wA9-_Bd", "expiresAt": "2027-01-15T20:00:00.000Z" }
```

`pass` is what the browser stores and sends back: the Unix second it was issued at, a dot, and 24 characters of signature. It is printable ASCII, so a request header carries it whole. `expiresAt` is when it ends, `access_pass_hours` after its issue, in UTC to the millisecond, or `null` when the site set no limit. The server keeps no list of passes. It takes one whose signature fits a code that is still in `access_codes`, that was issued at or after `access_passes_after`, that is not from more than five minutes ahead of the server's clock, and that is younger than `access_pass_hours` as that is set when the pass is checked (`ARCHITECTURE.md`, edit gate). The response is sent with `Cache-Control: no-store`, and sets no cookie.

A code is compared in a normal form: lowercase letters and digits, with any run of other characters as one separator. So `Maple River 42`, `maple.river.42`, and `MAPLE-river  42` are one code. The comparison is constant-time, against every code in the list.

A body that is not a JSON object, or whose `code` is not text, is a `400` with `bad_request`, and is not counted as a wrong code. Any text that is not one of the codes is `403` with `wrong_code`, and is counted for the client address it came from (`SECURITY.md`). The fifth wrong code in a row starts a wait of fifteen minutes, during which every call from that address is `429` with `rate_limited` and a `Retry-After` header, before its body is read. A right code starts the count again, and so does a quarter of an hour without a wrong one. The route is a mutation for the Origin check. On a segl without access codes it is `404` with `no_access_codes`.

Uploaded files, the bytes of the images on the canvases (D2-028):

| Method | Path | Function |
|---|---|---|
| POST | `/api/v1/slots/{n}/assets` | The body is the file's bytes, at most `max_asset_bytes`, and `Content-Type` is its image type. A pass when codes are set. Returns `{ "hash", "mediaType" }`. |
| GET | `/api/v1/assets/{hash}` | The bytes stored under that SHA-256. No pass. |

An upload stores the bytes once, under `assets_dir`, and answers with their SHA-256 as 64 lowercase hex digits. The same bytes uploaded again, to any slot, give the same answer. The upload alone changes no scene: the browser then names the file on the socket, in a `files` message. `Content-Type` is one of the editor's image types: `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `image/svg+xml`, `image/bmp`, `image/x-icon`, `image/avif`, or `image/jfif`. Anything else, or none, is a `415`. segl does not look inside the bytes. An empty body is a `400` with `bad_request`, and one over the limit a `413`, refused from its `Content-Length` before it is read.

A file is served as bytes and nothing else, whatever was uploaded: `Content-Type: application/octet-stream`, `X-Content-Type-Options: nosniff`, and `Content-Security-Policy: default-src 'none'; sandbox`, so that no browser shows one as a page or an image of this site (`SECURITY.md`). The page fetches the bytes and hands them to the editor with the `mimeType` from the file list. A file never changes, so the response is sent with `Cache-Control: max-age=31536000, immutable`. A name that is not 64 lowercase hex digits, or one segl has no file for, is a `404` with `not_found`. No route deletes or replaces a file.

Uploaded files live under `/api/v1/` so they never share a path with the Vite build's `assets/` directory.

## WebSocket

`GET /collab?slot={n}` upgraded to a WebSocket. The slot number in the query is not a secret. The pass is not a query parameter. Each message is one text frame holding a JSON object with a `type`.

The handshake is refused with an HTTP response, in the error shape above, and no socket opens:

| Status | `error` | When |
|---|---|---|
| 403 | `outside_network` | The client's address is outside `internal_networks`, when that is set. |
| 403 | `bad_origin` | `Origin` is present and does not match `Host`. |
| 404 | `invalid_slot` | `slot` is missing, or is not `1` to `9`. |

The first message must be `hello`, within 10 seconds. Until then the connection is not in the room: it is not counted and is sent nothing. A connection that sends anything else first, or nothing, gets an `error` with `bad_message` and is closed with code 1008.

Client → server:

- `hello` — `{ "type": "hello", "clientId", "displayName", "editToken": "" }`. `clientId` is this browser's own id, 1–64 letters, digits, `_`, and `-`, which it keeps in `localStorage`. `displayName` is the stored label, taken as written and not title-cased, or `null` for a browser that has none yet. `editToken` is this browser's pass, or `""` (`ARCHITECTURE.md`, edit gate). The field's name is from an earlier build, in which it carried a token. The server reads the pass here and nowhere else on the socket: it decides `viewOnly`, and the server keeps the time the pass ends for the life of the connection. A page whose pass changes says `hello` again on a new socket.
- `elements` — `{ "type": "elements", "epoch", "elements": [ ... ], "seq" }`. Each element is the editor's record, with a text `id` and whole-number `version` and `versionNonce`. The batch is taken whole or refused whole. `seq` is optional: the number this browser gives the message, which the server answers with `saved`. The list may be empty, which with a `seq` asks whether everything the server holds is saved.
- `presence` — `{ "type": "presence", "cursor": { "x", "y" } }`, in the canvas's own coordinates, or `"cursor": null`.
- `rename` — `{ "type": "rename", "displayName" }`, a name the person typed.
- `files` — `{ "type": "files", "epoch", "files": [ { "id", "hash", "mimeType" } ], "seq" }`, after the bytes were uploaded: these file ids mean those bytes. 1 to 256 files. `id` is 1–64 letters, digits, `_`, and `-`. `seq` is optional, as in `elements`.

Server → client:

- `welcome` — `{ "type": "welcome", "slot", "title", "epoch", "viewOnly", "editEndsIn", "connectionId", "participants": [ { "connectionId", "displayName" } ] }`. `editEndsIn` is the seconds until this connection's pass ends, to the millisecond, or `null` when nothing ends: the connection is a viewer, this segl has no access codes, or its passes have no limit. It is a length and not a time of day, so that a browser whose clock is wrong still counts it right. The page stops taking edits a second before it runs out (`ARCHITECTURE.md`, edit gate). `connectionId` is this connection's own. `participants` is every connection on the slot, this one included, in the order they joined. A `displayName` is `null` for a connection without a label.
- `scene` — `{ "type": "scene", "epoch", "elements": [ ... ], "files": [ ... ] }`: every element the room holds, deleted ones included, in drawing order, and the files those elements name. Sent after `welcome`, to a connection whose `elements` or `files` named another epoch, and to every connection on the slot after a restore or an import. A `scene` of the epoch the browser is on is merged into its canvas. One of another epoch replaces the canvas.
- `elements` — `{ "type": "elements", "epoch", "elements": [ ... ] }`: the elements of another connection's batch that the server kept. Not sent to the connection they came from.
- `slot` — `{ "type": "slot", "slot", "title" }` after a title change.
- `presence` — `{ "type": "presence", "connectionId", "displayName", "cursor" }`: a connection that joined (`cursor` is `null`), moved its cursor, or was renamed. A cursor goes to the other connections. A rename goes to every connection, the renamed one included.
- `presence-end` — `{ "type": "presence-end", "connectionId" }` when a connection leaves.
- `files` — `{ "type": "files", "epoch", "files": [ { "id", "hash", "mimeType" } ] }`: the files of another connection's message that were new to the slot, for this connection to fetch. Not sent to the connection they came from.
- `saved` — `{ "type": "saved", "epoch", "savedAt", "seq" }` after a head flush: every message this connection sent up to number `seq` is in the slot's head, on the server's disk. `savedAt` is the head's. Sent only to a connection that numbered a message, and once for the newest number a flush held.
- `error` — `{ "type": "error", "error", "message" }`. The connection stays open.

| `error` | When |
|---|---|
| `bad_message` | Not JSON text, not an object with a `type`, a second `hello`, or a field of the wrong shape. Nothing was applied. |
| `unknown_type` | A `type` this segl does not know. |
| `view_only` | `elements` or `files` from a connection that may not edit: one that had no pass the server takes in `hello`, or one whose pass has ended since. Nothing was applied, and nobody else was told. |
| `scene_too_large` | `elements` that would take the slot's elements over `max_scene_bytes`. Nothing was applied. |
| `unknown_file` | `files` that named a hash segl has no bytes for. Nothing was applied. The browser uploads the bytes and sends the message again. |
| `invalid_name` | `rename` with a name that is not 1–40 characters once title-cased. |

The server applies `elements` only when the sender is an editor and `epoch` matches the room. A connection is an editor until its pass ends: the first `elements` or `files` after that time is answered `view_only`, and from then on the connection is a viewer, as one that came without a pass. `welcome` is not sent again, and need not be: it said how long the pass had, in `editEndsIn`, and segl's own page has stopped by then. On an epoch mismatch it sends `scene` and does not apply the payload. It keeps the copy of each element with the higher `version`, and on equal versions the one with the lower `versionNonce` (`ARCHITECTURE.md`, collaboration). A deleted element is an element with `isDeleted` true, and is kept.

`files` follows the same two rules. A file id the slot already has keeps the bytes it was first given, and is not sent on. An image element and its file travel apart, in either order: the element goes out as soon as it is placed, and the other browsers draw a placeholder until the file is named and fetched.

A message that was refused, for any of the reasons above, is not answered with `saved`. The numbers are the browser's own and need only grow. A connection that sent no `seq` is never sent `saved`.

A restore or an import ends the wait for `saved`. What a connection sent for the scene that was replaced is answered by the `scene` of the new epoch, and no `saved` follows for it. The next `saved` names the new epoch.

`rename` is allowed for viewers. The server title-cases the name, sends `presence`, and does not write SQLite.

A participant has no color. The editor draws a connection's cursor in a color it works out from `connectionId`, the same in every browser, and takes no other.

Limits:

- A message may be up to `max_scene_bytes`. A longer one closes the connection with code 1009.
- The elements of one slot, as JSON, may come to `max_scene_bytes` together. A batch that would go over is `scene_too_large`. One that makes the scene smaller is always taken.
- The server pings every connection every 20 seconds (uvicorn's default) and closes one that does not answer.
- A browser that stops reading is not waited for. When 1024 messages, or 16 MiB, are waiting for it, the server closes its connection with code 1013. It reconnects and is sent the whole scene.
- The server answers nothing but JSON: a message with `NaN` or `Infinity` in it is `bad_message`. So is one with a number too large for the server to hold, such as `1e999`: it is JSON, and Python would read it as infinity and write `Infinity` to the other browsers and into the stored scene.

## Pages and the build's files

Served when `web_dir` holds a build (`DEPLOY.md`). Without one, these paths are `404` with `not_found`, and the API still answers.

| Method | Path | Function |
|---|---|---|
| GET | `/` and `/s` | The web application, as a page at segl's root: its files are named `./assets/...`, and `SEGL_CONFIG.root` is `./`. |
| GET | `/access` | The same page at segl's root. The application shows the access page, where a person enters an access code (`ARCHITECTURE.md`, edit gate). `/access/` and anything under it are not pages. |
| GET | `/s/{n}` and `/s/` | The same page one level down: `../assets/...`, and `root` is `../`. Any one segment gets it. The page, not this route, sends a segment that is not `1` to `9` to slot 1. |
| GET | `/assets/...`, `/fonts/...`, `/favicon.svg` | The files of the build, with `ETag` and `Last-Modified`. A file the build lacks is `404` with `not_found`. |

A page is `text/html` with `Cache-Control: no-cache`. It carries `window.SEGL_CONFIG = { "root", "editRequired" }` (`ARCHITECTURE.md`, mount and navigation) and never an access code, the secret, or a pass. No URL in it starts with `/`. A deeper path, such as `/s/1/x`, is not a page.

## Reserved paths

segl registers only these first segments: `s`, `access`, `api`, `collab`, and the folders and files at the top of the Vite build (`assets`, `fonts`, and `favicon.svg`). They are registered after the others, so a build cannot shadow them. Do not register `/{team}/{project}/{board}`.
