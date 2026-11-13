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
from harness import EMPTY_SCENE

from segl.repository import load_empty_scene
from segl.room import (
    MAX_FILES_IN_MESSAGE,
    Connection,
    Hello,
    Room,
    encode,
    named_files,
    parse_files,
    parse_hello,
    parse_scene,
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

    def send(self, message: object, uploaded: tuple[str, ...] = ()) -> None:
        self.room.receive(self.connection, message, uploaded)

    def draw(self, *elements: dict[str, Any], epoch: int = 1, seq: object = None) -> None:
        message = {"type": "elements", "epoch": epoch, "elements": list(elements)}
        self.send(message if seq is None else {**message, "seq": seq})

    def name_files(self, *files: dict[str, str], stored: bool = True, seq: object = None) -> None:
        """Say which bytes these file ids mean. ``stored`` is whether they were uploaded."""
        message: dict[str, Any] = {"type": "files", "epoch": 1, "files": list(files)}
        if seq is not None:
            message["seq"] = seq
        self.send(message, tuple(each["hash"] for each in files) if stored else ())

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


@pytest.mark.parametrize("kind", ["saved", "restore", "ELEMENTS", ""])
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


def test_hello_gives_the_client_the_label_and_the_pass() -> None:
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


# What the saver needs of a room (docs/DATA-MODEL.md, "Flush and revision rules").


class Listener:
    """Counts what a room tells its saver."""

    def __init__(self, room: Room) -> None:
        self.changes = 0
        self.empties = 0
        room.on_change = self.changed
        room.on_empty = self.emptied

    def changed(self) -> None:
        self.changes += 1

    def emptied(self) -> None:
        self.empties += 1


def test_an_accepted_edit_makes_the_room_dirty_and_says_so(room: Room) -> None:
    listener = Listener(room)
    browser = Browser(room, "Bravo2")
    assert (room.dirty, room.unsettled, listener.changes) == (False, False, 0)

    browser.draw(element("a", 1))

    assert (room.dirty, room.unsettled, listener.changes) == (True, True, 1)
    assert room.editor_label == "Bravo2"


def test_an_edit_that_changes_nothing_leaves_the_room_clean(room: Room) -> None:
    one, two = Browser(room, "Alpha1"), Browser(room, "Bravo2")
    one.draw(element("a", 5))
    room.snapshot()
    listener = Listener(room)

    two.draw(element("a", 4))
    two.draw(element("a", 5))
    two.send({"type": "presence", "cursor": {"x": 1, "y": 2}})
    two.send({"type": "rename", "displayName": "cy"})

    assert (room.dirty, listener.changes) == (False, 0)
    # The label is the one behind the newest change that was kept.
    assert room.editor_label == "Alpha1"


def test_the_label_is_the_name_at_the_time_of_the_edit(room: Room) -> None:
    browser = Browser(room, "Bravo2")
    browser.draw(element("a", 1))
    browser.send({"type": "rename", "displayName": "cy"})

    assert room.snapshot().editor_label == "Bravo2"
    browser.draw(element("a", 2))
    assert room.snapshot().editor_label == "Cy"


def test_an_edit_by_a_connection_without_a_label_has_none(room: Room) -> None:
    Browser(room, "Bravo2").draw(element("a", 1))
    Browser(room, None).draw(element("a", 2))

    assert room.snapshot().editor_label is None


def test_a_snapshot_is_the_whole_scene_and_leaves_the_room_clean(room: Room) -> None:
    browser = Browser(room)
    browser.draw(element("b", 1, index="a1"), element("a", 1, index="a0"))
    browser.draw(element("b", 2, index="a1", isDeleted=True))

    taken = room.snapshot()

    # In drawing order, with the deleted element: a restart must not forget a deletion.
    assert taken.elements == [
        element("a", 1, index="a0"),
        element("b", 2, index="a1", isDeleted=True),
    ]
    assert (taken.epoch, taken.files) == (1, [])
    assert (room.dirty, room.unsettled) == (False, False)
    # What is drawn afterwards is not in a snapshot already taken.
    browser.draw(element("c", 1, index="a2"))
    assert len(taken.elements) == 2
    assert room.dirty


def test_a_snapshot_that_was_not_written_is_taken_back(room: Room) -> None:
    browser = Browser(room)
    browser.name_files(FILE)
    browser.draw(element("a", 1))
    taken = room.snapshot()
    browser.name_files(OTHER_FILE)

    room.take_back(taken)

    assert room.dirty
    # Both files are still to be written, the older first.
    assert room.snapshot().files == [FILE, OTHER_FILE]
    assert room.snapshot().files == []


def test_a_room_nobody_changed_is_stored_as_the_head_it_came_from() -> None:
    """So that a flush of it writes nothing: the JSON is unchanged."""
    stored = load_empty_scene()

    room = Room.from_head(1, "Workspace 1", 1, stored)

    assert room.snapshot().scene_json() == stored
    assert room.document == EMPTY_SCENE


def test_the_stored_scene_is_the_heads_document_with_the_rooms_elements() -> None:
    head = {"type": "excalidraw", "version": 2, "elements": [], "appState": {"gridSize": 20}}
    room = Room.from_head(1, "Workspace 1", 1, json.dumps(head))
    Browser(room).draw(element("a", 1, text="café 😀"))

    stored = room.snapshot().scene_json()

    assert json.loads(stored) == {
        **head,
        "elements": [element("a", 1, text="café 😀")],
    }
    # ASCII, and compact.
    assert stored.isascii()
    assert ": " not in stored


def test_half_a_surrogate_pair_in_an_element_can_be_stored(room: Room) -> None:
    # JSON can carry it, and a browser can send it. SQLite takes the escape.
    Browser(room).draw(element("a", 1, text="bad \ud800 text"))

    stored = room.snapshot().scene_json()

    assert "\\ud800" in stored
    stored.encode("utf-8")


@pytest.mark.parametrize("scene", ["[]", "null", '"text"', "7"])
def test_a_stored_scene_that_is_not_a_document_gives_a_room_that_can_be_stored(scene: str) -> None:
    room = Room.from_head(1, "Workspace 1", 1, scene)
    Browser(room).draw(element("a", 1))

    assert json.loads(room.snapshot().scene_json()) == {"elements": [element("a", 1)]}


def test_the_room_says_when_its_last_connection_left(room: Room) -> None:
    listener = Listener(room)
    one, two = Browser(room), Browser(room)

    one.leave()
    assert listener.empties == 0
    two.leave()
    assert listener.empties == 1
    two.leave()
    assert listener.empties == 1


# `saved`: a browser numbers its messages, and is told which are on the disk.


def test_a_numbered_message_is_answered_with_saved_after_the_flush(room: Room) -> None:
    listener = Listener(room)
    one, two = Browser(room), Browser(room)
    one.take(), two.take()

    one.draw(element("a", 1), seq=4)
    assert one.take() == []
    assert listener.changes == 2

    # What the saver does once the head is written.
    room.snapshot()
    waiting = room.take_waiting()
    assert not room.unsettled
    room.saved(waiting, "2026-11-12T09:00:01.000Z")

    assert one.take() == [
        {"type": "saved", "epoch": 1, "savedAt": "2026-11-12T09:00:01.000Z", "seq": 4}
    ]
    # The other connection drew nothing, and is told nothing.
    assert [message["type"] for message in two.take()] == ["elements"]
    assert room.take_waiting() == []


def test_saved_names_the_newest_message_of_each_connection(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.draw(element("a", 1), seq=1)
    one.draw(element("a", 2), seq=2)
    two.draw(element("b", 1), seq=7)
    one.take(), two.take()

    room.saved(room.take_waiting(), "t")

    assert [message["seq"] for message in one.take()] == [2]
    assert [message["seq"] for message in two.take()] == [7]


def test_a_message_without_a_number_is_not_answered(room: Room) -> None:
    browser = Browser(room)
    browser.draw(element("a", 1))

    assert room.dirty
    assert room.take_waiting() == []


def test_a_numbered_message_that_changed_nothing_is_still_answered(room: Room) -> None:
    """A browser that reconnects asks, with an empty batch, whether it is saved."""
    listener = Listener(room)
    browser = Browser(room)
    browser.take()

    browser.draw(seq=3)

    assert (room.dirty, room.unsettled, listener.changes) == (False, True, 1)
    room.saved(room.take_waiting(), "t")
    assert browser.take() == [{"type": "saved", "epoch": 1, "savedAt": "t", "seq": 3}]


@pytest.mark.parametrize("seq", [True, -1, 1.5, "1", [1], 2**53])
def test_a_number_that_is_not_a_count_is_not_answered(room: Room, seq: object) -> None:
    browser = Browser(room)

    browser.draw(element("a", 1), seq=seq)

    # The edit itself was taken.
    assert room.dirty
    assert room.take_waiting() == []


def test_a_message_that_was_refused_is_not_answered(room: Room) -> None:
    editor, viewer = Browser(room), Browser(room, view_only=True)

    viewer.draw(element("a", 1), seq=1)
    editor.draw(element("b", 1), {"id": "c"}, seq=2)
    editor.draw(element("d", 1), epoch=2, seq=3)
    editor.name_files(FILE, stored=False, seq=4)

    assert room.take_waiting() == []
    assert not room.dirty


def test_a_connection_that_left_is_not_told(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.draw(element("a", 1), seq=1)
    two.draw(element("b", 1), seq=1)
    waiting = room.take_waiting()
    one.leave()
    one.take(), two.take()

    room.saved(waiting, "t")

    assert one.take() == []
    assert [message["type"] for message in two.take()] == ["saved"]


def test_a_flush_that_failed_keeps_its_connections_waiting(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.draw(element("a", 1), seq=1)
    two.draw(element("b", 1), seq=5)
    waiting = room.take_waiting()
    # While the write was failing, one of them drew again.
    one.draw(element("a", 2), seq=2)

    room.keep_waiting(waiting)

    assert sorted(seq for _, seq in room.take_waiting()) == [2, 5]


# The files of images (docs/API.md, the `files` message).

FILE = {"id": "f" * 40, "hash": "a" * 64, "mimeType": "image/png"}
OTHER_FILE = {"id": "e" * 40, "hash": "b" * 64, "mimeType": "image/jpeg"}


def image(identifier: str, file_id: str, **more: object) -> dict[str, Any]:
    return {**element(identifier, 1, type="image", fileId=file_id), **more}


def test_a_named_file_reaches_the_others_and_is_kept(room: Room) -> None:
    listener = Listener(room)
    one, two = Browser(room, "Bravo2"), Browser(room)
    one.take(), two.take()

    one.name_files(FILE)

    assert two.take() == [{"type": "files", "epoch": 1, "files": [FILE]}]
    assert one.take() == []
    assert room.files == {FILE["id"]: FILE}
    assert (room.dirty, listener.changes, room.editor_label) == (True, 1, "Bravo2")
    # The flush writes it once.
    assert room.snapshot().files == [FILE]
    assert room.snapshot().files == []


def test_a_new_connection_is_sent_the_files_its_scene_names(room: Room) -> None:
    browser = Browser(room)
    browser.name_files(FILE, OTHER_FILE)
    browser.draw(image("picture", FILE["id"]))

    scene = Browser(room).take()[1]

    assert scene["elements"] == [image("picture", FILE["id"])]
    # Not the file no element names: its image was never placed, or is long gone.
    assert scene["files"] == [FILE]


def test_a_deleted_image_still_names_its_file(room: Room) -> None:
    browser = Browser(room)
    browser.name_files(FILE)
    browser.draw(image("picture", FILE["id"], isDeleted=True))

    assert Browser(room).take()[1]["files"] == [FILE]


def test_a_room_starts_with_the_slots_file_list() -> None:
    stored = json.dumps({"elements": [image("picture", FILE["id"])]})

    room = Room.from_head(2, "Workspace 2", 1, stored, files=[FILE, OTHER_FILE])

    assert Browser(room).take()[1]["files"] == [FILE]
    assert room.snapshot().files == []


def test_a_file_id_keeps_the_bytes_it_was_first_given(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.name_files(FILE)
    room.snapshot()
    one.take(), two.take()
    listener = Listener(room)

    two.name_files({**FILE, "hash": "c" * 64}, seq=1)

    assert room.files == {FILE["id"]: FILE}
    assert one.take() == []
    assert (room.dirty, room.snapshot().files) == (False, [])
    # It is answered: what the slot holds for that id is saved.
    assert [seq for _, seq in room.take_waiting()] == [1]
    assert listener.changes == 1


def test_only_the_new_files_of_a_message_are_sent_on(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.name_files(FILE)
    one.take(), two.take()

    two.name_files(FILE, OTHER_FILE)

    assert one.take() == [{"type": "files", "epoch": 1, "files": [OTHER_FILE]}]


def test_a_file_whose_bytes_were_not_uploaded_is_refused(room: Room) -> None:
    one, two = Browser(room), Browser(room)
    one.take(), two.take()

    # One of the two was uploaded. The message is taken whole or not at all.
    one.send({"type": "files", "epoch": 1, "files": [FILE, OTHER_FILE]}, (FILE["hash"],))

    (error,) = one.take()
    assert (error["type"], error["error"]) == ("error", "unknown_file")
    assert two.take() == []
    assert (room.files, room.dirty) == ({}, False)


def test_a_viewer_cannot_name_a_file(room: Room) -> None:
    viewer, editor = Browser(room, view_only=True), Browser(room)
    viewer.take(), editor.take()

    viewer.name_files(FILE)

    (error,) = viewer.take()
    assert error["error"] == "view_only"
    assert editor.take() == []
    assert room.files == {}


def test_files_from_another_epoch_get_the_scene_back(room: Room) -> None:
    browser = Browser(room)
    browser.take()

    browser.send({"type": "files", "epoch": 2, "files": [FILE]}, (FILE["hash"],))

    (scene,) = browser.take()
    assert (scene["type"], scene["epoch"]) == ("scene", 1)
    assert room.files == {}


@pytest.mark.parametrize(
    "files",
    [
        None,
        [],
        {},
        "files",
        [FILE["id"]],
        [{}],
        [{**FILE, "id": ""}],
        [{**FILE, "id": "x" * 65}],
        [{**FILE, "id": "../etc/passwd"}],
        [{**FILE, "id": 7}],
        [{**FILE, "hash": "A" * 64}],
        [{**FILE, "hash": "a" * 63}],
        [{**FILE, "hash": "../" + "a" * 61}],
        [{**FILE, "hash": None}],
        [{**FILE, "mimeType": "text/html"}],
        [{**FILE, "mimeType": "application/octet-stream"}],
        [{**FILE, "mimeType": ["image/png"]}],
        [FILE] * (MAX_FILES_IN_MESSAGE + 1),
    ],
)
def test_a_files_message_of_the_wrong_shape_is_refused(room: Room, files: object) -> None:
    assert parse_files(files) is None
    browser = Browser(room)
    browser.take()

    browser.send({"type": "files", "epoch": 1, "files": files}, (FILE["hash"],))

    (error,) = browser.take()
    assert error["error"] == "bad_message"
    assert (room.files, room.dirty) == ({}, False)


def test_a_files_message_needs_an_epoch(room: Room) -> None:
    browser = Browser(room)
    browser.take()

    for epoch in (None, True, "1", 1.0):
        browser.send({"type": "files", "epoch": epoch, "files": [FILE]}, (FILE["hash"],))

    assert [message["error"] for message in browser.take()] == ["bad_message"] * 4


def test_a_file_entry_keeps_only_the_three_fields() -> None:
    sent = {**FILE, "dataURL": "data:image/png;base64,AAAA", "created": 1}

    assert parse_files([sent]) == [FILE]


def test_named_files_reads_only_text_file_ids() -> None:
    elements = [
        image("a", FILE["id"]),
        element("b", 1, fileId=None),
        element("c", 1, fileId={"not": "an id"}),
        element("d", 1, fileId=["x"]),
        "not an element",
    ]

    assert named_files([FILE, OTHER_FILE], elements) == [FILE]


# The size of a slot's scene (max_scene_bytes).


def size_of(*elements: dict[str, Any]) -> int:
    return sum(len(encode(each)) for each in elements)


def test_the_room_knows_the_size_of_its_scene(room: Room) -> None:
    browser = Browser(room)
    first, second = element("a", 1, text="x" * 100), element("b", 1)

    browser.draw(first, second)
    assert room.size == size_of(first, second)

    # A newer copy takes the place of the older one in the count.
    smaller = element("a", 2, text="")
    browser.draw(smaller)
    assert room.size == size_of(smaller, second)


def test_a_room_from_a_head_knows_the_size_of_what_it_loaded() -> None:
    stored = [element("a", 1, text="x" * 100), element("b", 3, index="a0")]

    room = Room.from_head(1, "Workspace 1", 1, json.dumps({"elements": stored}))

    assert room.size == size_of(*stored)


def test_a_batch_that_would_make_the_scene_too_large_is_refused_whole() -> None:
    room = Room(1, "Workspace 1", 1, [], max_scene_bytes=400)
    one, two = Browser(room), Browser(room)
    one.draw(element("a", 1, text="x" * 200))
    room.snapshot()
    one.take(), two.take()
    listener = Listener(room)

    one.draw(element("b", 1), element("c", 1, text="x" * 200), seq=9)

    (error,) = one.take()
    assert (error["type"], error["error"]) == ("error", "scene_too_large")
    assert "400" in error["message"]
    # Nothing of the batch was kept, nobody was told, and it is not called saved.
    assert sorted(room.elements) == ["a"]
    assert two.take() == []
    assert (room.dirty, room.take_waiting(), listener.changes) == (False, [], 0)
    assert room.size == size_of(element("a", 1, text="x" * 200))


def test_a_scene_at_its_limit_still_takes_an_element_that_fits() -> None:
    first = element("a", 1, text="x" * 200)
    second = element("b", 1)
    room = Room(1, "Workspace 1", 1, [], max_scene_bytes=size_of(first, second))
    browser = Browser(room)

    browser.draw(first)
    browser.draw(second)
    browser.draw(element("c", 1))

    assert sorted(room.elements) == ["a", "b"]
    assert room.size == size_of(first, second)


def test_a_full_slot_can_be_emptied() -> None:
    """A stored scene over the limit, as after the limit was lowered."""
    large = element("a", 1, text="x" * 500, isDeleted=False)
    room = Room.from_head(
        1, "Workspace 1", 1, json.dumps({"elements": [large]}), max_scene_bytes=100
    )
    browser = Browser(room)
    browser.take()

    browser.draw(element("b", 1))
    assert browser.take()[0]["error"] == "scene_too_large"

    # Smaller copies are taken although the scene is still over the limit.
    smaller = element("a", 2, text="x" * 300, isDeleted=True)
    browser.draw(smaller)
    assert browser.take() == []
    assert room.elements["a"] == smaller
    assert room.size == size_of(smaller)


def test_without_a_limit_a_scene_may_grow(room: Room) -> None:
    Browser(room).draw(element("a", 1, text="x" * 100_000))

    assert room.size > 100_000


# Another scene in the room's place: a restore.


def stored_scene(*elements: dict[str, Any], **more: object) -> str:
    """Return a scene document as a history row holds one."""
    return json.dumps({"type": "excalidraw", "elements": list(elements), **more})


def test_a_replaced_room_holds_the_new_scene_at_the_new_epoch(room: Room) -> None:
    browser = Browser(room)
    browser.draw(element("a", 3, index="a0"), element("b", 1, index="a1"))
    room.snapshot()
    kept = element("a", 1, index="a0")
    gone = element("c", 2, index="a2", isDeleted=True)

    room.replace(2, stored_scene(kept, gone, appState={"gridSize": 20}))

    assert room.epoch == 2
    # The older copy of a, although the room held a newer one: the scene is
    # put in place, not reconciled.
    assert room.elements == {"a": kept, "c": gone}
    assert room.document == {"type": "excalidraw", "elements": [], "appState": {"gridSize": 20}}
    assert not room.dirty
    assert scene_of(room) == [kept, gone]
    # A flush of it would write the very text it came from.
    assert room.snapshot().scene_json() == encode(
        {"type": "excalidraw", "elements": [kept, gone], "appState": {"gridSize": 20}}
    )


def test_a_replacement_is_sent_to_every_connection_viewers_too(room: Room) -> None:
    editor, viewer = Browser(room, "Guest1"), Browser(room, "Staff2", view_only=True)
    editor.draw(element("a", 1))
    editor.take(), viewer.take()

    room.replace(2, stored_scene(element("z", 1, index="a0")))

    expected = {
        "type": "scene",
        "epoch": 2,
        "elements": [element("z", 1, index="a0")],
        "files": [],
    }
    assert editor.take() == [expected]
    assert viewer.take() == [expected]


def test_a_replacement_ends_the_wait_for_saved(room: Room) -> None:
    browser = Browser(room)
    browser.draw(element("a", 1), seq=5)
    room.snapshot()
    assert browser.connection.awaiting == 5

    room.replace(2, stored_scene())

    # The new epoch is the answer. Nothing is left for a flush to tell.
    assert browser.connection.awaiting is None
    assert not room.unsettled
    assert room.take_waiting() == []


def test_an_edit_for_the_scene_that_went_is_answered_with_the_new_one(room: Room) -> None:
    browser, other = Browser(room), Browser(room)
    room.replace(2, stored_scene(element("z", 1)))
    browser.take(), other.take()

    browser.draw(element("a", 1), epoch=1, seq=6)

    assert browser.take() == [
        {"type": "scene", "epoch": 2, "elements": [element("z", 1)], "files": []}
    ]
    assert other.take() == []
    assert list(room.elements) == ["z"]
    assert (room.dirty, browser.connection.awaiting) == (False, None)

    # One for the new scene is applied, and goes to the others.
    browser.draw(element("a", 1), epoch=2, seq=7)

    assert other.take() == [{"type": "elements", "epoch": 2, "elements": [element("a", 1)]}]
    assert (room.dirty, browser.connection.awaiting) == (True, 7)
    assert room.snapshot().epoch == 2


def test_a_replaced_room_names_the_files_of_its_new_scene(room: Room) -> None:
    browser = Browser(room)
    browser.name_files(FILE, OTHER_FILE)
    browser.draw(element("picture", 1, type="image", fileId=FILE["id"]))
    room.snapshot()
    browser.take()
    other = element("other", 1, type="image", fileId=OTHER_FILE["id"])

    room.replace(2, stored_scene(other))

    # The slot's list keeps both. A scene names the ones its elements do.
    assert browser.take()[0]["files"] == [OTHER_FILE]
    assert list(room.files) == [FILE["id"], OTHER_FILE["id"]]
    room.replace(3, stored_scene())
    assert browser.take()[0]["files"] == []


def test_a_file_named_and_not_yet_written_outlasts_a_replacement(room: Room) -> None:
    changes: list[str] = []
    room.on_change = lambda: changes.append("change")
    browser = Browser(room)
    browser.name_files(FILE)
    changes.clear()

    room.replace(2, stored_scene())

    # Still to be written, and the saver is told so.
    assert room.dirty
    assert changes == ["change"]
    taken = room.snapshot()
    assert (taken.epoch, taken.files) == (2, [FILE])
    assert not room.dirty


def test_a_replacement_of_a_clean_room_asks_for_no_write(room: Room) -> None:
    changes: list[str] = []
    room.on_change = lambda: changes.append("change")

    room.replace(2, stored_scene(element("z", 1)))

    assert changes == []
    assert not room.unsettled


def test_the_size_limit_counts_the_scene_that_was_put_in_place() -> None:
    small = element("a", 1)
    limit = len(encode(small)) + 10
    room = Room(3, "Workspace 3", 1, [], max_scene_bytes=limit)
    browser = Browser(room)
    browser.draw(small)
    assert room.size == len(encode(small))

    # A restored scene may be larger than the limit, which may have been
    # lowered since. It is taken, and the count is of what the room holds now.
    large = [element(f"z{number}", 1, text="x" * 20) for number in range(4)]
    room.replace(2, stored_scene(*large))

    assert room.size == sum(len(encode(each)) for each in large) > limit
    browser.take()
    browser.draw(element("more", 1), epoch=2)
    assert browser.take()[0]["error"] == "scene_too_large"
    # Making it smaller is always allowed.
    browser.draw(element("z0", 2), epoch=2)
    assert browser.take() == []
    assert room.elements["z0"] == element("z0", 2)
    assert room.size == sum(len(encode(each)) for each in room.elements.values())


def test_an_import_puts_its_elements_and_its_files_in_place(room: Room) -> None:
    changes: list[str] = []
    room.on_change = lambda: changes.append("change")
    browser, viewer = Browser(room), Browser(room, view_only=True)
    browser.draw(element("a", 1), seq=4)
    room.snapshot()
    changes.clear()
    browser.take(), viewer.take()
    picture = element("picture", 1, type="image", fileId=FILE["id"], index="a1")
    document = {"type": "excalidraw", "elements": [], "appState": {"gridSize": 20}}

    room.put(2, document, [element("z", 3, index="a0"), picture], [FILE])

    scene = {
        "type": "scene",
        "epoch": 2,
        "elements": [element("z", 3, index="a0"), picture],
        "files": [FILE],
    }
    # Everyone is sent the scene with the files its images name, viewers too.
    assert browser.take() == [scene] and viewer.take() == [scene]
    assert (room.epoch, list(room.elements), room.document) == (2, ["z", "picture"], document)
    assert room.files == {FILE["id"]: FILE}
    assert room.size == sum(len(encode(each)) for each in room.elements.values())
    # The files were written with the scene, so nothing is left to write, and
    # what was sent for the scene that went has nothing left to wait for.
    assert not room.dirty and changes == []
    assert browser.connection.awaiting is None
    assert room.snapshot().files == []


def test_a_file_named_while_an_import_was_written_gives_way_to_the_imports(room: Room) -> None:
    browser = Browser(room)
    # Named on the socket after the import's write began: the slot's stored
    # list has the import's bytes for this id, and the room follows the list.
    named = {**FILE, "hash": "c" * 64}
    browser.name_files(named, OTHER_FILE)
    browser.take()
    picture = element("picture", 1, type="image", fileId=FILE["id"])

    room.put(2, {"elements": []}, [picture], [FILE])

    assert room.files[FILE["id"]] == FILE
    assert browser.take()[0]["files"] == [FILE]
    # The other file is still to be written, and only that one.
    assert room.dirty
    assert room.snapshot().files == [OTHER_FILE]


def test_a_replacement_forgets_who_edited_the_scene_that_went(room: Room) -> None:
    browser = Browser(room, "Guest1")
    browser.draw(element("a", 1))
    assert room.snapshot().editor_label == "Guest1"

    room.replace(2, stored_scene())

    # The row of the restore has its own label. The next flush is by whoever
    # edits next.
    assert room.editor_label is None


@pytest.mark.parametrize(
    ("text", "document", "identifiers"),
    [
        (
            '{"type":"excalidraw","elements":[{"id":"a","version":2,"versionNonce":5}]}',
            {"type": "excalidraw", "elements": []},
            ["a"],
        ),
        # What is not an element is left out, and a missing version is the editor's default.
        ('{"elements":[1,null,{"id":""},{"id":"b"},"x"]}', {"elements": []}, ["b"]),
        ('{"appState":{}}', {"appState": {}}, []),
        ('{"elements":{"id":"a"}}', {"elements": []}, []),
        ("[]", {}, []),
        ("null", {}, []),
    ],
)
def test_a_stored_scene_is_read_as_a_document_and_its_elements(
    text: str, document: dict[str, Any], identifiers: list[str]
) -> None:
    parsed, elements = parse_scene(text)

    assert parsed == document
    assert [each["id"] for each in elements] == identifiers
    assert all(isinstance(each["version"], int) for each in elements)
