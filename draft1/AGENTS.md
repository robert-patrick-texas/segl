# AI development instructions — segl

## Mission and priorities
Implement a self-hosted collaborative Excalidraw whiteboard first. Network icons and typed links second. Local CSV/JSON/database topology third. External integrations and advanced enterprise security later.

## Rules
1. Read `README.md`, `SSRAS.md`, `REQUIREMENTS.md`, `ARCHITECTURE.md`, `DATA-MODEL.md` and `DECISIONS.md` before proposing structural changes.
2. Work in small, reviewable increments; identify the requirement IDs addressed.
3. Do not claim implementation or tests passed unless actually run.
4. **Never delete existing code when editing.** Comment out superseded logic with an explanation and create a follow-up cleanup item; preserve history through version control.
5. Embed upstream Excalidraw; do not fork or modify upstream source without explicit approval.
6. Pin dependencies and verify compatibility against upstream docs/code.
7. Do not invent Excalidraw collaboration API compatibility; prove it with tests.
8. Do not store network device credentials in scene JSON, logs or frontend.
9. Treat imported inventory as read-only and keep planned changes separate.
10. No production network writeback or SSH/SNMP actions from the browser.
11. Use stable internal UUIDs; hostnames and canvas element IDs are not canonical device identities.
12. Provide migrations for schema changes and tests for data compatibility.
13. Keep a one-host Ubuntu 26.04 LTS deployment working.
14. Update relevant documentation and acceptance tests with every feature.
15. Flag security implications and any deferred control explicitly.

## Suggested repository structure
```text
segl/
  apps/web/                 # React + Excalidraw
  services/api/             # FastAPI
  services/collab/          # TypeScript WebSocket
  packages/canvas-adapter/  # Excalidraw bindings
  packages/network-schema/  # Shared typed contracts
  integrations/             # CSV, JSON, Nautobot, NetBox, Checkmk
  deploy/                   # Compose, Nginx, systemd examples
  docs/                     # Specifications and user/admin docs
  tests/                    # E2E, integration, fixtures
```

## Change workflow
- State objective, affected requirements, assumptions and affected files.
- Implement the smallest vertical slice.
- Run lint/typecheck/unit/integration/browser tests applicable to change.
- Inspect failures and resolve them rather than suppressing tests.
- Summarize changed files, commands run, test results, known risks and next task.
- Never report an untested feature as complete.

## Initial task queue
1. Create monorepo skeleton and deployment smoke test.
2. Embed Excalidraw with offline assets.
3. Prototype two-browser collaboration and persistence.
4. Add board CRUD, durable revisions and basic access checks.
5. Write browser E2E recovery tests.
6. Only then begin network object palette.

## Required quality gates
- Browser collaboration does not silently lose acknowledged changes.
- Unauthorized API/WebSocket access denied.
- Board assets survive restart and export/import.
- CSV/JSON imports are deterministic and idempotent.
- Topology refresh never silently changes planned state.
