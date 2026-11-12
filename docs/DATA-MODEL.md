# Data model (MVP)

SQLite, WAL mode, foreign keys on. Migrations are numbered SQL files in `src/segl/migrations/`, applied in order at startup. The repository module is the only code that runs SQL. A later PostgreSQL implementation must satisfy the same method list.

## Tables

```sql
CREATE TABLE slot (
  number INTEGER PRIMARY KEY CHECK (number BETWEEN 1 AND 9),
  title TEXT NOT NULL,
  epoch INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE slot_head (
  slot INTEGER PRIMARY KEY REFERENCES slot(number),
  epoch INTEGER NOT NULL,
  scene_json TEXT NOT NULL,
  editor_label TEXT NOT NULL,
  saved_at TEXT NOT NULL
);

CREATE TABLE revision (
  slot INTEGER NOT NULL REFERENCES slot(number),
  revision INTEGER NOT NULL,
  epoch INTEGER NOT NULL,
  scene_json TEXT NOT NULL,
  author_label TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (slot, revision)
);

CREATE TABLE name_counter (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  next_value INTEGER NOT NULL
);
```

Startup inserts slots 1–9 with title `Workspace N`, epoch 1, an empty scene the pinned editor accepts as `initialData`, and `name_counter.next_value = 1`. Capture the empty scene from the editor during T04 and store that fixture in tests. Do not hand-invent a scene schema and call it compatible.

If the pinned editor stores images as binary outside the scene document, add a migration for hashed files under `assets_dir` rather than stretching `scene_json` past `max_scene_bytes`. Record that choice in `DECISIONS.md`. The head records each file's editor id and SHA-256 hash, so a new load can fetch the bytes from `/api/v1/assets/{hash}`.

## Repository methods

- `bootstrap()` — migrations and the nine slots.
- `get_slot(n)` / `list_slots()` / `rename_slot(n, title)`.
- `get_head(n)` / `save_head(n, epoch, scene_json, editor_label)`.
- `append_revision(n, epoch, scene_json, author_label)` — returns the new revision number, then deletes oldest rows past the history limit.
- `list_revisions(n)` / `get_revision(n, revision)`.
- `allocate_display_name(words: Sequence[str]) -> str` — the transaction in `ARCHITECTURE.md`.

`save_head` refuses a write whose epoch does not match the stored epoch. Restore and import go through a method that increments the epoch and writes the head and a revision in one transaction.

## Flush and revision rules

- Mark the room dirty on each accepted element mutation.
- Flush the head at least every `head_flush_seconds` (default 0.2) while dirty, when the last connection for that slot closes, and on SIGTERM.
- Skip the write when the JSON is unchanged.
- Append a revision when a flush happens and the newest revision for that slot is at least `history_interval_seconds` old (default 1), or when the reason is last-leave, restore, or import.
- Keep at most `history_limit` revisions per slot (default 50).
- `editor_label` is the display name of the connection that sent the newest mutation in that flush. Use `System` when the server has no connection label.

## Explicitly not created in P0

No `board`, `workspace`, `user`, `session`, `network_object`, `interface`, `network_link`, `data_source`, or `import_run` tables. Protected workspace storage arrives with L-004, in tables that slot queries do not join.
