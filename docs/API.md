# HTTP and WebSocket (MVP)

Paths below are relative to segl's root. A proxy that mounts segl under a path, such as `/board/`, strips that path first (`ARCHITECTURE.md`, mount and navigation). The service binds `127.0.0.1`. Errors are JSON: `{ "error": "<code>", "message": "<human text>" }`. Clients branch on `error`. The message is for a person and may change.

Mutation routes require the edit token when `edit_token` is non-empty. The header is `X-Segl-Edit-Token`. A view-only call gets `403` and `error: view_only`. An empty configured token ignores the header and allows the write.

A mutation, or a WebSocket upgrade, whose `Origin` header is present and does not match the request's `Host` (host and port) gets `403` and `error: bad_origin` (`SECURITY.md`).

## HTTP

| Method | Path | Function |
|---|---|---|
| GET | `/api/v1/health` | `{ "status": "ok" }` |
| GET | `/api/v1/config` | `{ "editRequired" }`, true when `edit_token` is set. Same fact as the injected script. No token, and the token is never in the response. |
| GET | `/api/v1/slots` | `{ "slots": [ ... ] }` with nine entries in number order: number, title, epoch, savedAt. |
| GET | `/api/v1/slots/{n}` | One slot's metadata, the same object as its entry in the list. |
| PATCH | `/api/v1/slots/{n}` | Body `{ "title" }`. Trimmed, 1–80 characters. Edit token when set. Broadcasts a `slot` message to the room. |
| GET | `/api/v1/slots/{n}/scene` | Head scene, epoch, savedAt, editorLabel, and the head's file list (`id`, `hash`, `mimeType`). The list is empty until T07 stores files. |
| GET | `/api/v1/slots/{n}/revisions` | Newest first, at most 50: revision, epoch, authorLabel, createdAt. Scene bodies stay on the single-revision route. |
| GET | `/api/v1/slots/{n}/revisions/{revision}` | One stored scene. |
| POST | `/api/v1/slots/{n}/restore` | Body `{ "revision" }`. Replaces the head, increments epoch, appends a revision, broadcasts to the room. Edit token when set. |
| POST | `/api/v1/display-name` | Allocates the next `WordN`. No edit token. Rate-limited to 30 calls per minute per client address (`SECURITY.md`). |
| POST | `/api/v1/slots/{n}/import` | Body is an Excalidraw JSON document. Same epoch rules as restore. Edit token when set. Reject above `max_scene_bytes` with `413` and `payload_too_large`. |

Paths are exact. A trailing slash, as in `/api/v1/health/`, is a `404` and is not redirected.

`{n}` is one digit, `1` to `9`. Anything else in its place, such as `0`, `10`, `01`, or `abc`, returns `404` with `invalid_slot`. The app sends those URLs to slot 1 before calling the API.

Errors that no route names:

| Status | `error` | When |
|---|---|---|
| 404 | `not_found` | No route has this path. |
| 405 | `method_not_allowed` | The path exists and does not take this method. The `Allow` header lists the ones it takes. Slots have no create or delete route. |
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

`scene` is the stored document, returned as it was saved. `savedAt` is when the head was last written, in UTC to the millisecond. `editorLabel` is `System` until a connection has saved the slot.

Uploaded files, for the editor's file model (T07):

| Method | Path | Function |
|---|---|---|
| POST | `/api/v1/slots/{n}/assets` | Raw body, edit token, at most `max_asset_bytes`. Returns `{ "hash", "mediaType" }`. |
| GET | `/api/v1/assets/{hash}` | Bytes by SHA-256 hex name. No user-supplied paths. No token. |

Uploaded files live under `/api/v1/` so they never share a path with the Vite build's `assets/` directory.

## WebSocket

`GET /collab?slot={n}` upgraded to a WebSocket. The slot number in the query is not a secret. The edit token is not a query parameter. The server pings every connection every 20 seconds (uvicorn's default), and accepts messages up to `max_scene_bytes`.

Client → server:

- `hello` — `{ "type": "hello", "clientId", "displayName", "editToken": "" }`
- `elements` — `{ "type": "elements", "epoch", "elements": [ ... ] }`
- `files` — `{ "type": "files", "epoch", "files": [ { "id", "hash", "mimeType" } ] }`, after the bytes were uploaded
- `presence` — `{ "type": "presence", "cursor", "color" }`
- `rename` — `{ "type": "rename", "displayName" }`

Server → client:

- `welcome` — `{ "type": "welcome", "slot", "title", "epoch", "viewOnly", "participants": [ { "connectionId", "displayName", "color" } ] }`
- `scene` — full head after join, restore, or import. Includes `epoch`, `elements`, and `files`.
- `elements` — reconciled winners for the current epoch.
- `files` — files another connection added, for this connection to fetch.
- `slot` — `{ "type": "slot", "slot", "title" }` after a title change.
- `presence` / `presence-end` — one connection's cursor, or a departure.
- `saved` — `{ "type": "saved", "epoch", "savedAt" }` after a head flush that included this connection's edit.
- `error` — `{ "type": "error", "error", "message" }`

The server applies `elements` and `files` only when the sender is an editor and `epoch` matches the head. On an epoch mismatch it sends `scene` and does not apply the payload.

`rename` is allowed for viewers. The server title-cases the name, broadcasts `presence`, and does not write SQLite.

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
