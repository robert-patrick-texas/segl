# Agent rules

## Session start

1. Read `STATUS.md`.
2. Read the single task it names in `TASKS.md`.
3. Read `docs/DECISIONS.md` if the task touches collaboration, auth, storage, packaging, or URLs.
4. Implement that task only.
5. Run the task's acceptance commands. Inspect failures and fix them.
6. Update `TASKS.md` status for that task, then update `STATUS.md`: move the task id into Completed, set Next task to the following id, and append a log line with the date, the commands run, and the result.
7. Stop. Leave the following task for the next session unless the user explicitly asked to continue.

If a task is blocked, leave Next task unchanged, set `Blocked: yes`, and log the blocker and the evidence. Do not skip ahead.

## Authority

- `docs/` is the product manual. `draft2/` is the workbook for the next task. Both override `draft1/`, which is frozen.
- `STATUS.md` overrides any "suggested order" remembered from an older file.
- A locked decision in `docs/DECISIONS.md` stays locked. If the pinned Excalidraw package cannot do what a decision requires, stop, set Blocked, and record the evidence. Do not add a Node collaboration process and do not fork Excalidraw.

## Definition of done for a task

- Acceptance commands exited 0.
- ruff and ty are clean for the Python the task touched.
- The web checks are clean when the task touched `web/`.
- `STATUS.md` and the task status line match the tree that was actually verified.

## Implementation rules

1. Work the requirement ids listed on the task.
2. Pin dependencies. The Python project uses uv, ruff, and ty. The web package uses npm with exact versions and `web/package-lock.json` (D2-023).
3. Python commands go through uv (`uv add`, `uv sync`, `uv run pytest`, `uv run ruff`, `uv run ty`). Do not add a `requirements.txt`. Do not use pip, poetry, or a system virtualenv created by hand.
4. ruff lints and formats. ty type-checks. Both are dev dependencies. The production virtualenv does not need them.
5. Keep Excalidraw calls inside `web/src/canvas/`. The rest of the UI talks to that adapter.
6. Embed the upstream package. Do not modify or vendor its source.
7. Releases follow `docs/RELEASING.md`: every component moves to its newest release, and one is held back only after it fails the tests. Versions live only in `versions.toml`. Add a `CHANGELOG.md` bullet for a source or document change a contributor needs to know about. Write a `journal/YYYY-MM-DD-short-title.md` entry for a story or a lesson, not for every task.
8. The browser application stores preferences in `localStorage`. It does not use cookies. Do not add `Set-Cookie`, session middleware, or credentialed CORS.
9. The edit token, when configured, lives in the server TOML file. Do not put it in scene JSON, logs, the injected page config, or a query string.
10. Slot numbers 1–9 are the only workspaces in this phase. Do not add login, inventory, network symbols, PostgreSQL, a base-path setting, or a production container image.
11. Parameterized SQL only. Internal ids are allocated by the server. A hostname or an Excalidraw element id is not a domain identity.
12. Node builds the frontend. It is not a runtime service. systemd starts Python only.
13. Do not claim a test passed unless that command was run in this session.
14. A task that changes behavior updates the contract page it cites, in the same change.

## Additional notes

- `versions.toml` is the version list. Code that displays or checks a version reads that file. `.python-version`, `pyproject.toml`, `web/.node-version`, and `web/package.json` mirror it.
- Release notes start with one to three sentences, then only the New, Changed, Fixed, and Additional Notes headings that have bullets. The closing table starts with the `cloc` line count of first-party work, then the versions. Transitive dependencies go in a collapsed details block.
- The line count excludes dependency and vendor trees (`node_modules`, virtualenvs, build output, lockfiles, and embedded upstream packages). It includes the source and documents covered by `LICENSE`.
