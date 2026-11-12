# HTTP and WebSocket (MVP)

Paths below are relative to segl's root. A proxy that mounts segl under a path, such as `/board/`, strips that path first (`ARCHITECTURE.md`, mount and navigation). The service binds `127.0.0.1`. Errors are JSON: `{ "error": "<code>", "message": "<human text>" }`.

Mutation routes require the edit token when `edit_token` is non-empty. The header is `X-Segl-Edit-Token`. A view-only call gets `403` and `error: view_only`. An empty configured token ignores the header and allows the write.

A mutation, or a WebSocket upgrade, whose `Origin` header is present and does not match the request's `Host` (host and port) gets `403` and `error: bad_origin` (`SECURITY.md`).

## HTTP

| Method | Path | Function |
|---|---|---|
| GET | `/api/v1/health` | `{ "status": "ok" }` |
| GET | `/api/v1/config` | `{ "editRequired" }`, true when `edit_token` is set. Same fact as the injected script. No token, and the token is never in the response. |
| GET | `/api/v1/slots` | Nine entries: number, title, epoch, savedAt. |
| GET | `/api/v1/slots/{n}` | One slot's metadata. |
| PATCH | `/api/v1/slots/{n}` | Body `{ "title" }`. Trimmed, 1–80 characters. Edit token when set. Broadcasts a `slot` message to the room. |
| GET | `/api/v1/slots/{n}/scene` | Head scene, epoch, savedAt, editorLabel, and the head's file list (`id`, `hash`, `mimeType`). |
| GET | `/api/v1/slots/{n}/revisions` | Newest first, at most 50: revision, epoch, authorLabel, createdAt. Scene bodies stay on the single-revision route. |
| GET | `/api/v1/slots/{n}/revisions/{revision}` | One stored scene. |
| POST | `/api/v1/slots/{n}/restore` | Body `{ "revision" }`. Replaces the head, increments epoch, appends a revision, broadcasts to the room. Edit token when set. |
| POST | `/api/v1/display-name` | Allocates the next `WordN`. No edit token. Rate-limited to 30 calls per minute per client address (`SECURITY.md`). |
| POST | `/api/v1/slots/{n}/import` | Body is an Excalidraw JSON document. Same epoch rules as restore. Edit token when set. Reject above `max_scene_bytes` with `413` and `payload_too_large`. |

Paths are exact. A trailing slash, as in `/api/v1/health/`, is a `404` and is not redirected.

`{n}` outside 1–9 returns `404` with `invalid_slot`. The app sends those URLs to slot 1 before calling the API.

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

## Reserved paths

segl registers only these first segments: `s`, `api`, `collab`, and the static paths the Vite build emits (`assets`, the editor fonts, the favicon). Do not register `/{team}/{project}/{board}`.
