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

"""Follow mode and Diagram mode's cursors (T18; docs/API.md, "WebSocket").

A browser follows another connection's view with ``follow``. The server tells
the leader how many follow it, and sends the leader's ``view`` to them alone.
On slot 9 a cursor and a view also name the page of the diagram they are on.
First the rooms alone, as ``tests/test_room.py`` tests them, then the socket.
"""

import json
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from harness import make_settings
from starlette.testclient import WebSocketTestSession

from segl.app import create_app
from segl.diagram import DIAGRAM_SLOT, EMPTY_DIAGRAM, DiagramRoom
from segl.repository import Repository
from segl.room import MAX_PAGE_LENGTH, Connection, Hello, Room

VIEW = {"x": -120.5, "y": 40, "width": 1280, "height": 720}


class Browser:
    """A connection in a room, and everything the room has sent it."""

    def __init__(self, room: Room, name: str = "Guest1", *, view_only: bool = False) -> None:
        self.room = room
        self.received: list[dict[str, Any]] = []
        self.connection = Connection(
            lambda text: self.received.append(json.loads(text)),
            Hello("client-1", name, "", None),
            view_only=view_only,
        )
        room.join(self.connection)
        self.take()

    @property
    def id(self) -> str:
        return self.connection.id

    def take(self) -> list[dict[str, Any]]:
        """Return what arrived since the last call."""
        messages, self.received = self.received, []
        return messages

    def send(self, message: object) -> None:
        self.room.receive(self.connection, message)

    def follow(self, leader: Browser | None) -> None:
        self.send({"type": "follow", "connectionId": None if leader is None else leader.id})

    def look(self, view: dict[str, Any]) -> None:
        self.send({"type": "view", "view": view})

    def leave(self) -> None:
        self.room.leave(self.connection)

    def errors(self) -> list[str]:
        return [message["error"] for message in self.take() if message["type"] == "error"]


@pytest.fixture
def room() -> Room:
    return Room(3, "Workspace 3", 1, [], start="s")


@pytest.fixture
def diagram() -> DiagramRoom:
    return DiagramRoom(DIAGRAM_SLOT, "Workspace 9", 1, EMPTY_DIAGRAM, start="s")


def crowd(room: Room, count: int, *, viewers: tuple[int, ...] = ()) -> list[Browser]:
    """Return ``count`` browsers on the room, with nothing waiting for any of them.

    The ones whose places are in ``viewers`` may not edit.
    """
    browsers = [Browser(room, view_only=place in viewers) for place in range(count)]
    for browser in browsers:
        browser.take()
    return browsers


def followers(messages: list[dict[str, Any]]) -> list[int]:
    return [message["count"] for message in messages if message["type"] == "followers"]


# Following, and the count.


def test_a_leader_is_told_how_many_follow_it(room: Room) -> None:
    leader, first, second = crowd(room, 3)

    first.follow(leader)
    second.follow(leader)
    first.follow(None)

    assert followers(leader.take()) == [1, 2, 1]
    # Nothing goes to the followers: they know whom they follow.
    assert first.take() == second.take() == []


def test_following_the_same_connection_again_tells_nobody(room: Room) -> None:
    leader, follower = crowd(room, 2)
    leader.take()
    follower.follow(leader)
    follower.follow(leader)
    follower.follow(None)
    follower.follow(None)

    assert followers(leader.take()) == [1, 0]
    assert follower.take() == []


def test_a_follow_that_moves_tells_both_leaders(room: Room) -> None:
    first, second, follower = crowd(room, 3)
    follower.follow(first)
    first.take(), second.take()

    follower.follow(second)

    assert followers(first.take()) == [0]
    assert followers(second.take()) == [1]


# The view.


def test_a_view_goes_to_the_leaders_followers_and_nobody_else(room: Room) -> None:
    leader, follower, other = crowd(room, 3)
    follower.follow(leader)
    leader.take(), other.take()

    leader.look(VIEW)

    assert follower.take() == [{"type": "view", "connectionId": leader.id, "view": VIEW}]
    assert leader.take() == other.take() == []


def test_a_view_nobody_follows_goes_nowhere(room: Room) -> None:
    leader, follower = crowd(room, 2)
    follower.follow(leader)
    follower.follow(None)
    leader.take()

    leader.look(VIEW)

    assert leader.take() == follower.take() == []


def test_a_followers_own_view_goes_to_its_own_followers(room: Room) -> None:
    # A chain: the last one sees what the middle one shows.
    first, middle, last = crowd(room, 3)
    middle.follow(first)
    last.follow(middle)
    first.take(), middle.take()

    middle.look(VIEW)

    assert first.take() == []
    assert last.take() == [{"type": "view", "connectionId": middle.id, "view": VIEW}]


def test_a_viewer_may_follow_and_be_followed(room: Room) -> None:
    leader, viewer, other = crowd(room, 3, viewers=(1,))
    viewer.follow(leader)
    other.follow(viewer)
    leader.look(VIEW)
    viewer.look(VIEW)

    assert followers(leader.take()) == [1]
    assert [m["type"] for m in viewer.take()] == ["followers", "view"]
    assert [m["type"] for m in other.take()] == ["view"]


# A follow ends.


def test_a_follow_ends_when_the_leader_leaves(room: Room) -> None:
    leader, follower, later = crowd(room, 3)
    follower.follow(leader)
    leader.take(), later.take()

    leader.leave()

    # The follower learns it from presence-end, as everyone does.
    assert follower.take() == [{"type": "presence-end", "connectionId": leader.id}]
    assert follower.connection.following is None
    # And it follows nobody: a later connection's view does not reach it.
    later.look(VIEW)
    assert follower.take() == []


def test_a_follow_ends_when_the_follower_leaves(room: Room) -> None:
    leader, follower = crowd(room, 2)
    follower.follow(leader)
    leader.take()

    follower.leave()

    assert followers(leader.take()) == [0]
    leader.look(VIEW)
    assert leader.take() == []


# What is refused.


def test_a_follow_of_a_connection_not_on_the_slot_is_refused(room: Room) -> None:
    gone, follower = crowd(room, 2)
    gone.leave()
    follower.take()

    follower.send({"type": "follow", "connectionId": gone.id})
    follower.send({"type": "follow", "connectionId": "nobody"})

    assert follower.errors() == ["cannot_follow", "cannot_follow"]
    assert follower.connection.following is None


def test_a_connection_does_not_follow_itself(room: Room) -> None:
    (browser,) = crowd(room, 1)
    browser.follow(browser)
    assert browser.errors() == ["cannot_follow"]
    assert browser.connection.following is None


def test_a_follow_that_would_close_a_loop_is_refused(room: Room) -> None:
    first, second, third = crowd(room, 3)
    second.follow(first)
    third.follow(second)
    first.take()

    first.follow(second)
    first.follow(third)

    assert first.errors() == ["cannot_follow", "cannot_follow"]
    assert first.connection.following is None
    # The others still follow as they did.
    assert (second.connection.following, third.connection.following) == (
        first.connection,
        second.connection,
    )


def test_a_refused_follow_keeps_the_follow_there_was(room: Room) -> None:
    first, second, follower = crowd(room, 3)
    follower.follow(first)
    follower.send({"type": "follow", "connectionId": "nobody"})
    assert follower.errors() == ["cannot_follow"]
    assert follower.connection.following is first.connection
    assert second.take() == []


@pytest.mark.parametrize(
    "message",
    [
        {"type": "follow"},
        {"type": "follow", "connectionId": 7},
        {"type": "follow", "connectionId": ["a"]},
        {"type": "view"},
        {"type": "view", "view": None},
        {"type": "view", "view": {"x": 0, "y": 0, "width": 10}},
        {"type": "view", "view": {**VIEW, "width": 0}},
        {"type": "view", "view": {**VIEW, "height": -1}},
        {"type": "view", "view": {**VIEW, "x": True}},
        {"type": "view", "view": {**VIEW, "y": "0"}},
        {"type": "view", "view": {**VIEW, "x": float("inf")}},
        # A whiteboard has no pages.
        {"type": "view", "view": {**VIEW, "page": "segl-page-1"}},
        {"type": "presence", "cursor": {"x": 1, "y": 2, "page": "segl-page-1"}},
    ],
)
def test_a_malformed_follow_view_or_cursor_is_refused(room: Room, message: object) -> None:
    leader, follower = crowd(room, 2)
    follower.follow(leader)
    leader.take(), follower.take()

    leader.send(message)

    assert leader.errors() == ["bad_message"]
    assert follower.take() == []
    assert follower.connection.following is leader.connection


# Slot 9: the page of the diagram.


def test_on_slot_9_a_cursor_reaches_the_others_with_its_page(diagram: DiagramRoom) -> None:
    mover, other = crowd(diagram, 2)
    other.take()

    mover.send({"type": "presence", "cursor": {"x": 10.5, "y": -3, "page": "segl-page-1"}})
    mover.send({"type": "presence", "cursor": {"x": 1, "y": 2}})
    mover.send({"type": "presence", "cursor": None})

    assert [m["cursor"] for m in other.take()] == [
        {"x": 10.5, "y": -3, "page": "segl-page-1"},
        # A diagram's page may be unknown to drawio: then it is null.
        {"x": 1, "y": 2, "page": None},
        None,
    ]
    assert mover.take() == []


@pytest.mark.parametrize("page", ["", 3, True, ["segl-page-1"], "p" * (MAX_PAGE_LENGTH + 1)])
def test_on_slot_9_a_cursor_whose_page_is_not_a_short_text_is_refused(
    diagram: DiagramRoom, page: object
) -> None:
    mover, other = crowd(diagram, 2)
    other.take()

    mover.send({"type": "presence", "cursor": {"x": 1, "y": 2, "page": page}})
    mover.send({"type": "view", "view": {**VIEW, "page": page}})

    assert mover.errors() == ["bad_message", "bad_message"]
    assert other.take() == []


def test_on_slot_9_a_page_of_the_longest_length_is_taken(diagram: DiagramRoom) -> None:
    mover, other = crowd(diagram, 2)
    other.take()
    page = "p" * MAX_PAGE_LENGTH
    mover.send({"type": "presence", "cursor": {"x": 1, "y": 2, "page": page}})
    assert other.take()[0]["cursor"]["page"] == page


def test_on_slot_9_a_follower_gets_the_view_with_its_page(diagram: DiagramRoom) -> None:
    leader, follower = crowd(diagram, 2)
    follower.follow(leader)
    assert followers(leader.take()) == [1]

    leader.look({**VIEW, "page": "segl-page-2"})

    assert follower.take() == [
        {"type": "view", "connectionId": leader.id, "view": {**VIEW, "page": "segl-page-2"}}
    ]


def test_on_slot_9_the_pen_holder_leaving_ends_its_follows(diagram: DiagramRoom) -> None:
    holder, follower = crowd(diagram, 2)
    holder.send({"type": "pen", "take": True})
    follower.follow(holder)
    follower.take()

    holder.leave()

    assert [m["type"] for m in follower.take()] == ["pen", "presence-end"]
    assert follower.connection.following is None


# The socket.


def received(socket: WebSocketTestSession, seconds: float = 5.0) -> dict[str, Any]:
    """Return the next message, and fail the test rather than wait for ever."""

    async def receive() -> Any:
        with anyio.fail_after(seconds):
            return await socket._send_rx.receive()

    message = socket.portal.call(receive)
    socket._raise_on_close(message)
    return json.loads(message["text"])


def joined(socket: WebSocketTestSession, client_id: str) -> str:
    """Say hello, take the welcome and the scene, and return the connection id."""
    socket.send_json({"type": "hello", "clientId": client_id, "displayName": None, "editToken": ""})
    welcome = received(socket)
    received(socket)
    return welcome["connectionId"]


@pytest.mark.parametrize("slot", [3, DIAGRAM_SLOT])
def test_follow_and_view_at_the_socket(repository: Repository, slot: int) -> None:
    view = {**VIEW, "page": "segl-page-1"} if slot == DIAGRAM_SLOT else VIEW
    with (
        TestClient(create_app(make_settings(), repository)) as client,
        client.websocket_connect(f"/collab?slot={slot}") as leader,
        client.websocket_connect(f"/collab?slot={slot}") as follower,
    ):
        leader_id = joined(leader, "a")
        joined(follower, "b")
        assert received(leader)["type"] == "presence"

        follower.send_json({"type": "follow", "connectionId": leader_id})
        assert received(leader) == {"type": "followers", "count": 1}
        leader.send_json({"type": "view", "view": view})
        assert received(follower) == {"type": "view", "connectionId": leader_id, "view": view}

        follower.send_json({"type": "follow", "connectionId": "nobody"})
        assert received(follower)["error"] == "cannot_follow"


def test_a_cursor_on_slot_9_names_its_page_at_the_socket(repository: Repository) -> None:
    with (
        TestClient(create_app(make_settings(), repository)) as client,
        client.websocket_connect("/collab?slot=9") as mover,
        client.websocket_connect("/collab?slot=9") as other,
    ):
        joined(mover, "a")
        joined(other, "b")
        received(mover)

        mover.send_json({"type": "presence", "cursor": {"x": 5, "y": 6, "page": "segl-page-1"}})
        assert received(other)["cursor"] == {"x": 5, "y": 6, "page": "segl-page-1"}
