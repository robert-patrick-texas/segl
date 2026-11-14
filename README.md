<img width="1672" height="941" alt="SEGL: Map the network. Draw the future. A longship crew and two figures of light chart a glowing network together on a shared map, under a sail drawn with the same network" src="images/segl-sailing-the-living-network.png" />

# segl

Self-hosted collaborative whiteboard for network-operations meetings. The first release is nine shared Excalidraw slots on one Ubuntu server: nginx terminates TLS, and one Python process serves the TypeScript application, the API, and the live board. nginx can give segl a host name of its own or a path on an existing site, such as `https://dev.example.com/board/s/1` for slot 1.

Slots 1–9 need no account. Optional access codes can limit who changes a board, and an optional list of internal networks who reaches one. Preferences stay in the browser's local storage. Later named workspaces, behind a login, are where network inventory will live. The open slots do not read that data.

**Status:** the MVP is built, and its whole test plan passed on 2026-11-13. It is not released yet. The Python service exists: it reads its settings, keeps the nine slots in SQLite, and serves them over HTTP. The browser application exists too: each slot opens as an Excalidraw canvas under the segl bar, from the same build at a host root and through nginx at `/board/`. Each browser is given a display name, such as `Alpha1`, keeps it, and can change it. People on the same slot see each other's edits, cursors, and names live, and share the slot's title. What is drawn is saved: the bar says `Saving…` and then `Saved`, an image placed on the canvas reaches the other browsers, and both are still there after segl restarts. The server keeps the latest 50 revisions of each slot. The bar's History lists them, and any of them can be put back for everyone on the slot, which can itself be undone. A slot can be saved as an Excalidraw file from the editor's menu, and the bar's Import puts such a file in place of a slot's canvas for everyone, which the History can undo. When the site sets access codes, a browser watches live and cannot change anything until a person enters a code on the access page, which is not a login and knows no user. The site can also list its internal networks, and segl then answers no other address. A `.deb` installs all of it on Ubuntu 26.04, under `/opt/segl` with a Python of its own and a systemd unit, behind the site's nginx. `deploy/debian/build-deb.sh` builds it, and [`deploy/OPERATOR.md`](deploy/OPERATOR.md) says how to install and run it. An installed segl updates itself from signed releases with `segl update`, by hand or from a nightly timer that is off until the site turns it on, and goes back to the previous version when an update fails. No release has been published. [`draft2/STATUS.md`](draft2/STATUS.md) logs each finished build step, with the evidence of that test run. The manual is [`docs/README.md`](docs/README.md).

**License:** [Apache License 2.0](LICENSE). Excalidraw remains under its own license.

| | |
|---|---|
| Repository | <https://github.com/robert-patrick-texas/segl> |
| Start here | [`docs/README.md`](docs/README.md) |
| Documentation site | <https://robert-patrick-texas.github.io/segl/> |
| Development | [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) |
| Install | [`deploy/OPERATOR.md`](deploy/OPERATOR.md) and [`docs/DEPLOY.md`](docs/DEPLOY.md#the-package) |
| Update | [`docs/DEPLOY.md`](docs/DEPLOY.md#updates) |
| nginx | [`deploy/nginx/`](https://github.com/robert-patrick-texas/segl/tree/main/deploy/nginx) and [`docs/DEPLOY.md`](docs/DEPLOY.md#nginx) |
| Versions | [`versions.toml`](versions.toml) |
| Changes | [`CHANGELOG.md`](CHANGELOG.md) |
| Contributing | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Vulnerability reports | [`SECURITY.md`](SECURITY.md) |
| Narrative | [`journal/`](https://github.com/robert-patrick-texas/segl/tree/main/journal) |
