# segl

**Historical baseline, frozen 2026-11-11.** This folder stays in the git repository as the record of the earlier plan. It is not the current specification. The contributor manual is [`docs/`](../docs/README.md). The next implementation task is [`draft2/STATUS.md`](../draft2/STATUS.md).

**Working title:** segl — self-hosted collaborative network whiteboard and topology planning workspace.

**Status:** Draft specification, 2026-11-11. No implementation is claimed.

## Mission
Deliver useful, self-hosted collaborative whiteboarding for network operations teams quickly. Add typed network objects and connections next, then attach diagrams to real-world network inventory and discovery data.

## Delivery priorities
1. **MVP:** Embed Excalidraw in a self-hosted browser application; multi-user collaboration; board persistence, recovery, sharing, and export.
2. **Network modeling:** Reusable network icons, device objects, typed links, and freeform planning.
3. **Data integration:** Start with local PostgreSQL tables and CSV/JSON import; later add pluggable adapters for Nautobot, NetBox, Checkmk, and other sources.
4. **Enterprise hardening:** SAML/OIDC, stronger role management, encryption at rest, advanced audit/compliance controls in a later phase.

## Core principles
- Excalidraw is the canvas, not the source of truth for network objects.
- Observed topology and proposed topology are distinct.
- Editing a drawing never changes a production network or an upstream inventory.
- Local-first deployment: no mandatory SaaS or Internet connection at runtime.
- Fast initial delivery; avoid unnecessary infrastructure.
- Design extension seams now; defer feature implementation until needed.

## Draft documents
- [SSRAS.md](SSRAS.md) — software system requirements and architecture specification.
- [ARCHITECTURE.md](ARCHITECTURE.md) — services, data flow, collaboration and design decisions.
- [REQUIREMENTS.md](REQUIREMENTS.md) — prioritized requirements and acceptance criteria.
- [DATA-MODEL.md](DATA-MODEL.md) — boards, objects, links, external references, scenarios.
- [API.md](API.md) — proposed HTTP/WebSocket and adapter contracts.
- [SECURITY.md](SECURITY.md) — minimum safeguards and later federal features.
- [ROADMAP.md](ROADMAP.md) — milestones, gates and definition of done.
- [AGENTS.md](AGENTS.md) — instructions for AI coding agents.
- [TEST-PLAN.md](TEST-PLAN.md) — critical tests and verification.
- [DECISIONS.md](DECISIONS.md) — confirmed design direction and unresolved choices.

## Proposed stack (not yet validated)
React + TypeScript + Vite + `@excalidraw/excalidraw`; TypeScript/Node collaboration service; Python/FastAPI application and topology API; PostgreSQL; Nginx; Docker Compose or Podman on Ubuntu 26.04 LTS.

## Quick-start target
Eventually: clone repository, configure local environment, run one deployment command, open an internal HTTPS URL, create a board, invite a second user, collaborate, reload and recover.

**License:** Apache License 2.0 for segl. See `LICENSE` and `docs/DECISIONS.md` D2-019. Excalidraw remains under its own license.
