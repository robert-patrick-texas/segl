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

"""History that lasts (S-005, docs/TEST-PLAN.md T-023): which revisions stay,
the revisions kept before a big delete, a restore, and an import, and a
database from 0.5.0. Every test sets the clock. ``tests/test_clear.py`` covers
``segl slot clear``, and ``web/e2e/lasting.spec.ts`` runs T-023 in a browser.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from harness import EMPTY_SCENE, make_settings
from starlette.testclient import WebSocketTestSession

from segl.app import create_app
from segl.repository import (
    Repository,
    RevisionNotFound,
    apply_migrations,
    load_migrations,
    unpack_scene,
)
from segl.retention import KEPT_AT_MOST, Row, staying
from segl.saver import deletes_most

SLOT = 2
START = datetime(2026, 11, 26, 10, 0, 0, tzinfo=UTC)
REVISIONS = f"/api/v1/slots/{SLOT}/revisions"
# Short enough for a test to wait for.
SOON = 0.02
# Longer than any test: no timer writes, and no row is due by its age.
NEVER = 3600


class Clock:
    """A clock the test moves by hand, from ``START``."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def element(identifier: str, version: int = 1, **more: object) -> dict[str, Any]:
    return {
        "id": identifier,
        "version": version,
        "versionNonce": 1,
        "index": f"a{identifier}",
        "type": "rectangle",
        **more,
    }


def deleted(of: dict[str, Any]) -> dict[str, Any]:
    """The element, deleted: as the editor sends a delete."""
    return {**of, "version": of["version"] + 1, "isDeleted": True}


# Ten live elements on a board.
TEN = [element(str(number)) for number in range(10)]


def scene(*elements: dict[str, Any]) -> str:
    return json.dumps({**EMPTY_SCENE, "elements": list(elements)}, separators=(",", ":"))


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


def application(repository: Repository, folder: Path, **settings: Any) -> TestClient:
    settings.setdefault("head_flush_seconds", SOON)
    settings.setdefault("history_interval_seconds", 1)
    return TestClient(
        create_app(make_settings(assets_dir=folder / "assets", **settings), repository)
    )


def received(socket: WebSocketTestSession, seconds: float = 5.0) -> dict[str, Any]:
    """Return the next message, and fail the test rather than wait for ever."""

    async def receive() -> Any:
        with anyio.fail_after(seconds):
            return await socket._send_rx.receive()

    message = socket.portal.call(receive)
    socket._raise_on_close(message)
    return json.loads(message["text"])


def hello(socket: WebSocketTestSession, name: str = "Guest1") -> None:
    socket.send_json({"type": "hello", "clientId": "c1", "displayName": name, "editToken": ""})
    assert received(socket)["type"] == "welcome"
    assert received(socket)["type"] == "scene"


def draw(socket: WebSocketTestSession, seq: int, *elements: dict[str, Any]) -> None:
    """Send elements, and wait for the ``saved`` that says the head holds them."""
    socket.send_json({"type": "elements", "epoch": 1, "elements": list(elements), "seq": seq})
    saved = received(socket)
    assert (saved["type"], saved["seq"]) == ("saved", seq), saved


def kept_rows(client: TestClient) -> list[tuple[int, str | None]]:
    """Return the slot's history as the list route gives it: revision and mark."""
    response = client.get(REVISIONS)
    assert response.status_code == 200
    return [(row["revision"], row["kept"]) for row in response.json()["revisions"]]


def live_ids(document: dict[str, Any]) -> list[str]:
    return [each["id"] for each in document["elements"] if not each.get("isDeleted")]


# The rules alone (segl/retention.py).


def at(**delta: float) -> datetime:
    return START + timedelta(**delta)


def test_the_newest_revisions_up_to_the_limit_stay_whatever_their_age() -> None:
    rows = [Row(number, at(days=-30 + number)) for number in range(1, 6)]

    assert staying(rows, at(), limit=5) == {1, 2, 3, 4, 5}
    assert staying(rows, at(), limit=2) == {4, 5}


def test_the_newest_of_each_minute_stays_for_an_hour() -> None:
    # Revisions 1 to 6: two in each of the minutes 9:00 to 9:02, at 10 and at 40 seconds.
    rows = [
        Row(number, at(minutes=-60 + (number - 1) // 2, seconds=10 + 30 * ((number - 1) % 2)))
        for number in range(1, 7)
    ]

    # At 10:00:30, 9:01 and 9:02 are two of the last 60 clock minutes, and 9:00 is not.
    assert staying(rows, at(seconds=30), limit=1) == {4, 6}
    # A minute later 9:01 is out too. 9:02's newest is the newest of its hour and its day.
    assert staying(rows, at(minutes=1, seconds=30), limit=1) == {6}


def test_the_newest_of_each_hour_stays_for_a_day_and_of_each_day_for_a_week() -> None:
    # Revisions 1 to 215, one at 30 minutes past each hour: 215 is at 9:30 today.
    rows = [Row(number, at(hours=number - 216, minutes=30)) for number in range(1, 216)]

    stay = staying(rows, at(), limit=1)

    # The 24 clock hours up to 10:00, which has none: 11:30 yesterday to 9:30.
    hours = set(range(193, 216))
    # The 7 clock days up to today: today's newest is 215, and each day
    # before has its newest at 23:30.
    days = {215} | {216 - 11 - 24 * back for back in range(6)}
    assert days == {215, 205, 181, 157, 133, 109, 85}
    assert stay == hours | days


def test_a_revision_from_after_now_stays() -> None:
    # The clock went back: the newest row was made "later" than now.
    rows = [Row(1, at(hours=-3)), Row(2, at(hours=-2)), Row(3, at(hours=5))]

    assert 3 in staying(rows, at(), limit=1)


def test_a_kept_revision_stays_a_week_and_then_goes() -> None:
    rows = [Row(1, at(), kept="delete"), Row(2, at(minutes=1)), Row(3, at(minutes=2))]

    assert staying(rows, at(days=7, minutes=-1), limit=1) == {1, 3}
    assert staying(rows, at(days=7), limit=1) == {3}


def test_at_most_20_kept_revisions_stay() -> None:
    rows = [Row(number, at(seconds=number), kept="restore") for number in range(1, 22)]

    assert KEPT_AT_MOST == 20
    assert staying(rows, at(minutes=1), limit=1) == set(range(2, 22))


def test_a_big_delete_is_one_that_leaves_fewer_than_90_percent() -> None:
    assert deletes_most(10, 8)
    assert not deletes_most(10, 9)
    assert deletes_most(9, 8)
    assert deletes_most(1, 0)
    assert not deletes_most(0, 0)
    assert not deletes_most(100, 90)
    assert deletes_most(100, 89)
    # More elements than before is never a delete.
    assert not deletes_most(10, 12)


# Through the repository, with the clock.


def test_two_hours_of_drawing_keep_the_newest_50_and_the_tiers(
    repo: Repository, clock: Clock
) -> None:
    """T-023: a slot written once a second for two hours, from 10:00 to 12:00 UTC."""
    for number in range(1, 7201):
        clock.advance(seconds=1)
        flush = repo.flush_head(SLOT, 1, scene(element("a", number)), "Guest1", history_seconds=1)
        assert flush.revision == number

    kept = {row.revision for row in repo.list_revisions(SLOT)}

    # Revision n was made n seconds after 10:00:00, so the last is at 12:00:00.
    newest = set(range(7151, 7201))
    # Each of the 60 clock minutes 11:01 to 12:00: its newest is at second 59,
    # and 12:00's is the last revision itself.
    minutes = {3600 + 60 * minute + 59 for minute in range(1, 60)} | {7200}
    # Each of the clock hours 10:00, 11:00, and 12:00, today.
    hours = {3599, 7199, 7200}
    assert kept == newest | minutes | hours
    assert len(kept) == 109
    # The scene of a kept minute is that minute's.
    assert json.loads(repo.get_revision(SLOT, 3719).scene_json)["elements"] == [element("a", 3719)]
    with pytest.raises(RevisionNotFound):
        repo.get_revision(SLOT, 3718)
    # Another slot's history is not touched.
    assert repo.list_revisions(3) == []


def test_the_21st_kept_revision_drops_the_oldest_kept_one(database: Path, clock: Clock) -> None:
    with Repository(database, history_limit=3, clock=clock) as repo:
        repo.bootstrap()
        # Each round draws a board and deletes all of it: the board's row is kept.
        for round_ in range(1, 22):
            clock.advance(seconds=0.001)
            repo.flush_head(SLOT, 1, scene(element("a", 2 * round_)), "Guest1", history_seconds=0)
            clock.advance(seconds=0.001)
            repo.flush_head(
                SLOT,
                1,
                scene(deleted(element("a", 2 * round_))),
                "Guest1",
                history_seconds=0,
                before_delete=True,
            )

        rows = repo.list_revisions(SLOT)

    # 42 rows: the boards are the odd ones. The 20 newest boards stay, and
    # so do the newest three rows: the last delete, board 41, and delete 40.
    marked = [row.revision for row in rows if row.kept == "delete"]
    assert marked == list(range(41, 1, -2))
    assert {row.revision for row in rows} == set(range(41, 1, -2)) | {42, 40}
    assert all(row.kept is None for row in rows if row.revision % 2 == 0)


def test_a_mark_stays_on_a_row_that_another_rule_keeps(repo: Repository, clock: Clock) -> None:
    # With the newest 50 kept, the oldest marked row is still there, and still says why.
    for round_ in range(1, 22):
        clock.advance(seconds=1)
        repo.flush_head(SLOT, 1, scene(element("a", 2 * round_)), "Guest1", history_seconds=0)
        repo.flush_head(
            SLOT,
            1,
            scene(deleted(element("a", 2 * round_))),
            "Guest1",
            history_seconds=0,
            before_delete=True,
        )

    rows = repo.list_revisions(SLOT)

    assert len(rows) == 42
    assert [row.revision for row in rows if row.kept == "delete"] == list(range(41, 0, -2))


def test_a_big_delete_keeps_the_head_when_no_revision_holds_it(
    repo: Repository, clock: Clock
) -> None:
    repo.flush_head(SLOT, 1, scene(*TEN), "Guest1", history_seconds=1)
    clock.advance(seconds=0.1)
    moved = scene(element("0", 2, x=5), *TEN[1:])
    # Younger than a second: the head moves on, and no row is due.
    assert repo.flush_head(SLOT, 1, moved, "Staff2", history_seconds=1).revision is None
    clock.advance(seconds=0.1)

    flush = repo.flush_head(
        SLOT, 1, scene(element("0", 2, x=5)), "Guest3", history_seconds=1, before_delete=True
    )

    assert flush.revision == 3
    rows = repo.list_revisions(SLOT)
    assert [(row.revision, row.kept, row.author_label) for row in rows] == [
        (3, None, "Guest3"),
        # The head as it was, by whoever saved it.
        (2, "delete", "Staff2"),
        (1, None, "Guest1"),
    ]
    assert repo.get_revision(SLOT, 2).scene_json == moved
    assert rows[1].created_at == rows[0].created_at


def test_an_unknown_reason_to_keep_is_refused(repo: Repository) -> None:
    repo.flush_head(SLOT, 1, scene(*TEN), "Guest1", history_seconds=0)

    with pytest.raises(ValueError, match="not a reason"):
        repo.replace_head(SLOT, scene(), "Guest1", kept="lunch")

    assert [(row.revision, row.kept) for row in repo.list_revisions(SLOT)] == [(1, None)]
    assert repo.get_slot(SLOT).epoch == 1


def test_a_replacement_marks_the_newest_revision_only_when_it_holds_the_scene_that_goes(
    repo: Repository, clock: Clock
) -> None:
    repo.flush_head(SLOT, 1, scene(*TEN), "Guest1", history_seconds=1)
    clock.advance(seconds=0.1)
    # The head moves on, and no row holds it: nothing is marked.
    repo.flush_head(SLOT, 1, scene(*TEN[:9]), "Guest1", history_seconds=1)

    repo.replace_head(SLOT, scene(), "Staff2", kept="restore")

    assert [(row.revision, row.kept) for row in repo.list_revisions(SLOT)] == [(2, None), (1, None)]


# Through the socket: the saver says when a flush deletes most of the board.


def test_a_drop_below_90_percent_keeps_the_scene_before_it_for_a_week(
    database: Path, clock: Clock, tmp_path: Path
) -> None:
    with Repository(database, clock=clock) as repository:
        repository.bootstrap()
        with (
            application(repository, tmp_path) as client,
            client.websocket_connect(f"/collab?slot={SLOT}") as socket,
        ):
            hello(socket)
            draw(socket, 1, *TEN)
            # The clock stands still: no row is due by its age.
            draw(socket, 2, element("0", 2, x=5))
            assert kept_rows(client) == [(1, None)]

            # Two of ten deleted: eight are fewer than 90%.
            draw(socket, 3, deleted(TEN[1]), deleted(TEN[2]))

            assert kept_rows(client) == [(3, None), (2, "delete"), (1, None)]
            board = client.get(f"{REVISIONS}/2").json()
            assert board["kept"] == "delete"
            assert len(live_ids(board["scene"])) == 10
            assert board["scene"]["elements"][0]["x"] == 5
            after = client.get(f"{REVISIONS}/3").json()["scene"]
            assert len(live_ids(after)) == 8

    # Two more hours of drawing, a revision a second, on the same database.
    with Repository(database, clock=clock) as repository:
        for number in range(1, 7201):
            clock.advance(seconds=1)
            repository.flush_head(SLOT, 1, scene(element("z", number)), "Guest1", history_seconds=1)
        rows = {row.revision: row.kept for row in repository.list_revisions(SLOT)}
        assert rows[2] == "delete"
        assert 1 not in rows and 3 not in rows
        assert json.loads(repository.get_revision(SLOT, 2).scene_json) == board["scene"]

        # A week after it was kept, the next revision drops it.
        clock.advance(days=7)
        repository.flush_head(SLOT, 1, scene(element("z", 9000)), "Guest1", history_seconds=1)

        assert 2 not in {row.revision for row in repository.list_revisions(SLOT)}


def test_a_big_delete_marks_the_newest_revision_when_it_holds_the_board(
    repo: Repository, tmp_path: Path
) -> None:
    with (
        application(repo, tmp_path) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as socket,
    ):
        hello(socket)
        draw(socket, 1, *TEN)

        draw(socket, 2, *(deleted(each) for each in TEN[:5]))

        # Row 1 holds the board as it was: it is marked, and not written twice.
        assert kept_rows(client) == [(2, None), (1, "delete")]


def test_a_drop_that_leaves_90_percent_keeps_nothing_more(repo: Repository, tmp_path: Path) -> None:
    with (
        application(repo, tmp_path) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as socket,
    ):
        hello(socket)
        draw(socket, 1, *TEN)

        # Nine of ten is 90%: nothing more is kept, and no row is due.
        draw(socket, 2, deleted(TEN[0]))
        assert kept_rows(client) == [(1, None)]

        # Eight of the head's nine is fewer than 90%. The head, which no
        # revision holds, is kept first.
        draw(socket, 3, deleted(TEN[1]))
        assert kept_rows(client) == [(3, None), (2, "delete"), (1, None)]
        assert len(live_ids(client.get(f"{REVISIONS}/2").json()["scene"])) == 9


@pytest.fixture
def drawn(repo: Repository, clock: Clock) -> Repository:
    """Slot 2 with three revisions: a, then a and b, then a, b, and c."""
    for number, label in ((1, "Guest1"), (2, "Staff2"), (3, "Guest3")):
        clock.advance(seconds=1)
        elements = [element(name) for name in "abc"[:number]]
        repo.flush_head(SLOT, 1, scene(*elements), label, history_seconds=0)
    return repo


def test_a_restore_keeps_the_scene_it_replaced(drawn: Repository, tmp_path: Path) -> None:
    with (
        application(
            drawn, tmp_path, head_flush_seconds=NEVER, history_interval_seconds=NEVER
        ) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as socket,
    ):
        hello(socket)
        # In the room only: no timer writes it before the restore.
        socket.send_json({"type": "elements", "epoch": 1, "elements": [element("d")]})
        socket.send_json({"type": "rename", "displayName": "bea"})
        assert received(socket)["type"] == "presence"

        response = client.post(f"/api/v1/slots/{SLOT}/restore", json={"revision": 1})

        assert response.json()["revision"] == 5
        assert kept_rows(client) == [(5, None), (4, "restore"), (3, None), (2, None), (1, None)]
        replaced = client.get(f"{REVISIONS}/4").json()["scene"]
        assert live_ids(replaced) == ["a", "b", "c", "d"]


def test_a_restore_marks_the_newest_revision_when_it_holds_the_scene(
    drawn: Repository, tmp_path: Path
) -> None:
    with application(drawn, tmp_path) as client:
        client.post(f"/api/v1/slots/{SLOT}/restore", json={"revision": 1})

        assert kept_rows(client) == [(4, None), (3, "restore"), (2, None), (1, None)]


def test_an_import_keeps_the_scene_it_replaced(drawn: Repository, tmp_path: Path) -> None:
    document = {
        "type": "excalidraw",
        "version": 2,
        "source": "segl",
        "elements": [element("z")],
        "appState": {},
        "files": {},
    }
    with application(drawn, tmp_path) as client:
        response = client.post(f"/api/v1/slots/{SLOT}/import", content=json.dumps(document))

        assert response.status_code == 200
        assert kept_rows(client) == [(4, None), (3, "import"), (2, None), (1, None)]
        # The import itself is the first row of its epoch, and is not marked.
        assert client.get(f"{REVISIONS}/4").json()["epoch"] == 2


# A database from 0.5.0.


def test_a_database_from_0_5_0_migrates_and_reads_back_the_same(
    database: Path, clock: Clock
) -> None:
    """0.5.0 is at schema 2, with each revision's scene as plain text."""
    big = scene(*(element(f"{number:04d}", text="héllo \\u00e9 ✓") for number in range(300)))
    texts = [scene(element("a")), scene(element("a"), element("b")), big]
    with closing(sqlite3.connect(database, autocommit=True)) as connection:
        assert apply_migrations(connection, load_migrations()[:2]) == 2
        # What 0.5.0's bootstrap and flushes wrote.
        for slot in range(1, 10):
            connection.execute(
                "INSERT INTO slot VALUES (?, ?, ?, ?)",
                (slot, f"Workspace {slot}", 1, "2026-11-20T08:00:00.000Z"),
            )
            connection.execute(
                "INSERT INTO slot_head VALUES (?, 1, ?, 'System', '2026-11-20T08:00:00.000Z')",
                (slot, scene()),
            )
        connection.execute("UPDATE slot SET title = 'Core', epoch = 2 WHERE number = 2")
        connection.execute(
            "UPDATE slot_head SET epoch = 2, scene_json = ?, editor_label = 'Bravo2' "
            "WHERE slot = 2",
            (big,),
        )
        for number, text in enumerate(texts, start=1):
            connection.execute(
                "INSERT INTO revision VALUES (2, ?, ?, ?, ?, ?)",
                (
                    number,
                    min(number, 2),
                    text,
                    f"Guest{number}",
                    f"2026-11-20T08:0{number}:00.000Z",
                ),
            )
        connection.execute(
            "INSERT INTO slot_file VALUES (2, 'f1', ?, 'image/png', '2026-11-20T08:01:00.000Z')",
            ("a" * 64,),
        )
        connection.execute("INSERT INTO name_counter VALUES (1, 17)")

    with Repository(database, clock=clock) as repository:
        repository.bootstrap()

        rows = repository.list_revisions(2)
        assert [(row.revision, row.epoch, row.author_label, row.kept) for row in rows] == [
            (3, 2, "Guest3", None),
            (2, 2, "Guest2", None),
            (1, 1, "Guest1", None),
        ]
        assert [row.created_at for row in rows] == [
            "2026-11-20T08:03:00.000Z",
            "2026-11-20T08:02:00.000Z",
            "2026-11-20T08:01:00.000Z",
        ]
        for number, text in enumerate(texts, start=1):
            assert repository.get_revision(2, number).scene_json == text
        assert repository.get_head(2).scene_json == big
        assert repository.get_slot(2).title == "Core"
        assert [file.file_id for file in repository.list_files(2)] == ["f1"]
        assert repository.allocate_display_name(["Alpha"]) == "Alpha17"
        # Drawing goes on, and the history with it.
        assert repository.flush_head(2, 2, scene(), "Guest4", history_seconds=1).revision == 4

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (len(load_migrations()),)
        stored = connection.execute(
            "SELECT typeof(scene_zstd), scene_zstd FROM revision WHERE slot = 2 AND revision = 3"
        ).fetchone()
        assert stored[0] == "blob"
        assert unpack_scene(stored[1]) == big
        # Compressed: the 300 elements take far less room.
        assert len(stored[1]) * 5 < len(big)
        names = {name for (name,) in connection.execute("SELECT name FROM sqlite_master")}
        assert "revision_0002" not in names
