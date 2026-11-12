# Status

This file is the source of truth for what is done and what to do next. Update it at the end of every task. Do not mark a task complete unless its acceptance commands were run and passed.

- Updated: 2026-11-12
- Phase: P0 collaborative slots
- Next task: T01b
- Completed: T00, T00b, T01
- Blocked: no
- Application code: Python skeleton (`src/segl`), health route only

## Log

- 2026-11-11: Instruction set written from `draft1/` plus the locked decisions in `DECISIONS.md`. No application code exists. The next action is T01 in `TASKS.md`.
- 2026-11-11: Project license locked to Apache License 2.0 (D2-019). `LICENSE` is at the repository root. Next action remains T01.
- 2026-11-11: Release practice locked (D2-020). `versions.toml` is the version list. `scripts/release.py notes` previews the announcement. `cut` waits for the T01 test suite before it changes files. Next action remains T01.
- 2026-11-11: Python pin set to 3.15. PyPI publishing is off until a demoable build; GitHub Releases stay on (D2-020). Contributor manual moved to `docs/`. `draft1/` is frozen and `draft2/` remains the task workbook; both stay in git (D2-021). Next action remains T01.
- 2026-11-11: T00 done. Evidence:
  - `git init -b main`, then a signed-off baseline commit of the specification as received.
  - `gh repo create robert-patrick-texas/segl --public`.
  - `gh api -X PUT repos/robert-patrick-texas/segl/private-vulnerability-reporting` returned `{"enabled":true}`.
  - Decisions: D2-007 (relative mount, no `base_path`), D2-015 (rootful Docker for development), D2-016 (exact pin 3.15.2), and D2-020 (vakr/Sunstone release policy) amended. D2-022 (public repository, DCO) and D2-023 (npm, Node LTS, Vitest, Playwright Test, Prettier) added. T01 split into T01 and T01b.
  - nginx 1.28.3 against `deploy/nginx/` in a scratch prefix: `nginx -t` passed for both site examples.
  - A live run in front of a stub backend returned:
    - `/board` → 301 `/board/`
    - `/board/s/1` reached the backend as `/s/1`, with `Host: dev.example.com:18443`
    - a client-sent `X-Forwarded-For: 6.6.6.6` replaced by `127.0.0.1`
    - `Upgrade: websocket` and `Connection: upgrade` passed through for `/collab`, with no `Connection` header otherwise
    - a 51 MiB POST returned 200 and a 53 MiB POST returned 413
    - `/s/1` outside the prefix was not proxied
    - the host-root site proxied `/s/1`
    - the server block's HSTS header was kept
  - gzip was not exercised; the stub's responses were under `gzip_min_length`.
  - `python3 scripts/release.py check` printed `python cpython 3.15.2: current`.
  - `python3 scripts/release.py notes` printed `| Project lines of code | 1975 |` as the first table row.
  - `cut` refused, as designed, without `pyproject.toml`.
  - The default display names have 190 entries after dropping five.
  - `uvx ruff check scripts/release.py` reports EXE001 and FLY002, and `ruff format --check` wants to rewrap five lines. All of it is in code that predates T00, and the same two findings appear on the baseline commit. The checks ran with ruff's default 88-character lines because the repository has no ruff settings yet. T01's acceptance runs ruff over the whole tree under the project's own settings.
  - Next action T01.
- 2026-11-11: T00b done (documentation site, D2-024), at the user's request. Evidence:
  - `tools/md2html` copied from vakr `99f62e3`, with `--repo-in-index` added. `uv run --with pytest==9.2.0 --with markdown-it-py==4.3.0 --with mdit-py-plugins==0.7.0 pytest tools/md2html` gave 22 passed.
  - md2html's packages moved from markdown-it-py 4.2.0 and mdit-py-plugins 0.6.1 to 4.3.0 and 0.7.0, the newest per `python3 scripts/release.py check`, which now reports both current.
  - `python3 scripts/build_docs.py` rendered 36 Markdown files with 0 broken links and 0 broken HTML images, after two README folder links were pointed at GitHub's tree view.
  - A scratch copy showed a Markdown image and an HTML `<img>` both published from `images/`, a missing `<img>` file failing the build with exit 1, and `<img>` examples in code blocks ignored.
  - Screenshots through the Playwright 1.64.1 container (Chromium's libraries are missing on the host) showed the index opening with the GitHub mark and "segl", and no sideways scroll at 390 px.
  - GitHub Pages was already set to "GitHub Actions" (`build_type: workflow`). `.github/workflows/pages.yml` deploys on push to `main`.
  - Pages run 43142713250 for `96e0fa4` succeeded. https://robert-patrick-texas.github.io/segl/ and `docs/DEVELOPMENT.html`, `docs/DECISIONS.html`, `all-docs.html`, and `draft2/STATUS.html` each answered 200, and the live index opens with the `segl on GitHub` link.
  - Next action remains T01.
- 2026-11-12: T01 done. Evidence, all on commit `5a388ee`:
  - `uv run pytest` gave 58 passed: health (in process, and from a `python -m segl --config` process on a free port), config, both `versions.toml` lookups, the pins, the license header, and md2html's 22.
  - `uv run segl --version` printed `segl 0.0.0`.
  - `.python-version` holds `3.15.2`. `tests/test_pins.py` holds `pyproject.toml` to `versions.toml`: every direct dependency, the version, the license, `requires-python`, the ruff and ty targets, and md2html's inline metadata.
  - `uv run ruff check .` and `uv run ty check` printed `All checks passed!`. `uv run ruff format --check .` printed `18 files already formatted`.
  - `python3 scripts/release.py notes` printed `| Project lines of code | 3485 |` as the first table row. `python3 scripts/release.py check` reported every component current.
  - `docker build -f deploy/Containerfile .` (rootful Docker 29.8.2) ran the suite as the `ubuntu` account: 58 passed on Python 3.15.2. Rootless Docker and Podman were not tried on this host.
  - CI run 43163488454 succeeded: sync, lint, format, types, tests. Pages run 43163488488 succeeded. `python3 scripts/build_docs.py` found 0 broken links.
  - Differences from the task text:
    - The test client's transport is httpx2 2.16.0, not httpx. Starlette 1.10.0 warns that httpx is deprecated there, and vakr and Sunstone use httpx2.
    - hatchling 1.33.0 is the build backend, pinned in `versions.toml` `[python.build]`. `scripts/release.py` reads that table.
    - FastAPI's `/docs`, `/redoc`, and `/openapi.json` are off. `docs/API.md` does not list them, and their absolute URLs would break under a path mount.
    - ruff uses 100-character lines, skips Markdown (it had reformatted a code block in frozen `draft1/API.md`, which was restored), and holds `scripts/` to Python 3.11 syntax for the host's `python3`. `scripts/release.py` was reformatted to these settings, and one long docstring line in `tools/md2html/md2html_nav.py` was rewrapped.
    - `astral-sh/setup-uv` moved from v10.3.2 to v10.3.3 in both workflows.
  - Not listed in `versions.toml`: the uv 0.13.7 image digest in `deploy/Containerfile`. T01b's `check` covers the Actions pins and could cover this one.
  - Next action T01b.
