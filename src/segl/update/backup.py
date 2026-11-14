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

"""Copies of what an update or a merge is about to change, and putting them back.

A backup is a folder under ``/opt/segl/update/backups``, which only root
opens: the settings hold the access codes and their secret. Its name is a
kind and a time, such as ``pre-update-20261113T210000Z``. Inside, each file
is at a path that says what it is: ``etc/segl.toml``,
``nginx/snippets/segl-proxy.conf``, ``database/segl.sqlite``.

A file is put back whole, by a rename, with the owner and the mode it had.
"""

import contextlib
import filecmp
import os
import shutil
from datetime import datetime
from pathlib import Path

PRE_UPDATE = "pre-update"
MERGE = "merge"
KEPT = 3
DATABASE = "database"
# SQLite's own files beside a database that was not closed cleanly.
DATABASE_SUFFIXES = ("", "-wal", "-shm")


class BackupError(Exception):
    """A backup cannot be written, or a file cannot be put back."""


def new_backup(backups: Path, kind: str, now: datetime) -> Path:
    """Make an empty backup folder for this moment, and return it.

    Raises:
        BackupError: When the folder cannot be made.
    """
    stamp = f"{now:%Y%m%dT%H%M%SZ}"
    try:
        backups.mkdir(mode=0o700, parents=True, exist_ok=True)
        for attempt in range(1, 100):
            folder = backups / (f"{kind}-{stamp}" + (f"-{attempt}" if attempt > 1 else ""))
            try:
                folder.mkdir(mode=0o700)
            except FileExistsError:
                continue
            return folder
    except OSError as exc:
        raise BackupError(f"cannot make a backup folder in {backups}: {exc}") from exc
    raise BackupError(f"cannot make a backup folder in {backups}")


def list_backups(backups: Path, kind: str) -> list[Path]:
    """Return the backups of one kind, newest first."""
    return sorted((path for path in backups.glob(f"{kind}-*") if path.is_dir()), reverse=True)


def _copy(source: Path, dest: Path) -> None:
    """Copy one file with its mode, its times, and, where allowed, its owner."""
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    info = source.stat()
    # Only root may give a file away. A test runs as its own user.
    with contextlib.suppress(PermissionError):
        os.chown(dest, info.st_uid, info.st_gid)


def replace_file(target: Path, data: bytes, like: os.stat_result | None = None) -> None:
    """Put ``data`` in place of ``target`` by a rename, keeping its owner and mode.

    ``like`` is the file whose owner and mode to give it. Without it, the
    target's own are kept, and a new file is root's, mode 0644.
    """
    if like is None and target.exists():
        like = target.stat()
    part = target.with_name(f".{target.name}.segl-new")
    try:
        part.write_bytes(data)
        os.chmod(part, (like.st_mode & 0o7777) if like else 0o644)
        if like is not None:
            with contextlib.suppress(PermissionError):
                os.chown(part, like.st_uid, like.st_gid)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)


def save_file(backup: Path, name: str, source: Path) -> bool:
    """Copy ``source`` into the backup as ``name``. Return whether it was there.

    Raises:
        BackupError: When the file is there and cannot be copied.
    """
    if not source.is_file():
        return False
    try:
        _copy(source, backup / name)
    except OSError as exc:
        raise BackupError(f"cannot save {source}: {exc}") from exc
    return True


def save_folder(backup: Path, name: str, source: Path) -> None:
    """Copy every file under ``source`` into the backup, under ``name``.

    Raises:
        BackupError: When a file cannot be copied.
    """
    if not source.is_dir():
        return
    for path in sorted(source.rglob("*")):
        if path.is_file() and not path.is_symlink():
            save_file(backup, f"{name}/{path.relative_to(source)}", path)


def restore_file(backup: Path, name: str, target: Path) -> bool:
    """Put the backup's ``name`` back at ``target``. Return whether it was changed.

    Raises:
        BackupError: When the file cannot be put back.
    """
    saved = backup / name
    if not saved.is_file():
        return False
    part = target.with_name(f".{target.name}.segl-new")
    try:
        # Compared and copied in pieces: the database may be large.
        if target.is_file() and filecmp.cmp(saved, target, shallow=False):
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy(saved, part)
        os.replace(part, target)
    except OSError as exc:
        raise BackupError(f"cannot put {target} back: {exc}") from exc
    finally:
        part.unlink(missing_ok=True)
    return True


def restore_folder(backup: Path, name: str, target: Path, exact: bool = False) -> list[Path]:
    """Put every file the backup has under ``name`` back under ``target``.

    A file that is in the folder now and was not then is left alone, unless
    ``exact`` is set: then it is removed, and the folder is as it was.

    Raises:
        BackupError: When a file cannot be put back or removed.
    """
    saved = backup / name
    changed = []
    if exact and target.is_dir():
        try:
            for path in sorted(target.rglob("*")):
                if path.is_file() and not (saved / path.relative_to(target)).is_file():
                    path.unlink()
                    changed.append(path)
        except OSError as exc:
            raise BackupError(f"cannot put {target} back: {exc}") from exc
    for path in sorted(saved.rglob("*")) if saved.is_dir() else []:
        if path.is_file():
            relative = path.relative_to(saved)
            if restore_file(backup, f"{name}/{relative}", target / relative):
                changed.append(target / relative)
    return changed


def database_files(database: Path) -> list[Path]:
    """Return the database and SQLite's files beside it, those that exist."""
    found = [database.with_name(database.name + suffix) for suffix in DATABASE_SUFFIXES]
    return [path for path in found if path.is_file()]


def save_database(backup: Path, database: Path) -> None:
    """Copy the database into the backup. segl must not be running.

    Raises:
        BackupError: When a file cannot be copied.
    """
    for path in database_files(database):
        save_file(backup, f"{DATABASE}/{path.name}", path)


def restore_database(backup: Path, database: Path) -> bool:
    """Put the database back as the backup has it. Return whether it had one.

    segl must not be running. SQLite's files beside the database go first:
    they belong to the database that is being replaced.

    Raises:
        BackupError: When a file cannot be put back.
    """
    saved = backup / DATABASE
    if not (saved / database.name).is_file():
        return False
    try:
        for path in database_files(database):
            if path != database:
                path.unlink()
    except OSError as exc:
        raise BackupError(f"cannot put {database} back: {exc}") from exc
    restore_folder(backup, DATABASE, database.parent)
    return True


def database_bytes(database: Path) -> int:
    """Return how much room a copy of the database takes."""
    return sum(path.stat().st_size for path in database_files(database))


def prune(backups: Path, kind: str, keep: int = KEPT) -> None:
    """Keep the newest backups of one kind, and the database in the newest alone.

    An older copy of the database is of no use: an update goes back to the
    backup it made itself.
    """
    found = list_backups(backups, kind)
    for old in found[keep:]:
        shutil.rmtree(old, ignore_errors=True)
    for older in found[1:keep]:
        shutil.rmtree(older / DATABASE, ignore_errors=True)
