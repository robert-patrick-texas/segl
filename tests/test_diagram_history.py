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

"""History and restore on slot 9, and a big delete there (T19; D2-011, D2-030).

A restore on slot 9 is a whiteboard's: the diagram that goes is kept, marked
``restore``, and a new epoch starts with the revision's diagram, which every
browser is sent whole. While someone holds the pen, only the holder restores
(docs/API.md, the restore route). For the rule on a big delete, the saver
counts the diagram's shapes and links (docs/DATA-MODEL.md, "Slot 9's
diagram"). First the room alone, then the saver, then the routes and the
socket.
"""

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from harness import EMPTY_SCENE, MarkOf, make_settings
from starlette.testclient import WebSocketTestSession
from test_diagram import Browser, patch, patches_of
from test_follow import received

from segl import diagram as diagram_module
from segl.app import create_app
from segl.diagram import (
    DIAGRAM_SLOT,
    EMPTY_DIAGRAM,
    PEN_HELD,
    DiagramRoom,
    diagram_document,
    live_cells,
)
from segl.repository import Repository
from segl.saver import Saver

RESTORE = "/api/v1/slots/9/restore"
REVISIONS = "/api/v1/slots/9/revisions"
# Short enough for a test to wait for.
SOON = 0.02
# Shorter than the time between two flushes: every flush adds a history row.
EVERY_FLUSH = 0.001
# Longer than any test: only a slot's first change, a big delete, a leave, a
# stop, or a restore adds a row.
NEVER = 3600.0


def drawn(shapes: int, links: int = 0) -> str:
    """Return a diagram of one page, as drawio's autosave writes it, with these shapes and links."""
    cells = "".join(
        f'<mxCell id="v{n}" value="" style="rounded=0;" vertex="1" parent="1">'
        f'<mxGeometry x="{n * 100}" y="0" width="80" height="40" as="geometry"/></mxCell>'
        for n in range(shapes)
    )
    cells += "".join(
        f'<mxCell id="e{n}" edge="1" parent="1" source="v0" target="v1">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>'
        for n in range(links)
    )
    return (
        '<mxfile><diagram id="segl-page-1" name="Page-1"><mxGraphModel><root>'
        f'<mxCell id="0"/><mxCell id="1" parent="0"/>{cells}'
        "</root></mxGraphModel></diagram></mxfile>"
    )


@pytest.fixture
def room() -> DiagramRoom:
    return DiagramRoom(DIAGRAM_SLOT, "Workspace 9", 1, EMPTY_DIAGRAM, start="s")


# The room.


def test_a_restore_puts_the_diagram_in_place_at_a_new_epoch_and_sends_it_to_everyone(
    room: DiagramRoom,
) -> None:
    alpha, viewer = Browser(room, "Alpha1"), Browser(room, view_only=True)
    alpha.patch("a1", 0, drawn(1))
    alpha.patch("a2", 1, drawn(2))
    alpha.take(), viewer.take()

    room.replace(2, diagram_document(drawn(5)))

    # As a join's whole diagram, after one more change: the restore.
    whole = {
        "type": "diagram",
        "epoch": 2,
        "whole": True,
        "mark": "s.2.3",
        "count": 3,
        "patches": [],
        "xml": drawn(5),
    }
    assert alpha.take() == viewer.take() == [whole]
    # Nothing of the old epoch stays, and the head holds all of the new one.
    assert (room.epoch, room.xml, room.patches) == (2, drawn(5), [])
    assert (room.written, room.unsettled) == ((2, 3), False)


def test_after_a_restore_a_patch_or_a_copy_of_the_old_epoch_is_refused(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, drawn(1))
    room.replace(2, diagram_document(drawn(5)))
    alpha.take(), bravo.take()

    alpha.patch("old", 1, drawn(9))
    alpha.copy(1, drawn(9))

    # Its sender is sent the diagram it should be on, and nobody else anything.
    told = alpha.take()
    assert [(m["type"], m["epoch"], m["whole"], m["xml"]) for m in told] == [
        ("diagram", 2, True, drawn(5))
    ] * 2
    assert bravo.take() == []
    assert (room.count, room.xml) == (2, drawn(5))


def test_after_a_restore_patches_go_on_from_its_count(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    alpha.patch("a1", 0, drawn(1))
    room.replace(2, diagram_document(drawn(5)))
    alpha.take(), bravo.take()

    alpha.patch("a2", 2, drawn(6), epoch=2)

    assert patches_of(bravo.take()) == [(3, "a2", True)]
    assert (room.xml, room.copy_count) == (drawn(6), 3)


def test_a_restore_leaves_nobody_waiting_for_a_saved_of_the_old_epoch(room: DiagramRoom) -> None:
    alpha, bravo = Browser(room), Browser(room)
    # Alpha's copy is kept, and waits for a flush. Bravo's is not, and waits
    # for a copy that holds it.
    alpha.patch("a1", 0, drawn(1), seq=1)
    bravo.patch("b1", 0, drawn(2), seq=1)
    assert (alpha.connection.awaiting, bravo.connection.awaiting) == (1, None)

    room.replace(2, diagram_document(drawn(5)))

    assert (alpha.connection.awaiting, bravo.connection.awaiting) == (None, None)
    # A kept copy of the new epoch holds nothing bravo sent before it.
    alpha.patch("a2", 3, drawn(6), seq=2, epoch=2)
    assert (alpha.connection.awaiting, bravo.connection.awaiting) == (2, None)


def test_a_restore_keeps_the_pen_with_its_holder(room: DiagramRoom) -> None:
    holder, other = Browser(room), Browser(room)
    holder.send({"type": "pen", "take": True})
    holder.take(), other.take()

    room.replace(2, diagram_document(drawn(5)))

    assert room.pen is holder.connection
    assert [message["type"] for message in other.take()] == ["diagram"]
    other.patch("o1", 1, drawn(6), epoch=2)
    assert other.errors() == ["pen_held"]


def test_a_mark_of_the_new_epoch_at_count_0_gets_the_whole_diagram(room: DiagramRoom) -> None:
    # The scene route hands out count 0 of the new epoch while a restore is
    # on its way to the room (tests/test_marks.py).
    alpha = Browser(room)
    alpha.patch("a1", 0, drawn(1))
    alpha.patch("a2", 1, drawn(2))
    room.replace(2, diagram_document(drawn(5)))

    late = Browser(room, mark="s.2.0")

    diagram = late.take()[1]
    assert (diagram["whole"], diagram["count"], diagram["xml"]) == (True, 3, drawn(5))


def test_while_someone_holds_the_pen_only_the_holder_may_restore(room: DiagramRoom) -> None:
    holder, other = Browser(room), Browser(room)
    assert room.may_restore(None) and room.may_restore(other.id)

    holder.send({"type": "pen", "take": True})

    assert room.may_restore(holder.id)
    assert not any(room.may_restore(each) for each in (other.id, None, 7, "nobody"))
    holder.send({"type": "pen", "take": False})
    assert room.may_restore(other.id)


# Counting the shapes and links.


def test_the_count_is_the_shapes_and_links_on_every_page_also_inside_a_wrapper() -> None:
    xml = (
        '<mxfile host="app.diagrams.net">'
        '<diagram id="p1" name="One">\n  <mxGraphModel dx="800"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="a" value="R1" vertex="1" parent="1"><mxGeometry as="geometry"/></mxCell>'
        '<object id="b" label="R2" owner="noc">'
        '<mxCell vertex="1" parent="1"><mxGeometry as="geometry"/></mxCell></object>'
        '<mxCell id="c" edge="1" parent="1" source="a" target="b">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>'
        "</root></mxGraphModel>\n</diagram>"
        '<diagram id="p2" name="Two"><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<UserObject id="d" label="L1"><mxCell edge="1" parent="1"/></UserObject>'
        '<mxCell id="e" vertex="0" edge="0" parent="1"/>'
        "</root></mxGraphModel></diagram>"
        "</mxfile>"
    )

    assert live_cells(xml) == 4
    assert live_cells(EMPTY_DIAGRAM) == 0
    assert live_cells(drawn(8, 2)) == 10


@pytest.mark.parametrize(
    "xml",
    [
        # A DOCTYPE could declare entities. It is refused, even one that
        # declares none, and no entity is expanded.
        '<!DOCTYPE mxfile [<!ENTITY one "1">]><mxfile><diagram id="p"><mxGraphModel><root>'
        '<mxCell id="a" vertex="&one;"/></root></mxGraphModel></diagram></mxfile>',
        '<!DOCTYPE mxfile><mxfile><diagram id="p"><mxGraphModel><root>'
        '<mxCell id="a" vertex="1"/></root></mxGraphModel></diagram></mxfile>',
        # A page drawio wrote compressed, which the server does not inflate.
        '<mxfile><diagram id="p" name="Page-1">dZHBEoIgEIafhrvKWHY2q0snD51JNmEC</diagram></mxfile>',
        # Not XML.
        "",
        "not xml",
        "<mxfile><diagram>",
        # Half a surrogate pair, which JSON can carry and UTF-8 cannot.
        '<mxfile><diagram id="\ud800"/></mxfile>',
    ],
    ids=["entity", "doctype", "compressed", "empty", "text", "unclosed", "surrogate"],
)
def test_a_diagram_the_server_cannot_count_has_no_count(xml: str) -> None:
    assert live_cells(xml) is None


# The saver: a big delete.


def run_saver(
    repository: Repository, scenario: Callable[[DiagramRoom, Saver], Awaitable[None]]
) -> None:
    """Run a scenario on slot 9's room and saver, made from the stored head as segl makes them."""

    async def main() -> None:
        head = repository.get_head(DIAGRAM_SLOT)
        room = DiagramRoom.from_stored(
            DIAGRAM_SLOT, "Workspace 9", head.epoch, head.scene_json, start="s"
        )
        saver = Saver(
            room,
            repository,
            head_flush_seconds=0.01,
            history_interval_seconds=NEVER,
            saved_at=head.saved_at,
        )
        try:
            await scenario(room, saver)
        finally:
            # A stop that does not end is a failure, not a test that never ends.
            await asyncio.wait_for(saver.close(), 10)

    asyncio.run(main())


async def saved(browser: Browser, seq: int) -> None:
    """Wait until the browser is told its patch is saved, and fail rather than wait for ever."""
    async with asyncio.timeout(5):
        while not any(m["type"] == "saved" and m["seq"] == seq for m in browser.received):
            await asyncio.sleep(0.005)


def kept_rows(repository: Repository) -> list[tuple[int, str | None]]:
    return [(row.revision, row.kept) for row in repository.list_revisions(DIAGRAM_SLOT)]


def store(repository: Repository, xml: str) -> None:
    """Make this diagram slot 9's head, with its first revision."""
    repository.flush_head(DIAGRAM_SLOT, 1, diagram_document(xml), "Alpha1", history_seconds=0)


def change_to(
    xml: str, *, base: int = 0, epoch: int = 1
) -> Callable[[DiagramRoom, Saver], Awaitable[None]]:
    """Return a scenario: one browser changes the diagram to this one, and it is saved."""

    async def scenario(room: DiagramRoom, saver: Saver) -> None:
        browser = Browser(room, "Bravo2")
        browser.patch("b1", base, xml, seq=1, epoch=epoch)
        await saved(browser, 1)

    return scenario


@pytest.mark.parametrize(
    ("left", "rows"),
    [(9, [(2, None), (1, None)]), (8, [(2, None), (1, "delete")])],
    ids=["90%", "80%"],
)
def test_a_big_delete_on_slot_9_keeps_the_diagram_before_it(
    repository: Repository, left: int, rows: list[tuple[int, str | None]]
) -> None:
    # Ten shapes and links, and the delete leaves `left` of them. At 90%,
    # row 2 is the one the stop records.
    store(repository, drawn(8, 2))

    run_saver(repository, change_to(drawn(left)))

    assert kept_rows(repository) == rows
    assert repository.get_revision(DIAGRAM_SLOT, 1).scene_json == diagram_document(drawn(8, 2))
    assert repository.get_head(DIAGRAM_SLOT).scene_json == diagram_document(drawn(left))


@pytest.mark.parametrize(
    "xml",
    [
        '<mxfile><diagram id="segl-page-1" name="Page-1">dZHBEoIgEIafhrvKW</diagram></mxfile>',
        "<!DOCTYPE mxfile>" + drawn(0),
    ],
    ids=["compressed", "doctype"],
)
def test_a_diagram_the_server_cannot_count_is_still_saved(repository: Repository, xml: str) -> None:
    store(repository, drawn(8, 2))

    run_saver(repository, change_to(xml))

    assert repository.get_head(DIAGRAM_SLOT).scene_json == diagram_document(xml)
    # No row kept before it: the server cannot tell what it deleted. Row 2 is
    # the one the stop records.
    assert kept_rows(repository) == [(2, None), (1, None)]


def test_after_a_head_the_server_cannot_count_a_delete_keeps_no_row(
    repository: Repository,
) -> None:
    store(repository, "<!DOCTYPE mxfile>" + drawn(8, 2))

    run_saver(repository, change_to(drawn(0)))

    assert repository.get_head(DIAGRAM_SLOT).scene_json == diagram_document(drawn(0))
    assert kept_rows(repository) == [(2, None), (1, None)]


def test_after_a_restore_a_delete_is_counted_against_the_diagram_put_in_place(
    repository: Repository,
) -> None:
    async def scenario(room: DiagramRoom, saver: Saver) -> None:
        await saver.replace(diagram_document(drawn(8, 2)), "Bravo2")
        # The restore was change 1 of epoch 2.
        await change_to(drawn(1), base=1, epoch=2)(room, saver)

    # The slot starts empty: nothing to count against but the restored diagram.
    run_saver(repository, scenario)

    assert kept_rows(repository) == [(2, None), (1, "delete")]


def test_slot_9_is_counted_off_the_event_loop(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[int] = []
    count = diagram_module.live_cells

    def counting(xml: str) -> int | None:
        threads.append(threading.get_ident())
        return count(xml)

    monkeypatch.setattr(diagram_module, "live_cells", counting)
    store(repository, drawn(8, 2))
    loop: list[int] = []

    async def scenario(room: DiagramRoom, saver: Saver) -> None:
        loop.append(threading.get_ident())
        await change_to(drawn(0))(room, saver)

    run_saver(repository, scenario)

    # The head the room started from, and the copy: each in a worker thread.
    assert len(threads) == 2
    assert loop[0] not in threads
    assert kept_rows(repository) == [(2, None), (1, "delete")]


# The routes and the socket.


def application(repository: Repository, **settings: Any) -> TestClient:
    settings.setdefault("head_flush_seconds", SOON)
    settings.setdefault("history_interval_seconds", EVERY_FLUSH)
    return TestClient(create_app(make_settings(**settings), repository))


def hello(socket: WebSocketTestSession, name: str) -> str:
    """Say hello on slot 9, take the welcome and the diagram, and return the connection id."""
    socket.send_json({"type": "hello", "clientId": "c", "displayName": name, "editToken": ""})
    welcome = received(socket)
    assert received(socket)["type"] == "diagram"
    return welcome["connectionId"]


def send_patch(
    socket: WebSocketTestSession, seq: int, base: int, xml: str, *, epoch: int = 1
) -> None:
    pid = f"p{seq}"
    socket.send_json(
        {
            "type": "patch",
            "epoch": epoch,
            "base": base,
            "pid": pid,
            "patch": patch(pid),
            "checksum": None,
            "xml": xml,
            "seq": seq,
        }
    )


def rows(client: TestClient) -> list[tuple[int, int, str, str | None]]:
    """Return slot 9's history as the list route gives it: revision, epoch, label, and mark."""
    answer = client.get(REVISIONS).json()["revisions"]
    return [(row["revision"], row["epoch"], row["authorLabel"], row["kept"]) for row in answer]


def test_a_restore_on_slot_9_starts_a_new_epoch_and_sends_every_connection_the_diagram(
    repository: Repository,
) -> None:
    with (
        application(repository) as client,
        client.websocket_connect("/collab?slot=9") as alpha,
        client.websocket_connect("/collab?slot=9") as bravo,
    ):
        hello(alpha, "Alpha1")
        bravo_id = hello(bravo, "Bravo2")
        assert received(alpha)["type"] == "presence"
        for seq, xml in ((1, drawn(1)), (2, drawn(2))):
            send_patch(alpha, seq, seq - 1, xml)
            assert received(alpha)["n"] == received(bravo)["n"] == seq
            assert received(alpha)["type"] == "saved"
        assert rows(client) == [(2, 1, "Alpha1", None), (1, 1, "Alpha1", None)]

        reply = client.post(
            RESTORE, json={"revision": 1, "displayName": "Bravo2", "connectionId": bravo_id}
        )

        assert reply.status_code == 200
        assert reply.json() | {"savedAt": ""} == {"revision": 3, "epoch": 2, "savedAt": ""}
        for socket in (alpha, bravo):
            assert received(socket) == {
                "type": "diagram",
                "epoch": 2,
                "whole": True,
                "mark": MarkOf(2, 3),
                "count": 3,
                "patches": [],
                "xml": drawn(1),
            }
        # The diagram that went is kept, marked restore, and the restore is a revision.
        assert rows(client) == [
            (3, 2, "Bravo2", None),
            (2, 1, "Alpha1", "restore"),
            (1, 1, "Alpha1", None),
        ]
        assert client.get(f"{REVISIONS}/2").json()["scene"] == {"diagram": drawn(2)}
        head = client.get("/api/v1/slots/9/scene").json()
        assert (head["scene"], head["epoch"], head["editorLabel"]) == (
            {"diagram": drawn(1)},
            2,
            "Bravo2",
        )
        assert (head["mark"], head["savedAt"]) == (MarkOf(2, 3), reply.json()["savedAt"])

        # A patch and a copy of the old epoch are refused: the sender is sent
        # the diagram it should be on.
        send_patch(alpha, 3, 2, drawn(9))
        alpha.send_json({"type": "copy", "epoch": 1, "base": 2, "xml": drawn(9)})
        for _ in range(2):
            refused = received(alpha)
            assert (refused["type"], refused["epoch"], refused["xml"]) == ("diagram", 2, drawn(1))
        # Bravo's next message is the next patch: the refused ones reached nobody.
        send_patch(alpha, 4, 3, drawn(3), epoch=2)
        assert received(bravo)["n"] == received(alpha)["n"] == 4


def test_while_another_holds_the_pen_a_restore_from_anyone_else_is_refused(
    repository: Repository,
) -> None:
    with (
        application(repository) as client,
        client.websocket_connect("/collab?slot=9") as alpha,
        client.websocket_connect("/collab?slot=9") as bravo,
    ):
        alpha_id = hello(alpha, "Alpha1")
        bravo_id = hello(bravo, "Bravo2")
        received(alpha)
        send_patch(alpha, 1, 0, drawn(1))
        assert received(alpha)["n"] == received(bravo)["n"] == 1
        assert received(alpha)["type"] == "saved"
        alpha.send_json({"type": "pen", "take": True})
        assert received(alpha)["holder"] == received(bravo)["holder"] == alpha_id

        for body in (
            {"revision": 1, "connectionId": bravo_id},
            {"revision": 1},
            {"revision": 1, "connectionId": None},
            {"revision": 1, "connectionId": 7},
            {"revision": 1, "connectionId": "nobody"},
        ):
            reply = client.post(RESTORE, json=body)
            assert (reply.status_code, reply.json()) == (
                409,
                {"error": "pen_held", "message": PEN_HELD},
            ), body

        # Nothing was written.
        assert rows(client) == [(1, 1, "Alpha1", None)]
        assert client.get("/api/v1/slots/9").json()["epoch"] == 1

        # The holder restores, and keeps the pen.
        reply = client.post(
            RESTORE, json={"revision": 1, "displayName": "Alpha1", "connectionId": alpha_id}
        )
        assert (reply.status_code, reply.json()["epoch"]) == (200, 2)
        assert received(alpha)["type"] == received(bravo)["type"] == "diagram"
        send_patch(bravo, 2, 2, drawn(4), epoch=2)
        assert received(bravo)["error"] == "pen_held"
        send_patch(alpha, 3, 2, drawn(5), epoch=2)
        assert received(bravo)["n"] == 3


def test_with_the_pen_free_a_restore_needs_no_connection(repository: Repository) -> None:
    store(repository, drawn(1))
    repository.flush_head(9, 1, diagram_document(drawn(2)), "Bravo2", history_seconds=0)

    # Nobody has slot 9 open, and the body names no connection.
    with application(repository) as client:
        reply = client.post(RESTORE, json={"revision": 1, "displayName": "Charlie3"})

        assert (reply.status_code, reply.json()["epoch"]) == (200, 2)
        assert client.get("/api/v1/slots/9/scene").json()["scene"] == {"diagram": drawn(1)}
        assert rows(client) == [
            (3, 2, "Charlie3", None),
            (2, 1, "Bravo2", "restore"),
            (1, 1, "Alpha1", None),
        ]


def test_a_whiteboards_restore_ignores_the_connection_it_names(repository: Repository) -> None:
    drawing = {"id": "a", "version": 1, "versionNonce": 1, "index": "a0"}
    scene = json.dumps({**EMPTY_SCENE, "elements": [drawing]}, separators=(",", ":"))
    repository.flush_head(2, 1, scene, "Alpha1", history_seconds=0)

    with application(repository) as client:
        reply = client.post(
            "/api/v1/slots/2/restore", json={"revision": 1, "connectionId": "nobody"}
        )

        assert (reply.status_code, reply.json()["epoch"]) == (200, 2)


def test_a_big_delete_on_slot_9_keeps_a_delete_row_at_the_socket(repository: Repository) -> None:
    store(repository, drawn(8, 2))

    with (
        application(repository, history_interval_seconds=NEVER) as client,
        client.websocket_connect("/collab?slot=9") as alpha,
    ):
        hello(alpha, "Bravo2")
        # Two of the ten shapes and links are left: fewer than 90%.
        send_patch(alpha, 1, 0, drawn(2))
        assert received(alpha)["n"] == 1
        assert received(alpha)["type"] == "saved"

        assert rows(client) == [(2, 1, "Bravo2", None), (1, 1, "Alpha1", "delete")]
        assert client.get(f"{REVISIONS}/1").json()["scene"] == {"diagram": drawn(8, 2)}
