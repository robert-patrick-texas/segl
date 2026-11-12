# Contributing

segl is developed in the open under the Apache License 2.0. Excalidraw stays under its own license.

## Before writing code

Read [`draft2/STATUS.md`](draft2/STATUS.md) and do the single task it names. Product behavior is in [`docs/`](docs/README.md). [`draft1/`](draft1/README.md) is frozen history.

Run Python through uv. The version pin and the direct dependency versions live in [`versions.toml`](versions.toml). When you add or upgrade a direct dependency, update that file in the same change. `.python-version` and `pyproject.toml` mirror it.

## Notes that travel with a change

- Add a [`CHANGELOG.md`](CHANGELOG.md) bullet when the change is something another contributor or an operator needs to know.
- Add `journal/YYYY-MM-DD-short-title.md` when the change has a story or a lesson worth keeping. Ordinary tasks do not need a journal entry.
- New source files carry the Apache header from [`draft2/AGENTS.md`](draft2/AGENTS.md).

## Checks

`uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run ty check` cover the Python tree. The web package has its own typecheck once it exists.

A release is `python3 scripts/release.py`, described in [`docs/RELEASING.md`](docs/RELEASING.md). Publishing follows `versions.toml`: GitHub Releases are on, and PyPI stays off until a demoable build. Do not publish `0.0.0`.

Sign commits with `git commit -s` (the Developer Certificate of Origin). A separate contributor license agreement is not required.

## Reporting defects

Use a GitHub issue for defects and ideas. Use the private security path in [`SECURITY.md`](SECURITY.md) for a vulnerability.
