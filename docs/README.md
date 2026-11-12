# segl documentation

Contributor and operator manual. The agent task queue is [`draft2/STATUS.md`](../draft2/STATUS.md). [`draft1/`](../draft1/README.md) is the frozen earlier baseline and is not the current specification.

| Document | What it answers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How nginx, Python, the browser, and SQLite operate together |
| [REQUIREMENTS.md](REQUIREMENTS.md) | What the MVP must do, and what is later |
| [DECISIONS.md](DECISIONS.md) | Locked choices, including Python 3.15 and GitHub-only publishing for now |
| [API.md](API.md) | HTTP and WebSocket contract |
| [DATA-MODEL.md](DATA-MODEL.md) | SQLite tables and the repository seam |
| [SECURITY.md](SECURITY.md) | Product controls for the open slots |
| [DEPLOY.md](DEPLOY.md) | `/opt/segl`, systemd, and nginx |
| [RELEASING.md](RELEASING.md) | Versions, release notes, and publish destinations |
| [TEST-PLAN.md](TEST-PLAN.md) | Acceptance tests |
| [ROADMAP.md](ROADMAP.md) | Phases after the nine-slot MVP |

Vulnerability reports use the root [`SECURITY.md`](../SECURITY.md), not the product document in this folder.

The repository is public. `draft1/`, `draft2/`, and `docs/` are all committed. Git ignores secrets and build output: a local `segl.toml` (it can hold the edit token), virtualenvs, `node_modules`, databases, and `dist/`.
