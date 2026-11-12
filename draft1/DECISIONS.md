# Architecture decision log

## Confirmed direction (user-provided)
- **D-001:** Project working title: `segl`.
- **D-002:** First priority: embedded self-hosted collaborative whiteboard.
- **D-003:** Second priority: network icons, objects and typed links.
- **D-004:** Third priority: real network data, starting with database tables and CSV/JSON.
- **D-005:** Later adapters: Nautobot, NetBox, Checkmk and others.
- **D-006:** Defer advanced SAML/strong authentication/encryption-at-rest controls to later phase; prioritize usability and business value.

## Recommended design choices (not yet formally approved)
- **R-001:** Embed Excalidraw package instead of maintaining a fork.
- **R-002:** React/TypeScript frontend; TypeScript collaboration; FastAPI/Python application API.
- **R-003:** PostgreSQL from first persistent release.
- **R-004:** Nginx + single-host Compose/Podman deployment.
- **R-005:** Keep minimal access control/HTTPS in initial pilot.
- **R-006:** Separate semantic network records from canvas geometry.
- **R-007:** All upstream integrations initially read-only.
- **R-008:** No graph database or Kubernetes for MVP.

## Open decisions
- **O-001:** Confirm collaboration protocol/implementation after compatibility spike.
- **O-002:** Choose MVP identity mechanism: local accounts vs trusted gateway.
- **O-003:** Project license is Apache License 2.0 (locked in `docs/DECISIONS.md` D2-019). Contributor governance beyond that license is still open.
- **O-004:** Choose storage and quotas for image assets.
- **O-005:** Confirm visual standards for circuits, cables and neighbor links.
- **O-006:** Decide whether initial CSV/JSON ingestion is UI upload, watched directory, CLI or all three.
- **O-007:** Define initial maximum board sizes and restore-point frequency based on tests.

## Decision protocol
For each open decision: record options, rationale, trade-offs, acceptance tests, owner and decision date before implementation becomes hard to reverse.
