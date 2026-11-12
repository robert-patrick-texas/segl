# Contributing

segl is developed in the open at <https://github.com/robert-patrick-texas/segl> under the Apache License 2.0. Excalidraw stays under its own license.

## Before writing code

Read [`draft2/STATUS.md`](draft2/STATUS.md) and do the single task it names. Product behavior is in [`docs/`](docs/README.md). [`draft1/`](draft1/README.md) is frozen history. The tools a development host needs are in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

Run Python through uv. The version pin and the direct dependency versions live in [`versions.toml`](versions.toml). When you add or upgrade a direct dependency, update that file in the same change. `.python-version`, `pyproject.toml`, `web/.node-version`, and `web/package.json` mirror it.

## License header

New source files start with this header, in the comment syntax of the language. From T01, a test checks first-party source files for it.

```text
Copyright 2026 segl contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

When a dependency's license requires an attribution notice, add it to `NOTICE` in the change that adds the dependency (D2-019).

## Notes that travel with a change

- Add a [`CHANGELOG.md`](CHANGELOG.md) bullet when the change is something another contributor or an operator needs to know.
- Add `journal/YYYY-MM-DD-short-title.md` when the change has a story or a lesson worth keeping. Ordinary tasks do not need a journal entry.

## Checks

The commands are in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md#checks): pytest, ruff, and ty for Python, and the typecheck, Vitest, Prettier, and Playwright for `web/` once it exists. CI runs the same commands.

A release follows [`docs/RELEASING.md`](docs/RELEASING.md): every dependency moves to its newest release unless that release fails the tests. GitHub Releases are on. PyPI stays off until a demoable build. Do not publish `0.0.0`.

Sign commits with `git commit -s` (the Developer Certificate of Origin). A separate contributor license agreement is not required.

## Reporting defects

Use a GitHub issue for defects and ideas. Use the private security path in [`SECURITY.md`](SECURITY.md) for a vulnerability.
