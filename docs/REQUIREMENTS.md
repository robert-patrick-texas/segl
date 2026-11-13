# Requirements

Priority **M** is required for the MVP gate. **L** is recorded so it is not built early. Draft1 ids are noted where the meaning changed.

## P0 — nine-slot collaborative whiteboard

| ID | Pri | Requirement | Acceptance |
|---|---|---|---|
| S-001 | M | Embedded Excalidraw | The slot page shows the upstream editor inside the segl bar. Canvas tools remain usable. |
| S-002 | M | Live collaboration | Two browsers on the same slot see each other's element edits and cursors. |
| S-003 | M | Nine persistent slots | Slots 1–9 exist after first startup. Each has its own scene and title. Users cannot create or delete slots. |
| S-004 | M | Restart recovery | After the process is killed once the UI says saved, the head scene returns on reload. |
| S-005 | M | History | The latest 50 revisions per slot can be listed and restored. Restore updates every connected browser and can itself be restored. |
| S-006 | M | Mount path | The same build works at a host root (`/s/1`) and under a path a proxy strips (`https://dev.example.com/board/s/1`). No setting names the path, and the page requests nothing outside it. |
| S-007 | M | No cookies | No MVP response sets `Set-Cookie`. Preferences and the pass an access code buys live in `localStorage`. |
| S-008 | M | Optional access codes | With no access codes, every viewer can edit. With one or more, viewers still follow live, and scene, title, restore, import, and asset writes need a pass. A browser is issued a pass when a person enters one of the codes on the access page, and enters a code again when the pass has ended. Nobody is authenticated: a pass says that someone knew a code (D2-033). |
| S-009 | M | Display labels | A new browser receives `WordN` from the name file and the server counter, keeps it, and can rename it with title case. |
| S-010 | M | Presence list | The menu count equals current WebSocket connections on this slot. Activating it lists their labels. |
| S-011 | M | JSON round-trip | A scene exported to Excalidraw JSON and imported back restores the drawing, bumps the epoch, and writes a revision. |
| S-012 | M | Embedded image | An image on the canvas appears in the other open browsers on the slot, and survives process restart and a new browser load. |
| S-013 | M | Connection state | The UI shows connecting, live, saving, saved, and disconnected. Reconnect reconciles without a blind overwrite. |
| S-014 | M | Self-hosted runtime | With outbound network blocked, a loaded slot still renders the editor and previously saved scene. Fonts and assets are local. |
| S-015 | M | Ubuntu install | A `.deb` installs uv-pinned CPython and the app under `/opt/segl`. systemd runs it. nginx proxies TLS to it. |
| S-016 | M | Shared notice | Every slot shows that the workspace is shared and open. View-only clients also show that editing is locked. |
| S-017 | M | Dev container | The dev container runs the automated test suite, including the two-browser cases, under rootful Docker, rootless Docker, or rootless Podman. |
| S-018 | M | Internal networks | With `internal_networks` set, segl answers no request and no WebSocket handshake from an address outside those networks. Loopback is inside. With the list empty, segl answers every address. |

## Later — do not implement in P0

| ID | Requirement |
|---|---|
| L-001 | Network symbol palette, typed links, and observed-versus-planned styling (draft1 N-001–N-006). |
| L-002 | CSV, JSON, and TOML inventory import. Slot APIs never read that data. |
| L-003 | PostgreSQL repository implementation, when a deployment outgrows SQLite. |
| L-004 | Login with a bearer token in `localStorage`, and protected boards at `/{team}/{project}/{board-slug}`. |
| L-005 | Production container image as a second install method beside the `.deb`. |
| L-006 | Enterprise SSO, encryption-at-rest policy, and external adapters (Nautobot, NetBox, Checkmk). |

Draft1 W-005 (arbitrary board CRUD) and W-008 (authentication required before any access) are not MVP requirements. D2-005 and D2-009 replace them.
