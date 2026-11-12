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

"""SQLite storage for the nine slots. The contract is docs/DATA-MODEL.md.

This module is the only code that runs SQL. ``Repository`` holds one
connection in WAL mode with foreign keys on, and its public methods are the
method list in docs/DATA-MODEL.md. Every method blocks and takes one lock, so
any thread may call it. An ``async`` caller runs it in a worker thread.

The schema is the numbered SQL files in ``segl/migrations``. The database
records the number of the newest file applied to it in ``PRAGMA user_version``.
"""

import re
import sqlite3
import threading
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Self

SLOT_NUMBERS = range(1, 10)

# The head of a new slot until T04 captures the editor's own empty scene. T04
# replaces a stored head only when it still equals this text.
PLACEHOLDER_SCENE = '{"elements":[]}'

# The label on a head or a revision that no connection wrote.
SYSTEM_LABEL = "System"

DEFAULT_HISTORY_LIMIT = 50

# How long a statement waits for another process's lock on the file.
BUSY_SECONDS = 5.0

_MIGRATION_FILE = re.compile(r"(\d{4})_[a-z0-9_]+\.sql")

_SLOT_COLUMNS = (
    "SELECT slot.number, slot.title, slot.epoch, slot.updated_at, slot_head.saved_at "
    "FROM slot JOIN slot_head ON slot_head.slot = slot.number"
)


class StorageError(Exception):
    """The database cannot be opened, migrated, read, or written."""


class InvalidSlot(LookupError):
    """The slot number is not 1 to 9."""

    def __init__(self, number: object) -> None:
        super().__init__(f"slot {number!r} is not one of 1 to 9")


class RevisionNotFound(LookupError):
    """The slot has no revision with this number. It may have aged out."""

    def __init__(self, slot: int, revision: int) -> None:
        super().__init__(f"slot {slot} has no revision {revision}")
        self.slot = slot
        self.revision = revision


class EpochMismatch(Exception):
    """A write named an epoch that is not the slot's current one."""

    def __init__(self, slot: int, current: int, given: int) -> None:
        super().__init__(f"slot {slot} is at epoch {current}, and the write named epoch {given}")
        self.slot = slot
        self.current = current
        self.given = given


@dataclass(frozen=True)
class Slot:
    """One slot's metadata. ``saved_at`` is when its head was last written."""

    number: int
    title: str
    epoch: int
    updated_at: str
    saved_at: str


@dataclass(frozen=True)
class Head:
    """A slot's current scene."""

    slot: int
    epoch: int
    # Kept out of the repr so that a logged Head does not carry the scene.
    scene_json: str = field(repr=False)
    editor_label: str
    saved_at: str


@dataclass(frozen=True)
class RevisionSummary:
    """One history row without its scene."""

    slot: int
    revision: int
    epoch: int
    author_label: str
    created_at: str


@dataclass(frozen=True)
class Revision(RevisionSummary):
    """One history row with its scene."""

    scene_json: str = field(repr=False)


@dataclass(frozen=True)
class Replacement:
    """What ``replace_head`` wrote: the slot's new epoch and the new revision."""

    epoch: int
    revision: int
    saved_at: str


@dataclass(frozen=True)
class Migration:
    """One numbered SQL file."""

    number: int
    name: str
    sql: str


def load_migrations() -> tuple[Migration, ...]:
    """Return the packaged migrations, oldest first.

    Raises:
        StorageError: When there are none, or their numbers do not run from 1
            without a gap.
    """
    folder = resources.files("segl").joinpath("migrations")
    found: list[Migration] = []
    for entry in folder.iterdir():
        match = _MIGRATION_FILE.fullmatch(entry.name)
        if match:
            found.append(Migration(int(match[1]), entry.name, entry.read_text(encoding="utf-8")))
    found.sort(key=lambda migration: migration.number)
    if not found:
        raise StorageError(f"there are no migration files in {folder}")
    if [migration.number for migration in found] != list(range(1, len(found) + 1)):
        names = ", ".join(migration.name for migration in found)
        raise StorageError(f"the migration files are not numbered from 0001 without a gap: {names}")
    return tuple(found)


def apply_migrations(connection: sqlite3.Connection, migrations: Sequence[Migration]) -> int:
    """Apply the migrations the database does not have yet. Return how many ran.

    They run in one transaction with the new schema number, so a failure
    leaves the database as it was.

    Raises:
        StorageError: When a newer segl wrote the database.
        sqlite3.Error: When a migration fails.
    """
    newest = len(migrations)
    # The write lock first: a second process starting now waits, then finds nothing to do.
    connection.execute("BEGIN IMMEDIATE")
    try:
        current = connection.execute("PRAGMA user_version").fetchone()[0]
        if current > newest:
            file = connection.execute("PRAGMA database_list").fetchone()[2]
            raise StorageError(
                f"the database {file} has schema {current}, and this segl knows schema "
                f"{newest}: a newer segl wrote it. Run that release, or restore a copy made "
                "before it"
            )
        for migration in migrations[current:]:
            connection.executescript(migration.sql)
            # A pragma takes no parameter. The number is an int from a file name.
            connection.execute(f"PRAGMA user_version = {migration.number:d}")
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    return newest - current


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _open(path: Path) -> sqlite3.Connection:
    """Open the file, creating it and its folder when missing, with segl's pragmas."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # autocommit=True: the driver opens no transaction of its own, so every
        # BEGIN and COMMIT is written out in this module. check_same_thread is
        # off because request handlers run in worker threads; Repository's lock
        # lets one of them use the connection at a time.
        connection = sqlite3.connect(
            path, timeout=BUSY_SECONDS, autocommit=True, check_same_thread=False
        )
    except (OSError, sqlite3.Error) as exc:
        raise StorageError(f"cannot open the database {path}: {exc}") from exc
    try:
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if mode != "wal":
            raise StorageError(
                f"the database {path} cannot use WAL mode (it stays in {mode} mode). "
                "Keep it on a local disk"
            )
        connection.execute("PRAGMA foreign_keys = ON")
        # A head the UI calls saved has reached the disk, not only the page cache.
        connection.execute("PRAGMA synchronous = FULL")
    except sqlite3.Error as exc:
        connection.close()
        raise StorageError(f"cannot open the database {path}: {exc}") from exc
    except StorageError:
        connection.close()
        raise
    return connection


class Repository:
    """The slots, heads, revisions, and name counter in one SQLite file."""

    def __init__(
        self,
        path: Path,
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Open the database, creating the file when it does not exist.

        ``history_limit`` is the number of revisions kept per slot. ``clock``
        returns the current time in UTC, and tests replace it.

        Raises:
            StorageError: When the file cannot be opened as a WAL database.
        """
        self.path = path
        self._history_limit = history_limit
        self._clock = clock
        self._lock = threading.Lock()
        self._connection = _open(path)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the connection. The repository cannot be used afterwards."""
        with self._lock:
            self._connection.close()

    def bootstrap(self) -> None:
        """Apply the migrations, then add the nine slots and the name counter.

        Rows that already exist are left alone, so this runs at every startup.

        Raises:
            StorageError: When a migration fails, or a newer segl wrote the database.
        """
        migrations = load_migrations()
        with self._reading() as db:
            apply_migrations(db, migrations)
        now = self._now()
        with self._transaction() as db:
            for number in SLOT_NUMBERS:
                db.execute(
                    "INSERT INTO slot (number, title, epoch, updated_at) VALUES (?, ?, 1, ?) "
                    "ON CONFLICT (number) DO NOTHING",
                    (number, f"Workspace {number}", now),
                )
                db.execute(
                    "INSERT INTO slot_head (slot, epoch, scene_json, editor_label, saved_at) "
                    "VALUES (?, 1, ?, ?, ?) ON CONFLICT (slot) DO NOTHING",
                    (number, PLACEHOLDER_SCENE, SYSTEM_LABEL, now),
                )
            db.execute(
                "INSERT INTO name_counter (id, next_value) VALUES (1, 1) "
                "ON CONFLICT (id) DO NOTHING"
            )

    def list_slots(self) -> list[Slot]:
        """Return the nine slots in number order."""
        with self._reading() as db:
            rows = db.execute(f"{_SLOT_COLUMNS} ORDER BY slot.number").fetchall()
        return [Slot(*row) for row in rows]

    def get_slot(self, n: int) -> Slot:
        """Return one slot's metadata.

        Raises:
            InvalidSlot: When ``n`` is not 1 to 9.
        """
        _check_slot(n)
        with self._reading() as db:
            return self._slot(db, n)

    def rename_slot(self, n: int, title: str) -> Slot:
        """Store a new title and return the slot. The caller has trimmed and checked it.

        Raises:
            InvalidSlot: When ``n`` is not 1 to 9.
        """
        _check_slot(n)
        now = self._now()
        with self._transaction() as db:
            db.execute(
                "UPDATE slot SET title = ?, updated_at = ? WHERE number = ?", (title, now, n)
            )
            return self._slot(db, n)

    def get_head(self, n: int) -> Head:
        """Return a slot's current scene.

        Raises:
            InvalidSlot: When ``n`` is not 1 to 9.
        """
        _check_slot(n)
        with self._reading() as db:
            row = db.execute(
                "SELECT slot, epoch, scene_json, editor_label, saved_at FROM slot_head "
                "WHERE slot = ?",
                (n,),
            ).fetchone()
        return Head(*row)

    def save_head(self, n: int, epoch: int, scene_json: str, editor_label: str) -> str:
        """Write a slot's scene at its current epoch. Return the ``saved_at`` time.

        Raises:
            InvalidSlot: When ``n`` is not 1 to 9.
            EpochMismatch: When ``epoch`` is not the slot's epoch. Nothing is written.
        """
        _check_slot(n)
        now = self._now()
        with self._transaction() as db:
            self._require_epoch(db, n, epoch)
            self._write_head(db, n, epoch, scene_json, editor_label, now)
        return now

    def append_revision(self, n: int, epoch: int, scene_json: str, author_label: str) -> int:
        """Add a history row at the slot's current epoch. Return its revision number.

        The oldest rows past the history limit are deleted in the same transaction.

        Raises:
            InvalidSlot: When ``n`` is not 1 to 9.
            EpochMismatch: When ``epoch`` is not the slot's epoch. Nothing is written.
        """
        _check_slot(n)
        now = self._now()
        with self._transaction() as db:
            self._require_epoch(db, n, epoch)
            return self._insert_revision(db, n, epoch, scene_json, author_label, now)

    def replace_head(self, n: int, scene_json: str, editor_label: str) -> Replacement:
        """Start a new epoch with this scene: the write behind restore and import.

        The epoch goes up by one, the head becomes this scene, and a revision
        records it, in one transaction.

        Raises:
            InvalidSlot: When ``n`` is not 1 to 9.
        """
        _check_slot(n)
        now = self._now()
        with self._transaction() as db:
            epoch = db.execute("SELECT epoch FROM slot WHERE number = ?", (n,)).fetchone()[0] + 1
            db.execute(
                "UPDATE slot SET epoch = ?, updated_at = ? WHERE number = ?", (epoch, now, n)
            )
            self._write_head(db, n, epoch, scene_json, editor_label, now)
            revision = self._insert_revision(db, n, epoch, scene_json, editor_label, now)
        return Replacement(epoch=epoch, revision=revision, saved_at=now)

    def list_revisions(self, n: int) -> list[RevisionSummary]:
        """Return a slot's history rows, newest first, without their scenes.

        Raises:
            InvalidSlot: When ``n`` is not 1 to 9.
        """
        _check_slot(n)
        with self._reading() as db:
            rows = db.execute(
                "SELECT slot, revision, epoch, author_label, created_at FROM revision "
                "WHERE slot = ? ORDER BY revision DESC",
                (n,),
            ).fetchall()
        return [RevisionSummary(*row) for row in rows]

    def get_revision(self, n: int, revision: int) -> Revision:
        """Return one history row with its scene.

        Raises:
            InvalidSlot: When ``n`` is not 1 to 9.
            RevisionNotFound: When the slot has no such revision.
        """
        _check_slot(n)
        with self._reading() as db:
            row = db.execute(
                "SELECT slot, revision, epoch, author_label, created_at, scene_json "
                "FROM revision WHERE slot = ? AND revision = ?",
                (n, revision),
            ).fetchone()
        if row is None:
            raise RevisionNotFound(n, revision)
        return Revision(*row)

    def allocate_display_name(self, words: Sequence[str]) -> str:
        """Return the next label, such as ``Alpha1``, and advance the counter.

        The counter moves in its own transaction and never repeats a value
        (docs/ARCHITECTURE.md, display names).

        Raises:
            ValueError: When ``words`` is empty. The counter does not move.
        """
        if not words:
            raise ValueError("the display-name list is empty")
        with self._transaction() as db:
            value = db.execute("SELECT next_value FROM name_counter WHERE id = 1").fetchone()[0]
            db.execute("UPDATE name_counter SET next_value = ? WHERE id = 1", (value + 1,))
        return f"{words[(value - 1) % len(words)]}{value}"

    def _now(self) -> str:
        """Return the time as stored: UTC to the millisecond, ending in ``Z``."""
        moment = self._clock().astimezone(UTC)
        return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @contextmanager
    def _reading(self) -> Generator[sqlite3.Connection]:
        """Lend the connection for statements that need no transaction of their own."""
        with self._lock:
            try:
                yield self._connection
            except sqlite3.Error as exc:
                raise StorageError(f"the database {self.path} failed: {exc}") from exc

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection]:
        """Lend the connection inside one write transaction.

        The block's writes are committed together, or rolled back together
        when it raises.
        """
        with self._reading() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    @staticmethod
    def _slot(db: sqlite3.Connection, n: int) -> Slot:
        return Slot(*db.execute(f"{_SLOT_COLUMNS} WHERE slot.number = ?", (n,)).fetchone())

    @staticmethod
    def _require_epoch(db: sqlite3.Connection, n: int, epoch: int) -> None:
        current = db.execute("SELECT epoch FROM slot WHERE number = ?", (n,)).fetchone()[0]
        if epoch != current:
            raise EpochMismatch(n, current, epoch)

    @staticmethod
    def _write_head(
        db: sqlite3.Connection, n: int, epoch: int, scene_json: str, editor_label: str, now: str
    ) -> None:
        db.execute(
            "UPDATE slot_head SET epoch = ?, scene_json = ?, editor_label = ?, saved_at = ? "
            "WHERE slot = ?",
            (epoch, scene_json, editor_label, now, n),
        )

    def _insert_revision(
        self,
        db: sqlite3.Connection,
        n: int,
        epoch: int,
        scene_json: str,
        author_label: str,
        now: str,
    ) -> int:
        revision = db.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM revision WHERE slot = ?", (n,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO revision (slot, revision, epoch, scene_json, author_label, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (n, revision, epoch, scene_json, author_label, now),
        )
        # A slot's numbers have no gap, so the newest `limit` rows are the ones above this.
        db.execute(
            "DELETE FROM revision WHERE slot = ? AND revision <= ?",
            (n, revision - self._history_limit),
        )
        return revision


def _check_slot(n: int) -> None:
    if n not in SLOT_NUMBERS:
        raise InvalidSlot(n)
