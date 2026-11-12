# Delivery roadmap and phase gates

These are dependency-ordered milestones, **not calendar commitments**.

## Phase 0 — Collaboration spike
- Create React/Vite shell and embed pinned Excalidraw package.
- Verify upstream collaboration integration strategy.
- Demonstrate two clients, live edits, cursors, reconnect and durable snapshots.
- Test server restart and scene/file recovery.
**Gate:** repeatable two-browser demo with no silent data loss.

## Phase 1 — Minimum useful product
- Board list, create/open/rename/duplicate/delete, basic protected access.
- Reliable persistence and export/import; simple deployment.
- CI, unit tests, integration tests, browser tests, backup/restore.
**Gate:** operations staff can conduct and recover a real meeting.

## Phase 2 — Network object toolkit
- Symbol manifest and palette; network objects with UUID/name/type.
- Typed links: cable, circuit, relationship, neighbor, connector.
- Interface labels and observed/planned styling.
- Diagram editing never mutates external inventory.
**Gate:** build a mixed physical/logical/planned network diagram.

## Phase 3 — Local topology data
- PostgreSQL catalog, CSV/JSON imports, validation, search.
- Add device by name, expand one-hop neighbors, provenance.
- Refresh preview preserving layout; planned vs observed separation.
**Gate:** import sample topology, expand and plan a replacement.

## Phase 4 — External source adapters
- Nautobot, NetBox, Checkmk read-only adapters.
- Scheduled/manual sync, provenance, reconciliation and error reporting.
**Gate:** source updates reconcile without destroying plans or layout.

## Phase 5 — Enterprise hardening
- Enterprise SSO, expanded RBAC, encryption at rest, audit/retention, compliance support.
- Operational metrics, security baselines, HA options.
**Gate:** controls verified against deployment organization's requirements.

## Backlog discipline
Do not start phase N+1 until critical acceptance tests for phase N pass. A small interface stub is acceptable if it prevents expensive rework, but do not build unneeded infrastructure early.
