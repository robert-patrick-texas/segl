# Architecture — segl (draft)

## Design tenets
1. Embed Excalidraw; isolate package-specific APIs in a `canvas-adapter`.
2. Separate scene geometry from network domain records.
3. Keep collaboration, board persistence and inventory ingestion independently testable.
4. No direct browser-to-device SNMP/SSH/API calls.
5. Make all source integrations read-only in initial releases.
6. Keep a one-host deployment simple.

## Components
- `web`: React/TypeScript UI, Excalidraw, workspace navigation, network palette, inventory browser.
- `api`: FastAPI, board CRUD, revisions, object catalog, imports, scenarios, authorization.
- `collab`: Node/TypeScript WebSocket synchronization and presence.
- `db`: PostgreSQL, transactional records and version metadata.
- `assets`: local managed directory or S3-compatible interface later.
- `proxy`: Nginx HTTPS/WSS routing.
- `integrations`: Python adapters invoked by API/worker.

## Initial topology
```text
Browser(s) --HTTPS/WSS--> Nginx
                            |-- /          --> React static assets
                            |-- /api/v1    --> FastAPI --> PostgreSQL
                            |-- /collab    --> WS service --> persistence API/DB
                                                    |
                                            asset references
```

## Collaboration and persistence boundaries
- Rooms are authorized by backend-issued, board-scoped credentials.
- Collaboration server validates board access before join.
- Presence is ephemeral; boards and scene assets are durable.
- The server tracks scene revisions/checkpoints, with a documented save acknowledgment.
- Browser reconnect must resynchronize without replacing newer edits.
- Treat Excalidraw scene updates, element versions, files and app state as a coordinated compatibility contract.
- Prototype upstream `excalidraw-room` behavior before implementation choices are locked.

## Semantic-to-visual mapping
`network_object.id` is stable; `excalidraw_element.id` is presentation-only.
Each bound element may carry `customData.segl = { schemaVersion, objectId, objectType, scenarioId }`.
All references are validated server-side. Freeform arrows and symbols remain legal.

## Typed links
- `cable`: physical media/path between endpoints.
- `circuit`: contracted/provider connectivity; may attach to transport/cloud rather than imply point-to-point inter-site wiring.
- `relationship`: logical, administrative or functional association.
- `neighbor`: observed adjacency with source protocol and timestamp.
- `connector`: drawing-only or unspecified link, not asserted as physical reality.

## Integration boundary
Adapters return canonical records and provenance. A reconciler merges assertions without changing user-created plans. No API adapter should need to know Excalidraw element format.

## Scalability
One host and one collab process initially. Later: Redis-backed room coordination, horizontal collab scaling, object storage, background import workers and dedicated database. Do not introduce these before demonstrated need.

## Failure handling
Crash/restart recovery; optimistic concurrency on metadata; scene revision checks; import transactions; asset reference integrity; visible disconnected state; restore drills.
