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

"""What is drawn is kept (S-004, S-012): the head flush, ``saved``, the history
rows, and the files of images, at the socket.

In process, and then from ``segl`` processes that are stopped, or killed, and
started again over the same folder (docs/TEST-PLAN.md T-005, T-006, T-007).
``tests/test_saver.py`` covers when a flush happens, and
``web/e2e/durability.spec.ts`` runs the same rows in a browser.
"""

import hashlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from harness import (
    BOARD_SITE,
    EMPTY_SCENE,
    GATED,
    PASS_HEADER,
    NginxTools,
    SeglServer,
    issue_pass,
    make_settings,
    next_message,
    running_mount,
    running_segl,
    say_hello,
)
from starlette.testclient import WebSocketTestSession
from websockets.sync.client import ClientConnection

from segl.app import create_app
from segl.repository import Repository
from segl.room import Connection, Hello

# A pass a segl with ``GATED`` takes, issued as the tests are collected.
PASS = issue_pass()
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
PNG_HASH = hashlib.sha256(PNG).hexdigest()
FILE_ID = "f" * 40
FILE = {"id": FILE_ID, "hash": PNG_HASH, "mimeType": "image/png"}
# Short enough for a test to wait for, and long enough that only a leave, or
# a stop, can be why something was written.
SOON = 0.02
NEVER = 3600


def element(identifier: str, version: int, nonce: int = 1, **more: object) -> dict[str, Any]:
    return {"id": identifier, "version": version, "versionNonce": nonce, **more}


def image(identifier: str = "picture") -> dict[str, Any]:
    return element(identifier, 1, type="image", fileId=FILE_ID, status="pending", index="a5")


def application(repository: Repository, folder: Path, **settings: Any) -> TestClient:
    settings.setdefault("head_flush_seconds", SOON)
    return TestClient(
        create_app(make_settings(assets_dir=folder / "assets", **settings), repository)
    )


@pytest.fixture
def client(repository: Repository, tmp_path: Path) -> Iterator[TestClient]:
    with application(repository, tmp_path) as client:
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
    socket.send_json(
        {"type": "hello", "clientId": "client-1", "displayName": name, "editToken": edit_pass}
    )
    return received(socket), received(socket)


def draw(socket: WebSocketTestSession, seq: int, *elements: dict[str, Any]) -> None:
    socket.send_json({"type": "elements", "epoch": 1, "elements": list(elements), "seq": seq})


def stored_scene(client: TestClient, slot: int) -> dict[str, Any]:
    response = client.get(f"/api/v1/slots/{slot}/scene")
    assert response.status_code == 200
    return response.json()


def test_an_edit_is_answered_with_saved_once_the_head_holds_it(client: TestClient) -> None:
    rectangle = element("a", 1, type="rectangle", index="a0")
    before = stored_scene(client, 2)
    with client.websocket_connect("/collab?slot=2") as socket:
        hello(socket, "Bravo2")

        draw(socket, 1, rectangle)
        saved = received(socket)

        assert saved == {"type": "saved", "epoch": 1, "savedAt": saved["savedAt"], "seq": 1}
        head = stored_scene(client, 2)
        assert head["scene"] == {**EMPTY_SCENE, "elements": [rectangle]}
        assert (head["editorLabel"], head["savedAt"]) == ("Bravo2", saved["savedAt"])
        assert saved["savedAt"] > before["savedAt"]
        # The slot list has the new time too.
        assert client.get("/api/v1/slots/2").json()["savedAt"] == saved["savedAt"]
    # Slot 1 is unchanged.
    assert stored_scene(client, 1)["scene"] == EMPTY_SCENE


def test_the_browser_that_did_not_draw_is_not_told_saved(client: TestClient) -> None:
    with (
        client.websocket_connect("/collab?slot=2") as one,
        client.websocket_connect("/collab?slot=2") as two,
    ):
        hello(one), hello(two)
        received(one)

        draw(one, 1, element("a", 1))

        assert received(one)["type"] == "saved"
        assert received(two)["type"] == "elements"
        # The next thing the other browser hears is its own rename.
        two.send_json({"type": "rename", "displayName": "bea"})
        assert received(two)["type"] == "presence"


def test_a_drawing_is_there_after_everyone_left_and_came_back(
    repository: Repository, tmp_path: Path
) -> None:
    """T-005 at the socket: draw on slot 2, close both, open slot 2 again."""
    rectangle = element("a", 1, type="rectangle", index="a0")
    gone = element("b", 2, type="ellipse", index="a1", isDeleted=True)
    # No flush on a timer here: closing the last socket is what writes.
    with application(repository, tmp_path, head_flush_seconds=NEVER) as client:
        with (
            client.websocket_connect("/collab?slot=2") as one,
            client.websocket_connect("/collab?slot=2") as two,
        ):
            hello(one, "Guest1"), hello(two, "Staff2")
            one.send_json({"type": "elements", "epoch": 1, "elements": [rectangle]})
            two.send_json({"type": "elements", "epoch": 1, "elements": [gone]})
            assert received(two)["elements"] == [rectangle]
            assert stored_scene(client, 2)["scene"]["elements"] == []

        with client.websocket_connect("/collab?slot=2") as later:
            _, scene = hello(later, "Guest3")
            assert scene["elements"] == [rectangle, gone]
        # Closing the first two had written the head, with the deleted element,
        # and a history row, although the newest one could be no older.
        head = stored_scene(client, 2)
        assert head["scene"]["elements"] == [rectangle, gone]
        assert head["editorLabel"] == "Staff2"
        (row,) = repository.list_revisions(2)
        assert (row.revision, row.author_label) == (1, "Staff2")
        assert json.loads(repository.get_revision(2, 1).scene_json) == head["scene"]
        # Slot 1 is unchanged.
        assert stored_scene(client, 1)["scene"] == EMPTY_SCENE
        assert stored_scene(client, 1)["editorLabel"] == "System"
        assert repository.list_revisions(1) == []


def test_stopping_the_application_writes_what_was_drawn(
    repository: Repository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shutdown hook flushes every room, and only then closes the database."""
    closed: list[list[dict[str, Any]]] = []
    close = repository.close

    def closing() -> None:
        # What the database holds at the moment the application closes it.
        closed.append(json.loads(repository.get_head(3).scene_json)["elements"])
        close()

    monkeypatch.setattr(repository, "close", closing)
    client = application(repository, tmp_path, head_flush_seconds=NEVER)

    async def draw() -> None:
        # A connection that is still in the room when segl is told to stop, as
        # a browser left open is. No socket: the test client cannot stop under one.
        room = await client.app.state.rooms.room(3)  # ty: ignore[missing-attribute]
        connection = Connection(lambda text: None, Hello("client-1", "Guest1", ""), view_only=False)
        room.join(connection)
        room.receive(connection, {"type": "elements", "epoch": 1, "elements": [element("a", 1)]})

    with client:
        assert client.portal is not None
        client.portal.call(draw)
        assert stored_scene(client, 3)["scene"]["elements"] == []

    assert closed == [[element("a", 1)]]


def test_a_new_application_over_the_same_database_has_the_scene(
    repository: Repository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restart, in process: the room is built again from the head."""
    # The database outlives the first application, as the file outlives a process.
    monkeypatch.setattr(repository, "close", lambda: None)
    kept = element("a", 3, type="rectangle", index="a0")
    gone = element("b", 2, type="ellipse", index="a1", isDeleted=True)
    with application(repository, tmp_path) as first, first.websocket_connect("/collab?slot=4") as a:
        hello(a)
        draw(a, 1, kept, gone)
        assert received(a)["type"] == "saved"

    with (
        application(repository, tmp_path) as second,
        second.websocket_connect("/collab?slot=4") as b,
    ):
        _, scene = hello(b)
        # With the deleted element: a browser that was away cannot bring it back.
        assert scene["elements"] == [kept, gone]
        draw(b, 1, element("b", 1, type="ellipse", index="a1", isDeleted=False))
        assert received(b)["type"] == "saved"
        assert stored_scene(second, 4)["scene"]["elements"] == [kept, gone]


def test_half_a_surrogate_pair_in_a_scene_is_stored_and_served(client: TestClient) -> None:
    """A browser can send one. The slot must still load afterwards."""
    with client.websocket_connect("/collab?slot=2") as socket:
        hello(socket)
        socket.send_text(
            '{"type":"elements","epoch":1,"seq":1,"elements":'
            '[{"id":"a","version":1,"versionNonce":1,"text":"bad \\ud800 text"}]}'
        )
        assert received(socket)["type"] == "saved"

    response = client.get("/api/v1/slots/2/scene")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert b"bad \\ud800 text" in response.content
    assert response.json()["scene"]["elements"][0]["text"] == "bad \ud800 text"


def test_the_history_keeps_the_newest_revisions_up_to_the_limit(tmp_path: Path) -> None:
    """The caps and intervals of the configuration reach the flush."""
    database = tmp_path / "segl.sqlite"
    with Repository(database, history_limit=3) as repository:
        repository.bootstrap()
        client = application(repository, tmp_path, history_interval_seconds=0.001)
        with client, client.websocket_connect("/collab?slot=5") as socket:
            hello(socket)
            for version in range(1, 7):
                draw(socket, version, element("a", version))
                assert received(socket)["seq"] == version
            rows = repository.list_revisions(5)
            assert [row.revision for row in rows] == [6, 5, 4]


def test_a_scene_over_the_limit_is_refused_and_not_saved(
    repository: Repository, tmp_path: Path
) -> None:
    with (
        application(repository, tmp_path, max_scene_bytes=500) as client,
        client.websocket_connect("/collab?slot=5") as socket,
    ):
        hello(socket)
        draw(socket, 1, element("a", 1, text="x" * 300))
        assert received(socket)["type"] == "saved"

        draw(socket, 2, element("b", 1, text="x" * 300))

        assert received(socket)["error"] == "scene_too_large"
        # A numbered question afterwards is answered: what the room took is saved.
        draw(socket, 3)
        assert received(socket) == {
            "type": "saved",
            "epoch": 1,
            "savedAt": stored_scene(client, 5)["savedAt"],
            "seq": 3,
        }
        assert [each["id"] for each in stored_scene(client, 5)["scene"]["elements"]] == ["a"]


# Images: the bytes are uploaded, and the socket says which file id they are.


def upload(client: TestClient, slot: int = 6, edit_pass: str | None = None) -> str:
    headers = {"Content-Type": "image/png"}
    if edit_pass is not None:
        headers[PASS_HEADER] = edit_pass
    response = client.post(f"/api/v1/slots/{slot}/assets", content=PNG, headers=headers)
    assert response.status_code == 200
    return response.json()["hash"]


def test_an_image_placed_in_one_browser_reaches_the_other_and_a_later_one(
    client: TestClient, repository: Repository
) -> None:
    """T-007 at the socket, up to the restart."""
    with (
        client.websocket_connect("/collab?slot=6") as one,
        client.websocket_connect("/collab?slot=6") as two,
    ):
        hello(one), hello(two)
        received(one)

        # The element goes out at once, as the editor sends it. The bytes follow.
        draw(one, 1, image())
        assert received(two)["elements"] == [image()]
        assert upload(client) == PNG_HASH
        one.send_json({"type": "files", "epoch": 1, "files": [FILE], "seq": 2})

        assert received(two) == {"type": "files", "epoch": 1, "files": [FILE]}
        assert client.get(f"/api/v1/assets/{PNG_HASH}").content == PNG
        # Saved, through the second message: the head and the file list. One
        # flush may have held both messages.
        saved = received(one)
        if saved["seq"] == 1:
            saved = received(one)
        assert (saved["type"], saved["seq"]) == ("saved", 2)
        head = stored_scene(client, 6)
        assert head["scene"]["elements"] == [image()]
        assert head["files"] == [FILE]

        with client.websocket_connect("/collab?slot=6") as later:
            assert hello(later)[1]["files"] == [FILE]
    assert [file.file_id for file in repository.list_files(6)] == [FILE_ID]
    # Another slot has neither the element nor the file.
    assert stored_scene(client, 7)["files"] == []


def test_a_file_no_element_names_is_not_in_a_scenes_file_list(client: TestClient) -> None:
    with client.websocket_connect("/collab?slot=6") as socket:
        hello(socket)
        upload(client)
        socket.send_json({"type": "files", "epoch": 1, "files": [FILE], "seq": 1})
        assert received(socket)["type"] == "saved"

        assert stored_scene(client, 6)["files"] == []
        # Once an element names it, it is listed.
        draw(socket, 2, image())
        assert received(socket)["seq"] == 2
        assert stored_scene(client, 6)["files"] == [FILE]


def test_a_file_that_was_not_uploaded_cannot_be_named(client: TestClient) -> None:
    with (
        client.websocket_connect("/collab?slot=6") as one,
        client.websocket_connect("/collab?slot=6") as two,
    ):
        hello(one), hello(two)
        received(one)

        one.send_json({"type": "files", "epoch": 1, "files": [FILE], "seq": 1})

        assert received(one)["error"] == "unknown_file"
        # Nobody was told, and after the upload the same message is taken.
        upload(client)
        one.send_json({"type": "files", "epoch": 1, "files": [FILE], "seq": 2})
        assert received(two)["type"] == "files"
        assert received(one) == {
            "type": "saved",
            "epoch": 1,
            "savedAt": stored_scene(client, 6)["savedAt"],
            "seq": 2,
        }


def test_with_a_token_a_viewer_gets_the_files_and_cannot_name_one(
    repository: Repository, tmp_path: Path
) -> None:
    """S-008: asset writes need a pass, at the route and on the socket."""
    with (
        application(repository, tmp_path, **GATED) as client,
        client.websocket_connect("/collab?slot=6") as editor,
        client.websocket_connect("/collab?slot=6") as viewer,
    ):
        hello(editor, "Guest1", PASS), hello(viewer, "Staff2")
        received(editor)
        refused = client.post(
            "/api/v1/slots/6/assets", content=PNG, headers={"Content-Type": "image/png"}
        )
        assert refused.json()["error"] == "view_only"
        upload(client, edit_pass=PASS)

        viewer.send_json({"type": "files", "epoch": 1, "files": [FILE]})
        assert received(viewer)["error"] == "view_only"

        editor.send_json({"type": "files", "epoch": 1, "files": [FILE]})
        assert received(viewer) == {"type": "files", "epoch": 1, "files": [FILE]}
        # A viewer fetches the bytes without a pass.
        assert client.get(f"/api/v1/assets/{PNG_HASH}").content == PNG


# From running processes, stopped or killed, and started again on the same folder.


def numbered(socket: ClientConnection, seq: int, **message: Any) -> None:
    socket.send(json.dumps({"epoch": 1, "seq": seq, **message}))


def wait_for_saved(socket: ClientConnection, seq: int) -> dict[str, Any]:
    """Read until the ``saved`` that covers message ``seq``."""
    while True:
        message = next_message(socket)
        if message["type"] == "saved" and message["seq"] >= seq:
            return message


def slot_scene(server: SeglServer, slot: int) -> dict[str, Any]:
    reply = server.get(f"/api/v1/slots/{slot}/scene")
    assert reply.status == 200
    return reply.json()


def test_a_killed_process_comes_back_with_the_scene_it_called_saved(tmp_path: Path) -> None:
    """T-006: after ``saved``, kill the process and start it. The head scene matches."""
    rectangle = element("a", 1, type="rectangle", index="a0", x=10.5)
    moved = element("a", 2, type="rectangle", index="a0", x=40.5)
    gone = element("b", 2, type="ellipse", index="a1", isDeleted=True)
    with (
        running_segl(tmp_path, "head_flush_seconds = 0.05\n") as server,
        server.socket("/collab?slot=2") as socket,
    ):
        say_hello(socket, "Bravo2")
        numbered(socket, 1, type="elements", elements=[rectangle])
        numbered(socket, 2, type="elements", elements=[moved, gone])
        saved = wait_for_saved(socket, 2)
        before = slot_scene(server, 2)
        assert before["scene"]["elements"] == [moved, gone]
        assert before["savedAt"] == saved["savedAt"]

        # No SIGTERM, so no flush on the way out and no close of the database.
        server.kill()

    assert (tmp_path / "segl.sqlite-wal").exists()
    with running_segl(tmp_path) as again:
        after = slot_scene(again, 2)
        assert after == before
        assert after["editorLabel"] == "Bravo2"
        # Slot 1 is as it was made.
        assert slot_scene(again, 1)["scene"] == EMPTY_SCENE
        # A browser that connects is sent the same scene, deleted element included.
        with again.socket("/collab?slot=2") as socket:
            _, scene = say_hello(socket)
            assert scene["elements"] == [moved, gone]


def test_a_stopped_process_writes_what_it_had_not_yet_flushed(tmp_path: Path) -> None:
    """SIGTERM under an open socket, with a flush interval that never comes."""
    drawn = element("a", 1, type="rectangle", index="a0")
    with (
        running_segl(tmp_path, f"head_flush_seconds = {NEVER}\n") as server,
        server.socket("/collab?slot=3") as one,
        server.socket("/collab?slot=3") as two,
    ):
        say_hello(one, "Guest1"), say_hello(two, "Staff2")
        next_message(one)
        numbered(one, 1, type="elements", elements=[drawn])
        assert next_message(two)["elements"] == [drawn]
        # Not written yet: the other browser has it, and the head does not.
        assert slot_scene(server, 3)["scene"]["elements"] == []

    # The stop wrote it, and closed the database into its one file.
    assert sorted(path.name for path in tmp_path.glob("segl.sqlite*")) == ["segl.sqlite"]
    with Repository(tmp_path / "segl.sqlite") as stored:
        head = stored.get_head(3)
        assert json.loads(head.scene_json)["elements"] == [drawn]
        assert head.editor_label == "Guest1"
        # With a history row, as when the last browser leaves.
        assert [row.revision for row in stored.list_revisions(3)] == [1]
    with running_segl(tmp_path) as again:
        assert slot_scene(again, 3)["scene"]["elements"] == [drawn]


def test_an_image_is_there_after_the_process_is_killed_and_started(tmp_path: Path) -> None:
    """T-007 from a running process: reach saved, restart, load the slot afresh."""
    with (
        running_segl(tmp_path, "head_flush_seconds = 0.05\n") as server,
        server.socket("/collab?slot=6") as one,
        server.socket("/collab?slot=6") as two,
    ):
        origin = f"http://127.0.0.1:{server.port}"
        say_hello(one), say_hello(two)
        next_message(one)
        numbered(one, 1, type="elements", elements=[image()])
        stored = server.post(
            "/api/v1/slots/6/assets", {"Content-Type": "image/png", "Origin": origin}, PNG
        )
        assert stored.status == 200
        assert "Set-Cookie" not in stored.headers
        numbered(one, 2, type="files", files=[{**FILE, "hash": stored.json()["hash"]}])
        # The browser that was already open is told, without reloading.
        assert next_message(two)["elements"] == [image()]
        assert next_message(two) == {"type": "files", "epoch": 1, "files": [FILE]}
        wait_for_saved(one, 2)

        server.kill()

    assert (tmp_path / "assets" / PNG_HASH).read_bytes() == PNG
    with running_segl(tmp_path) as again:
        head = slot_scene(again, 6)
        assert head["scene"]["elements"] == [image()]
        assert head["files"] == [FILE]
        fetched = again.get(f"/api/v1/assets/{PNG_HASH}")
        assert (fetched.status, fetched.body) == (200, PNG)
        assert "Set-Cookie" not in fetched.headers
        with again.socket("/collab?slot=6") as fresh:
            assert say_hello(fresh)[1]["files"] == [FILE]
        # The log has the paths and the sizes, and not the bytes or the scene.
        assert "picture" not in again.log()


def test_an_edit_that_was_not_yet_saved_can_be_lost_by_a_kill(tmp_path: Path) -> None:
    """The boundary: what was only sent on to the others is not on the disk."""
    with (
        running_segl(tmp_path, f"head_flush_seconds = {NEVER}\n") as server,
        server.socket("/collab?slot=2") as one,
        server.socket("/collab?slot=2") as two,
    ):
        say_hello(one), say_hello(two)
        next_message(one)
        numbered(one, 1, type="elements", elements=[element("a", 1)])
        assert next_message(two)["type"] == "elements"
        # Longer than the default flush interval: the one in the TOML file is
        # the one that counts, and it has not come.
        time.sleep(0.6)
        server.kill()

    with running_segl(tmp_path) as again:
        assert slot_scene(again, 2)["scene"] == EMPTY_SCENE


def test_a_folder_segl_cannot_write_uploads_to_stops_it_at_startup(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the folder should be", encoding="utf-8")

    with pytest.raises(AssertionError, match="cannot store uploaded files in") as stopped:
        running_segl(tmp_path / "segl", f'assets_dir = "{blocked / "assets"}"\n').__enter__()

    assert "Traceback" not in str(stopped.value)


def test_a_started_process_makes_the_folder_for_uploaded_files(tmp_path: Path) -> None:
    with running_segl(tmp_path):
        assert (tmp_path / "assets").is_dir()
        assert os.listdir(tmp_path / "assets") == []


# Through nginx: the same messages over /board/collab, and the upload beside them.


def test_an_image_syncs_and_is_saved_through_nginx(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    with running_mount(tools, certificate, tmp_path, "head_flush_seconds = 0.05\n") as mount:
        origin = mount.origin(BOARD_SITE)
        with (
            mount.socket(BOARD_SITE, "/board/collab?slot=6", origin=origin) as one,
            mount.socket(BOARD_SITE, "/board/collab?slot=6", origin=origin) as two,
        ):
            say_hello(one), say_hello(two)
            next_message(one)
            numbered(one, 1, type="elements", elements=[image()])
            headers = {"Content-Type": "image/png", "Origin": origin}
            stored = mount.post(BOARD_SITE, "/board/api/v1/slots/6/assets", headers, PNG)
            assert stored.json() == {"hash": PNG_HASH, "mediaType": "image/png"}
            numbered(one, 2, type="files", files=[FILE])

            assert next_message(two)["type"] == "elements"
            assert next_message(two) == {"type": "files", "epoch": 1, "files": [FILE]}
            saved = wait_for_saved(one, 2)
            head = mount.get(BOARD_SITE, "/board/api/v1/slots/6/scene").json()
            assert (head["files"], head["savedAt"]) == ([FILE], saved["savedAt"])
