# Roadmap

Phases are dependency order, not dates. P0 is the task list in `draft2/TASKS.md`. Do not start a later phase by adding tables, routes, or services early.

## P0 — Collaborative slots

Nine Excalidraw slots, live sync, SQLite durability, history, optional access codes, an optional list of internal networks, display labels, the relative mount, dev container, the `/opt/segl` `.deb`, and `segl update`.

**Gate:** `TEST-PLAN.md` rows T-001 through T-021 pass and `draft2/STATUS.md` records the evidence. Next task becomes `NONE`.

The gate passed on 2026-11-13, on commit `00ea07f` (T13).

## P1 — Network objects on a canvas (L-001)

Symbol palette and typed links from the draft1 baseline: cable, circuit, relationship, neighbor, connector. Drawing stays separate from any future inventory record. This phase still uses the open slots or, if P2's workspaces exist, the same canvas adapter. It does not query live network gear.

T15 built the first part on 2026-11-16 (`REQUIREMENTS.md`, N-001 to N-005; D2-038): 12 device kinds and 5 link kinds in the editor's library, a small segl panel, and a letter tag for the state. segl sets no color. Each record rides in its element's `customData`. Named interfaces at a link's ends (draft1 N-006, L-001) come later.

On 2026-11-26 the user put collaboration first and queued three tasks before named interfaces (`draft2/TASKS.md`):

1. T16, history that lasts, and clearing a slot: the newest 50 revisions, then fewer as they age, for a week, and the board as it was before a big delete, a restore, or an import. `segl slot clear N` wipes a slot for good.
2. T17, Diagram mode on slot 9: drawio's editor with live co-editing, and the pen for one editor at a time while the others watch (D2-039). It measures how well co-editing works.
3. T18, follow mode on the whiteboards: click a name and follow that person's view.

Diagram mode's polish comes next, as a task written from T17's decision: History and restore on slot 9, `.drawio` import, and segl's device and link kinds in drawio's library. Then named interfaces, and then P2.

## P2 — Inventory files and protected workspaces (L-002, L-004)

Bearer-token login stored in `localStorage`. This is where real user authentication starts: RADIUS as one option, and SAML or other methods after it. Until then P0's access codes (D2-033) keep editing to people who were given a code, and they authenticate nobody. Some boards may stay open to read without signing in. Named boards at `/{team}/{project}/{board-slug}` with multiple boards per project folder. CSV, JSON, and TOML import into those workspaces only. Slot routes and slot tables do not join to inventory tables. The first path segment `s` remains the slots.

## P3 — Scale-out stores and adapters (L-003, L-006)

A PostgreSQL implementation of the repository interface when a deployment outgrows the single SQLite file. Read-only Nautobot, NetBox, and Checkmk adapters behind the same import boundary. A production container image (L-005) as a second way to install the same `/opt/segl` layout.

## P4 — Enterprise hardening

SSO, encryption at rest, audit retention, and the other deferred controls listed in `draft1/SECURITY.md`. Basic perimeter control, TLS, access codes, `internal_networks`, and the ban on cookies are already in P0 and stay.

## After the gate — send a scene once

Built in T14 (2026-11-16, D2-037). The scene route's answer carries a mark, `hello` hands it back, and the socket's `scene` holds only what changed since. A late browser on a slot of 1,024 elements got a socket `scene` of 92 characters, where the stored scene had 464,739.

- **Not planned.** A browser that keeps a slot's scene between visits, so that a return visit downloads only what changed. That needs storage in the browser, and a mark that outlives a restart of the server.

## Held until a dependency moves

- **TLS 1.3 for the test harness's WebSocket client.** The pytest harness speaks TLS 1.2 to its test nginx and nothing newer (`tests/harness.py`, `running_mount`). The client is the `websockets` package's sync client, 17.4 when the hold was made. It starts a thread that reads the socket before it has written its request, and under TLS 1.3 on a busy machine that request was sometimes lost: 2 of 2,253 handshakes with eight busy processes on four cores, and none of 6,000 over TLS 1.2. nginx then waits a minute for a request that does not come, and the test fails. Where the request is lost, in the client, in Python's `ssl`, or in OpenSSL, was not traced. Nothing segl ships is held: nginx offers TLS 1.3, browsers use it, and the browser tests run over it. When `scripts/release.py upgrade` brings a newer `websockets`, run `uv run python tests/handshake_loop.py 3000 --busy 8 --tls13` a few times. If it loses none, remove the one line that sets `maximum_version`, and this entry.

## Carried forward from draft1

These product rules remain in force when their phase starts:

- segl provides the canvas, and Excalidraw is no longer the only one (2026-11-26, D2-039). Slots 1–8 are Excalidraw whiteboards. Slot 9 is Diagram mode, drawio's editor, from T17. A network object's id is not an element id.
- Observed topology and proposed plans stay distinct.
- Editing a drawing never changes a production network or an upstream inventory system.
- Imported inventory is read-only from the whiteboard.
- One Ubuntu 26.04 host remains a supported deployment.
