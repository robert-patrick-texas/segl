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

"""The others' selections on slot 9 (T19; docs/API.md, "Diagram mode").

A browser sends what it has selected in drawio: the page, and 1 to 50 cell
ids, or null. The server keeps each connection's newest, sends it to the
others, and sends a browser that joins the ones already made. A selection is
presence, as a cursor is: anyone may send one, and it changes no diagram.
First the room alone, as ``tests/test_diagram.py`` tests it, then the socket.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from harness import make_settings
from test_diagram import Browser
from test_follow import joined, received

from segl.app import create_app
from segl.diagram import DIAGRAM_SLOT, EMPTY_DIAGRAM, DiagramRoom
from segl.repository import Repository
from segl.room import Connection, Hello, Room

PICKED = {"page": "segl-page-1", "cells": ["2", "3"]}
# The limits docs/API.md gives, written here and not read from segl, so that a
# change to segl's own constants fails a test.
MOST_CELLS = 50
LONGEST_ID = 128


@pytest.fixture
def room() -> DiagramRoom:
    return DiagramRoom(DIAGRAM_SLOT, "Workspace 9", 1, EMPTY_DIAGRAM, start="s")


def crowd(room: DiagramRoom, count: int, *, viewers: tuple[int, ...] = ()) -> list[Browser]:
    """Return ``count`` browsers on the room, with nothing waiting for any of them."""
    browsers = [Browser(room, view_only=place in viewers) for place in range(count)]
    for browser in browsers:
        browser.take()
    return browsers


def select(browser: Browser, selection: object) -> None:
    browser.send({"type": "selection", "selection": selection})


def selections(browser: Browser) -> list[tuple[str, Any]]:
    """Return the selections a browser was sent since the last call: whose, and what."""
    return [
        (message["connectionId"], message["selection"])
        for message in browser.take()
        if message["type"] == "selection"
    ]


# What the others are sent.


def test_a_selection_reaches_the_others_and_not_its_sender(room: DiagramRoom) -> None:
    alpha, bravo, charlie = crowd(room, 3)

    select(alpha, PICKED)

    assert bravo.take() == [{"type": "selection", "connectionId": alpha.id, "selection": PICKED}]
    assert selections(charlie) == [(alpha.id, PICKED)]
    assert alpha.take() == []


def test_selecting_nothing_reaches_the_others_as_null(room: DiagramRoom) -> None:
    alpha, bravo = crowd(room, 2)
    select(alpha, PICKED)

    select(alpha, None)

    assert selections(bravo) == [(alpha.id, PICKED), (alpha.id, None)]


def test_a_viewer_and_a_watcher_while_the_pen_is_held_both_send_a_selection(
    room: DiagramRoom,
) -> None:
    holder, viewer, watcher = crowd(room, 3, viewers=(1,))
    holder.send({"type": "pen", "take": True})
    holder.take(), viewer.take(), watcher.take()

    select(viewer, PICKED)
    select(watcher, {"page": None, "cells": ["7"]})

    assert selections(holder) == [(viewer.id, PICKED), (watcher.id, {"page": None, "cells": ["7"]})]
    assert viewer.errors() == watcher.errors() == []
    # A selection changes no diagram.
    assert (room.count, room.dirty) == (0, False)


def test_the_server_sends_the_page_and_the_cells_and_nothing_else(room: DiagramRoom) -> None:
    alpha, bravo = crowd(room, 2)

    # A selection without a page names none, as a cursor without one does.
    select(alpha, {"cells": ["2"], "colour": "red"})

    assert selections(bravo) == [(alpha.id, {"page": None, "cells": ["2"]})]


def test_a_selection_at_the_limits_is_taken(room: DiagramRoom) -> None:
    alpha, bravo = crowd(room, 2)
    widest = {
        "page": "p" * LONGEST_ID,
        "cells": [f"{n:03}".ljust(LONGEST_ID, "c") for n in range(MOST_CELLS)],
    }

    select(alpha, widest)
    select(alpha, {"page": "q", "cells": ["c"]})

    assert alpha.errors() == []
    assert selections(bravo) == [(alpha.id, widest), (alpha.id, {"page": "q", "cells": ["c"]})]


@pytest.mark.parametrize(
    "message",
    [
        {"type": "selection"},
        {"type": "selection", "selection": ["2"]},
        {"type": "selection", "selection": "2"},
        {"type": "selection", "selection": True},
        {"type": "selection", "selection": {"page": "", "cells": ["2"]}},
        {"type": "selection", "selection": {"page": 3, "cells": ["2"]}},
        {"type": "selection", "selection": {"page": True, "cells": ["2"]}},
        {"type": "selection", "selection": {"page": ["p"], "cells": ["2"]}},
        {"type": "selection", "selection": {"page": "p" * (LONGEST_ID + 1), "cells": ["2"]}},
        {"type": "selection", "selection": {"page": "p"}},
        {"type": "selection", "selection": {"page": "p", "cells": None}},
        {"type": "selection", "selection": {"page": "p", "cells": "23"}},
        {"type": "selection", "selection": {"page": "p", "cells": {"2": True}}},
        {"type": "selection", "selection": {"page": "p", "cells": []}},
        {
            "type": "selection",
            "selection": {"page": "p", "cells": [str(n) for n in range(MOST_CELLS + 1)]},
        },
        {"type": "selection", "selection": {"page": "p", "cells": ["2", ""]}},
        {"type": "selection", "selection": {"page": "p", "cells": ["2", 3]}},
        {"type": "selection", "selection": {"page": "p", "cells": [None]}},
        {"type": "selection", "selection": {"page": "p", "cells": [["2"]]}},
        {
            "type": "selection",
            "selection": {"page": "p", "cells": ["c" * (LONGEST_ID + 1)]},
        },
    ],
    ids=lambda message: repr(message.get("selection", "missing"))[:40],
)
def test_a_bad_selection_is_refused_and_reaches_nobody(
    room: DiagramRoom, message: dict[str, Any]
) -> None:
    alpha, bravo = crowd(room, 2)
    select(alpha, PICKED)
    bravo.take()

    alpha.send(message)

    assert alpha.errors() == ["bad_message"]
    assert bravo.take() == []
    # The selection it had stays, and a browser that comes later is sent it.
    assert selections(Browser(room)) == [(alpha.id, PICKED)]


def test_a_whiteboard_knows_no_selection() -> None:
    room = Room(3, "Workspace 3", 1, [], start="s")
    received: list[str] = []
    connection = Connection(received.append, Hello("client-1", None, ""), view_only=False)
    room.join(connection)
    received.clear()

    room.receive(connection, {"type": "selection", "selection": PICKED})

    assert len(received) == 1
    assert '"error":"unknown_type"' in received[0]


# A browser that comes later.


def test_a_browser_that_joins_gets_the_selections_already_made_after_the_diagram(
    room: DiagramRoom,
) -> None:
    alpha, bravo, charlie = crowd(room, 3)
    select(alpha, {"page": "segl-page-1", "cells": ["old"]})
    select(alpha, PICKED)
    select(bravo, PICKED)
    select(bravo, None)
    select(charlie, {"page": None, "cells": ["9"]})
    alpha.take()

    late = Browser(room)

    told = late.take()
    assert [message["type"] for message in told] == ["welcome", "diagram", "selection", "selection"]
    # The newest of each, in the order they joined. Bravo has nothing selected.
    assert [(message["connectionId"], message["selection"]) for message in told[2:]] == [
        (alpha.id, PICKED),
        (charlie.id, {"page": None, "cells": ["9"]}),
    ]
    # The others are told only that it came.
    assert [message["type"] for message in alpha.take()] == ["presence"]


def test_a_selection_goes_with_its_connection(room: DiagramRoom) -> None:
    alpha, bravo = crowd(room, 2)
    select(alpha, PICKED)
    bravo.take()

    room.leave(alpha.connection)

    # The others drop it on presence-end, and nothing more is sent.
    assert bravo.take() == [{"type": "presence-end", "connectionId": alpha.id}]
    assert selections(Browser(room)) == []


# The socket.


def test_selections_at_the_socket(repository: Repository) -> None:
    with (
        TestClient(create_app(make_settings(), repository)) as client,
        client.websocket_connect("/collab?slot=9") as alpha,
        client.websocket_connect("/collab?slot=9") as bravo,
    ):
        alpha_id = joined(alpha, "a")
        joined(bravo, "b")
        assert received(alpha)["type"] == "presence"

        alpha.send_json({"type": "selection", "selection": PICKED})
        assert received(bravo) == {
            "type": "selection",
            "connectionId": alpha_id,
            "selection": PICKED,
        }
        bravo.send_json({"type": "selection", "selection": {"page": "p", "cells": []}})
        assert received(bravo)["error"] == "bad_message"

        with client.websocket_connect("/collab?slot=9") as late:
            joined(late, "c")
            assert received(late) == {
                "type": "selection",
                "connectionId": alpha_id,
                "selection": PICKED,
            }

        with client.websocket_connect("/collab?slot=3") as board:
            joined(board, "d")
            board.send_json({"type": "selection", "selection": PICKED})
            assert received(board)["error"] == "unknown_type"
