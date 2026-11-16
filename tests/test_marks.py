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

"""A scene sent once (D2-037): the scene route's mark, and ``hello`` handing it
back, in process, from a running ``segl`` process, and through nginx.

``tests/test_room.py`` covers what a room sends for a mark. These tests cover
the rule between the route and the room: a mark never says that the head the
route returned holds more than it does. Each test holds a write in its worker
thread, as ``tests/test_saver.py`` does, at the moment the rule is about.
"""

import json
import threading
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from harness import (
    BOARD_SITE,
    EMPTY_SCENE,
    ROOT_SITE,
    MarkOf,
    NginxTools,
    make_settings,
    next_message,
    running_mount,
    running_segl,
    say_hello,
)
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from segl.app import create_app
from segl.repository import Repository

SLOT = 2
SCENE = f"/api/v1/slots/{SLOT}/scene"
COLLAB = f"/collab?slot={SLOT}"
# Long enough that a test is over first: the head stays where it is.
NEVER = 3600.0


def element(identifier: str, version: int = 1, **more: object) -> dict[str, Any]:
    return {"id": identifier, "version": version, "versionNonce": 1, **more}


A = element("a", index="a0")
B = element("b", index="a1")
C = element("c", index="a2")


def application(repository: Repository, **settings: Any) -> TestClient:
    settings.setdefault("head_flush_seconds", 0.01)
    return TestClient(create_app(make_settings(**settings), repository))


@pytest.fixture
def client(repository: Repository) -> Iterator[TestClient]:
    with application(repository) as client:
        yield client


def received(socket: WebSocketTestSession, seconds: float = 5.0) -> dict[str, Any]:
    """Return the next message, and fail the test rather than wait for ever."""

    async def receive() -> Any:
        with anyio.fail_after(seconds):
            return await socket._send_rx.receive()

    message = socket.portal.call(receive)
    socket._raise_on_close(message)
    return json.loads(message["text"])


def hello(socket: WebSocketTestSession, mark: str | None = None) -> dict[str, Any]:
    """Say hello, and return the scene that follows the welcome."""
    socket.send_json(
        {"type": "hello", "clientId": "client-1", "displayName": "Guest1", "mark": mark}
    )
    assert received(socket)["type"] == "welcome"
    scene = received(socket)
    assert scene["type"] == "scene"
    return scene


def draw(socket: WebSocketTestSession, seq: int, *elements: dict[str, Any]) -> None:
    """Draw, and wait until the head holds it."""
    socket.send_json({"type": "elements", "epoch": 1, "elements": list(elements), "seq": seq})
    while (message := received(socket))["type"] != "saved":
        pass
    assert message["seq"] == seq


class Hold:
    """Hold one call of a repository method in its worker thread, after it ran."""

    def __init__(self, repository: Repository, name: str) -> None:
        self.entered = threading.Event()
        self.gate = threading.Event()
        self.armed = False
        self.thread: threading.Thread | None = None
        real: Callable[..., Any] = getattr(repository, name)

        def held(*arguments: Any, **options: Any) -> Any:
            result = real(*arguments, **options)
            if self.armed:
                self.armed = False
                self.entered.set()
                # `until_done` opens the gate first. This is the backstop.
                self.gate.wait(10)
            return result

        setattr(repository, name, held)

    def wait(self) -> None:
        assert self.entered.wait(5), "the held call never came"

    def request(self, call: Callable[[], Any]) -> list[Any]:
        """Start a request in a thread of its own, since the test holds it halfway."""
        result: list[Any] = []
        self.thread = threading.Thread(target=lambda: result.append(call()), daemon=True)
        self.thread.start()
        return result

    def release(self) -> None:
        """Let the held call go on, and wait for the request that made it."""
        self.gate.set()
        if self.thread is not None:
            self.thread.join(5)

    @contextmanager
    def until_done(self) -> Generator[None]:
        """Release on the way out, whatever happened.

        The test client does not wait for a request in flight when it stops.
        Without this, a test that failed while a call was held would hang.
        """
        try:
            yield
        finally:
            self.release()


def test_a_slot_nobody_opened_has_the_mark_of_its_head_at_count_0(client: TestClient) -> None:
    answer = client.get(SCENE).json()

    assert answer["mark"] == MarkOf(1, 0)
    with client.websocket_connect(COLLAB) as socket:
        # The room starts from that head: a quiet slot.
        assert hello(socket, answer["mark"]) == {
            "type": "scene",
            "epoch": 1,
            "whole": False,
            "mark": answer["mark"],
            "elements": [],
            "files": [],
        }


def test_a_page_that_hands_the_routes_mark_back_gets_only_what_changed_since(
    client: TestClient,
) -> None:
    with client.websocket_connect(COLLAB) as one:
        hello(one)
        draw(one, 1, A)
        answer = client.get(SCENE).json()
        assert (answer["mark"], answer["scene"]["elements"]) == (MarkOf(1, 1), [A])

        with client.websocket_connect(COLLAB) as two:
            assert hello(two, answer["mark"])["elements"] == []
        draw(one, 2, B)
        with client.websocket_connect(COLLAB) as three:
            scene = hello(three, answer["mark"])
            assert (scene["whole"], scene["elements"], scene["mark"]) == (False, [B], MarkOf(1, 2))


def test_a_head_a_flush_behind_the_room_gets_the_rest_over_the_socket(
    repository: Repository,
) -> None:
    with (
        application(repository, head_flush_seconds=NEVER) as client,
        client.websocket_connect(COLLAB) as one,
        client.websocket_connect(COLLAB) as watcher,
    ):
        hello(one)
        hello(watcher)
        one.send_json({"type": "elements", "epoch": 1, "elements": [A]})
        while received(watcher)["type"] != "elements":
            pass
        # The room has it, and the head does not yet.
        answer = client.get(SCENE).json()
        assert (answer["mark"], answer["scene"]["elements"]) == (MarkOf(1, 0), [])

        with client.websocket_connect(COLLAB) as two:
            assert hello(two, answer["mark"])["elements"] == [A]


def test_while_a_flush_is_written_the_route_hands_out_the_mark_of_the_write_before(
    repository: Repository,
) -> None:
    hold = Hold(repository, "flush_head")
    with (
        application(repository) as client,
        client.websocket_connect(COLLAB) as one,
        hold.until_done(),
    ):
        hello(one)
        draw(one, 1, A)
        hold.armed = True
        one.send_json({"type": "elements", "epoch": 1, "elements": [B], "seq": 2})
        hold.wait()

        # The head on the disk has b. The write has not finished, so the
        # mark does not say so: the copy holds more than its mark.
        answer = client.get(SCENE).json()
        assert (answer["mark"], answer["scene"]["elements"]) == (MarkOf(1, 1), [A, B])
        hold.release()
        while (message := received(one))["type"] != "saved":
            pass
        assert message["seq"] == 2
        assert client.get(SCENE).json()["mark"] == MarkOf(1, 2)

        # The page gets b a second time, which costs a little, and loses nothing.
        with client.websocket_connect(COLLAB) as two:
            assert hello(two, answer["mark"])["elements"] == [B]


def test_a_write_that_ends_while_the_route_reads_the_head_does_not_move_its_mark(
    repository: Repository,
) -> None:
    # The mark is taken before the head is read. The other order would hand
    # out the newer mark with the older head, and the page would never get b.
    hold = Hold(repository, "get_head")
    with (
        application(repository) as client,
        client.websocket_connect(COLLAB) as one,
        hold.until_done(),
    ):
        hello(one)
        draw(one, 1, A)
        # Armed once the room is made, which reads the head too.
        hold.armed = True
        result = hold.request(lambda: client.get(SCENE).json())
        hold.wait()

        draw(one, 2, B)
        hold.release()

        answer = result[0]
        assert (answer["mark"], answer["scene"]["elements"]) == (MarkOf(1, 1), [A])
        with client.websocket_connect(COLLAB) as two:
            assert hello(two, answer["mark"])["elements"] == [B]


@pytest.fixture
def restorable(repository: Repository) -> Repository:
    """A database whose slot 2 has revision 1 with c, and a head with a."""
    repository.flush_head(SLOT, 1, scene_text(C), "Guest1", history_seconds=0)
    repository.flush_head(SLOT, 1, scene_text(A), "Guest1", history_seconds=0)
    return repository


def scene_text(*elements: dict[str, Any]) -> str:
    return json.dumps({**EMPTY_SCENE, "elements": list(elements)}, separators=(",", ":"))


def test_between_a_restores_head_write_and_the_room_the_route_names_the_new_epoch(
    restorable: Repository,
) -> None:
    hold = Hold(restorable, "replace_head")
    with (
        application(restorable) as client,
        client.websocket_connect(COLLAB) as one,
        hold.until_done(),
    ):
        assert hello(one)["elements"] == [A]
        # A flush first: the newest finished write then has a count of its own.
        draw(one, 1, B)
        hold.armed = True
        body = {"revision": 1, "displayName": "Guest1"}
        result = hold.request(lambda: client.post(f"/api/v1/slots/{SLOT}/restore", json=body))
        hold.wait()

        # The head is the restored scene at epoch 2, and the room is still on
        # epoch 1. Count 0 of epoch 2 says no more than the head holds.
        answer = client.get(SCENE).json()
        assert (answer["epoch"], answer["scene"]["elements"]) == (2, [C])
        assert answer["mark"] == MarkOf(2, 0)

        # A page that says hello now is on another epoch than the room: it
        # gets the room's whole scene, and the restored one right after.
        with client.websocket_connect(COLLAB) as early:
            scene = hello(early, answer["mark"])
            assert (scene["whole"], scene["epoch"], scene["elements"]) == (True, 1, [A, B])
            hold.release()
            assert result[0].status_code == 200
            while (message := received(early))["type"] != "scene":
                pass
            assert (message["whole"], message["epoch"], message["elements"]) == (True, 2, [C])

        # One that says hello once the room took the new epoch gets all of it.
        with client.websocket_connect(COLLAB) as late:
            scene = hello(late, answer["mark"])
            assert (scene["whole"], scene["epoch"], scene["elements"]) == (False, 2, [C])


def test_a_mark_of_another_slot_gets_the_whole_scene(client: TestClient) -> None:
    # Each slot's marks have a start of their own, so a mark names one room.
    other = client.get("/api/v1/slots/3/scene").json()["mark"]
    with client.websocket_connect(COLLAB) as socket:
        assert other == MarkOf(1, 0) and other != client.get(SCENE).json()["mark"]
        assert hello(socket, other)["whole"] is True


@pytest.mark.parametrize("mark", [7, True, ["m"], {"m": 1}, "m" * 65])
def test_a_hello_whose_mark_is_not_one_is_refused(client: TestClient, mark: object) -> None:
    with client.websocket_connect(COLLAB) as socket:
        socket.send_json(
            {"type": "hello", "clientId": "client-1", "displayName": None, "mark": mark}
        )
        assert received(socket)["error"] == "bad_message"
        with pytest.raises(WebSocketDisconnect) as closed:
            received(socket)
        assert closed.value.code == 1008


def test_a_mark_from_before_a_restart_gets_the_whole_scene(tmp_path: Path) -> None:
    config = "head_flush_seconds = 0.01\n"
    with running_segl(tmp_path, config) as server:
        with server.socket(COLLAB) as one:
            say_hello(one)
            one.send(json.dumps({"type": "elements", "epoch": 1, "elements": [A], "seq": 1}))
            assert next_message(one)["type"] == "saved"
        before = server.get(SCENE).json()["mark"]
        with server.socket(COLLAB) as two:
            assert say_hello(two, mark=before)[1]["whole"] is False

    with running_segl(tmp_path, config) as server:
        assert server.get(SCENE).json()["mark"] != before
        with server.socket(COLLAB) as three:
            scene = say_hello(three, mark=before)[1]
            assert (scene["whole"], scene["elements"], scene["mark"]) == (True, [A], MarkOf(1, 0))


def test_the_mark_through_nginx_at_board_and_at_a_host_root(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    with running_mount(tools, certificate, tmp_path) as mount:
        for site, prefix, slot in ((BOARD_SITE, "/board", 3), (ROOT_SITE, "", 4)):
            origin = mount.origin(site)
            with mount.socket(site, f"{prefix}/collab?slot={slot}", origin=origin) as one:
                say_hello(one)
                one.send(json.dumps({"type": "elements", "epoch": 1, "elements": [A], "seq": 1}))
                assert next_message(one)["type"] == "saved"

            answer = mount.get(site, f"{prefix}/api/v1/slots/{slot}/scene").json()
            assert (answer["mark"], answer["scene"]["elements"]) == (MarkOf(1, 1), [A])
            with mount.socket(site, f"{prefix}/collab?slot={slot}", origin=origin) as two:
                scene = say_hello(two, mark=answer["mark"])[1]
                assert (scene["whole"], scene["elements"], scene["files"]) == (False, [], [])
