# Copyright 2026 segl contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The SQLite repository: migrations, the nine slots, and every method in
docs/DATA-MODEL.md."""

import json
import re
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from harness import EMPTY_SCENE, EMPTY_SCENE_FILE

from segl.repository import (
    PLACEHOLDER_SCENE,
    SYSTEM_LABEL,
    EpochMismatch,
    InvalidSlot,
    Migration,
    Replacement,
    Repository,
    RevisionNotFound,
    Slot,
    StorageError,
    apply_migrations,
    load_empty_scene,
    load_migrations,
)

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 11, 12, 9, 0, 0, tzinfo=UTC)
STARTED = "2026-11-12T09:00:00.000Z"
DRAWN = '{"elements":[{"id":"a","version":1}]}'
# The head of a new slot, as the repository stores it.
EMPTY = load_empty_scene()


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "segl.sqlite"


@pytest.fixture
def repo(database: Path, clock: Clock) -> Iterator[Repository]:
    with Repository(database, clock=clock) as repository:
        repository.bootstrap()
        yield repository


def rows(database: Path, sql: str) -> list[tuple]:
    """Run a query on a second connection, as another process would."""
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(sql).fetchall()


def squeeze(sql: str) -> str:
    return " ".join(sql.split()).rstrip(";")


# Migrations and bootstrap.


def test_the_packaged_migrations_are_numbered_from_one() -> None:
    migrations = load_migrations()

    assert [migration.number for migration in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "0001_slots.sql"
    assert "CREATE TABLE slot (" in migrations[0].sql


def test_the_tables_are_the_ones_in_the_data_model_page(repo: Repository, database: Path) -> None:
    page = (ROOT / "docs" / "DATA-MODEL.md").read_text(encoding="utf-8")
    block = re.search(r"^```sql\n(.*?)^```$", page, flags=re.MULTILINE | re.DOTALL)
    assert block, "docs/DATA-MODEL.md has no ```sql block"
    documented = {squeeze(statement) for statement in block.group(1).split(";\n")} - {""}

    # SQLite keeps each CREATE TABLE as it was written.
    stored = rows(database, "SELECT sql FROM sqlite_master WHERE type = 'table'")

    assert len(documented) == 4
    assert {squeeze(sql) for (sql,) in stored} == documented


def test_bootstrap_records_the_schema_number(repo: Repository, database: Path) -> None:
    assert rows(database, "PRAGMA user_version") == [(len(load_migrations()),)]


def test_the_database_is_in_wal_mode_with_foreign_keys_on(repo: Repository, database: Path) -> None:
    assert rows(database, "PRAGMA journal_mode") == [("wal",)]
    # The repository's own connection refuses a row for a slot that does not exist.
    with pytest.raises(StorageError, match="FOREIGN KEY"), repo._transaction() as db:
        db.execute("INSERT INTO revision VALUES (99, 1, 1, '{}', 'x', 'now')")


def test_bootstrap_creates_nine_slots(repo: Repository) -> None:
    slots = repo.list_slots()

    assert slots == [
        Slot(number=n, title=f"Workspace {n}", epoch=1, updated_at=STARTED, saved_at=STARTED)
        for n in range(1, 10)
    ]


def test_a_new_slot_has_the_editors_empty_scene(repo: Repository) -> None:
    for n in range(1, 10):
        head = repo.get_head(n)

        assert (head.slot, head.epoch, head.editor_label) == (n, 1, "System")
        assert head.scene_json == EMPTY
        assert head.saved_at == STARTED


def test_the_empty_scene_is_the_captured_file_without_its_whitespace() -> None:
    assert json.loads(EMPTY) == EMPTY_SCENE
    assert json.dumps(EMPTY_SCENE, separators=(",", ":")) == EMPTY
    assert list(json.loads(EMPTY)) == list(EMPTY_SCENE), "the keys keep the editor's order"


def test_the_empty_scene_is_an_excalidraw_document_with_no_elements() -> None:
    """What the editor wrote, not a hand-made schema (docs/DATA-MODEL.md)."""
    assert EMPTY_SCENE["type"] == "excalidraw"
    assert EMPTY_SCENE["source"] == "segl"
    assert EMPTY_SCENE["elements"] == []
    assert isinstance(EMPTY_SCENE["version"], int)
    assert isinstance(EMPTY_SCENE["appState"], dict)
    # No host name of the machine it was captured on.
    assert "://" not in EMPTY_SCENE_FILE.read_text(encoding="utf-8")


def placeholder_database(database: Path, clock: Clock) -> None:
    """Leave ``database`` as T03 made one: every head holds the placeholder."""
    with Repository(database, clock=clock) as repo:
        repo.bootstrap()
    with closing(sqlite3.connect(database)) as db:
        db.execute("UPDATE slot_head SET scene_json = ?", (PLACEHOLDER_SCENE,))
        db.commit()


def test_bootstrap_gives_a_placeholder_head_the_empty_scene(database: Path, clock: Clock) -> None:
    placeholder_database(database, clock)

    clock.advance(60)
    with Repository(database, clock=clock) as repo:
        repo.bootstrap()

        for n in range(1, 10):
            head = repo.get_head(n)
            assert (head.scene_json, head.epoch, head.editor_label) == (EMPTY, 1, "System")
            assert head.saved_at == "2026-11-12T09:01:00.000Z"
        assert repo.list_revisions(1) == []


def test_bootstrap_leaves_every_other_head_alone(database: Path, clock: Clock) -> None:
    placeholder_database(database, clock)
    spaced = '{"elements": []}'
    with Repository(database, clock=clock) as repo:
        # Saved by a person: drawn on, the placeholder's own text, and nearly that text.
        repo.save_head(2, 1, DRAWN, "Alpha1")
        repo.save_head(3, 1, PLACEHOLDER_SCENE, "Bravo2")
        repo.save_head(4, 1, spaced, SYSTEM_LABEL)

    clock.advance(60)
    with Repository(database, clock=clock) as repo:
        repo.bootstrap()

        assert repo.get_head(1).scene_json == EMPTY
        assert [repo.get_head(n).scene_json for n in (2, 3, 4)] == [
            DRAWN,
            PLACEHOLDER_SCENE,
            spaced,
        ]
        assert [repo.get_head(n).saved_at for n in (2, 3, 4)] == [STARTED] * 3


def test_a_head_does_not_show_its_scene_when_logged(repo: Repository) -> None:
    repo.save_head(1, 1, DRAWN, "Alpha1")

    assert "elements" not in repr(repo.get_head(1))


def test_a_second_bootstrap_keeps_what_is_stored(database: Path, clock: Clock) -> None:
    with Repository(database, clock=clock) as first:
        first.bootstrap()
        first.rename_slot(3, "Core routers")
        first.save_head(2, 1, DRAWN, "Alpha1")
        assert first.allocate_display_name(["Guest"]) == "Guest1"
        first.bootstrap()

    clock.advance(60)
    with Repository(database, clock=clock) as second:
        second.bootstrap()

        assert [slot.title for slot in second.list_slots()] == [
            "Workspace 1",
            "Workspace 2",
            "Core routers",
            *(f"Workspace {n}" for n in range(4, 10)),
        ]
        assert second.get_head(2).scene_json == DRAWN
        assert second.get_head(2).saved_at == STARTED
        assert second.get_head(1).scene_json == EMPTY
        assert second.get_head(1).saved_at == STARTED
        assert second.allocate_display_name(["Guest"]) == "Guest2"


def test_a_missing_folder_is_created(tmp_path: Path) -> None:
    database = tmp_path / "var" / "data" / "segl.sqlite"

    with Repository(database) as repository:
        repository.bootstrap()

        assert len(repository.list_slots()) == 9
    assert database.is_file()


def test_a_file_that_is_not_a_database_is_refused_by_name(tmp_path: Path) -> None:
    database = tmp_path / "segl.sqlite"
    database.write_text("this is not a database, and it is long enough to have a header\n" * 4)

    with pytest.raises(StorageError, match=re.escape(str(database))):
        Repository(database)


def test_a_folder_that_cannot_be_made_is_refused_by_name(tmp_path: Path) -> None:
    (tmp_path / "var").write_text("a file where the folder should be")
    database = tmp_path / "var" / "segl.sqlite"

    with pytest.raises(StorageError, match=re.escape(str(database))):
        Repository(database)


def test_a_database_from_a_newer_segl_is_refused_and_left_alone(
    database: Path, clock: Clock
) -> None:
    with Repository(database, clock=clock) as first:
        first.bootstrap()
        first.rename_slot(1, "Kept")
    newer = len(load_migrations()) + 1
    with closing(sqlite3.connect(database, autocommit=True)) as connection:
        connection.execute(f"PRAGMA user_version = {newer}")

    with (
        Repository(database) as second,
        pytest.raises(StorageError, match=f"has schema {newer}.*a newer segl wrote it") as refusal,
    ):
        second.bootstrap()

    assert str(database) in str(refusal.value)
    assert rows(database, "PRAGMA user_version") == [(newer,)]
    assert rows(database, "SELECT title FROM slot WHERE number = 1") == [("Kept",)]


def test_only_the_migrations_a_database_lacks_are_applied(database: Path) -> None:
    first = Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER);")
    second = Migration(2, "0002_b.sql", "CREATE TABLE b (y INTEGER);\nCREATE TABLE c (z INTEGER);")
    with closing(sqlite3.connect(database, autocommit=True)) as connection:
        assert apply_migrations(connection, [first]) == 1
        assert apply_migrations(connection, [first]) == 0
        # Running 0001 a second time would fail: table a exists.
        assert apply_migrations(connection, [first, second]) == 1

    assert rows(database, "PRAGMA user_version") == [(2,)]
    assert rows(database, "SELECT name FROM sqlite_master ORDER BY name") == [
        ("a",),
        ("b",),
        ("c",),
    ]


def test_a_failed_migration_leaves_the_database_as_it_was(database: Path) -> None:
    good = Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER);")
    also_good = Migration(2, "0002_b.sql", "CREATE TABLE b (y INTEGER);")
    broken = Migration(3, "0003_c.sql", "CREATE TABLE c (z INTEGER);\nCREATE TABLE a (x INTEGER);")
    with closing(sqlite3.connect(database, autocommit=True)) as connection:
        apply_migrations(connection, [good])

        with pytest.raises(sqlite3.OperationalError, match="table a already exists"):
            apply_migrations(connection, [good, also_good, broken])

        assert not connection.in_transaction
    # Neither 0002 nor the first half of 0003 stayed.
    assert rows(database, "PRAGMA user_version") == [(1,)]
    assert rows(database, "SELECT name FROM sqlite_master") == [("a",)]


# Slots.


def test_get_slot_returns_one_slot(repo: Repository) -> None:
    assert repo.get_slot(9) == Slot(9, "Workspace 9", 1, STARTED, STARTED)


@pytest.mark.parametrize("n", [0, 10, -1, 99])
def test_a_number_outside_one_to_nine_is_an_invalid_slot(repo: Repository, n: int) -> None:
    calls = (
        lambda: repo.get_slot(n),
        lambda: repo.rename_slot(n, "x"),
        lambda: repo.get_head(n),
        lambda: repo.save_head(n, 1, DRAWN, "x"),
        lambda: repo.append_revision(n, 1, DRAWN, "x"),
        lambda: repo.replace_head(n, DRAWN, "x"),
        lambda: repo.list_revisions(n),
        lambda: repo.get_revision(n, 1),
    )
    for call in calls:
        with pytest.raises(InvalidSlot, match="is not one of 1 to 9"):
            call()


def test_rename_changes_one_title_and_its_time(repo: Repository, clock: Clock) -> None:
    clock.advance(5)

    renamed = repo.rename_slot(4, "Data center east")

    assert renamed == Slot(4, "Data center east", 1, "2026-11-12T09:00:05.000Z", STARTED)
    assert repo.get_slot(4) == renamed
    assert repo.get_slot(5).title == "Workspace 5"
    assert repo.get_slot(5).updated_at == STARTED


def test_a_title_is_data_and_never_sql(repo: Repository) -> None:
    title = 'Robert\'); DROP TABLE slot;-- "x" ü'

    repo.rename_slot(1, title)

    assert repo.get_slot(1).title == title
    assert len(repo.list_slots()) == 9


# Heads.


def test_save_head_writes_one_slot(repo: Repository, clock: Clock) -> None:
    clock.advance(1.25)

    saved_at = repo.save_head(2, 1, DRAWN, "Bravo2")

    assert saved_at == "2026-11-12T09:00:01.250Z"
    head = repo.get_head(2)
    assert (head.epoch, head.scene_json, head.editor_label) == (1, DRAWN, "Bravo2")
    assert head.saved_at == saved_at
    assert repo.get_slot(2).saved_at == saved_at
    for other in (1, 3, 4, 5, 6, 7, 8, 9):
        assert repo.get_head(other).scene_json == EMPTY
        assert repo.get_head(other).saved_at == STARTED


@pytest.mark.parametrize("epoch", [0, 2])
def test_save_head_refuses_an_epoch_that_is_not_current(repo: Repository, epoch: int) -> None:
    with pytest.raises(EpochMismatch) as refusal:
        repo.save_head(1, epoch, DRAWN, "Alpha1")

    assert (refusal.value.slot, refusal.value.current, refusal.value.given) == (1, 1, epoch)
    assert repo.get_head(1).scene_json == EMPTY
    assert repo.get_head(1).editor_label == "System"


# Revisions.


def test_revisions_are_numbered_per_slot_and_listed_newest_first(
    repo: Repository, clock: Clock
) -> None:
    assert repo.list_revisions(1) == []

    assert repo.append_revision(1, 1, '{"elements":[1]}', "Alpha1") == 1
    clock.advance(2)
    assert repo.append_revision(1, 1, '{"elements":[2]}', "Bravo2") == 2
    assert repo.append_revision(7, 1, '{"elements":[7]}', "Charlie3") == 1

    listed = repo.list_revisions(1)
    assert [(row.revision, row.author_label, row.created_at) for row in listed] == [
        (2, "Bravo2", "2026-11-12T09:00:02.000Z"),
        (1, "Alpha1", STARTED),
    ]
    assert not hasattr(listed[0], "scene_json")
    assert [row.revision for row in repo.list_revisions(7)] == [1]
    assert repo.list_revisions(2) == []


def test_get_revision_returns_the_stored_scene(repo: Repository) -> None:
    repo.append_revision(1, 1, '{"elements":[1]}', "Alpha1")
    repo.append_revision(1, 1, '{"elements":[2]}', "Bravo2")

    revision = repo.get_revision(1, 1)

    assert (revision.slot, revision.revision, revision.epoch) == (1, 1, 1)
    assert (revision.scene_json, revision.author_label) == ('{"elements":[1]}', "Alpha1")
    assert "elements" not in repr(revision)


def test_a_revision_that_does_not_exist_is_not_found(repo: Repository) -> None:
    repo.append_revision(1, 1, DRAWN, "Alpha1")

    for slot, number in ((1, 2), (1, 0), (2, 1)):
        with pytest.raises(RevisionNotFound, match=f"slot {slot} has no revision {number}"):
            repo.get_revision(slot, number)


def test_append_revision_refuses_an_epoch_that_is_not_current(repo: Repository) -> None:
    with pytest.raises(EpochMismatch):
        repo.append_revision(1, 2, DRAWN, "Alpha1")

    assert repo.list_revisions(1) == []


def test_the_51st_revision_drops_the_oldest(repo: Repository) -> None:
    for count in range(1, 51):
        repo.append_revision(1, 1, f'{{"elements":[{count}]}}', "Alpha1")
    repo.append_revision(2, 1, DRAWN, "Bravo2")
    assert [row.revision for row in repo.list_revisions(1)] == list(range(50, 0, -1))

    assert repo.append_revision(1, 1, '{"elements":[51]}', "Alpha1") == 51

    assert [row.revision for row in repo.list_revisions(1)] == list(range(51, 1, -1))
    with pytest.raises(RevisionNotFound):
        repo.get_revision(1, 1)
    assert repo.get_revision(1, 2).scene_json == '{"elements":[2]}'
    # Another slot's history is not counted or trimmed.
    assert [row.revision for row in repo.list_revisions(2)] == [1]


def test_the_history_limit_is_the_one_given(database: Path) -> None:
    with Repository(database, history_limit=3) as repository:
        repository.bootstrap()
        for _ in range(5):
            repository.append_revision(1, 1, DRAWN, "Alpha1")

        assert [row.revision for row in repository.list_revisions(1)] == [5, 4, 3]


# Restore and import.


def test_replace_head_starts_a_new_epoch_with_a_revision(repo: Repository, clock: Clock) -> None:
    repo.save_head(1, 1, DRAWN, "Alpha1")
    repo.append_revision(1, 1, DRAWN, "Alpha1")
    clock.advance(3)

    replaced = repo.replace_head(1, '{"elements":[]}', "Bravo2")

    now = "2026-11-12T09:00:03.000Z"
    assert replaced == Replacement(epoch=2, revision=2, saved_at=now)
    assert repo.get_slot(1) == Slot(1, "Workspace 1", 2, now, now)
    head = repo.get_head(1)
    assert (head.epoch, head.scene_json, head.editor_label) == (2, '{"elements":[]}', "Bravo2")
    newest = repo.get_revision(1, 2)
    assert (newest.epoch, newest.scene_json, newest.author_label) == (
        2,
        '{"elements":[]}',
        "Bravo2",
    )
    assert repo.get_slot(2).epoch == 1


def test_a_write_for_the_old_epoch_is_refused_after_a_replace(repo: Repository) -> None:
    repo.replace_head(1, '{"elements":[]}', "Bravo2")

    with pytest.raises(EpochMismatch) as refusal:
        repo.save_head(1, 1, DRAWN, "Alpha1")
    with pytest.raises(EpochMismatch):
        repo.append_revision(1, 1, DRAWN, "Alpha1")

    assert (refusal.value.current, refusal.value.given) == (2, 1)
    assert repo.get_head(1).scene_json == '{"elements":[]}'
    assert repo.save_head(1, 2, DRAWN, "Alpha1")


def test_a_replace_that_fails_changes_nothing(repo: Repository) -> None:
    repo.save_head(1, 1, DRAWN, "Alpha1")

    # None is not text the scene column takes, so the head update fails after
    # the epoch update ran.
    with pytest.raises(StorageError, match="NOT NULL"):
        repo.replace_head(1, None, "Bravo2")  # ty: ignore[invalid-argument-type]

    assert repo.get_slot(1).epoch == 1
    assert repo.get_head(1).scene_json == DRAWN
    assert repo.list_revisions(1) == []
    # The connection is usable again: the failed transaction was rolled back.
    assert repo.save_head(1, 1, DRAWN, "Alpha1")


# Display names.


def test_names_walk_the_list_and_the_counter_never_repeats(repo: Repository) -> None:
    words = ["Guest", "Staff"]

    assert [repo.allocate_display_name(words) for _ in range(5)] == [
        "Guest1",
        "Staff2",
        "Guest3",
        "Staff4",
        "Guest5",
    ]


def test_an_empty_list_allocates_nothing(repo: Repository) -> None:
    with pytest.raises(ValueError, match="the display-name list is empty"):
        repo.allocate_display_name([])

    assert repo.allocate_display_name(["Guest"]) == "Guest1"


def test_threads_share_the_repository(repo: Repository) -> None:
    """Request handlers run in worker threads, on one connection."""

    def work(index: int) -> str:
        repo.save_head(index % 9 + 1, 1, DRAWN, f"Thread{index}")
        repo.list_slots()
        return repo.allocate_display_name(["Guest"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        names = list(pool.map(work, range(80)))

    assert sorted(names, key=lambda name: int(name[5:])) == [f"Guest{n}" for n in range(1, 81)]
    assert all(repo.get_head(n).scene_json == DRAWN for n in range(1, 10))


def test_a_closed_repository_fails_as_a_storage_error(repo: Repository, database: Path) -> None:
    repo.close()

    with pytest.raises(StorageError, match=re.escape(str(database))):
        repo.list_slots()
    with pytest.raises(StorageError):
        repo.save_head(1, 1, DRAWN, "Alpha1")
