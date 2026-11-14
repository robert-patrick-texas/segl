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

"""Copies of what an update changes, and putting them back."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from segl.update import backup

NOW = datetime(2026, 11, 13, 21, 0, 5, tzinfo=UTC)


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o7777


def test_a_backup_folder_is_named_for_its_kind_and_time_and_is_the_owners_alone(
    tmp_path: Path,
) -> None:
    backups = tmp_path / "update" / "backups"

    folder = backup.new_backup(backups, backup.PRE_UPDATE, NOW)

    assert folder == backups / "pre-update-20261113T210005Z"
    assert mode(folder) == mode(backups) == 0o700
    # Two in one second get two folders.
    assert backup.new_backup(backups, backup.PRE_UPDATE, NOW).name == (
        "pre-update-20261113T210005Z-2"
    )
    assert backup.new_backup(backups, backup.MERGE, NOW).name == "merge-20261113T210005Z"
    assert [path.name for path in backup.list_backups(backups, backup.PRE_UPDATE)] == [
        "pre-update-20261113T210005Z-2",
        "pre-update-20261113T210005Z",
    ]


def test_a_backup_folder_that_cannot_be_made_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "backups").write_text("a file in the way", encoding="utf-8")

    with pytest.raises(backup.BackupError, match="cannot make a backup folder"):
        backup.new_backup(tmp_path / "backups", backup.MERGE, NOW)


def test_a_file_is_saved_with_its_mode_and_put_back_whole(tmp_path: Path) -> None:
    settings = tmp_path / "etc" / "segl.toml"
    settings.parent.mkdir()
    settings.write_text("as the site wrote it\n", encoding="utf-8")
    settings.chmod(0o640)
    folder = backup.new_backup(tmp_path / "backups", backup.PRE_UPDATE, NOW)

    assert backup.save_file(folder, "etc/segl.toml", settings) is True
    assert backup.save_file(folder, "etc/absent.toml", tmp_path / "etc" / "absent.toml") is False

    assert mode(folder / "etc/segl.toml") == 0o640
    # Unchanged, there is nothing to put back.
    assert backup.restore_file(folder, "etc/segl.toml", settings) is False
    settings.write_text("as an update left it\n", encoding="utf-8")
    settings.chmod(0o600)
    assert backup.restore_file(folder, "etc/segl.toml", settings) is True
    assert settings.read_text(encoding="utf-8") == "as the site wrote it\n"
    assert mode(settings) == 0o640
    assert backup.restore_file(folder, "etc/absent.toml", settings) is False
    assert sorted(path.name for path in settings.parent.iterdir()) == ["segl.toml"]


def test_a_file_that_was_removed_since_is_put_back(tmp_path: Path) -> None:
    site = tmp_path / "nginx" / "snippets" / "segl-proxy.conf"
    site.parent.mkdir(parents=True)
    site.write_text("proxy_pass http://segl/;\n", encoding="utf-8")
    folder = backup.new_backup(tmp_path / "backups", backup.PRE_UPDATE, NOW)
    backup.save_file(folder, "nginx/snippets/segl-proxy.conf", site)
    site.unlink()

    assert backup.restore_file(folder, "nginx/snippets/segl-proxy.conf", site) is True
    assert site.read_text(encoding="utf-8") == "proxy_pass http://segl/;\n"


def test_a_folder_is_saved_without_its_links_and_put_back(tmp_path: Path) -> None:
    etc = tmp_path / "etc"
    (etc / "more").mkdir(parents=True)
    (etc / "segl.toml").write_text("settings\n", encoding="utf-8")
    (etc / "more" / "notes.txt").write_text("notes\n", encoding="utf-8")
    (etc / "link").symlink_to("/etc/shadow")
    folder = backup.new_backup(tmp_path / "backups", backup.PRE_UPDATE, NOW)

    backup.save_folder(folder, "etc", etc)
    backup.save_folder(folder, "none", tmp_path / "absent")

    saved = sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())
    assert saved == ["etc/more/notes.txt", "etc/segl.toml"]
    (etc / "segl.toml").write_text("changed\n", encoding="utf-8")
    (etc / "added.toml").write_text("new since\n", encoding="utf-8")

    assert backup.restore_folder(folder, "etc", etc) == [etc / "segl.toml"]

    assert (etc / "segl.toml").read_text(encoding="utf-8") == "settings\n"
    # A file that is new since is the site's, and stays.
    assert (etc / "added.toml").is_file()


def test_an_exact_restore_removes_what_was_not_there(tmp_path: Path) -> None:
    merged = tmp_path / "merged" / "nginx"
    merged.mkdir(parents=True)
    (merged / "segl-proxy.conf").write_text("old\n", encoding="utf-8")
    folder = backup.new_backup(tmp_path / "backups", backup.PRE_UPDATE, NOW)
    backup.save_folder(folder, "merged", merged)
    (merged / "segl-proxy.conf").write_text("new\n", encoding="utf-8")
    (merged / "segl-new.conf").write_text("new file\n", encoding="utf-8")

    changed = backup.restore_folder(folder, "merged", merged, exact=True)

    assert sorted(changed) == [merged / "segl-new.conf", merged / "segl-proxy.conf"]
    assert sorted(path.name for path in merged.iterdir()) == ["segl-proxy.conf"]
    assert (merged / "segl-proxy.conf").read_text(encoding="utf-8") == "old\n"


def test_the_database_goes_back_without_the_files_of_the_one_it_replaces(tmp_path: Path) -> None:
    database = tmp_path / "var" / "segl.sqlite"
    database.parent.mkdir()
    database.write_bytes(b"before the update")
    database.chmod(0o640)
    folder = backup.new_backup(tmp_path / "backups", backup.PRE_UPDATE, NOW)
    assert backup.database_bytes(database) == len(b"before the update")

    backup.save_database(folder, database)

    assert sorted(path.name for path in (folder / "database").iterdir()) == ["segl.sqlite"]
    # The newer version wrote the database, and left a write-ahead log.
    database.write_bytes(b"migrated")
    wal = database.with_name("segl.sqlite-wal")
    wal.write_bytes(b"pages of the migrated database")
    database.with_name("segl.sqlite-shm").write_bytes(b"index")
    (database.parent / "assets").mkdir()

    assert backup.restore_database(folder, database) is True

    assert database.read_bytes() == b"before the update"
    assert mode(database) == 0o640
    assert sorted(path.name for path in database.parent.iterdir()) == ["assets", "segl.sqlite"]


def test_a_backup_without_a_database_puts_none_back(tmp_path: Path) -> None:
    database = tmp_path / "segl.sqlite"
    database.write_bytes(b"as it is")
    folder = backup.new_backup(tmp_path / "backups", backup.PRE_UPDATE, NOW)

    assert backup.restore_database(folder, database) is False
    assert database.read_bytes() == b"as it is"


def test_replace_file_keeps_the_mode_and_leaves_no_part(tmp_path: Path) -> None:
    target = tmp_path / "segl.conf"
    target.write_bytes(b"old")
    target.chmod(0o600)

    backup.replace_file(target, b"new")
    backup.replace_file(tmp_path / "made.conf", b"made")

    assert target.read_bytes() == b"new" and mode(target) == 0o600
    assert mode(tmp_path / "made.conf") == 0o644
    assert sorted(path.name for path in tmp_path.iterdir()) == ["made.conf", "segl.conf"]


def test_prune_keeps_the_newest_and_one_copy_of_the_database(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    for second in range(5):
        folder = backup.new_backup(backups, backup.PRE_UPDATE, NOW.replace(second=second))
        (folder / "database").mkdir()
        (folder / "database" / "segl.sqlite").write_bytes(b"x")
        (folder / "etc").mkdir()
    backup.new_backup(backups, backup.MERGE, NOW)

    backup.prune(backups, backup.PRE_UPDATE)

    kept = backup.list_backups(backups, backup.PRE_UPDATE)
    assert [path.name[-3:] for path in kept] == ["04Z", "03Z", "02Z"]
    assert [(path / "database").exists() for path in kept] == [True, False, False]
    assert all((path / "etc").is_dir() for path in kept)
    # Another kind is not touched.
    assert len(backup.list_backups(backups, backup.MERGE)) == 1
