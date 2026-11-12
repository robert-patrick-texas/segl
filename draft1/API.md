# API and integration contracts (proposed, not implemented)

## REST v1
| Method | Endpoint | Function |
|---|---|---|
| GET | `/api/v1/health` | Readiness |
| GET/POST | `/api/v1/workspaces` | List/create workspaces |
| GET/POST | `/api/v1/boards` | List/create boards |
| GET/PATCH/DELETE | `/api/v1/boards/{id}` | Board metadata |
| GET | `/api/v1/boards/{id}/scene` | Current durable scene |
| PUT | `/api/v1/boards/{id}/scene` | Conditional scene save with revision precondition |
| GET | `/api/v1/boards/{id}/revisions` | History |
| POST | `/api/v1/boards/{id}/restore` | Restore revision |
| GET | `/api/v1/network/objects` | Search/filter catalog |
| GET | `/api/v1/network/objects/{id}/neighbors?depth=1` | Bounded topology expansion |
| POST | `/api/v1/imports` | Upload validated CSV/JSON |
| GET | `/api/v1/imports/{id}` | Import status/errors |
| GET/POST | `/api/v1/boards/{id}/scenarios` | Scenario management |
| POST | `/api/v1/boards/{id}/collab-token` | Short-lived room credential |

## WebSocket
`/collab?board_id=...` with a securely conveyed board-scoped credential. Avoid long-lived secrets in URL query strings or logs. Actual synchronization message schema must be fixed after the Excalidraw compatibility spike.

Expected logical events: join/leave, presence, scene-delta, resync-request, save-status, error. These are semantic events, not a claim of upstream protocol compatibility.

## Adapter Python protocol (conceptual)
```python
from typing import Protocol, Iterable

class TopologyAdapter(Protocol):
    def capabilities(self) -> set[str]: ...
    def list_devices(self) -> Iterable[dict]: ...
    def list_interfaces(self) -> Iterable[dict]: ...
    def list_connections(self) -> Iterable[dict]: ...
```
Adapters emit canonical records with source IDs and timestamps. Implementations should support pagination and bounded sync; a production interface will use typed models and async/batch semantics as appropriate.

## Conflict resolution
Canonical identity uses `(source_id, external_id)` mappings. For competing assertions, preserve both evidence records; choose displayed preferred values through documented source priority or operator choice. Do not silently merge on hostname alone.

## Versioning and limits
Use `/api/v1`; schema version on imports; paginated search; bounded neighbor depth/count; upload size limits; explicit 409 on conflicting scene revisions; actionable validation errors.
