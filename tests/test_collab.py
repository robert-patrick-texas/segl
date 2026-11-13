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

"""The collaboration WebSocket and the title route (docs/API.md), in process,
from a running ``segl`` process, and through nginx at ``/board/collab``.

``tests/test_room.py`` covers what a room does with each message. These tests
cover the socket around it: the handshake, ``hello``, who is told what, the
edit gate, and a title change reaching the room.
"""

import asyncio
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from harness import (
    BOARD_SITE,
    GATED,
    GATED_TOML,
    PASS_HEADER,
    ROOT_SITE,
    NginxTools,
    assert_no_secrets,
    issue_pass,
    make_settings,
    next_message,
    running_mount,
    running_segl,
    say_hello,
)
from starlette.testclient import WebSocketDenialResponse, WebSocketTestSession
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from segl import collab
from segl.app import create_app
from segl.assets import AssetStore
from segl.collab import Rooms, _Outbox, parse_message
from segl.repository import Repository, Slot
from segl.room import encode

# A pass a segl with ``GATED`` takes, issued as the tests are collected.
PASS = issue_pass()
INVALID_SLOT = {"error": "invalid_slot", "message": "Slots are numbered 1 to 9."}


def element(identifier: str, version: int, nonce: int = 1, **more: object) -> dict[str, Any]:
    return {"id": identifier, "version": version, "versionNonce": nonce, **more}


@pytest.fixture
def client(repository: Repository) -> Iterator[TestClient]:
    # Entered, so that every socket of a test runs on one event loop, as in
    # the server.
    with TestClient(create_app(make_settings(), repository)) as client:
        yield client


@pytest.fixture
def gated(repository: Repository) -> Iterator[TestClient]:
    """A server that asks for an access code."""
    with TestClient(create_app(make_settings(**GATED), repository)) as client:
        yield client


def received(socket: WebSocketTestSession, seconds: float = 5.0) -> dict[str, Any]:
    """Return the next message, and fail the test rather than wait for ever."""

    async def receive() -> Any:
        with anyio.fail_after(seconds):
            return await socket._send_rx.receive()

    message = socket.portal.call(receive)
    socket._raise_on_close(message)
    return json.loads(message["text"])


def hello(
    socket: WebSocketTestSession, name: str | None = "Guest1", edit_pass: str = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Say hello, and return the welcome and the scene."""
    socket.send_json(
        {"type": "hello", "clientId": "client-1", "displayName": name, "editToken": edit_pass}
    )
    return received(socket), received(socket)


def test_hello_is_answered_with_a_welcome_and_the_scene(client: TestClient) -> None:
    with client.websocket_connect("/collab?slot=3") as socket:
        welcome, scene = hello(socket, "Guest1")

    (me,) = welcome.pop("participants")
    assert welcome == {
        "type": "welcome",
        "slot": 3,
        "title": "Workspace 3",
        "epoch": 1,
        "viewOnly": False,
        "editEndsIn": None,
        "connectionId": me["connectionId"],
    }
    assert me["displayName"] == "Guest1"
    assert scene == {"type": "scene", "epoch": 1, "elements": [], "files": []}


def test_the_room_starts_from_the_slots_stored_head(
    client: TestClient, repository: Repository
) -> None:
    stored = {"type": "excalidraw", "elements": [element("a", 4, 9, index="a0")], "appState": {}}
    repository.save_head(5, 1, json.dumps(stored), "Bravo2")
    repository.rename_slot(5, "Lab")

    with client.websocket_connect("/collab?slot=5") as socket:
        welcome, scene = hello(socket)

    assert welcome["title"] == "Lab"
    assert scene["elements"] == [element("a", 4, 9, index="a0")]


def test_two_connections_on_a_slot_see_each_other_and_share_edits(client: TestClient) -> None:
    """T-001, T-015, and the broadcast of T-014, at the socket."""
    with (
        client.websocket_connect("/collab?slot=3") as one,
        client.websocket_connect("/collab?slot=1") as elsewhere,
    ):
        mine = hello(one, "Guest1")[0]["connectionId"]
        assert len(hello(elsewhere, "Guest3")[0]["participants"]) == 1

        with client.websocket_connect("/collab?slot=3") as two:
            welcome, _ = hello(two, "Staff2")
            assert [each["displayName"] for each in welcome["participants"]] == [
                "Guest1",
                "Staff2",
            ]
            arrived = received(one)
            assert (arrived["type"], arrived["displayName"]) == ("presence", "Staff2")
            assert arrived["connectionId"] == welcome["connectionId"] != mine

            rectangle = element("a", 1, type="rectangle", index="a0")
            one.send_json({"type": "elements", "epoch": 1, "elements": [rectangle]})
            assert received(two) == {"type": "elements", "epoch": 1, "elements": [rectangle]}

            two.send_json({"type": "rename", "displayName": "john smith"})
            assert received(one)["displayName"] == "John Smith"
            assert received(two)["displayName"] == "John Smith"

        # Closing one drops the count to 1.
        assert received(one) == {"type": "presence-end", "connectionId": welcome["connectionId"]}
        # The drawing outlasts the browser that watched it arrive.
        with client.websocket_connect("/collab?slot=3") as later:
            welcome, scene = hello(later, "Guest4")
            assert [each["displayName"] for each in welcome["participants"]] == [
                "Guest1",
                "Guest4",
            ]
            assert scene["elements"] == [rectangle]
        # Slot 1 heard none of it: the next thing it is sent is its own rename.
        elsewhere.send_json({"type": "rename", "displayName": "still here"})
        assert received(elsewhere)["displayName"] == "Still Here"


@pytest.mark.parametrize(
    "path",
    [
        "/collab",
        "/collab?slot=",
        "/collab?slot=0",
        "/collab?slot=10",
        "/collab?slot=01",
        "/collab?slot=abc",
        "/collab?slot=%D9%A1",
        "/collab?board=1",
    ],
)
def test_a_socket_for_no_slot_is_refused_in_the_handshake(client: TestClient, path: str) -> None:
    with pytest.raises(WebSocketDenialResponse) as refused, client.websocket_connect(path):
        pass

    assert refused.value.status_code == 404
    assert refused.value.json() == INVALID_SLOT


@pytest.mark.parametrize(
    "first",
    [
        {"type": "elements", "epoch": 1, "elements": []},
        {"type": "hello"},
        {"type": "hello", "clientId": "not a client id"},
        "hello",
        [],
    ],
)
def test_a_socket_whose_first_message_is_not_hello_is_closed(
    client: TestClient, first: object
) -> None:
    with client.websocket_connect("/collab?slot=1") as socket:
        socket.send_json(first)

        error = received(socket)
        assert (error["type"], error["error"]) == ("error", "bad_message")
        with pytest.raises(WebSocketDisconnect) as closed:
            received(socket)
        assert closed.value.code == collab.POLICY_VIOLATION
    assert client.app.state.rooms._rooms[1].connections == {}  # ty: ignore[missing-attribute]


def test_a_socket_that_never_says_hello_is_closed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collab, "HELLO_SECONDS", 0.05)

    with client.websocket_connect("/collab?slot=1") as socket:
        assert received(socket)["error"] == "bad_message"
        with pytest.raises(WebSocketDisconnect) as closed:
            received(socket)
    assert closed.value.code == collab.POLICY_VIOLATION


def test_a_socket_is_not_in_the_room_before_it_says_hello(client: TestClient) -> None:
    with (
        client.websocket_connect("/collab?slot=2") as one,
        client.websocket_connect("/collab?slot=2") as silent,
    ):
        assert len(hello(one)[0]["participants"]) == 1
        one.send_json({"type": "rename", "displayName": "one"})
        assert received(one)["displayName"] == "One"

        # It was sent nothing, and is not counted, until its own hello.
        assert len(hello(silent)[0]["participants"]) == 2


@pytest.mark.parametrize(
    "frame",
    [
        "{",
        "",
        "NaN",
        '{"type": "presence", "cursor": {"x": NaN}}',
        '{"type": "presence", "cursor": {"x": 1e999, "y": 0}}',
    ],
)
def test_text_that_is_not_json_is_answered_with_an_error(client: TestClient, frame: str) -> None:
    with client.websocket_connect("/collab?slot=1") as socket:
        hello(socket)

        socket.send_text(frame)

        assert received(socket)["error"] == "bad_message"
        # The connection is still there.
        socket.send_json({"type": "rename", "displayName": "ada"})
        assert received(socket)["displayName"] == "Ada"


def test_a_binary_frame_is_answered_with_an_error(client: TestClient) -> None:
    with client.websocket_connect("/collab?slot=1") as socket:
        hello(socket)

        socket.send_bytes(b'{"type": "rename", "displayName": "ada"}')

        assert received(socket)["error"] == "bad_message"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_number_json_does_not_have_is_not_read(constant: str) -> None:
    # Python's parser would take it, and a browser sent it back could not parse it.
    with pytest.raises(ValueError, match=constant.lstrip("-")):
        parse_message(f'{{"type": "elements", "elements": [{{"x": {constant}}}]}}')


@pytest.mark.parametrize("number", ["1e999", "-1e999", "1E400", "2.5e+309", "[[-1e999]]"])
def test_a_number_too_large_to_write_back_is_not_read(number: str) -> None:
    # It is JSON, and Python reads it as infinity, which it would write as `Infinity`.
    with pytest.raises(ValueError, match=r"[eE]"):
        parse_message(f'{{"type": "elements", "elements": [{{"x": {number}}}]}}')


def test_the_largest_numbers_json_can_carry_are_read() -> None:
    whole = 10**400
    message = parse_message(
        f'{{"x": 1.7976931348623157e308, "y": -1e308, "z": {whole}, "w": 1e-999}}'
    )

    assert message == {"x": 1.7976931348623157e308, "y": -1e308, "z": whole, "w": 0.0}
    # Each is written back as JSON a browser reads.
    parse_message(encode({"again": message}))


def test_an_element_with_a_number_too_large_reaches_nobody_and_is_not_stored(
    client: TestClient,
) -> None:
    # Before, the other browser was sent `Infinity`, the sender was told
    # `saved`, and the scene route answered with text no browser can parse.
    drawn = '{"id": "a", "version": 1, "versionNonce": 1, "x": 1e999}'
    with (
        client.websocket_connect("/collab?slot=3") as one,
        client.websocket_connect("/collab?slot=3") as two,
    ):
        hello(one), hello(two)
        received(one)

        one.send_text(f'{{"type": "elements", "epoch": 1, "elements": [{drawn}], "seq": 1}}')

        assert received(one)["error"] == "bad_message"
        # The connection is still there, and the other heard nothing of the element.
        one.send_json({"type": "rename", "displayName": "ada"})
        assert received(one)["displayName"] == "Ada"
        assert received(two)["type"] == "presence"
    answer = client.get("/api/v1/slots/3/scene")
    assert "Infinity" not in answer.text
    assert parse_message(answer.text)["scene"]["elements"] == []  # ty: ignore[not-subscriptable]
    assert client.get("/api/v1/slots/3/revisions").json() == {"revisions": []}


def test_a_long_message_is_parsed_and_applied(client: TestClient) -> None:
    # Longer than what is parsed on the event loop itself.
    text = "x" * (2 * collab._PARSE_INLINE_CHARACTERS)
    drawn = element("a", 1, type="text", text=text)
    with (
        client.websocket_connect("/collab?slot=1") as one,
        client.websocket_connect("/collab?slot=1") as two,
    ):
        hello(one), hello(two)
        received(one)

        one.send_json({"type": "elements", "epoch": 1, "elements": [drawn]})

        assert received(two)["elements"] == [drawn]


def test_without_a_token_configured_everyone_edits(client: TestClient) -> None:
    """T-008: with no access codes, both clients can edit."""
    with (
        client.websocket_connect("/collab?slot=1") as one,
        client.websocket_connect("/collab?slot=1") as two,
    ):
        assert hello(one, edit_pass="")[0]["viewOnly"] is False
        assert hello(two, edit_pass="anything")[0]["viewOnly"] is False
        received(one)

        one.send_json({"type": "elements", "epoch": 1, "elements": [element("a", 1)]})
        two.send_json({"type": "elements", "epoch": 1, "elements": [element("b", 1)]})

        assert received(two)["elements"] == [element("a", 1)]
        assert received(one)["elements"] == [element("b", 1)]
    assert client.patch("/api/v1/slots/1", json={"title": "Open"}).status_code == 200


def test_with_a_token_a_client_without_it_watches_and_cannot_edit(gated: TestClient) -> None:
    """T-008: the scene and the title, with ``edit_token`` set."""
    with (
        gated.websocket_connect("/collab?slot=4") as editor,
        gated.websocket_connect("/collab?slot=4") as viewer,
        gated.websocket_connect("/collab?slot=4") as guesser,
    ):
        assert hello(editor, "Guest1", PASS)[0]["viewOnly"] is False
        assert hello(viewer, "Staff2")[0]["viewOnly"] is True
        assert hello(guesser, "Guest3", "correct-horse")[0]["viewOnly"] is True
        for _ in range(2):
            received(editor)
        received(viewer)

        # The viewer sees a live edit.
        editor.send_json({"type": "elements", "epoch": 1, "elements": [element("a", 1)]})
        assert received(viewer)["elements"] == [element("a", 1)]
        assert received(guesser)["elements"] == [element("a", 1)]

        # It cannot change an element.
        for socket in (viewer, guesser):
            socket.send_json({"type": "elements", "epoch": 1, "elements": [element("a", 2)]})
            assert received(socket)["error"] == "view_only"

        # It cannot change the title. A client that has a pass can.
        for headers in ({}, {PASS_HEADER: "correct-horse"}, {PASS_HEADER: ""}):
            refused = gated.patch("/api/v1/slots/4", json={"title": "Mine"}, headers=headers)
            assert refused.status_code == 403
            assert refused.json() == {
                "error": "view_only",
                "message": "Editing needs an access code.",
            }
        assert gated.get("/api/v1/slots/4").json()["title"] == "Workspace 4"
        changed = gated.patch(
            "/api/v1/slots/4", json={"title": "Core"}, headers={PASS_HEADER: PASS}
        )
        assert changed.status_code == 200

        # The editor was sent the title and nothing else: the refused elements went nowhere.
        assert received(editor) == {"type": "slot", "slot": 4, "title": "Core"}
        assert received(viewer) == {"type": "slot", "slot": 4, "title": "Core"}

        # A viewer still has a name of its own.
        viewer.send_json({"type": "rename", "displayName": "ada"})
        assert received(editor)["displayName"] == "Ada"

    with gated.websocket_connect("/collab?slot=4") as later:
        assert hello(later)[1]["elements"] == [element("a", 1)]


def test_the_token_is_never_sent_to_a_socket(gated: TestClient) -> None:
    with (
        gated.websocket_connect("/collab?slot=1") as editor,
        gated.websocket_connect("/collab?slot=1") as viewer,
    ):
        sent = [*hello(editor, "Guest1", PASS), *hello(viewer, "Staff2"), received(editor)]

    assert PASS not in json.dumps(sent)


def test_a_title_change_is_stored_and_sent_to_the_slots_room(client: TestClient) -> None:
    """T-016, at the socket."""
    with (
        client.websocket_connect("/collab?slot=4") as watcher,
        client.websocket_connect("/collab?slot=5") as elsewhere,
    ):
        hello(watcher), hello(elsewhere)

        response = client.patch("/api/v1/slots/4", json={"title": "  Core network  "})

        assert response.status_code == 200
        assert response.json() == client.get("/api/v1/slots/4").json()
        assert response.json()["title"] == "Core network"
        assert received(watcher) == {"type": "slot", "slot": 4, "title": "Core network"}
        titles = [slot["title"] for slot in client.get("/api/v1/slots").json()["slots"]]
        assert titles[3:5] == ["Core network", "Workspace 5"]
        # Slot 5 was not told: the next thing it is sent is its own rename.
        elsewhere.send_json({"type": "rename", "displayName": "ada"})
        assert received(elsewhere)["type"] == "presence"

    with client.websocket_connect("/collab?slot=4") as later:
        assert hello(later)[0]["title"] == "Core network"


def test_a_title_can_change_before_anyone_has_opened_the_slot(client: TestClient) -> None:
    assert client.patch("/api/v1/slots/6", json={"title": "Lab"}).json()["title"] == "Lab"

    with client.websocket_connect("/collab?slot=6") as socket:
        assert hello(socket)[0]["title"] == "Lab"


@pytest.mark.parametrize(
    ("sent", "stored"),
    [
        ("Core", "Core"),
        ("  padded\t", "padded"),
        ("x" * 80, "x" * 80),
        (" " + "x" * 80 + " ", "x" * 80),
        ("Réseau cœur ✓", "Réseau cœur ✓"),
        ("😀" * 80, "😀" * 80),
        ("<b>bold</b>", "<b>bold</b>"),
    ],
)
def test_a_title_is_trimmed_and_stored(client: TestClient, sent: str, stored: str) -> None:
    response = client.patch("/api/v1/slots/2", json={"title": sent})

    assert response.status_code == 200
    assert response.json()["title"] == stored
    assert client.get("/api/v1/slots/2").json()["title"] == stored


@pytest.mark.parametrize(
    "title",
    ["", "   ", "x" * 81, "two\nlines", "tab\tinside", "nul\x00", None, 7, ["Core"], {"a": 1}],
)
def test_a_title_that_is_not_usable_is_refused(client: TestClient, title: object) -> None:
    response = client.patch("/api/v1/slots/2", json={"title": title})

    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_title",
        "message": "A title is 1 to 80 characters on one line.",
    }
    assert client.get("/api/v1/slots/2").json()["title"] == "Workspace 2"


def test_half_a_surrogate_pair_is_not_a_title(client: TestClient) -> None:
    # JSON can carry it, and SQLite cannot store it.
    response = client.patch(
        "/api/v1/slots/2",
        content=b'{"title": "bad \\ud800 text"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_title"


@pytest.mark.parametrize("body", [b"", b"Core", b'"Core"', b"[]", b"{", b"null", b'{"title": NaN'])
def test_a_title_body_that_is_not_a_json_object_is_refused(client: TestClient, body: bytes) -> None:
    response = client.patch("/api/v1/slots/2", content=body)

    assert response.status_code == 400
    assert response.json() == {"error": "bad_request", "message": "The body is a JSON object."}


def test_a_title_body_without_a_title_is_refused(client: TestClient) -> None:
    assert client.patch("/api/v1/slots/2", json={"name": "Core"}).status_code == 422


def test_a_title_body_that_is_too_large_is_refused(client: TestClient) -> None:
    response = client.patch("/api/v1/slots/2", json={"title": "x", "padding": "y" * 5000})

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"
    assert client.get("/api/v1/slots/2").json()["title"] == "Workspace 2"


@pytest.mark.parametrize("slot", ["0", "10", "01", "abc"])
def test_a_title_for_no_slot_is_refused(client: TestClient, slot: str) -> None:
    response = client.patch(f"/api/v1/slots/{slot}", json={"title": "Core"})

    assert response.status_code == 404
    assert response.json() == INVALID_SLOT


def test_slots_still_have_no_create_or_delete_route(client: TestClient) -> None:
    """T-016: a title can change, and that is all."""
    for method, path in (
        ("POST", "/api/v1/slots"),
        ("PUT", "/api/v1/slots/4"),
        ("DELETE", "/api/v1/slots/4"),
        ("POST", "/api/v1/slots/4"),
    ):
        response = client.request(method, path, json={"title": "Core"})
        assert response.status_code == 405, (method, path)
        assert response.json()["error"] == "method_not_allowed"
    allowed = client.request("DELETE", "/api/v1/slots/4").headers["allow"]
    assert sorted(allowed.split(", ")) == ["GET", "PATCH"]
    assert len(client.get("/api/v1/slots").json()["slots"]) == 9


def test_no_response_of_a_title_change_sets_a_cookie(gated: TestClient) -> None:
    for headers in ({}, {PASS_HEADER: PASS}):
        response = gated.patch("/api/v1/slots/1", json={"title": "Core"}, headers=headers)
        assert "set-cookie" not in response.headers
        assert PASS not in response.text


def test_the_last_title_stored_is_the_last_one_sent(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two changes at once reach the database and the room in one order."""
    store = repository.rename_slot

    def slow_first(slot: int, title: str) -> Slot:
        stored = store(slot, title)
        # The first change is stored first, and its answer is held up until
        # well after the second change has been stored and answered.
        if title == "First":
            time.sleep(0.3)
        return stored

    monkeypatch.setattr(repository, "rename_slot", slow_first)

    async def scenario() -> tuple[str, list[str]]:
        rooms = Rooms(repository, make_settings(), AssetStore(Path("unused")))
        room = await rooms.room(7)
        sent: list[str] = []
        room.retitle = sent.append  # ty: ignore[invalid-assignment]
        first = asyncio.create_task(rooms.retitle(7, "First"))
        await asyncio.sleep(0.1)
        await asyncio.gather(first, rooms.retitle(7, "Second"))
        return repository.get_slot(7).title, sent

    stored, sent = asyncio.run(scenario())

    assert stored == "Second"
    assert sent == ["First", "Second"]


def test_a_room_is_loaded_once(repository: Repository) -> None:
    async def scenario() -> set[int]:
        rooms = Rooms(repository, make_settings(), AssetStore(Path("unused")))
        return {id(room) for room in await asyncio.gather(*(rooms.room(2) for _ in range(10)))}

    assert len(asyncio.run(scenario())) == 1


def test_an_outbox_hands_out_what_was_put_in_order() -> None:
    async def scenario() -> list[str | None]:
        outbox = _Outbox()
        outbox.put("one")
        outbox.put("two")
        return [await outbox.get(), await outbox.get()]

    assert asyncio.run(scenario()) == ["one", "two"]


def test_an_outbox_waits_for_the_next_text() -> None:
    async def scenario() -> str | None:
        outbox = _Outbox()
        waiting = asyncio.create_task(outbox.get())
        await asyncio.sleep(0)
        assert not waiting.done()
        outbox.put("late")
        return await waiting

    assert asyncio.run(scenario()) == "late"


def test_an_outbox_that_is_not_read_overflows_and_keeps_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collab, "OUTBOX_MESSAGES", 3)

    async def scenario() -> tuple[bool, str | None]:
        outbox = _Outbox()
        for number in range(3):
            outbox.put(str(number))
        assert not outbox.overflowed
        outbox.put("one too many")
        outbox.put("ignored")
        return outbox.overflowed, await outbox.get()

    assert asyncio.run(scenario()) == (True, None)


def test_an_outbox_takes_one_text_of_any_size_and_overflows_on_the_bytes_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collab, "OUTBOX_BYTES", 10)

    async def scenario() -> tuple[str | None, bool, bool]:
        outbox = _Outbox()
        outbox.put("a scene larger than the limit")
        first = await outbox.get()
        outbox.put("12345")
        outbox.put("67890")
        fits = outbox.overflowed
        outbox.put("x")
        return first, fits, outbox.overflowed

    assert asyncio.run(scenario()) == ("a scene larger than the limit", False, True)


def test_a_browser_that_falls_behind_is_disconnected_and_the_others_go_on(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collab, "OUTBOX_MESSAGES", 3)
    with (
        client.websocket_connect("/collab?slot=1") as slow,
        client.websocket_connect("/collab?slot=1") as watcher,
    ):
        hello(slow), hello(watcher)
        received(slow)
        room = client.app.state.rooms._rooms[1]  # ty: ignore[missing-attribute]
        behind = next(iter(room.connections.values()))
        put = behind.deliver
        # More at once than its outbox holds, as when a browser has stopped reading.
        behind.deliver = lambda text: [put(text) for _ in range(4)]

        watcher.send_json({"type": "rename", "displayName": "ada"})

        with pytest.raises(WebSocketDisconnect) as closed:
            received(slow)
        assert closed.value.code == collab.TRY_AGAIN_LATER
        # The other browser got its answer, was told who left, and is still served.
        assert received(watcher)["displayName"] == "Ada"
        assert received(watcher) == {"type": "presence-end", "connectionId": behind.id}
        watcher.send_json({"type": "rename", "displayName": "bea"})
        assert received(watcher)["displayName"] == "Bea"
        assert list(room.connections) != [behind.id]
        assert len(room.connections) == 1


# From a running process: uvicorn, and the WebSocket protocol it speaks.


def test_a_running_server_serves_the_socket(tmp_path: Path) -> None:
    with running_segl(tmp_path) as server:
        origin = f"http://127.0.0.1:{server.port}"
        with (
            server.socket("/collab?slot=3", origin=origin) as one,
            server.socket("/collab?slot=3") as two,
        ):
            # T-012: the handshake sets no cookie.
            assert one.response is not None
            assert one.response.status_code == 101
            assert "Set-Cookie" not in one.response.headers
            welcome, scene = say_hello(one, "Guest1")
            assert (welcome["slot"], welcome["title"], scene["elements"]) == (3, "Workspace 3", [])
            assert len(say_hello(two, "Staff2")[0]["participants"]) == 2
            assert next_message(one)["displayName"] == "Staff2"

            drawn = element("a", 1, type="rectangle", index="a0")
            one.send(json.dumps({"type": "elements", "epoch": 1, "elements": [drawn]}))
            assert next_message(two) == {"type": "elements", "epoch": 1, "elements": [drawn]}

            changed = server.patch("/api/v1/slots/3", {"title": "Core"}, {"Origin": origin})
            assert changed.status == 200
            assert next_message(one) == {"type": "slot", "slot": 3, "title": "Core"}
            assert next_message(two) == {"type": "slot", "slot": 3, "title": "Core"}

        # The log has the slot, and neither the scene nor a name.
        log = server.log()
        assert "/collab?slot=3" in log
        assert "rectangle" not in log
        assert "Guest1" not in log


def test_a_running_server_refuses_a_socket_from_another_site(tmp_path: Path) -> None:
    """T-012: a WebSocket upgrade whose Origin does not match Host is refused."""
    with running_segl(tmp_path) as server:
        with pytest.raises(InvalidStatus) as refused:
            server.socket("/collab?slot=1", origin="https://evil.example")
        assert refused.value.response.status_code == 403
        assert json.loads(refused.value.response.body or b"")["error"] == "bad_origin"
        assert "Set-Cookie" not in refused.value.response.headers

        with pytest.raises(InvalidStatus) as missing:
            server.socket("/collab?slot=0")
        assert missing.value.response.status_code == 404
        assert json.loads(missing.value.response.body or b"") == INVALID_SLOT

        mutation = server.patch(
            "/api/v1/slots/1", {"title": "x"}, {"Origin": "https://evil.example"}
        )
        assert (mutation.status, mutation.json()["error"]) == (403, "bad_origin")
        assert server.get("/api/v1/slots/1").json()["title"] == "Workspace 1"


def test_a_running_server_takes_a_message_up_to_max_scene_bytes_and_no_larger(
    tmp_path: Path,
) -> None:
    with (
        running_segl(tmp_path, "max_scene_bytes = 200000\n") as server,
        server.socket("/collab?slot=1") as one,
        server.socket("/collab?slot=1") as two,
    ):
        say_hello(one), say_hello(two)
        next_message(one)
        fits = element("a", 1, type="text", text="x" * 150_000)
        one.send(json.dumps({"type": "elements", "epoch": 1, "elements": [fits]}))
        assert next_message(two)["elements"] == [fits]

        too_large = element("b", 1, type="text", text="x" * 250_000)
        one.send(json.dumps({"type": "elements", "epoch": 1, "elements": [too_large]}))
        with pytest.raises(ConnectionClosed) as closed:
            next_message(one)
        # 1009 is "message too big".
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 1009
        assert next_message(two)["type"] == "presence-end"


def test_with_a_token_a_running_server_gates_the_scene_and_the_title(tmp_path: Path) -> None:
    """T-008 from a running process, with the codes in the TOML file."""
    with running_segl(tmp_path, GATED_TOML) as server:
        with server.socket("/collab?slot=2") as editor, server.socket("/collab?slot=2") as viewer:
            assert say_hello(editor, "Guest1", edit_pass=PASS)[0]["viewOnly"] is False
            assert say_hello(viewer, "Staff2")[0]["viewOnly"] is True
            next_message(editor)

            viewer.send(json.dumps({"type": "elements", "epoch": 1, "elements": [element("a", 1)]}))
            assert next_message(viewer)["error"] == "view_only"
            editor.send(json.dumps({"type": "elements", "epoch": 1, "elements": [element("b", 1)]}))
            assert next_message(viewer)["elements"] == [element("b", 1)]

            assert server.patch("/api/v1/slots/2", {"title": "No"}).json()["error"] == "view_only"
            allowed = server.patch("/api/v1/slots/2", {"title": "Yes"}, {PASS_HEADER: PASS})
            assert allowed.json()["title"] == "Yes"
            # The editor heard the title and never the viewer's element.
            assert next_message(editor) == {"type": "slot", "slot": 2, "title": "Yes"}
        # The pass is in no log line, and neither is a code or the secret.
        assert PASS not in server.log()
        assert_no_secrets(server.log())


# Through nginx, with the files in deploy/nginx/: the WebSocket half of T-013.


def test_two_sockets_sync_through_nginx_at_board_and_at_a_host_root(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    with running_mount(tools, certificate, tmp_path) as mount:
        for site, prefix, slot in ((BOARD_SITE, "/board", 1), (ROOT_SITE, "", 2)):
            origin = mount.origin(site)
            path = f"{prefix}/collab?slot={slot}"
            with (
                mount.socket(site, path, origin=origin) as one,
                mount.socket(site, path, origin=origin) as two,
            ):
                assert one.response is not None
                assert "Set-Cookie" not in one.response.headers
                assert say_hello(one, "Guest1")[0]["slot"] == slot
                assert len(say_hello(two, "Staff2")[0]["participants"]) == 2
                assert next_message(one)["displayName"] == "Staff2"

                drawn = element(f"through-{slot}", 1, type="rectangle", index="a0")
                one.send(json.dumps({"type": "elements", "epoch": 1, "elements": [drawn]}))
                assert next_message(two)["elements"] == [drawn]

                # The title route, through the same mount, reaches both sockets.
                changed = mount.patch(
                    site, f"{prefix}/api/v1/slots/{slot}", {"title": "Core"}, {"Origin": origin}
                )
                assert changed.status == 200
                assert "Set-Cookie" not in changed.headers
                assert next_message(one) == {"type": "slot", "slot": slot, "title": "Core"}
                assert next_message(two) == {"type": "slot", "slot": slot, "title": "Core"}

        # segl saw the path without /board.
        mount.segl.logged_line("/collab?slot=1")
        assert "/board/collab" not in mount.segl.log()


def test_nginx_passes_the_host_with_its_port_so_the_origin_check_holds(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    """A page on another site, or on another port of this one, is refused through nginx."""
    with running_mount(tools, certificate, tmp_path) as mount:
        for site, prefix in ((BOARD_SITE, "/board"), (ROOT_SITE, "")):
            for origin in (
                "https://evil.example",
                f"https://{site}",
                f"http://{site}:{mount.https_port}".replace("http://", "https://evil."),
                f"https://{site}:{mount.https_port + 1}",
            ):
                with pytest.raises(InvalidStatus) as refused:
                    mount.socket(site, f"{prefix}/collab?slot=1", origin=origin)
                assert refused.value.response.status_code == 403, origin
                assert json.loads(refused.value.response.body or b"")["error"] == "bad_origin"

                mutation = mount.patch(
                    site, f"{prefix}/api/v1/slots/1", {"title": "x"}, {"Origin": origin}
                )
                assert (mutation.status, mutation.json()["error"]) == (403, "bad_origin")
                named = mount.post(site, f"{prefix}/api/v1/display-name", {"Origin": origin})
                assert named.json()["error"] == "bad_origin"
            assert mount.get(site, f"{prefix}/api/v1/slots/1").json()["title"] == "Workspace 1"

            # The page's own origin, with the port the site listens on.
            own = mount.origin(site)
            assert mount.post(site, f"{prefix}/api/v1/display-name", {"Origin": own}).status == 200
