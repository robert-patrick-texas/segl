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

"""One slot's room: joining, the scene, presence, and the edit gate
(docs/API.md, "WebSocket"). No socket and no event loop: a test's browser is a
list of the messages the room delivered to it."""

import json
from typing import Any

import pytest

from segl.room import (
    Connection,
    Hello,
    Room,
    may_edit,
    parse_hello,
    stored_name,
)


def element(identifier: str, version: int, nonce: int = 1, **more: object) -> dict[str, Any]:
    return {"id": identifier, "version": version, "versionNonce": nonce, **more}


class Browser:
    """A connection in a room, and everything the room has sent it."""

    def __init__(self, room: Room, name: str | None = "Guest1", *, view_only: bool = False) -> None:
        self.room = room
        self.received: list[dict[str, Any]] = []
        self.connection = Connection(
            lambda text: self.received.append(json.loads(text)),
            Hello("client-1", name, ""),
            view_only=view_only,
        )
        room.join(self.connection)

    @property
    def id(self) -> str:
        return self.connection.id

    def take(self) -> list[dict[str, Any]]:
        """Return what arrived since the last call."""
        messages, self.received = self.received, []
        return messages

    def send(self, message: object) -> None:
        self.room.receive(self.connection, message)

    def draw(self, *elements: dict[str, Any], epoch: int = 1) -> None:
        self.send({"type": "elements", "epoch": epoch, "elements": list(elements)})

    def leave(self) -> None:
        self.room.leave(self.connection)


@pytest.fixture
def room() -> Room:
    return Room(3, "Workspace 3", 1, [])


def scene_of(room: Room) -> list[dict[str, Any]]:
    """Return the scene a browser joining now would be sent."""
    return Browser(room).take()[1]["elements"]


def test_a_connection_is_welcomed_and_then_sent_the_scene(room: Room) -> None:
    room.elements["a"] = element("a", 2, index="a0")

    browser = Browser(room, "Guest1")

    welcome, scene = browser.take()
    assert welcome == {
        "type": "welcome",
        "slot": 3,
        "title": "Workspace 3",
        "epoch": 1,
        "viewOnly": False,
        "connectionId": browser.id,
        "participants": [{"connectionId": browser.id, "displayName": "Guest1"}],
    }
    assert scene == {
        "type": "scene",
        "epoch": 1,
        "elements": [element("a", 2, index="a0")],
        "files": [],
    }


def test_the_participant_list_is_every_connection_in_the_order_they_joined(room: Room) -> None:
    first = Browser(room, "Guest1")
    second = Browser(room, "Staff2")
    third = Browser(room, "Guest1")

    welcome = third.take()[0]

    # Two connections may show one label: the count is connections, not names.
    assert [each["displayName"] for each in welcome["participants"]] == [
        "Guest1",
        "Staff2",
        "Guest1",
    ]
    assert [each["connectionId"] for each in welcome["participants"]] == [
        first.id,
        second.id,
        third.id,
    ]
    assert len({first.id, second.id, third.id}) == 3


def test_the_others_are_told_who_came(room: Room) -> None:
    first = Browser(room, "Guest1")
    first.take()

    second = Browser(room, "Staff2")

    assert first.take() == [
        {
            "type": "presence",
            "connectionId": second.id,
            "displayName": "Staff2",
            "cursor": None,
        }
    ]


def test_the_others_are_told_who_left(room: Room) -> None:
    first = Browser(room)
    second = Browser(room)
    first.take()

    second.leave()

    assert first.take() == [{"type": "presence-end", "connectionId": second.id}]
    assert list(room.connections) == [first.id]
    assert second.take()[2:] == []


def test_leaving_twice_tells_the_others_once(room: Room) -> None:
    first = Browser(room)
    second = Browser(room)
    first.take()

    second.leave()
    second.leave()

    assert len(first.take()) == 1


def test_connection_ids_are_not_reused_while_a_connection_has_one(room: Room) -> None:
    browsers = [Browser(room) for _ in range(50)]

    assert len({browser.id for browser in browsers}) == 50
    assert all(len(browser.id) >= 12 for browser in browsers)


def test_a_drawn_element_reaches_the_others_and_not_its_sender(room: Room) -> None:
    """The server half of T-001."""
    drawer, watcher = Browser(room), Browser(room)
    drawer.take(), watcher.take()
    rectangle = element("a", 1, type="rectangle", index="a0")

    drawer.draw(rectangle)

    assert watcher.take() == [{"type": "elements", "epoch": 1, "elements": [rectangle]}]
    assert drawer.take() == []
    assert scene_of(room) == [rectangle]


def test_two_people_drawing_at_once_both_keep_their_elements(room: Room) -> None:
    """The server half of T-002."""
    one, two = Browser(room), Browser(room)

    one.draw(element("a", 1, index="a0"))
    two.draw(element("b", 1, index="a1"))
    one.draw(element("a", 2, index="a0"))
    two.draw(element("b", 2, index="a1"))

    assert scene_of(room) == [element("a", 2, index="a0"), element("b", 2, index="a1")]


def test_a_deleted_element_stays_deleted(room: Room) -> None:
    """The server half of T-003: the tombstone wins, and an older copy cannot undo it."""
    mover, deleter = Browser(room), Browser(room)
    mover.draw(element("a", 1, isDeleted=False, x=0))
    mover.draw(element("a", 2, isDeleted=False, x=40))
    mover.take(), deleter.take()

    deleter.draw(element("a", 3, isDeleted=True, x=40))
    # A copy from before the deletion, as from a browser that was away.
    mover.draw(element("a", 2, isDeleted=False, x=40))

    tombstone = element("a", 3, isDeleted=True, x=40)
    assert mover.take() == [{"type": "elements", "epoch": 1, "elements": [tombstone]}]
    assert deleter.take() == []
    # A browser that loads the slot afterwards is sent the tombstone too.
    assert scene_of(room) == [tombstone]


def test_an_element_that_loses_is_not_sent_on(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.draw(element("a", 5))
    one.take(), two.take()

    two.draw(element("a", 4), element("b", 1))

    assert one.take() == [{"type": "elements", "epoch": 1, "elements": [element("b", 1)]}]


def test_a_batch_with_no_winner_is_not_sent_on(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.draw(element("a", 5))
    one.take(), two.take()

    two.draw(element("a", 5))
    two.draw()

    assert one.take() == []
    assert two.take() == []


def test_elements_from_another_epoch_get_the_scene_back_and_are_not_applied(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.draw(element("a", 1))
    one.take(), two.take()

    two.draw(element("b", 1), epoch=2)
    two.draw(element("c", 1), epoch=0)

    scene = {"type": "scene", "epoch": 1, "elements": [element("a", 1)], "files": []}
    assert two.take() == [scene, scene]
    assert one.take() == []
    assert list(room.elements) == ["a"]


def test_a_batch_with_one_bad_element_is_refused_whole(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.take(), two.take()

    one.draw(element("a", 1), {"id": "b", "version": "2", "versionNonce": 1})

    (error,) = one.take()
    assert (error["type"], error["error"]) == ("error", "bad_message")
    assert two.take() == []
    assert room.elements == {}


@pytest.mark.parametrize(
    "message",
    [
        {"type": "elements"},
        {"type": "elements", "epoch": 1},
        {"type": "elements", "epoch": 1, "elements": {}},
        {"type": "elements", "epoch": "1", "elements": []},
        {"type": "elements", "epoch": True, "elements": []},
        {"type": "elements", "epoch": 1, "elements": ["a"]},
        {"type": "presence", "cursor": "here"},
        {"type": "presence", "cursor": {"x": 1}},
        {"type": "presence", "cursor": {"x": "1", "y": 2}},
        {"type": "presence", "cursor": {"x": True, "y": 2}},
        {"type": "presence", "cursor": {"x": float("inf"), "y": 2}},
        {"type": "presence", "cursor": {"x": float("nan"), "y": 2}},
        {"type": "hello", "clientId": "again"},
        {"type": 7},
        {},
        [],
        "elements",
        None,
    ],
)
def test_a_malformed_message_is_answered_with_an_error_and_changes_nothing(
    room: Room, message: object
) -> None:
    one, two = Browser(room), Browser(room)
    one.take(), two.take()

    one.send(message)

    (error,) = one.take()
    assert (error["type"], error["error"]) == ("error", "bad_message")
    assert isinstance(error["message"], str)
    assert two.take() == []
    assert room.elements == {}
    assert one.connection.cursor is None


@pytest.mark.parametrize("kind", ["files", "restore", "ELEMENTS", ""])
def test_an_unknown_type_is_answered_with_an_error(room: Room, kind: str) -> None:
    browser = Browser(room)
    browser.take()

    browser.send({"type": kind, "epoch": 1, "elements": [element("a", 1)]})

    (error,) = browser.take()
    assert (error["type"], error["error"]) == ("error", "unknown_type")
    assert room.elements == {}


def test_a_cursor_reaches_the_others_with_its_owner(room: Room) -> None:
    one, two = Browser(room, "Guest1"), Browser(room, "Staff2")
    one.take(), two.take()

    one.send({"type": "presence", "cursor": {"x": 12.5, "y": -3, "tool": "laser"}})

    assert two.take() == [
        {
            "type": "presence",
            "connectionId": one.id,
            "displayName": "Guest1",
            "cursor": {"x": 12.5, "y": -3},
        }
    ]
    assert one.take() == []


def test_a_cursor_can_be_taken_away(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.send({"type": "presence", "cursor": {"x": 1, "y": 2}})
    two.take()

    one.send({"type": "presence", "cursor": None})

    assert two.take()[0]["cursor"] is None


def test_a_rename_is_title_cased_and_sent_to_everyone(room: Room) -> None:
    """The broadcast half of T-014."""
    one, two = Browser(room, "Guest1"), Browser(room, "Staff2")
    one.take(), two.take()

    one.send({"type": "rename", "displayName": "john smith"})

    presence = {
        "type": "presence",
        "connectionId": one.id,
        "displayName": "John Smith",
        "cursor": None,
    }
    assert two.take() == [presence]
    # The sender too, so that its own entry in the list is the server's spelling.
    assert one.take() == [presence]
    assert Browser(room).take()[0]["participants"][0]["displayName"] == "John Smith"


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, None, 7, ["john"]])
def test_a_name_that_is_not_usable_is_refused(room: Room, name: object) -> None:
    one, two = Browser(room, "Guest1"), Browser(room)
    one.take(), two.take()

    one.send({"type": "rename", "displayName": name})

    (error,) = one.take()
    assert (error["type"], error["error"]) == ("error", "invalid_name")
    assert two.take() == []
    assert one.connection.display_name == "Guest1"


def test_a_viewer_sees_edits_and_cannot_make_them(room: Room) -> None:
    """The scene half of T-008."""
    editor, viewer = Browser(room, "Guest1"), Browser(room, "Staff2", view_only=True)
    assert viewer.take()[0]["viewOnly"] is True
    editor.take()

    editor.draw(element("a", 1))
    viewer.draw(element("a", 2), element("b", 1))

    edit, error = viewer.take()
    assert edit == {"type": "elements", "epoch": 1, "elements": [element("a", 1)]}
    assert (error["type"], error["error"]) == ("error", "view_only")
    assert editor.take() == []
    assert room.elements == {"a": element("a", 1)}


def test_a_viewer_is_refused_before_its_message_is_read(room: Room) -> None:
    viewer = Browser(room, view_only=True)
    viewer.take()

    viewer.send({"type": "elements", "epoch": 99, "elements": "nonsense"})

    (error,) = viewer.take()
    assert error["error"] == "view_only"


def test_a_viewer_has_a_cursor_and_may_rename(room: Room) -> None:
    editor, viewer = Browser(room, "Guest1"), Browser(room, "Staff2", view_only=True)
    editor.take(), viewer.take()

    viewer.send({"type": "presence", "cursor": {"x": 1, "y": 2}})
    viewer.send({"type": "rename", "displayName": "ada"})

    cursor, renamed = editor.take()
    assert cursor["cursor"] == {"x": 1, "y": 2}
    assert renamed["displayName"] == "Ada"
    assert renamed["cursor"] == {"x": 1, "y": 2}


def test_a_new_title_is_sent_to_every_connection(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.take(), two.take()

    room.retitle("Core network")

    message = {"type": "slot", "slot": 3, "title": "Core network"}
    assert one.take() == [message]
    assert two.take() == [message]
    assert Browser(room).take()[0]["title"] == "Core network"


def test_a_connection_without_a_label_is_listed_without_one(room: Room) -> None:
    browser = Browser(room, None)

    assert browser.take()[0]["participants"] == [{"connectionId": browser.id, "displayName": None}]


def test_a_delivery_that_ends_a_connection_does_not_stop_the_broadcast(room: Room) -> None:
    one = Browser(room)
    gone = Browser(room)
    last = Browser(room)
    one.take(), last.take()
    # What the socket route does when a browser has fallen too far behind.
    gone.connection.deliver = lambda text: room.leave(gone.connection)

    one.draw(element("a", 1))

    assert last.take() == [
        {"type": "presence-end", "connectionId": gone.id},
        {"type": "elements", "epoch": 1, "elements": [element("a", 1)]},
    ]


def test_a_room_starts_from_the_stored_scene() -> None:
    stored = {
        "type": "excalidraw",
        "elements": [
            element("b", 3, 9, index="a1"),
            element("a", 2, 8, index="a0"),
            {"id": "old", "type": "rectangle"},
            "not an element",
            {"version": 1},
        ],
        "appState": {"viewBackgroundColor": "#ffffff"},
    }

    room = Room.from_head(5, "Lab", 4, json.dumps(stored))

    assert (room.slot, room.title, room.epoch) == (5, "Lab", 4)
    assert scene_of(room) == [
        element("a", 2, 8, index="a0"),
        element("b", 3, 9, index="a1"),
        {"id": "old", "type": "rectangle", "version": 1, "versionNonce": 0},
    ]


@pytest.mark.parametrize("scene", ["{}", "[]", "null", '{"elements": {}}', '{"elements": null}'])
def test_a_stored_scene_without_an_element_list_is_an_empty_room(scene: str) -> None:
    assert Room.from_head(1, "Workspace 1", 1, scene).elements == {}


def test_hello_gives_the_client_the_label_and_the_token() -> None:
    hello = {"type": "hello", "clientId": "c-1_A", "displayName": " McKinley7 ", "editToken": "t"}

    assert parse_hello(hello) == Hello("c-1_A", "McKinley7", "t")
    assert parse_hello({"type": "hello", "clientId": "c"}) == Hello("c", None, "")


@pytest.mark.parametrize(
    "message",
    [
        None,
        "hello",
        [],
        {},
        {"type": "elements", "clientId": "c"},
        {"type": "hello"},
        {"type": "hello", "clientId": ""},
        {"type": "hello", "clientId": 7},
        {"type": "hello", "clientId": "has space"},
        {"type": "hello", "clientId": "x" * 65},
        {"type": "hello", "clientId": "c", "editToken": None},
        {"type": "hello", "clientId": "c", "editToken": 7},
    ],
)
def test_what_is_not_a_hello_is_not_one(message: object) -> None:
    assert parse_hello(message) is None


@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        ("McKinley7", "McKinley7"),
        ("  john smith ", "john smith"),
        ("x" * 40, "x" * 40),
        ("x" * 41, None),
        ("", None),
        ("   ", None),
        (None, None),
        (7, None),
    ],
)
def test_the_label_in_hello_is_kept_as_written(sent: object, kept: str | None) -> None:
    # Not title-cased: a label from the word file keeps the file's spelling.
    assert stored_name(sent) == kept


@pytest.mark.parametrize(
    ("configured", "given", "allowed"),
    [
        ("", None, True),
        ("", "", True),
        ("", "anything", True),
        ("secret", "secret", True),
        ("secret", None, False),
        ("secret", "", False),
        ("secret", "Secret", False),
        ("secret", "secret ", False),
        ("secret", "secre", False),
        ("sécret", "sécret", True),
        ("sécret", "secret", False),
    ],
)
def test_the_edit_gate(configured: str, given: str | None, allowed: bool) -> None:
    assert may_edit(configured, given) is allowed
