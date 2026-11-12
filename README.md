# segl

Self-hosted collaborative whiteboard for network-operations meetings. The first release is nine shared Excalidraw slots on one Ubuntu server: nginx terminates TLS, and one Python process serves the TypeScript application, the API, and the live board.

Slots 1–9 need no account. An optional site-wide edit token can limit who changes a board. Preferences stay in the browser's local storage. Later named workspaces, behind a login, are where network inventory will live. The open slots do not read that data.

**Status:** specification. Application code not started. The manual is [`docs/README.md`](docs/README.md). The next build step is T01 in [`draft2/STATUS.md`](draft2/STATUS.md).

**License:** [Apache License 2.0](LICENSE). Excalidraw remains under its own license.

| | |
|---|---|
| Start here | [`docs/README.md`](docs/README.md) |
| Versions | [`versions.toml`](versions.toml) |
| Changes | [`CHANGELOG.md`](CHANGELOG.md) |
| Contributing | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Vulnerability reports | [`SECURITY.md`](SECURITY.md) |
| Narrative | [`journal/`](journal/) |
