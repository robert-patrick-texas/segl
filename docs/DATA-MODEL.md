# Data model (MVP)

SQLite, WAL mode, foreign keys on. Migrations are numbered SQL files in `src/segl/migrations/`, applied in order at startup: `0001_slots.sql`, and `0002_slot_files.sql` for the files of images. The repository module, `src/segl/repository.py`, is the only code that runs SQL. A later PostgreSQL implementation must satisfy the same method list.

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

CREATE TABLE slot_file (
  slot INTEGER NOT NULL REFERENCES slot(number),
  file_id TEXT NOT NULL,
  hash TEXT NOT NULL,
  media_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (slot, file_id)
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

That is the shape of every stored scene: an Excalidraw JSON document, with the elements, and the part of the editor's state it keeps for storage. A stored scene has every element the slot's room holds, the deleted ones included (`isDeleted` true), so that a restart does not forget a deletion and an older copy cannot bring the element back. The other parts of the document, such as `appState`, stay as the head had them: a flush writes the head's own document with the room's elements in it. The bytes of images are not in it (see "The files of images"). The repository stores the file's JSON without its whitespace, and a flush writes ASCII, with every other character as a `\u` escape. A browser test, `web/e2e/fixture.spec.ts`, gives the editor a slot with no elements and compares what it would store with the file, so a new editor release that changes the document fails the test. `DEVELOPMENT.md` has the command that captures it again.

Before T04, a new head held the placeholder `{"elements":[]}` (`PLACEHOLDER_SCENE`). Startup gives the empty scene to a head that still holds exactly that text with the label `System`, and leaves its epoch as it is. Every other head is left alone.

Times are text in UTC to the millisecond, such as `2026-11-12T09:00:00.000Z`. `slot.updated_at` changes when the title or the epoch does. `slot_head.saved_at` changes when the head is written, and is the `savedAt` the API returns.

## The files of images

The pinned editor keeps an image's bytes outside the scene, under a file id of its own, and an image element names that id in `fileId` (D2-028). segl stores the bytes the same way, outside `scene_json`:

- The bytes are a file under `assets_dir`, named by the SHA-256 of its content, 64 lowercase hex digits. The same bytes are stored once, whichever slots use them. A file is written beside its place, synced to the disk, and then moved there.
- `slot_file` says which hash one of a slot's file ids means, and the image type the browser gave. A flush adds the rows for the files named since the last one, in the transaction that writes the head. A row is never changed or deleted: a file id keeps the bytes it was first given, and a revision that names it still finds them.
- A slot's file list, as the API returns it with a scene, is the rows whose file id an element of that scene names. A deleted image still names its file.

Nothing removes a file from `assets_dir`. A backup of segl is the database file and that folder together.

## Repository methods

- `bootstrap()` — migrations and the nine slots.
- `get_slot(n)` / `list_slots()` / `rename_slot(n, title)`.
- `get_head(n)` / `save_head(n, epoch, scene_json, editor_label)`.
- `flush_head(n, epoch, scene_json, editor_label, history_seconds=, files=)` — the write behind a head flush, in one transaction. It writes the head unless the head already holds that scene, adds `files` to the slot's file list, and appends a revision under the rules below. It returns the head's `saved_at`, whether it wrote the head, the new revision number or none, and whether the newest revision now holds the head's scene. A revision for a head that this flush did not write carries the head's own label.
- `list_files(n)` — every file the slot's scenes have named, oldest first.
- `append_revision(n, epoch, scene_json, author_label)` — returns the new revision number, then deletes oldest rows past the history limit.
- `replace_head(n, scene_json, editor_label)` — the write behind restore and import. Returns the new epoch, the new revision number, and the save time. The caller first flushes what the slot's room holds (restore rules below).
- `list_revisions(n)` / `get_revision(n, revision)`. The list is newest first and leaves the scenes out. `GET /api/v1/slots/{n}/revisions` and `.../revisions/{revision}` are these two.
- `allocate_display_name(words: Sequence[str]) -> str` — the transaction in `ARCHITECTURE.md`.

`save_head`, `append_revision`, and `flush_head` refuse a write whose epoch does not match the slot's epoch (`EpochMismatch`), and write nothing. Restore and import go through `replace_head`, which increments the epoch and writes the head and a revision in one transaction.

Revision numbers count up per slot from 1 and are not reused after the oldest rows are deleted. A slot number outside 1–9 raises `InvalidSlot`, and a revision the slot does not have raises `RevisionNotFound`. A database failure raises `StorageError`. `rename_slot` stores the title it is given. The route that calls it trims and checks the title (`API.md`).

The repository holds one connection behind a lock, and every method blocks. HTTP handlers call it from worker threads. Code on the event loop, such as the WebSocket room, calls it through a worker thread.

## Flush and revision rules

A slot's live scene is in its room, in memory, from the first connection to the slot until segl stops (`ARCHITECTURE.md`, collaboration). `src/segl/saver.py` writes it to the head. The title is not part of the scene: `PATCH /api/v1/slots/{n}` stores it at once, through `rename_slot`.

- The room is dirty from an accepted change until a flush has taken its scene. A change is an `elements` batch in which some element won, or a `files` message that named a new file. A batch in which nothing won leaves the room clean.
- A dirty room is flushed `head_flush_seconds` (default 0.2) after it became dirty. Every edit in that time is one write. An edit that arrives while a write is under way is in the next one, `head_flush_seconds` later.
- When the last connection for the slot closes, the room is flushed at once. When segl stops, on SIGTERM or an interrupt, every room is flushed before the database is closed.
- The head is not written when it already holds that scene: the JSON is compared in the transaction, and `saved_at` and `editor_label` stay as they were.
- A flush appends a revision when the newest revision for that slot does not hold this scene and is at least `history_interval_seconds` old (default 1). The flush after the last connection left, and the one when segl stops, append it whatever its age. So the history has at most one row a second while people draw, and always the scene the slot was left with. Restore and import write their own revision (`replace_head`).
- A restore is two writes by the slot's saver, under the lock its flushes take (`ARCHITECTURE.md`, collaboration). First a flush of the room, which appends a revision whatever the age of the newest one, unless the newest already holds that scene. Then `replace_head` with the scene of the chosen revision, which was read before the flush: the flush may be the row that drops it. So after a restore the two newest revisions are the scene that was replaced and the scene put in its place, and restoring the first of them undoes the restore.
- A slot's first revision is the first flush that changes the head. The scene a slot starts with is not history, and a slot someone only looked at gets no row.
- At most `history_limit` revisions per slot are kept (default 50). The 51st drops the oldest.
- `editor_label`, on the head and on the revision, is the display name the connection had when it sent the newest change in that flush, and `System` for a connection without a label. A revision added for a head that an earlier flush wrote, as after a restart, carries that head's label. The revision a restore writes, and the head with it, carry the display name the request gave, or `System`.
- A write that fails is logged with the slot's number and tried again after five seconds. The room stays dirty, and nobody is told `saved` meanwhile. A write that fails while segl is stopping is not tried again.
- After a flush, each connection whose numbered message it held is sent `saved` (`API.md`, WebSocket).

The elements of one slot come to at most `max_scene_bytes` as JSON, each counted as the server writes it. A batch that would take the scene over the limit is refused whole with `scene_too_large`. A batch that makes the scene smaller is always taken, so a slot whose limit was lowered can still be emptied.

## Explicitly not created in P0

No `board`, `workspace`, `user`, `session`, `network_object`, `interface`, `network_link`, `data_source`, or `import_run` tables. Protected workspace storage arrives with L-004, in tables that slot queries do not join.
