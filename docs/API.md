# HTTP and WebSocket (MVP)

Paths below are relative to segl's root. A proxy that mounts segl under a path, such as `/board/`, strips that path first (`ARCHITECTURE.md`, mount and navigation). The service binds `127.0.0.1`. Errors are JSON: `{ "error": "<code>", "message": "<human text>" }`. Clients branch on `error`. The message is for a person and may change.

Mutation routes require the edit token when `edit_token` is non-empty. The header is `X-Segl-Edit-Token`. A view-only call gets `403` and `error: view_only`. An empty configured token ignores the header and allows the write.

A mutation, or a WebSocket upgrade, whose `Origin` header is present and does not match the request's `Host` (host and port) gets `403` and `error: bad_origin` (`SECURITY.md`). A mutation is a request with any method but `GET`, `HEAD`, and `OPTIONS`, whatever its path. A request without `Origin` is not checked.

## HTTP

| Method | Path | Function |
|---|---|---|
| GET | `/api/v1/health` | `{ "status": "ok" }` |
| GET | `/api/v1/config` | `{ "editRequired" }`, true when `edit_token` is set. Same fact as the injected script. No token, and the token is never in the response. |
| GET | `/api/v1/slots` | `{ "slots": [ ... ] }` with nine entries in number order: number, title, epoch, savedAt. |
| GET | `/api/v1/slots/{n}` | One slot's metadata, the same object as its entry in the list. |
| PATCH | `/api/v1/slots/{n}` | Body `{ "title" }`, a JSON object of at most 4096 bytes. The title is trimmed, and is 1–80 characters on one line. Returns the slot's metadata with the title as stored. Edit token when set. Sends a `slot` message to the slot's room. |
| GET | `/api/v1/slots/{n}/scene` | Head scene, epoch, savedAt, editorLabel, and the head's file list (`id`, `hash`, `mimeType`): the files its images name. |
| GET | `/api/v1/slots/{n}/revisions` | Newest first, at most 50: revision, epoch, authorLabel, createdAt. Scene bodies stay on the single-revision route. |
| GET | `/api/v1/slots/{n}/revisions/{revision}` | One stored scene. |
| POST | `/api/v1/slots/{n}/restore` | Body `{ "revision" }`. Replaces the head, increments epoch, appends a revision, broadcasts to the room. Edit token when set. |
| POST | `/api/v1/display-name` | Allocates the next `WordN` and returns `{ "displayName" }`. No body and no edit token. At most 30 names per minute per client address (`SECURITY.md`). The next call gets `429` with `rate_limited` and a `Retry-After` header. |
| POST | `/api/v1/slots/{n}/import` | Body is an Excalidraw JSON document. Same epoch rules as restore. Edit token when set. Reject above `max_scene_bytes` with `413` and `payload_too_large`. |

Paths are exact. A trailing slash, as in `/api/v1/health/`, is a `404` and is not redirected.

`{n}` is one digit, `1` to `9`. Anything else in its place, such as `0`, `10`, `01`, or `abc`, returns `404` with `invalid_slot`. The app sends those URLs to slot 1 before calling the API.

Errors that no route names:

| Status | `error` | When |
|---|---|---|
| 400 | `bad_request` | The body of a mutation is not a JSON object. |
| 403 | `bad_origin` | A mutation, or a WebSocket handshake, with an `Origin` that does not match `Host`. Nothing was changed. |
| 403 | `view_only` | A mutation without the edit token, or with a wrong one, when `edit_token` is set. |
| 404 | `not_found` | No route has this path. |
| 405 | `method_not_allowed` | The path exists and does not take this method. The `Allow` header lists the ones it takes. Slots have no create or delete route. |
| 413 | `payload_too_large` | The body is larger than the route takes. |
| 415 | `unsupported_media_type` | An upload whose `Content-Type` is not one of the image types. |
| 422 | `invalid_title` | A slot title that is not text, is empty once trimmed, is longer than 80 characters, or has a control character, such as a line break. |
| 429 | `rate_limited` | This client address has been given 30 display names in the last minute. `Retry-After` is the whole seconds until it may have another. The refused call takes no name. |
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

A display name, from `POST /api/v1/display-name`:

```json
{ "displayName": "Alpha1" }
```

Every call takes the next number, so the response is sent with `Cache-Control: no-store`, and a browser calls the route only when it has no stored label (`ARCHITECTURE.md`, display names).

Uploaded files, the bytes of the images on the canvases (D2-028):

| Method | Path | Function |
|---|---|---|
| POST | `/api/v1/slots/{n}/assets` | The body is the file's bytes, at most `max_asset_bytes`, and `Content-Type` is its image type. Edit token when set. Returns `{ "hash", "mediaType" }`. |
| GET | `/api/v1/assets/{hash}` | The bytes stored under that SHA-256. No token. |

An upload stores the bytes once, under `assets_dir`, and answers with their SHA-256 as 64 lowercase hex digits. The same bytes uploaded again, to any slot, give the same answer. The upload alone changes no scene: the browser then names the file on the socket, in a `files` message. `Content-Type` is one of the editor's image types: `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `image/svg+xml`, `image/bmp`, `image/x-icon`, `image/avif`, or `image/jfif`. Anything else, or none, is a `415`. segl does not look inside the bytes. An empty body is a `400` with `bad_request`, and one over the limit a `413`, refused from its `Content-Length` before it is read.

A file is served as bytes and nothing else, whatever was uploaded: `Content-Type: application/octet-stream`, `X-Content-Type-Options: nosniff`, and `Content-Security-Policy: default-src 'none'; sandbox`, so that no browser shows one as a page or an image of this site (`SECURITY.md`). The page fetches the bytes and hands them to the editor with the `mimeType` from the file list. A file never changes, so the response is sent with `Cache-Control: max-age=31536000, immutable`. A name that is not 64 lowercase hex digits, or one segl has no file for, is a `404` with `not_found`. No route deletes or replaces a file.

Uploaded files live under `/api/v1/` so they never share a path with the Vite build's `assets/` directory.

## WebSocket

`GET /collab?slot={n}` upgraded to a WebSocket. The slot number in the query is not a secret. The edit token is not a query parameter. Each message is one text frame holding a JSON object with a `type`.

The handshake is refused with an HTTP response, in the error shape above, and no socket opens:

| Status | `error` | When |
|---|---|---|
| 403 | `bad_origin` | `Origin` is present and does not match `Host`. |
| 404 | `invalid_slot` | `slot` is missing, or is not `1` to `9`. |

The first message must be `hello`, within 10 seconds. Until then the connection is not in the room: it is not counted and is sent nothing. A connection that sends anything else first, or nothing, gets an `error` with `bad_message` and is closed with code 1008.

Client → server:

- `hello` — `{ "type": "hello", "clientId", "displayName", "editToken": "" }`. `clientId` is this browser's own id, 1–64 letters, digits, `_`, and `-`, which it keeps in `localStorage`. `displayName` is the stored label, taken as written and not title-cased, or `null` for a browser that has none yet. `editToken` is the stored token, or `""`. It decides `viewOnly` for the life of the connection.
- `elements` — `{ "type": "elements", "epoch", "elements": [ ... ], "seq" }`. Each element is the editor's record, with a text `id` and whole-number `version` and `versionNonce`. The batch is taken whole or refused whole. `seq` is optional: the number this browser gives the message, which the server answers with `saved`. The list may be empty, which with a `seq` asks whether everything the server holds is saved.
- `presence` — `{ "type": "presence", "cursor": { "x", "y" } }`, in the canvas's own coordinates, or `"cursor": null`.
- `rename` — `{ "type": "rename", "displayName" }`, a name the person typed.
- `files` — `{ "type": "files", "epoch", "files": [ { "id", "hash", "mimeType" } ], "seq" }`, after the bytes were uploaded: these file ids mean those bytes. 1 to 256 files. `id` is 1–64 letters, digits, `_`, and `-`. `seq` is optional, as in `elements`.

Server → client:

- `welcome` — `{ "type": "welcome", "slot", "title", "epoch", "viewOnly", "connectionId", "participants": [ { "connectionId", "displayName" } ] }`. `connectionId` is this connection's own. `participants` is every connection on the slot, this one included, in the order they joined. A `displayName` is `null` for a connection without a label.
- `scene` — `{ "type": "scene", "epoch", "elements": [ ... ], "files": [ ... ] }`: every element the room holds, deleted ones included, in drawing order, and the files those elements name. Sent after `welcome`, and to a connection whose `elements` or `files` named another epoch. T08 and T09 send it to the room after a restore or an import.
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
| `view_only` | `elements` or `files` from a connection that may not edit. Nothing was applied, and nobody else was told. |
| `scene_too_large` | `elements` that would take the slot's elements over `max_scene_bytes`. Nothing was applied. |
| `unknown_file` | `files` that named a hash segl has no bytes for. Nothing was applied. The browser uploads the bytes and sends the message again. |
| `invalid_name` | `rename` with a name that is not 1–40 characters once title-cased. |

The server applies `elements` only when the sender is an editor and `epoch` matches the room. On an epoch mismatch it sends `scene` and does not apply the payload. It keeps the copy of each element with the higher `version`, and on equal versions the one with the lower `versionNonce` (`ARCHITECTURE.md`, collaboration). A deleted element is an element with `isDeleted` true, and is kept.

`files` follows the same two rules. A file id the slot already has keeps the bytes it was first given, and is not sent on. An image element and its file travel apart, in either order: the element goes out as soon as it is placed, and the other browsers draw a placeholder until the file is named and fetched.

A message that was refused, for any of the reasons above, is not answered with `saved`. The numbers are the browser's own and need only grow. A connection that sent no `seq` is never sent `saved`.

`rename` is allowed for viewers. The server title-cases the name, sends `presence`, and does not write SQLite.

A participant has no color. The editor draws a connection's cursor in a color it works out from `connectionId`, the same in every browser, and takes no other.

Limits:

- A message may be up to `max_scene_bytes`. A longer one closes the connection with code 1009.
- The elements of one slot, as JSON, may come to `max_scene_bytes` together. A batch that would go over is `scene_too_large`. One that makes the scene smaller is always taken.
- The server pings every connection every 20 seconds (uvicorn's default) and closes one that does not answer.
- A browser that stops reading is not waited for. When 1024 messages, or 16 MiB, are waiting for it, the server closes its connection with code 1013. It reconnects and is sent the whole scene.
- The server answers nothing but JSON: a message with `NaN` or `Infinity` in it is `bad_message`.

## Pages and the build's files

Served when `web_dir` holds a build (`DEPLOY.md`). Without one, these paths are `404` with `not_found`, and the API still answers.

| Method | Path | Function |
|---|---|---|
| GET | `/` and `/s` | The web application, as a page at segl's root: its files are named `./assets/...`, and `SEGL_CONFIG.root` is `./`. |
| GET | `/s/{n}` and `/s/` | The same page one level down: `../assets/...`, and `root` is `../`. Any one segment gets it. The page, not this route, sends a segment that is not `1` to `9` to slot 1. |
| GET | `/assets/...`, `/fonts/...`, `/favicon.svg` | The files of the build, with `ETag` and `Last-Modified`. A file the build lacks is `404` with `not_found`. |

A page is `text/html` with `Cache-Control: no-cache`. It carries `window.SEGL_CONFIG = { "root", "editRequired" }` (`ARCHITECTURE.md`, mount and navigation) and never the edit token. No URL in it starts with `/`. A deeper path, such as `/s/1/x`, is not a page.

## Reserved paths

segl registers only these first segments: `s`, `api`, `collab`, and the folders and files at the top of the Vite build (`assets`, `fonts`, and `favicon.svg`). They are registered after the others, so a build cannot shadow them. Do not register `/{team}/{project}/{board}`.
