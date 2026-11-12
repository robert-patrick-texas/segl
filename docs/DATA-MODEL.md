# Data model (MVP)

SQLite, WAL mode, foreign keys on. Migrations are numbered SQL files in `src/segl/migrations/`, applied in order at startup. The repository module, `src/segl/repository.py`, is the only code that runs SQL. A later PostgreSQL implementation must satisfy the same method list.

## Database file and migrations

segl opens the `database` file when it starts, before it listens, and creates the file and its folder when they are missing. The connection uses WAL mode, foreign keys, and `synchronous = FULL`, so a head the UI calls saved is on the disk.

A migration is a file named `NNNN_name.sql`, such as `0001_slots.sql`. The numbers start at `0001` and have no gap. The database keeps the number of the newest file applied to it in `PRAGMA user_version`. Startup applies the files above that number, all in one transaction, so a migration that fails leaves the database as it was. A migration file has no `BEGIN` or `COMMIT` of its own. A released migration is never edited. A schema change is a new file.

When segl stops, on SIGTERM or an interrupt, it closes the database, which folds the write-ahead log back into the one file. After a kill that skips this, the `-wal` and `-shm` files stay beside the database and the next start reads them.

A database whose number is higher than the newest file was written by a newer segl. segl refuses it and changes nothing. Run the newer release, or restore a copy made before it.

The wheel carries the SQL files inside the package, and a test checks that.

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

Startup inserts slots 1–9 with title `Workspace N`, epoch 1, the editor's empty scene, editor label `System`, and `name_counter.next_value = 1`. Rows that already exist are left alone.

The empty scene is `src/segl/empty_scene.json`, which the wheel carries. It is the document the pinned editor itself serializes for storage when its canvas is empty, captured from the running editor in T04, not written by hand:

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "segl",
  "elements": [],
  "appState": {
    "gridSize": 20,
    "gridStep": 5,
    "gridModeEnabled": false,
    "viewBackgroundColor": "#ffffff"
  }
}
```

That is the shape of every stored scene: an Excalidraw JSON document, with the elements, and the part of the editor's state it keeps for storage. Files are not in it (T07). The repository stores the file's JSON without its whitespace. A browser test, `web/e2e/fixture.spec.ts`, gives the editor a slot with no elements and compares what it would store with the file, so a new editor release that changes the document fails the test. `DEVELOPMENT.md` has the command that captures it again.

Before T04, a new head held the placeholder `{"elements":[]}` (`PLACEHOLDER_SCENE`). Startup gives the empty scene to a head that still holds exactly that text with the label `System`, and leaves its epoch as it is. Every other head is left alone.

Times are text in UTC to the millisecond, such as `2026-11-12T09:00:00.000Z`. `slot.updated_at` changes when the title or the epoch does. `slot_head.saved_at` changes when the head is written, and is the `savedAt` the API returns.

If the pinned editor stores images as binary outside the scene document, add a migration for hashed files under `assets_dir` rather than stretching `scene_json` past `max_scene_bytes`. Record that choice in `DECISIONS.md`. The head records each file's editor id and SHA-256 hash, so a new load can fetch the bytes from `/api/v1/assets/{hash}`.

## Repository methods

- `bootstrap()` — migrations and the nine slots.
- `get_slot(n)` / `list_slots()` / `rename_slot(n, title)`.
- `get_head(n)` / `save_head(n, epoch, scene_json, editor_label)`.
- `append_revision(n, epoch, scene_json, author_label)` — returns the new revision number, then deletes oldest rows past the history limit.
- `replace_head(n, scene_json, editor_label)` — the write behind restore and import. Returns the new epoch, the new revision number, and the save time.
- `list_revisions(n)` / `get_revision(n, revision)`. The list is newest first and leaves the scenes out.
- `allocate_display_name(words: Sequence[str]) -> str` — the transaction in `ARCHITECTURE.md`.

`save_head` and `append_revision` refuse a write whose epoch does not match the slot's epoch (`EpochMismatch`), and write nothing. Restore and import go through `replace_head`, which increments the epoch and writes the head and a revision in one transaction.

Revision numbers count up per slot from 1 and are not reused after the oldest rows are deleted. A slot number outside 1–9 raises `InvalidSlot`, and a revision the slot does not have raises `RevisionNotFound`. A database failure raises `StorageError`. `rename_slot` stores the title it is given. The route that calls it trims and checks the title (`API.md`).

The repository holds one connection behind a lock, and every method blocks. HTTP handlers call it from worker threads. Code on the event loop, such as the WebSocket room, calls it through a worker thread.

## Flush and revision rules

- Mark the room dirty on each accepted element mutation.
- Flush the head at least every `head_flush_seconds` (default 0.2) while dirty, when the last connection for that slot closes, and on SIGTERM.
- Skip the write when the JSON is unchanged.
- Append a revision when a flush happens and the newest revision for that slot is at least `history_interval_seconds` old (default 1), or when the reason is last-leave, restore, or import.
- Keep at most `history_limit` revisions per slot (default 50).
- `editor_label` is the display name of the connection that sent the newest mutation in that flush. Use `System` when the server has no connection label.

## Explicitly not created in P0

No `board`, `workspace`, `user`, `session`, `network_object`, `interface`, `network_link`, `data_source`, or `import_run` tables. Protected workspace storage arrives with L-004, in tables that slot queries do not join.
