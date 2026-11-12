<img width="1672" height="941" alt="SEGL: Map the network. Draw the future. A longship crew and two figures of light chart a glowing network together on a shared map, under a sail drawn with the same network" src="images/segl-sailing-the-living-network.png" />

# segl

Self-hosted collaborative whiteboard for network-operations meetings. The first release is nine shared Excalidraw slots on one Ubuntu server: nginx terminates TLS, and one Python process serves the TypeScript application, the API, and the live board. nginx can give segl a host name of its own or a path on an existing site, such as `https://dev.example.com/board/s/1` for slot 1.

Slots 1–9 need no account. An optional site-wide edit token can limit who changes a board. Preferences stay in the browser's local storage. Later named workspaces, behind a login, are where network inventory will live. The open slots do not read that data.

**Status:** specification. Application code not started. T00, the repository and pre-build decisions, is done. The next build step is T01 in [`draft2/STATUS.md`](draft2/STATUS.md). The manual is [`docs/README.md`](docs/README.md).

**License:** [Apache License 2.0](LICENSE). Excalidraw remains under its own license.

| | |
|---|---|
| Repository | <https://github.com/robert-patrick-texas/segl> |
| Start here | [`docs/README.md`](docs/README.md) |
| Documentation site | <https://robert-patrick-texas.github.io/segl/> |
| Development | [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) |
| nginx | [`deploy/nginx/`](https://github.com/robert-patrick-texas/segl/tree/main/deploy/nginx) and [`docs/DEPLOY.md`](docs/DEPLOY.md#nginx) |
| Versions | [`versions.toml`](versions.toml) |
| Changes | [`CHANGELOG.md`](CHANGELOG.md) |
| Contributing | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Vulnerability reports | [`SECURITY.md`](SECURITY.md) |
| Narrative | [`journal/`](https://github.com/robert-patrick-texas/segl/tree/main/journal) |
