# Data model (MVP)

SQLite, WAL mode, foreign keys on. Migrations are numbered SQL files in `src/segl/migrations/`, applied in order at startup: `0001_slots.sql`, `0002_slot_files.sql` for the files of images, `0003_lasting_history.sql`, which compresses each revision's scene and adds its mark (T16), and `0004_diagram_slot.sql`, which makes slot 9 Diagram mode (T17). The repository module, `src/segl/repository.py`, is the only code that runs SQL. A later PostgreSQL implementation must satisfy the same method list.

## Database file and migrations

segl opens the `database` file when it starts, before it listens, and creates the file and its folder when they are missing. The connection uses WAL mode, foreign keys, and `synchronous = FULL`, so a head the UI calls saved is on the disk.

A migration is a file named `NNNN_name.sql`, such as `0001_slots.sql`. The numbers start at `0001` and have no gap. The database keeps the number of the newest file applied to it in `PRAGMA user_version`. Startup applies the files above that number, all in one transaction, so a migration that fails leaves the database as it was. A migration file has no `BEGIN` or `COMMIT` of its own. A released migration is never edited. A schema change is a new file. The connection that runs them has two functions of segl's own. `segl_zstd(text)` returns the text compressed as a revision stores it, and `0003` calls it on every revision that exists. `segl_empty_diagram()` returns slot 9's empty head, and `0004` calls it.

`0004` drops slot 9's whiteboard: its revisions and its rows in `slot_file` are deleted, and its head gets the empty diagram, with the label `System`, at the next epoch. Its title stays. It removes no file under `assets_dir`, since a migration changes only the database: bytes another slot still names stay, and so do bytes only slot 9 named, which no slot names afterwards. No site held data to keep (D2-039).

`0003` builds the revision table again: it renames the old one, makes the new one, copies each row with its scene compressed, and drops the old one. SQLite keeps the pages it freed in the file and uses them again, so the file does not shrink by itself. A `VACUUM`, with segl stopped, gives them back to the disk.

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
  author_label TEXT NOT NULL,
  created_at TEXT NOT NULL,
  kept TEXT CHECK (kept IN ('delete', 'restore', 'import')),
  scene_zstd BLOB NOT NULL,
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

`revision.scene_zstd` is the scene's text, compressed with zstd from Python's own library (`compression.zstd`). The head stays plain JSON text. `revision.kept` is why segl kept that revision ("Which revisions stay", below), or null.

Startup inserts slots 1–9 with title `Workspace N`, epoch 1, the editor's empty scene, editor label `System`, and `name_counter.next_value = 1`. Slot 9's head is the empty diagram in its place ("Slot 9's diagram", below). Rows that already exist are left alone.

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

## Slot 9's diagram

Slot 9 is Diagram mode (D2-039). Its head, and each of its revisions, is a JSON document that holds drawio's XML: `{"diagram":"<mxfile>…</mxfile>"}`, as ASCII JSON text, with no elements and no files. The server never reads the XML. A new or cleared slot 9 holds the empty diagram, `segl.diagram.EMPTY_DIAGRAM`: one page, whose id is `segl-page-1`. Every browser loads the same text, so a patch names a page each one has.

slot 9's room keeps a copy of the diagram, which a browser sent, and the number of the newest patch it holds (`ARCHITECTURE.md`, Diagram mode). The saver writes that copy as it writes a whiteboard's scene, by the rules below, with the display name behind the newest change. A copy is dirty from the moment the room keeps it until a flush takes it. A diagram has no elements, so no flush keeps the board before a big delete, and the head's `max_scene_bytes` is the copy's size as JSON text.

## The files of images

The pinned editor keeps an image's bytes outside the scene, under a file id of its own, and an image element names that id in `fileId` (D2-028). segl stores the bytes the same way, outside `scene_json`:

- The bytes are a file under `assets_dir`, named by the SHA-256 of its content, 64 lowercase hex digits. The same bytes are stored once, whichever slots use them. A file is written beside its place, synced to the disk, and then moved there.
- `slot_file` says which hash one of a slot's file ids means, and the image type the browser gave. A flush adds the rows for the files named since the last one, in the transaction that writes the head. A row is never changed: a file id keeps the bytes it was first given, and a revision that names it still finds them. Only a clear deletes rows ("Clearing a slot", below).
- A slot's file list, as the API returns it with a scene, is the rows whose file id an element of that scene names. A deleted image still names its file.

Only `segl slot clear` removes a file from `assets_dir`: one that no slot names once the cleared slots' rows are gone. A backup of segl is the database file and that folder together.

## Repository methods

- `bootstrap()` — migrations and the nine slots.
- `get_slot(n)` / `list_slots()` / `rename_slot(n, title)`.
- `get_head(n)` / `save_head(n, epoch, scene_json, editor_label)`.
- `flush_head(n, epoch, scene_json, editor_label, history_seconds=, files=, before_delete=)` — the write behind a head flush, in one transaction. It writes the head unless the head already holds that scene, adds `files` to the slot's file list, and appends a revision under the rules below. `before_delete` keeps the head's scene first: the saver works out when. It returns the head's `saved_at`, whether it wrote the head, the new revision number or none, and whether the newest revision now holds the head's scene. A revision for a head that this flush did not write carries the head's own label.
- `list_files(n)` — every file the slot's scenes have named, oldest first.
- `append_revision(n, epoch, scene_json, author_label)` — returns the new revision number, then deletes the rows the rules no longer keep.
- `replace_head(n, scene_json, editor_label, files=, kept=)` — the write behind restore and import. `files` are the ones an import brought, added to the slot's file list in the same transaction. `kept` is `restore` or `import`, which marks the revision of the scene that goes. Returns the new epoch, the new revision number, and the save time. The caller first flushes what the slot's room holds (restore rules below).
- `list_revisions(n)` / `get_revision(n, revision)`. The list is newest first and leaves the scenes out. Each row has its mark, `kept`. `GET /api/v1/slots/{n}/revisions` and `.../revisions/{revision}` are these two.
- `allocate_display_name(words: Sequence[str]) -> str` — the transaction in `ARCHITECTURE.md`.
- `slot_contents(n)` / `hashes_named_outside(slots)` / `clear_slot(n)` — what `segl slot clear` counts, and its write ("Clearing a slot", below).

`save_head`, `append_revision`, and `flush_head` refuse a write whose epoch does not match the slot's epoch (`EpochMismatch`), and write nothing. Restore and import go through `replace_head`, which increments the epoch and writes the head and a revision in one transaction.

Revision numbers count up per slot from 1 and are not reused after older rows are deleted. A clear deletes them all, so the slot's numbers start again from 1. A slot number outside 1–9 raises `InvalidSlot`, and a revision the slot does not have raises `RevisionNotFound`. A database failure raises `StorageError`. `rename_slot` stores the title it is given. The route that calls it trims and checks the title (`API.md`).

The repository holds one connection behind a lock, and every method blocks. HTTP handlers call it from worker threads. Code on the event loop, such as the WebSocket room, calls it through a worker thread.

## Flush and revision rules

A slot's live scene is in its room, in memory, from the first connection to the slot until segl stops (`ARCHITECTURE.md`, collaboration). `src/segl/saver.py` writes it to the head. The title is not part of the scene: `PATCH /api/v1/slots/{n}` stores it at once, through `rename_slot`.

- The room is dirty from an accepted change until a flush has taken its scene. A change is an `elements` batch in which some element won, or a `files` message that named a new file. A batch in which nothing won leaves the room clean.
- A dirty room is flushed `head_flush_seconds` (default 0.2) after it became dirty. Every edit in that time is one write. An edit that arrives while a write is under way is in the next one, `head_flush_seconds` later.
- When the last connection for the slot closes, the room is flushed at once. When segl stops, on SIGTERM or an interrupt, every room is flushed before the database is closed.
- The head is not written when it already holds that scene: the JSON is compared in the transaction, and `saved_at` and `editor_label` stay as they were.
- A flush appends a revision when the newest revision for that slot does not hold this scene and is at least `history_interval_seconds` old (default 1). The flush after the last connection left, and the one when segl stops, append it whatever its age. So the history has at most one row a second while people draw, and always the scene the slot was left with. Restore and import write their own revision (`replace_head`).
- A restore is two writes by the slot's saver, under the lock its flushes take (`ARCHITECTURE.md`, collaboration). First a flush of the room, which appends a revision whatever the age of the newest one, unless the newest already holds that scene. Then `replace_head` with the scene of the chosen revision, which was read before the flush: the flush may be the row that drops it. The second write marks the newest revision `restore`, in its own transaction, when that revision holds the scene being replaced, whether the first write added it or it was there already. So a restore whose second write fails marks nothing. So after a restore the two newest revisions are the scene that was replaced and the scene put in its place, and restoring the first of them undoes the restore.
- An import is the same two writes (D2-031), and its second marks the scene being replaced `import`. The scene of the second is the slot's own stored document with the imported elements in its list, in drawing order. The bytes of the files the document carried are written under `assets_dir` first, and the file ids the slot did not have join `slot_file` in the second write, `replace_head`. An import whose second write fails leaves the bytes, which no scene names, and nothing else.
- A slot's first revision is the first flush that changes the head. The scene a slot starts with is not history, and a slot someone only looked at gets no row.
- Each write that adds a revision, or marks one kept, then deletes what the rules in "Which revisions stay" no longer keep.
- When a flush would leave fewer than 90% of the live elements the head holds (elements whose `isDeleted` is not true), the head's scene is kept first. If the newest revision holds it, that row is marked `delete`. If not, the head's scene becomes a revision marked `delete`, with the head's own label. The flush then writes the head, and a revision of its own scene whatever the newest one's age. The saver works out the drop from the elements in the room and the count it keeps for the head, so the flush reads no JSON for it. Nine of ten is 90%: nothing more is kept. A drop made in several small flushes is compared one flush at a time.
- `editor_label`, on the head and on the revision, is the display name the connection had when it sent the newest change in that flush, and `System` for a connection without a label. A revision added for a head that an earlier flush wrote, as after a restart, carries that head's label. The revision a restore or an import writes, and the head with it, carry the display name the request gave, or `System`.
- A write that fails is logged with the slot's number and tried again after five seconds. The room stays dirty, and nobody is told `saved` meanwhile. A write that fails while segl is stopping is not tried again.
- After a flush, each connection whose numbered message it held is sent `saved` (`API.md`, WebSocket).

The elements of one slot come to at most `max_scene_bytes` as JSON, each counted as the server writes it. A batch that would take the scene over the limit is refused whole with `scene_too_large`. A batch that makes the scene smaller is always taken, so a slot whose limit was lowered can still be emptied.

## Which revisions stay

Each write that adds or marks a revision applies these rules to the slot's revisions, in the same transaction (`src/segl/retention.py`). A revision stays when any rule keeps it:

- It is one of the newest `history_limit` (default 50).
- It is the newest revision of its clock minute, and that minute is one of the last 60, the current one with them. So a person finds the board as it was in each minute of the last hour.
- It is the newest of its clock hour, and that hour is one of the last 24, the current one with them.
- It is the newest of its clock day, and that day is one of the last 7, today with them.
- It is marked kept, it is less than a week old, and it is one of the slot's 20 newest marked revisions. So the 21st drops the oldest kept one.

Minutes, hours, and days are UTC clock ones, from `created_at`. Newest means the highest revision number. A revision from after the time of the write, as after a clock that went back, counts as now. The rest go. A slot nobody draws on keeps what it had, since only a write applies the rules.

A mark says why segl kept the revision: `delete`, `restore`, or `import`, the write that came after its scene. A row keeps its mark after the week or the 20, while another rule keeps the row. The History control shows it as `Before delete`, `Before restore`, or `Before import`.

At most, a slot that is drawn on all week keeps 50 + 60 + 24 + 7 revisions, fewer where they overlap, and 20 marked ones. Measured on one slot of 1,024 elements, a scene of 500 KB, with a full history (T16): 135 revisions took 7.1 MiB, where 0.5.0's 50 took 24.9 MiB. A flush that adds a revision took 3.2 ms, where it took 2.4 ms, and reading the history list 0.2 ms, where it took 8.1 ms. The scene is the table's last column, so a read of the other columns does not walk its pages.

## Clearing a slot

`segl slot clear N` empties slots for good (`DEPLOY.md`, clearing a slot). `clear_slot(n)` does it in one transaction for each slot:

- The slot's revisions and its rows in `slot_file` are deleted.
- The head gets the empty scene, or slot 9 the empty diagram, with the label `System`.
- The title goes back to `Workspace N`, and the epoch goes up by one, as a restore's does.

It returns the new epoch, and the hashes no row of any slot names now. The command then deletes those files under `assets_dir`. So a file another slot names stays, and slots cleared in one command take the files only they named.

The epoch is what a browser that was open on the slot meets when it reconnects: the server's scene is of another epoch, so the page puts the empty board in place of its own, and sends nothing of the old one (`takeScene` in `web/src/collab/session.ts`). An edit it still sends for the old epoch is answered with the scene of the new one.

segl must not be running: a room holds an open slot's scene in memory and would write it back. The command stops the unit first, or refuses (`DEPLOY.md`).

## Network objects (P1)

A network object lives in the scene, on its elements, as `customData.segl` (D2-038). No table holds one, and no route or service serves one.

- A device is a group: its card, which is a rectangle with the device's name as its label, the lines of its glyph, and its tag when it has one. The card carries the record `{ "schemaVersion": 1, "objectId", "objectType", "state" }`.
- A link is an arrow, and carries the same record. Its ends are the editor's bindings to the cards. The record keeps no copy of them, and a link with an end on nothing is legal.
- A device's tag is a text in its group, with `{ "schemaVersion": 1, "objectId", "part": "tag" }`. A link's tag is the start of its label.
- `objectId` is a random UUID the page makes when the object is placed. It is not an element id. `objectType` is one of the 12 device kinds or the 5 link kinds (`REQUIREMENTS.md`, N-001 and N-002), with the device kinds `wireless_ap` and `voip_phone` in that spelling. `state` is `existing`, `planned`, or `remove`.
- The page reads a record strictly: exactly one of the two shapes, at schema version 1, with a lowercase UUID and a known kind and state, on an element of the right type. A device's record is on a rectangle, an ellipse, or a diamond, a link's on an arrow, and a tag's on a text. Anything else is no record, and the element is freeform.
- The server stores and sends `customData` as it arrived, as it does every field it does not read. It checks nothing in a record.

## Explicitly not created in P0

No `board`, `workspace`, `user`, `session`, `network_object`, `interface`, `network_link`, `data_source`, or `import_run` tables. Protected workspace storage arrives with L-004, in tables that slot queries do not join. P1 adds none of these tables either: its network objects are in the scene.
