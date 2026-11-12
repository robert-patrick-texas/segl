# segl — Software System Requirements and Architecture Specification (SSRAS)

**Version:** 0.1-draft  
**Date:** 2026-11-11  
**Target:** Ubuntu Linux 26.04 LTS, internal enterprise deployment  
**Status:** Planning baseline, subject to prototype validation

## 1. Executive summary
segl is an open-source, self-hosted collaborative whiteboard for network operations and engineering. The first release must make Excalidraw available to multiple concurrent users with durable boards. The next release introduces reusable network objects and semantically typed connections. Subsequent releases link those objects to authoritative network data, initially imported from database tables, CSV and JSON, and later through Nautobot, NetBox, Checkmk and other adapters. Advanced federal-enterprise controls are deferred, but basic access protection and data integrity are not.

## 2. Goals and non-goals
### Goals
- Rapid usable deployment on one Ubuntu host.
- Multi-user collaborative planning and troubleshooting.
- Persist boards and recover after browser/server restarts.
- Represent equipment and network relationships accurately.
- Preserve a clean boundary between observed network state and proposed plans.
- Provide versioned interfaces for integrations.

### Initial non-goals
- Network management system or replacement for NetBox/Nautobot/Checkmk.
- Automated configuration deployment or writeback to infrastructure.
- Enterprise-scale discovery engine built into the whiteboard.
- Full federal ATO/FIPS compliance in the first milestone.
- Large-scale HA cluster or Kubernetes prerequisite.

## 3. Stakeholders and use cases
**Users:** network operators, engineers, architects, meeting facilitators, team leads.
**UC-01:** Two or more engineers open the same board and collaborate live.
**UC-02:** A facilitator saves and reopens a troubleshooting diagram.
**UC-03:** An engineer places router, switch, firewall, AP, server and endpoint symbols.
**UC-04:** An engineer distinguishes physical cable, provider circuit, logical relationship and discovered adjacency.
**UC-05:** An engineer imports CSV/JSON inventory, searches a device and adds it to a board.
**UC-06:** An engineer expands one-hop neighbors from imported topology.
**UC-07:** An engineer adds planned equipment and proposed links without altering imported observations.
**UC-08:** A future adapter refreshes source records while preserving manual diagram layout.

## 4. Phased requirements
### P0 — usable collaborative whiteboard (must)
- Embed upstream Excalidraw package without forking.
- Support create/list/open/rename/duplicate/delete boards.
- Concurrent drawing and cursor/presence awareness.
- Authenticated or access-token-protected board sessions; no anonymous public Internet exposure by default.
- Durable server-side scene snapshots including images/assets.
- Recover after refresh, reconnect, restart and abrupt disconnect.
- Export/import native Excalidraw JSON; export PNG/SVG if supported by embedded APIs.
- Self-host fonts, assets and application services.
- Browser-compatible responsive UI for desktop and tablet.
- Run locally on one Ubuntu 26.04 LTS server.

### P1 — network shapes and semantics (must after P0)
- Symbol library: routers, switches, firewalls, Wi-Fi APs, servers, workstations, printers, VoIP phones, mobile devices, generic hosts, cloud/transport, unknown.
- Network object fields: UUID, display name, kind, optional model/site/address, lifecycle state, source reference.
- Typed connections: cable, circuit, logical relationship, discovered neighbor, generic connector.
- Connections may be attached to named device interfaces when known; otherwise device-level.
- Visible styles distinguish observed versus planned and physical versus logical.
- Users may create unbound freeform shapes and arrows; these are not automatically network records.
- Deleting an object from a board never deletes source inventory.
- Duplicating a visual object must not accidentally duplicate its source identity as a separate real device.

### P2 — local sources of truth (must after P1)
- Import device/interface/link records from CSV and JSON using documented schemas.
- Persist normalized topology records in PostgreSQL.
- Search by hostname, device type, site and source identifier.
- Place existing device by name and expand one-hop neighbors with preview.
- Detect duplicate external IDs and inconsistent endpoints.
- Maintain source attribution, import timestamps, import run history and validation errors.
- Preserve manual layout during refresh; never silently replace a user's scene.
- Support planned-only objects and links distinct from imported observed objects.

### P3 — pluggable integrations (should)
- Adapter interfaces for Nautobot, NetBox and Checkmk.
- Read-only polling or user-triggered refresh; configurable credentials and scopes.
- Map external records to canonical device/interface/link records.
- Reconcile conflicting source assertions by explicit priority and provenance, not last-write-wins.
- Import diff/preview before applying changes.
- API hooks for future integrations.

### P4 — enterprise hardening (later)
- SAML/OIDC with enterprise IdP and optional PIV/CAC via enterprise identity path.
- Granular RBAC, enterprise audit and retention policies.
- Encryption at rest and evaluated cryptographic posture.
- Security baseline mapping, SBOM, signed builds, vulnerability gates, backup/DR and HA.
- Operational observability, supportability and agency authorization documentation.

## 5. Architecture
**Frontend:** React/TypeScript embedding Excalidraw, plus board navigation and inventory side panel.
**Application API:** FastAPI for board metadata, network catalog, import, scenarios and authorization.
**Collaboration:** Node/TypeScript WebSocket service; evaluate Excalidraw collaboration semantics and reference implementations, but do not assume a room server provides persistence or authorization.
**Persistence:** PostgreSQL for metadata, normalized topology and versioned board snapshots; assets in a controlled local object/file store with DB references.
**Proxy:** Nginx terminates HTTPS/WSS and routes requests to frontend, API and collaboration service.
**Deployment:** Single-host Compose/Podman first, with separate services for later scaling.

### Logical flows
1. User opens a board through HTTPS; API validates access and returns metadata and saved scene.
2. Browser joins a WebSocket room with short-lived board-scoped authorization.
3. Scene edits synchronize through collaboration protocol; server persists checkpoints and recovery data.
4. Inventory panel queries the application API, not network equipment.
5. Application maps canonical network records into Excalidraw shapes with stable `customData` references.
6. User may add planned objects/links; these remain separate from imported observed topology.

## 6. Data architecture
- **Board scene:** Excalidraw elements, app state subset, embedded file references, scene version.
- **Semantic graph:** device, interface, connection, external source, observed assertion, planned change.
- **Binding:** one or more visual elements may reference one semantic object; a visual ID is not a device ID.
- **Provenance:** source system, external ID, observation/import time and data freshness.
- **Versions:** immutable snapshots or revisions support restore and comparisons.
- **Deletion:** removing an element from a board does not remove its semantic object or upstream record.

## 7. Collaboration correctness
- Confirm compatibility with the pinned Excalidraw release before choosing wire protocol.
- Test concurrent edits, delete/update conflicts, reconnection, multi-tab and room authorization.
- Persist assets and scene state; define an acknowledged-save boundary.
- Avoid naive last-writer-wins full-scene replacement.
- Checkpoint frequently and on room lifecycle transitions, with recovery on process failure.
- Track room version/epoch to prevent stale sessions overwriting newer snapshots.
- Establish single-server correctness before adding distributed coordination.

## 8. Interfaces
- Versioned REST `/api/v1/` for boards, versions, catalog, imports, topology and scenarios.
- Authenticated `/collab` WebSocket with board-scoped room membership.
- Import contract with stable IDs and validation feedback.
- Adapter contract with `list_devices`, `list_interfaces`, `list_connections`, `sync` and capability declaration.
- No upstream write operations in initial adapter contract.

## 9. Quality attributes and preliminary targets
Targets below are proposed acceptance goals, not demonstrated performance:
- 2–10 simultaneous collaborators per board for initial acceptance testing.
- 50 concurrent users across boards for preliminary load testing.
- 1,000 elements per board with responsive editing on reference hardware.
- One-host restore from a tested database/assets backup.
- No required outbound Internet requests during normal runtime.
- No acknowledged saved edit lost under defined crash/restart tests.
- Clear user indication of disconnected/unsaved status.

## 10. Security staging
**Minimum now:** HTTPS for shared deployments, board authorization, non-public-by-default service, input validation, upload limits, CSRF/CORS policy, safe secrets handling, backup access controls, dependency pinning and no credentials in board JSON.
**Later:** SAML/OIDC, stronger RBAC, encryption at rest, formal audit and compliance alignment.
Deferral of advanced controls does not permit unauthenticated production exposure of sensitive topology.

## 11. Verification and acceptance
See `TEST-PLAN.md`. P0 acceptance requires two-browser collaboration, durable reopen, safe concurrent edits, export/import, restart recovery and no external runtime dependency. P1 requires typed objects and links; P2 requires deterministic import, search, neighbor expansion and source/proposal separation.

## 12. Risks and mitigations
- **Excalidraw protocol/API changes:** pin versions and maintain compatibility tests.
- **Collaboration data loss:** test concurrent editing and checkpoint/recovery; no naive scene overwrite.
- **Imported topology ambiguity:** preserve link type, evidence, provenance and freshness.
- **Diagram refresh disrupts layout:** explicit preview and stable bindings.
- **Sensitive information exposure:** internal deployment, access checks and no public share links by default.
- **Scope creep:** enforce phase exit gates and postpone enterprise features not required for MVP.

## 13. Decisions needing prototype validation
- Whether to adapt upstream `excalidraw-room` protocol or implement a compatible collaboration transport.
- Whether to use SQLite for a prototype or PostgreSQL from day one (PostgreSQL recommended).
- Asset storage approach and maximum board/file sizes.
- Initial identity mechanism (simple local login versus gateway-backed access).
- Visual representation for interface anchors and complex circuits.
- Repository governance beyond the Apache License 2.0 grant (see `docs/DECISIONS.md` D2-019).

## 14. Definition of success
A network team can deploy segl internally, hold a real planning meeting, jointly edit a board, leave, return, recover the board, and export the result. Each subsequent phase adds business value without forcing a rewrite of the canvas or topology model.
