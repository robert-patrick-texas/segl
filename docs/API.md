# HTTP and WebSocket (MVP)

Paths below are relative to `base_path`. The service binds `127.0.0.1`. Errors are JSON: `{ "error": "<code>", "message": "<human text>" }`.

Mutation routes require the edit token when `edit_token` is non-empty. The header is `X-Segl-Edit-Token`. A view-only call gets `403` and `error: view_only`. An empty configured token ignores the header and allows the write.

## HTTP

| Method | Path | Function |
|---|---|---|
| GET | `/api/v1/health` | `{ "status": "ok" }` |
| GET | `/api/v1/config` | `{ "basePath", "editRequired" }`. Same facts as the injected script. No token. |
| GET | `/api/v1/slots` | Nine entries: number, title, epoch, savedAt. |
| GET | `/api/v1/slots/{n}` | One slot's metadata. |
| PATCH | `/api/v1/slots/{n}` | Body `{ "title" }`. Trimmed, 1–80 characters. Edit token when set. |
| GET | `/api/v1/slots/{n}/scene` | Head scene, epoch, savedAt, editorLabel. |
| GET | `/api/v1/slots/{n}/revisions` | Newest first, at most 50: revision, epoch, authorLabel, createdAt. Scene bodies stay on the single-revision route. |
| GET | `/api/v1/slots/{n}/revisions/{revision}` | One stored scene. |
| POST | `/api/v1/slots/{n}/restore` | Body `{ "revision" }`. Replaces the head, increments epoch, appends a revision, broadcasts to the room. Edit token when set. |
| POST | `/api/v1/display-name` | Allocates the next `WordN`. No edit token. Rate-limited to 30 calls per minute per client address. |
| POST | `/api/v1/slots/{n}/import` | Body is an Excalidraw JSON document. Same epoch rules as restore. Edit token when set. Reject above `max_scene_bytes`. |

`{n}` outside 1–9 returns `404` with `invalid_slot`. The HTML app redirects those URLs to slot 1 before calling the API.

Asset upload, if T07 needs it for the editor's file model:

| Method | Path | Function |
|---|---|---|
| POST | `/api/v1/slots/{n}/assets` | Raw body, edit token, size cap. Returns `{ "hash", "mediaType" }`. |
| GET | `/assets/{hash}` | Bytes by SHA-256 hex name. No user-supplied paths. |

## WebSocket

`GET {base}/collab?slot={n}` upgraded to a WebSocket. The slot number in the query is not a secret. The edit token is not a query parameter.

Client → server:

- `hello` — `{ "type": "hello", "clientId", "displayName", "editToken": "" }`
- `elements` — `{ "type": "elements", "epoch", "elements": [ ... ] }`
- `presence` — `{ "type": "presence", "cursor", "color" }`
- `rename` — `{ "type": "rename", "displayName" }`

Server → client:

- `welcome` — `{ "type": "welcome", "slot", "epoch", "viewOnly", "participants": [ { "connectionId", "displayName", "color" } ] }`
- `scene` — full head after join, restore, or import. Includes `epoch` and `elements`.
- `elements` — reconciled winners for the current epoch.
- `presence` / `presence-end` — one connection's cursor, or a departure.
- `saved` — `{ "type": "saved", "epoch", "savedAt" }` after a head flush that included this connection's edit.
- `error` — `{ "type": "error", "error", "message" }`

The server applies `elements` only when the sender is an editor and `epoch` matches the head. On an epoch mismatch it sends `scene` and does not apply the payload.

`rename` is allowed for viewers. The server title-cases the name, broadcasts `presence`, and does not write SQLite.

## Reserved paths

These first segments are reserved and are the only ones the MVP registers: `s`, `api`, `collab`, `assets`, plus the static asset paths the Vite build emits. Do not register `/{team}/{project}/{board}`.
