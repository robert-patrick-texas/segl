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

"""Diagram mode on slot 9 (docs/API.md, "Diagram mode"; D2-039, D2-040).

First the room alone, as ``tests/test_room.py`` tests a whiteboard's: a test's
browser is a list of the messages the room delivered to it. Then the socket,
a restart, the migration that makes slot 9 a diagram, and the routes.
"""

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from harness import (
    GATED,
    PASS_HEADER,
    MarkOf,
    issue_pass,
    make_settings,
    next_message,
    running_segl,
    say_hello,
)
from starlette.testclient import WebSocketTestSession

from segl.app import create_app
from segl.diagram import (
    DIAGRAM_SLOT,
    EMPTY_DIAGRAM,
    PEN_HELD,
    DiagramRoom,
    diagram_document,
    diagram_of,
    empty_diagram,
)
from segl.repository import Repository, apply_migrations, load_migrations
from segl.room import NEEDS_CODE, Connection, Hello
from segl.saver import Saver

ONE = '<mxfile><diagram id="segl-page-1">one</diagram></mxfile>'
TWO = '<mxfile><diagram id="segl-page-1">two</diagram></mxfile>'
THREE = '<mxfile><diagram id="segl-page-1">three</diagram></mxfile>'


def patch(label: str) -> dict[str, Any]:
    """A drawio patch. The server never reads one, so any object stands in."""
    return {"u": {"segl-page-1": {"cells": {"i": [{"id": label}]}}}}


class Browser:
    """A connection on slot 9, and everything the room has sent it."""

    def __init__(
        self,
        room: DiagramRoom,
        name: str | None = "Guest1",
        *,
        view_only: bool = False,
        mark: str | None = None,
    ) -> None:
        self.room = room
        self.received: list[dict[str, Any]] = []
        self.connection = Connection(
            lambda text: self.received.append(json.loads(text)),
            Hello("client-1", name, "", mark),
            view_only=view_only,
        )
        room.join(self.connection, mark)

    @property
    def id(self) -> str:
        return self.connection.id

    def take(self) -> list[dict[str, Any]]:
        """Return what arrived since the last call."""
        messages, self.received = self.received, []
        return messages

    def send(self, message: object) -> None:
        self.room.receive(self.connection, message)

    def patch(
        self, pid: str, base: int, xml: str = ONE, *, seq: int | None = None, epoch: int = 1
    ) -> None:
        message: dict[str, Any] = {
            "type": "patch",
            "epoch": epoch,
            "base": base,
            "pid": pid,
            "patch": patch(pid),
            "checksum": -12345,
            "xml": xml,
        }
        self.send(message if seq is None else {**message, "seq": seq})

    def copy(self, base: int, xml: str) -> None:
        self.send({"type": "copy", "epoch": 1, "base": base, "xml": xml})

    def errors(self) -> list[str]:
        return [message["error"] for message in self.take() if message["type"] == "error"]


@pytest.fixture
def room() -> DiagramRoom:
    return DiagramRoom(DIAGRAM_SLOT, "Workspace 9", 1, EMPTY_DIAGRAM, start="s")


def patches_of(messages: list[dict[str, Any]]) -> list[tuple[int, str, bool]]:
    return [(m["n"], m["pid"], m["exact"]) for m in messages if m["type"] == "patch"]


# The head as stored.


def test_slot_9_is_stored_as_a_json_document_that_holds_the_xml() -> None:
    assert json.loads(empty_diagram()) == {"diagram": EMPTY_DIAGRAM}
    assert diagram_of(diagram_document(ONE)) == ONE
    # A head that holds no diagram, such as a whiteboard's, reads as the empty one.
    assert diagram_of('{"elements":[]}') == EMPTY_DIAGRAM
    assert diagram_of("[]") == EMPTY_DIAGRAM


def test_the_empty_diagram_has_one_page_with_a_fixed_id() -> None:
    # Every browser loads the same text, so a patch names a page each one has.
    assert EMPTY_DIAGRAM.count("<diagram ") == 1
    assert 'id="segl-page-1"' in EMPTY_DIAGRAM


# Joining.


def test_a_browser_is_welcomed_with_the_pen_and_sent_the_whole_diagram(room: DiagramRoom) -> None:
    browser = Browser(room, "Alpha1")

    welcome, diagram = browser.take()
    assert welcome["type"] == "welcome"
    assert (welcome["slot"], welcome["epoch"], welcome["viewOnly"]) == (9, 1, False)
    assert welcome["pen"] is None
    assert diagram == {
        "type": "diagram",
        "epoch": 1,
        "whole": True,
        "mark": "s.1.0",
        "count": 0,
        "patches": [],
        "xml": EMPTY_DIAGRAM,
    }


def test_a_mark_of_this_room_gets_only_the_patches_after_it(room: DiagramRoom) -> None:
    first = Browser(room)
    for n in range(1, 4):
        first.patch(f"p{n}", n - 1)

    late = Browser(room, mark="s.1.1")

    diagram = late.take()[1]
    assert (diagram["whole"], diagram["count"], diagram["mark"]) == (False, 1, "s.1.3")
    assert "xml" not in diagram
    assert [entry["n"] for entry in diagram["patches"]] == [2, 3]


@pytest.mark.parametrize("mark", [None, "other.1.0", "s.2.0", "s.1.9", "s.1.x"])
def test_any_other_mark_gets_the_whole_diagram(room: DiagramRoom, mark: str | None) -> None:
    first = Browser(room)
    first.patch("p1", 0, ONE)

    late = Browser(room, mark=mark)

    diagram = late.take()[1]
    assert (diagram["whole"], diagram["xml"], diagram["count"]) == (True, ONE, 1)
    assert diagram["patches"] == []


def test_a_mark_older_than_the_stored_head_gets_the_whole_diagram(room: DiagramRoom) -> None:
    first = Browser(room)
    first.patch("p1", 0, ONE)
    first.patch("p2", 1, TWO)
    room.wrote(room.snapshot())

    late = Browser(room, mark="s.1.1")

    diagram = late.take()[1]
    assert (diagram["whole"], diagram["xml"], diagram["count"]) == (True, TWO, 2)
    assert room.patches == []


# Numbering and order.


def test_patches_are_numbered_in_the_order_taken_and_sent_to_everyone(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room, "Alpha1"), Browser(room, "Bravo2")
    alpha.take(), bravo.take()

    alpha.patch("a1", 0)
    bravo.patch("b1", 0)
    alpha.patch("a2", 2)

    for browser in (alpha, bravo):
        assert patches_of(browser.take()) == [(1, "a1", True), (2, "b1", False), (3, "a2", True)]
    assert room.count == 3


def test_a_patch_carries_what_the_page_sent_and_the_mark_after_it(room: DiagramRoom) -> None:
    alpha = Browser(room)
    alpha.take()

    alpha.patch("a1", 0)

    (sent,) = alpha.take()
    assert sent == {
        "type": "patch",
        "epoch": 1,
        "mark": "s.1.1",
        "n": 1,
        "pid": "a1",
        "patch": patch("a1"),
        "checksum": -12345,
        "exact": True,
    }


# The copy rule.


def test_a_copy_is_kept_when_its_sender_held_every_patch_before_it(room: DiagramRoom) -> None:
    alpha = Browser(room, "Alpha1")

    alpha.patch("a1", 0, ONE)

    assert (room.xml, room.copy_count, room.dirty) == (ONE, 1, True)
    assert room.editor_label == "Alpha1"


def test_a_copy_is_not_kept_when_another_patch_came_between(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, ONE)

    bravo.patch("b1", 0, TWO)

    assert (room.xml, room.copy_count) == (ONE, 1)


def test_the_senders_own_patches_between_do_not_count(room: DiagramRoom) -> None:
    alpha = Browser(room)
    alpha.patch("a1", 0, ONE)

    # Sent before the first came back: its base is still 0.
    alpha.patch("a2", 0, TWO)

    assert (room.xml, room.copy_count) == (TWO, 2)


def test_a_copy_message_is_kept_when_it_holds_every_patch(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, ONE)
    bravo.patch("b1", 0, TWO)

    bravo.copy(2, THREE)

    assert (room.xml, room.copy_count) == (THREE, 2)


def test_a_copy_message_holds_the_senders_own_patches_after_its_base(room: DiagramRoom) -> None:
    alpha = Browser(room)
    alpha.patch("a1", 0, ONE)
    alpha.patch("a2", 0, TWO)

    # Sent before either came back: the copy holds both.
    alpha.copy(0, THREE)

    assert (room.xml, room.copy_count) == (THREE, 2)


def test_a_patch_whose_base_the_room_has_let_go_of_is_not_exact(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, ONE)
    alpha.patch("a2", 1, TWO)
    room.wrote(room.snapshot())
    alpha.take(), bravo.take()

    # Patches 1 and 2 are only in the stored head now: the room cannot tell
    # whether bravo held them.
    bravo.patch("b1", 0, THREE)

    assert patches_of(bravo.take()) == [(3, "b1", False)]
    assert room.xml == TWO


def test_a_copy_message_that_misses_a_patch_is_not_kept(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, ONE)
    bravo.patch("b1", 0, TWO)

    # Alpha had not seen b1.
    alpha.copy(1, THREE)

    assert (room.xml, room.copy_count) == (ONE, 1)


def test_a_change_outside_the_pages_is_kept_with_no_new_patch(room: DiagramRoom) -> None:
    alpha = Browser(room, "Alpha1")
    alpha.patch("a1", 0, ONE)
    room.snapshot()

    # A page's background, say: drawio sends the diagram and no patch.
    alpha.copy(1, TWO)

    assert (room.xml, room.copy_count, room.dirty) == (TWO, 1, True)


# What is saved.


def test_saved_waits_for_a_kept_copy_that_holds_the_patch(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, seq=1)
    bravo.patch("b1", 0, seq=1)

    assert alpha.connection.awaiting == 1
    assert bravo.connection.awaiting is None

    bravo.copy(2, TWO)

    assert bravo.connection.awaiting == 1


def test_another_browsers_copy_saves_a_patch_it_holds(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, seq=4)
    bravo.patch("b1", 0, seq=7)
    alpha.patch("a2", 2, seq=5)

    assert (alpha.connection.awaiting, bravo.connection.awaiting) == (5, 7)


# Reload.


def test_reload_sends_the_whole_diagram_to_the_asker_alone(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, ONE)
    bravo.patch("b1", 0, TWO)
    alpha.take(), bravo.take()

    bravo.send({"type": "reload"})

    assert alpha.take() == []
    (whole,) = bravo.take()
    assert (whole["whole"], whole["xml"], whole["count"], whole["mark"]) == (True, ONE, 1, "s.1.2")
    assert [entry["pid"] for entry in whole["patches"]] == ["b1"]


def test_a_viewer_may_reload(room: DiagramRoom) -> None:
    viewer = Browser(room, view_only=True)
    viewer.take()

    viewer.send({"type": "reload"})

    assert viewer.take()[0]["type"] == "diagram"


# The edit gate, the size limit, and bad messages.


def test_a_viewer_changes_nothing(room: DiagramRoom) -> None:
    viewer = Browser(room, view_only=True)
    viewer.take()

    viewer.patch("v1", 0)
    viewer.copy(0, ONE)

    assert viewer.errors() == ["view_only", "view_only"]
    assert (room.count, room.xml, room.dirty) == (0, EMPTY_DIAGRAM, False)


def test_a_copy_larger_than_the_limit_is_refused_and_a_smaller_one_taken() -> None:
    limit = len(json.dumps(ONE))
    room = DiagramRoom(9, "Workspace 9", 1, EMPTY_DIAGRAM, max_scene_bytes=limit, start="s")
    alpha = Browser(room)
    alpha.take()

    alpha.patch("a1", 0, ONE)
    alpha.patch("a2", 1, ONE + "x")
    # A diagram over the limit can still be made smaller.
    room.xml = ONE * 3
    alpha.patch("a3", 1, ONE * 2)

    (error,) = [m for m in alpha.take() if m["type"] == "error"]
    assert error["error"] == "scene_too_large"
    assert [patch.pid for patch in room.patches] == ["a1", "a3"]


@pytest.mark.parametrize(
    "change",
    [
        {"epoch": "1"},
        {"epoch": True},
        {"base": -1},
        {"base": 5},
        {"base": 1.5},
        {"pid": ""},
        {"pid": "a/b"},
        {"pid": "x" * 65},
        {"patch": []},
        {"patch": "u"},
        {"checksum": 1.5},
        {"checksum": True},
        {"checksum": 2**60},
        {"xml": None},
    ],
    ids=lambda change: json.dumps(change)[:40],
)
def test_a_bad_patch_is_refused_and_changes_nothing(
    room: DiagramRoom, change: dict[str, object]
) -> None:
    alpha = Browser(room)
    alpha.take()
    message = {"type": "patch", "epoch": 1, "base": 0, "pid": "p", "patch": {}, "xml": ONE}

    alpha.send({**message, "checksum": None, **change})

    assert alpha.errors() == ["bad_message"]
    assert room.count == 0


def test_a_patch_for_another_epoch_gets_the_whole_diagram(room: DiagramRoom) -> None:
    alpha = Browser(room)
    alpha.take()

    alpha.patch("old", 0, epoch=0)

    (whole,) = alpha.take()
    assert (whole["type"], whole["whole"]) == ("diagram", True)
    assert room.count == 0


@pytest.mark.parametrize("kind", ["elements", "files", "lasso"])
def test_slot_9_knows_no_whiteboard_message(room: DiagramRoom, kind: str) -> None:
    alpha = Browser(room)
    alpha.take()

    alpha.send({"type": kind, "epoch": 1, "elements": []})

    assert alpha.errors() == ["unknown_type"]


# The pen.


def pens(browser: Browser) -> list[str | None]:
    return [message["holder"] for message in browser.take() if message["type"] == "pen"]


def test_taking_the_pen_tells_everyone(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.take(), bravo.take()

    alpha.send({"type": "pen", "take": True})

    assert pens(alpha) == pens(bravo) == [alpha.id]
    assert room.pen is alpha.connection


def test_while_someone_holds_the_pen_only_the_holder_changes_the_diagram(
    room: DiagramRoom,
) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.send({"type": "pen", "take": True})
    alpha.take(), bravo.take()

    bravo.patch("b1", 0, TWO)
    bravo.copy(0, TWO)
    alpha.patch("a1", 0, ONE)

    errors = [m for m in bravo.take() if m["type"] == "error"]
    assert [(m["error"], m["message"]) for m in errors] == [("pen_held", PEN_HELD)] * 2
    assert [patch.pid for patch in room.patches] == ["a1"]
    assert room.xml == ONE


def test_anyone_who_may_edit_takes_the_pen_from_its_holder(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.send({"type": "pen", "take": True})
    alpha.take()

    bravo.send({"type": "pen", "take": True})
    alpha.patch("a1", 0)

    told = alpha.take()
    assert [(m["type"], m.get("holder"), m.get("error")) for m in told] == [
        ("pen", bravo.id, None),
        ("error", None, "pen_held"),
    ]


def test_a_viewer_never_gets_the_pen(room: DiagramRoom) -> None:
    viewer = Browser(room, view_only=True)
    viewer.take()

    viewer.send({"type": "pen", "take": True})

    assert [(m["error"], m["message"]) for m in viewer.take()] == [("view_only", NEEDS_CODE)]
    assert room.pen is None


def test_the_holder_gives_the_pen_back(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.send({"type": "pen", "take": True})
    alpha.take(), bravo.take()

    bravo.send({"type": "pen", "take": False})
    assert room.pen is alpha.connection
    alpha.send({"type": "pen", "take": False})

    assert pens(bravo) == [None]
    bravo.patch("b1", 0)
    assert room.count == 1


def test_the_pen_is_free_again_when_its_holder_leaves(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.send({"type": "pen", "take": True})
    bravo.take()

    room.leave(alpha.connection)

    assert pens(bravo) == [None]
    assert room.pen is None


def test_a_browser_that_joins_is_told_who_holds_the_pen(room: DiagramRoom) -> None:
    alpha = Browser(room)
    alpha.send({"type": "pen", "take": True})

    late = Browser(room)

    assert late.take()[0]["pen"] == alpha.id


@pytest.mark.parametrize("take", [None, 1, "yes"])
def test_a_pen_message_needs_true_or_false(room: DiagramRoom, take: object) -> None:
    alpha = Browser(room)
    alpha.take()

    alpha.send({"type": "pen", "take": take})

    assert alpha.errors() == ["bad_message"]


def test_taking_the_pen_twice_tells_nobody_again(room: DiagramRoom) -> None:
    alpha = Browser(room)
    alpha.send({"type": "pen", "take": True})
    alpha.take()

    alpha.send({"type": "pen", "take": True})

    assert alpha.take() == []


# The snapshot the saver writes.


def test_a_snapshot_is_the_kept_copy_at_its_count(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room, "Alpha1"), Browser(room)
    alpha.patch("a1", 0, ONE)
    bravo.patch("b1", 0, TWO)

    snapshot = room.snapshot()

    assert (snapshot.count, snapshot.elements, snapshot.files) == (1, [], [])
    assert snapshot.scene_json() == diagram_document(ONE)
    assert room.dirty is False
    room.take_back(snapshot)
    assert room.dirty is True


def test_a_written_copy_lets_go_of_the_patches_it_holds(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, ONE)
    bravo.patch("b1", 0, TWO)

    room.wrote(room.snapshot())

    assert [patch.pid for patch in room.patches] == ["b1"]
    assert (room.trimmed, room.written) == (1, (1, 1))


def test_the_saver_writes_the_copy_to_slot_9s_head(tmp_path: Path) -> None:
    with Repository(tmp_path / "segl.sqlite") as repository:
        repository.bootstrap()
        room = DiagramRoom(9, "Workspace 9", 1, EMPTY_DIAGRAM, start="s")

        async def main() -> Browser:
            saver = Saver(
                room,
                repository,
                head_flush_seconds=3600,
                history_interval_seconds=0,
                saved_at="",
            )
            alpha = Browser(room, "Alpha1")
            alpha.patch("a1", 0, ONE, seq=1)
            # A stop writes what the room holds, as a SIGTERM does.
            await asyncio.wait_for(saver.close(), 10)
            return alpha

        alpha = asyncio.run(main())

        head = repository.get_head(9)
        assert (head.scene_json, head.editor_label) == (diagram_document(ONE), "Alpha1")
        (row,) = repository.list_revisions(9)
        assert repository.get_revision(9, row.revision).scene_json == diagram_document(ONE)
        assert [m["type"] for m in alpha.take()][-1] == "saved"


# At the socket.


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[Repository]:
    with Repository(tmp_path / "segl.sqlite") as repository:
        repository.bootstrap()
        yield repository


def numbered_patch(pid: str, base: int, xml: str, seq: int) -> dict[str, Any]:
    return {
        "type": "patch",
        "epoch": 1,
        "base": base,
        "pid": pid,
        "patch": patch(pid),
        "checksum": None,
        "xml": xml,
        "seq": seq,
    }


def received(socket: WebSocketTestSession, seconds: float = 5.0) -> dict[str, Any]:
    """Return the next message, and fail the test rather than wait for ever."""

    async def receive() -> Any:
        with anyio.fail_after(seconds):
            return await socket._send_rx.receive()

    message = socket.portal.call(receive)
    socket._raise_on_close(message)
    return json.loads(message["text"])


def test_the_socket_numbers_patches_and_saves_the_copy(repository: Repository) -> None:
    settings = make_settings(head_flush_seconds=0.02)
    with (
        TestClient(create_app(settings, repository)) as client,
        client.websocket_connect("/collab?slot=9") as alpha,
        client.websocket_connect("/collab?slot=9") as bravo,
    ):
        alpha.send_json(
            {"type": "hello", "clientId": "a", "displayName": "Alpha1", "editToken": ""}
        )
        welcome, diagram = received(alpha), received(alpha)
        bravo.send_json({"type": "hello", "clientId": "b", "displayName": None, "editToken": ""})
        received(bravo), received(bravo), received(alpha)
        assert (welcome["pen"], diagram["whole"], diagram["xml"]) == (None, True, EMPTY_DIAGRAM)

        alpha.send_json(numbered_patch("a1", 0, ONE, 1))
        assert received(alpha)["n"] == received(bravo)["n"] == 1
        saved = received(alpha)
        assert (saved["type"], saved["seq"]) == ("saved", 1)

        scene = client.get("/api/v1/slots/9/scene").json()
        assert scene["scene"] == {"diagram": ONE}
        assert scene["mark"] == MarkOf(1, 1)


def test_the_socket_refuses_a_browser_without_a_pass(repository: Repository) -> None:
    with (
        TestClient(create_app(make_settings(**GATED), repository)) as client,
        client.websocket_connect("/collab?slot=9") as viewer,
        client.websocket_connect("/collab?slot=9") as editor,
    ):
        viewer.send_json({"type": "hello", "clientId": "v", "displayName": None, "editToken": ""})
        assert received(viewer)["viewOnly"] is True
        received(viewer)
        editor.send_json(
            {"type": "hello", "clientId": "e", "displayName": None, "editToken": issue_pass()}
        )
        assert received(editor)["viewOnly"] is False
        received(editor), received(viewer)

        viewer.send_json(numbered_patch("v1", 0, ONE, 1))
        viewer.send_json({"type": "pen", "take": True})
        assert [received(viewer)["error"] for _ in range(2)] == ["view_only"] * 2
        editor.send_json({"type": "pen", "take": True})
        assert received(viewer)["type"] == "pen"
        assert client.get("/api/v1/slots/9/scene").json()["scene"] == {"diagram": EMPTY_DIAGRAM}


def test_a_restart_keeps_slot_9s_head(tmp_path: Path) -> None:
    with (
        running_segl(tmp_path, "head_flush_seconds = 0.05\n") as server,
        server.socket("/collab?slot=9") as socket,
    ):
        say_hello(socket, "Alpha1")
        socket.send(json.dumps(numbered_patch("a1", 0, TWO, 1)))
        assert next_message(socket)["n"] == 1
        assert next_message(socket)["type"] == "saved"

    with running_segl(tmp_path) as again:
        scene = again.get("/api/v1/slots/9/scene").json()
        assert (scene["scene"], scene["editorLabel"]) == ({"diagram": TWO}, "Alpha1")
        with again.socket("/collab?slot=9") as socket:
            _, diagram = say_hello(socket, mark=scene["mark"])
            # The same process's mark: nothing has changed since the head.
            assert (diagram["whole"], diagram["patches"]) == (False, [])


# The migration, and the routes.


def schema_3(path: Path) -> None:
    """Make a database as 0.6.0 left it, with slot 9 drawn on as a whiteboard."""
    with Repository(path) as repository:
        repository.bootstrap()
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA user_version = 3")
        db.execute(
            "UPDATE slot_head SET scene_json = ?, editor_label = 'Bravo2' WHERE slot IN (8, 9)",
            ('{"elements":[{"id":"a"}]}',),
        )
        db.execute("UPDATE slot SET title = 'Plans', epoch = 4 WHERE number = 9")
        for slot in (8, 9):
            db.execute(
                "INSERT INTO revision (slot, revision, epoch, author_label, created_at, scene_zstd)"
                " VALUES (?, 1, 1, 'Bravo2', '2026-11-20T10:00:00.000Z', x'00')",
                (slot,),
            )
            db.execute(
                "INSERT INTO slot_file (slot, file_id, hash, media_type, created_at)"
                " VALUES (?, 'f', ?, 'image/png', '2026-11-20T10:00:00.000Z')",
                (slot, "a" * 64),
            )
        db.commit()


def test_the_migration_makes_slot_9_an_empty_diagram(tmp_path: Path) -> None:
    path = tmp_path / "segl.sqlite"
    schema_3(path)

    with Repository(path) as repository:
        repository.bootstrap()
        head, slot = repository.get_head(9), repository.get_slot(9)

        assert (head.scene_json, head.editor_label, head.epoch) == (empty_diagram(), "System", 5)
        assert (slot.title, slot.epoch) == ("Plans", 5)
        assert repository.list_revisions(9) == []
        assert repository.list_files(9) == []
        # Slot 8 is as it was.
        assert repository.get_head(8).scene_json == '{"elements":[{"id":"a"}]}'
        assert len(repository.list_revisions(8)) == 1
        assert [file.hash for file in repository.list_files(8)] == ["a" * 64]


def test_the_migration_is_number_4_and_calls_segls_function() -> None:
    migration = load_migrations()[3]

    assert migration.name == "0004_diagram_slot.sql"
    assert "segl_empty_diagram()" in migration.sql
    with closing(sqlite3.connect(":memory:", autocommit=True)) as db:
        assert apply_migrations(db, load_migrations()) == 4


def test_clearing_slot_9_gives_it_the_empty_diagram(repository: Repository) -> None:
    repository.flush_head(9, 1, diagram_document(ONE), "Alpha1", history_seconds=0)

    cleared = repository.clear_slot(9)

    assert repository.get_head(9).scene_json == empty_diagram()
    assert (cleared.epoch, repository.list_revisions(9)) == (2, [])


def test_slot_9_has_no_import_yet(repository: Repository) -> None:
    client = TestClient(create_app(make_settings(), repository))

    reply = client.post("/api/v1/slots/9/import", json={"type": "excalidraw", "elements": []})

    assert reply.status_code == 409
    assert reply.json()["error"] == "diagram_mode"
    # Slot 9's restore is tests/test_diagram_history.py's (T19).


@pytest.mark.parametrize("route", ["restore", "import"])
def test_a_viewer_is_told_view_only_before_diagram_mode(repository: Repository, route: str) -> None:
    client = TestClient(create_app(make_settings(**GATED), repository))

    reply = client.post(f"/api/v1/slots/9/{route}", json={"revision": 1})

    assert (reply.status_code, reply.json()["error"]) == (403, "view_only")
    assert (
        client.post(
            "/api/v1/slots/9/import", json={"revision": 1}, headers={PASS_HEADER: issue_pass()}
        ).json()["error"]
        == "diagram_mode"
    )
