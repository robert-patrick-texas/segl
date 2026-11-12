# Roadmap

Phases are dependency order, not dates. P0 is the task list in `draft2/TASKS.md`. Do not start a later phase by adding tables, routes, or services early.

## P0 — Collaborative slots

Nine Excalidraw slots, live sync, SQLite durability, history, optional edit token, display labels, the relative mount, dev container, and the `/opt/segl` `.deb`.

**Gate:** `TEST-PLAN.md` rows T-001 through T-018 pass and `draft2/STATUS.md` records the evidence. Next task becomes `NONE`.

## P1 — Network objects on a canvas (L-001)

Symbol palette and typed links from the draft1 baseline: cable, circuit, relationship, neighbor, connector. Drawing stays separate from any future inventory record. This phase still uses the open slots or, if P2's workspaces exist, the same canvas adapter. It does not query live network gear.

## P2 — Inventory files and protected workspaces (L-002, L-004)

Bearer-token login stored in `localStorage`. Named boards at `/{team}/{project}/{board-slug}` with multiple boards per project folder. CSV, JSON, and TOML import into those workspaces only. Slot routes and slot tables do not join to inventory tables. The first path segment `s` remains the slots.

## P3 — Scale-out stores and adapters (L-003, L-006)

A PostgreSQL implementation of the repository interface when a deployment outgrows the single SQLite file. Read-only Nautobot, NetBox, and Checkmk adapters behind the same import boundary. A production container image (L-005) as a second way to install the same `/opt/segl` layout.

## P4 — Enterprise hardening

SSO, encryption at rest, audit retention, and the other deferred controls listed in `draft1/SECURITY.md`. Basic perimeter control, TLS, the edit token, and the ban on cookies are already in P0 and stay.

## Held until a dependency moves

- **TLS 1.3 for the test harness's WebSocket client.** The pytest harness speaks TLS 1.2 to its test nginx and nothing newer (`tests/harness.py`, `running_mount`). The client is the `websockets` package's sync client, 17.4 when the hold was made. It starts a thread that reads the socket before it has written its request, and under TLS 1.3 on a busy machine that request was sometimes lost: 2 of 2,253 handshakes with eight busy processes on four cores, and none of 6,000 over TLS 1.2. nginx then waits a minute for a request that does not come, and the test fails. Where the request is lost, in the client, in Python's `ssl`, or in OpenSSL, was not traced. Nothing segl ships is held: nginx offers TLS 1.3, browsers use it, and the browser tests run over it. When `scripts/release.py upgrade` brings a newer `websockets`, run `uv run python tests/handshake_loop.py 3000 --busy 8 --tls13` a few times. If it loses none, remove the one line that sets `maximum_version`, and this entry.

## Carried forward from draft1

These product rules remain in force when their phase starts:

- Excalidraw is the canvas. A network object's id is not an element id.
- Observed topology and proposed plans stay distinct.
- Editing a drawing never changes a production network or an upstream inventory system.
- Imported inventory is read-only from the whiteboard.
- One Ubuntu 26.04 host remains a supported deployment.
