# Test plan

P0 is done when every row below has been run and recorded in `draft2/STATUS.md`, with the command, the environment, and the result. T11 automates the browser rows in the dev container. T10b added T-019 and T-020 after the list was numbered, so they follow T-018. T02 and T03 cover the rows that pytest can reach without a browser. T12 records the install rows.

| ID | Covers | Pass condition |
|---|---|---|
| T-001 | S-002 | Two browser contexts on slot 1: a rectangle drawn in one appears in the other. |
| T-002 | S-002 | Both contexts edit different elements at the same time. Both elements remain. |
| T-003 | S-002 | One context deletes an element the other context just moved. The tombstone wins and the element stays gone after reload. |
| T-004 | S-013 | Kill the socket. The UI shows disconnected. Restore the socket. Edits made while down reconcile, and a newer server edit is not discarded. |
| T-005 | S-003, S-004 | Draw on slot 2, close both browsers, open slot 2 again. The drawing is there. Slot 1 is unchanged. |
| T-006 | S-004 | After the UI shows saved, stop the process and start it. The head scene matches. |
| T-007 | S-012 | Place an image. A second context already open on the slot shows it without reloading. Reach saved, restart, load the slot in a fresh context. The image renders. |
| T-008 | S-008 | With `access_codes` set, a client without a pass sees live edits and cannot change elements, the title, or history. A client whose browser was issued a pass for an access code can. With no codes, both clients can edit. `web/e2e/access.spec.ts` runs it in two browser contexts against a second test server that has a code, directly and through nginx at both mounts. |
| T-009 | S-011 | Export Excalidraw JSON, clear the slot by restoring an empty revision or importing an empty document, import the file. The drawing returns and a new revision exists. `web/e2e/import.spec.ts` runs it in two browser contexts: the editor's own export, of a drawing with an image, then an empty document to clear the slot, then the file. `tests/test_import.py` runs it at the socket and across a kill of the server, and holds what the route refuses and its limits. |
| T-010 | S-014 | With outbound network blocked, the slot page still paints the editor. |
| T-011 | S-005 | Produce more than one revision, restore an older one, and see every connected client switch. Restore the pre-restore revision and the later drawing returns. The 51st revision drops the oldest. `web/e2e/history.spec.ts` runs it in two browser contexts through the History control. `tests/test_history.py` runs it at the socket, and holds the 51st revision and a restore of the oldest revision of a full history. |
| T-012 | S-007 | Walk health, config, slots, scene, display-name, a view-only mutation, and a WebSocket handshake. No response includes `Set-Cookie`. A mutation and a WebSocket upgrade whose `Origin` does not match `Host` are refused with `bad_origin`. |
| T-013 | S-006 | nginx runs the `deploy/nginx/` files on a loopback port in front of the test server. At `/board/`: `/board` redirects to `/board/`, `/board/api/v1/health` answers, `/board/s/1` renders the slot, two contexts sync over `/board/collab`, and the page requests nothing outside `/board/`. The same build passes the same checks at a host root (`location /`). T02 covers the HTTP part, T04 the page, and T06 the WebSocket. |
| T-014 | S-009 | Against a temp word file `Guest` / `Staff`, three fresh clients receive `Guest1`, `Staff2`, `Guest3`. A stored label is not replaced on reload. A rename of `john smith` is broadcast as `John Smith`. Through nginx, 31 allocations from one address within a minute, each sending a different `X-Forwarded-For`, are limited at 30. T05 covers all of it except the broadcast: there the rename is shown as `John Smith` in the browser that made it. T06 covers the broadcast. |
| T-015 | S-010 | Two connections on slot 3 show count 2 and both labels. Closing one drops the count to 1. Slot 1's count does not include them. |
| T-016 | S-003 | `PATCH` title on slot 4 is visible to a second browser. Slots have no create or delete route. |
| T-017 | S-015 | On Ubuntu 26.04 the `.deb` places the interpreter under `/opt/segl/python`, the unit is active, and nginx proxies a TLS request to a slot page. |
| T-018 | S-017 | The dev container runs T-001 through T-016, T-019, and T-020 without using the host's system Python for the app. |
| T-019 | S-008 | A viewer follows the bar's link to the access page, enters a code, and edits on the slot it came from. A wrong code is answered in words, and the sixth try after five wrong ones from one address is refused with `rate_limited`. A pass is refused when no listed code signed it, when it was issued before `access_passes_after`, when it is from more than five minutes ahead, and when it is older than `access_pass_hours`. A pass that ends while its socket is open leaves that browser a viewer until a code is entered again. `web/e2e/access.spec.ts` and `web/e2e/expiry.spec.ts` run the page, and `tests/test_access.py` the codes, the passes with a clock the test moves, the count of wrong codes, and each gate. |
| T-020 | S-018 | With `internal_networks` set, an address outside it gets `403` with `outside_network` for the health route, a page, a mutation, and a WebSocket handshake, and an address inside it, loopback among them, is answered as ever. `tests/test_networks.py` runs it in process and against a real process that is sent `X-Forwarded-For` from a trusted address. |

Preliminary sizes, as targets for a fixture rather than a tuning project: 2 concurrent editors on one slot is the gate; 10 is the stretch case to try once during T11 and record, not to block the gate. A 1,000-element fixture should still load and sync. Do not spend the MVP on horizontal scaling.

## Evidence

For the gate task, append to `draft2/STATUS.md`: environment, git revision, Python pin, Excalidraw version, commands, and any failed row. A failed row leaves Next task on the task that owns the defect.
