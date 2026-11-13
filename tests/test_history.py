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

"""The history of a slot (S-005): the revision list, one revision, and restore
(docs/API.md, and docs/TEST-PLAN.md T-011).

In process first: the routes over revisions a test wrote to the database, and
then sockets that draw, restore, and are sent the scene of the new epoch. Then
``segl`` processes that are killed and started again, and nginx in front of
one. ``tests/test_saver.py`` covers how a restore takes its turn with the head
flushes, and ``web/e2e/history.spec.ts`` runs T-011 in a browser.
"""

import asyncio
import hashlib
import json
import logging
import threading
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
from starlette.testclient import WebSocketTestSession
from websockets.sync.client import ClientConnection

from segl.app import MAX_REVISION, create_app
from segl.assets import AssetStore
from segl.collab import Rooms
from segl.repository import Repository, RevisionNotFound

# A pass a segl with ``GATED`` takes, issued as the tests are collected.
PASS = issue_pass()
SLOT = 2
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
PNG_HASH = hashlib.sha256(PNG).hexdigest()
FILE_ID = "f" * 40
FILE = {"id": FILE_ID, "hash": PNG_HASH, "mimeType": "image/png"}
# Short enough for a test to wait for.
SOON = 0.02
# Shorter than the time between two flushes: every flush that changes the
# scene adds a history row.
EVERY_FLUSH = 0.001
# Longer than any test: only a slot's first change, a leave, a stop, or a
# restore adds a row.
NEVER = 3600

RESTORE = f"/api/v1/slots/{SLOT}/restore"
REVISIONS = f"/api/v1/slots/{SLOT}/revisions"


def element(identifier: str, version: int, nonce: int = 1, **more: object) -> dict[str, Any]:
    return {"id": identifier, "version": version, "versionNonce": nonce, **more}


A = element("a", 1, type="rectangle", index="a0")
B = element("b", 1, type="ellipse", index="a1")
C = element("c", 1, type="diamond", index="a2")


def scene_text(*elements: dict[str, Any]) -> str:
    """Return a scene document with these elements, as a flush stores one."""
    return json.dumps({**EMPTY_SCENE, "elements": list(elements)}, separators=(",", ":"))


def application(repository: Repository, folder: Path, **settings: Any) -> TestClient:
    settings.setdefault("head_flush_seconds", SOON)
    settings.setdefault("history_interval_seconds", EVERY_FLUSH)
    return TestClient(
        create_app(make_settings(assets_dir=folder / "assets", **settings), repository)
    )


@pytest.fixture
def client(repository: Repository, tmp_path: Path) -> Iterator[TestClient]:
    with application(repository, tmp_path) as client:
        yield client


@pytest.fixture
def written(repository: Repository) -> Repository:
    """A database whose slot 2 has three revisions: a, then a and b, then a, b, and c."""
    for label, elements in (("Guest1", [A]), ("Staff2", [A, B]), ("Guest3", [A, B, C])):
        repository.flush_head(SLOT, 1, scene_text(*elements), label, history_seconds=0)
    return repository


@pytest.fixture
def stored(written: Repository, tmp_path: Path) -> Iterator[TestClient]:
    """An application over that database. Nobody has opened the slot."""
    with application(written, tmp_path) as client:
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


def draw(
    socket: WebSocketTestSession, seq: int, *elements: dict[str, Any], epoch: int = 1
) -> dict[str, Any]:
    """Send elements, and return the ``saved`` that says the head holds them."""
    socket.send_json({"type": "elements", "epoch": epoch, "elements": list(elements), "seq": seq})
    saved = received(socket)
    assert (saved["type"], saved["seq"]) == ("saved", seq), saved
    return saved


def rows(client: TestClient, slot: int = SLOT) -> list[tuple[int, int, str]]:
    """Return a slot's history as the list route gives it: revision, epoch, and label."""
    response = client.get(f"/api/v1/slots/{slot}/revisions")
    assert response.status_code == 200
    return [
        (row["revision"], row["epoch"], row["authorLabel"]) for row in response.json()["revisions"]
    ]


def head(client: TestClient, slot: int = SLOT) -> dict[str, Any]:
    response = client.get(f"/api/v1/slots/{slot}/scene")
    assert response.status_code == 200
    return response.json()


# The list, and one revision.


def test_a_slot_nobody_has_changed_has_no_history(client: TestClient) -> None:
    for slot in range(1, 10):
        response = client.get(f"/api/v1/slots/{slot}/revisions")

        assert response.status_code == 200
        assert response.json() == {"revisions": []}


def test_the_list_is_newest_first_and_leaves_the_scenes_out(
    stored: TestClient, written: Repository
) -> None:
    response = stored.get(REVISIONS)

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    listed = response.json()["revisions"]
    assert [(row["revision"], row["epoch"], row["authorLabel"]) for row in listed] == [
        (3, 1, "Guest3"),
        (2, 1, "Staff2"),
        (1, 1, "Guest1"),
    ]
    # The four fields of docs/API.md and nothing else: no scene.
    assert [set(row) for row in listed] == [{"revision", "epoch", "authorLabel", "createdAt"}] * 3
    assert [row["createdAt"] for row in listed] == [
        row.created_at for row in written.list_revisions(SLOT)
    ]
    # The slots beside it have none.
    assert rows(stored, 1) == [] and rows(stored, 3) == []


def test_one_revision_is_its_scene_as_it_was_stored(stored: TestClient) -> None:
    response = stored.get(f"{REVISIONS}/2")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    body = response.json()
    assert (body["revision"], body["epoch"], body["authorLabel"]) == (2, 1, "Staff2")
    assert body["scene"] == {**EMPTY_SCENE, "elements": [A, B]}
    assert body["files"] == []
    assert set(body) == {"revision", "epoch", "authorLabel", "createdAt", "scene", "files"}


def test_a_revision_lists_the_files_its_images_name(repository: Repository, tmp_path: Path) -> None:
    picture = element("picture", 1, type="image", fileId=FILE_ID, index="a5")
    with application(repository, tmp_path) as client:
        with client.websocket_connect(f"/collab?slot={SLOT}") as socket:
            hello(socket)
            draw(socket, 1, A)
            uploaded = client.post(
                f"/api/v1/slots/{SLOT}/assets", content=PNG, headers={"Content-Type": "image/png"}
            )
            assert uploaded.json()["hash"] == PNG_HASH
            socket.send_json({"type": "files", "epoch": 1, "files": [FILE]})
            draw(socket, 2, picture)

        assert client.get(f"{REVISIONS}/1").json()["files"] == []
        newest = rows(client)[0][0]
        assert client.get(f"{REVISIONS}/{newest}").json()["files"] == [FILE]


def test_a_revision_with_half_a_surrogate_pair_is_still_served(
    repository: Repository, tmp_path: Path
) -> None:
    # A browser can send one in an element's text. The framework's own JSON
    # response would fail on it.
    broken = element("t", 1, type="text", text="\ud83d", index="a0")
    with application(repository, tmp_path) as client:
        with client.websocket_connect(f"/collab?slot={SLOT}") as socket:
            hello(socket)
            draw(socket, 1, broken)

        response = client.get(f"{REVISIONS}/1")

        assert response.status_code == 200
        assert response.content.isascii()
        assert "\\ud83d" in response.text


# The last two would reach the database as numbers, were they taken as such:
# one is larger than its integers go, and the other is a 3 in another script.
@pytest.mark.parametrize("name", ["4", "0", "01", "+1", "-1", "1.0", "abc", "9" * 20, "٣"])
def test_a_revision_the_slot_does_not_have_is_not_found(stored: TestClient, name: str) -> None:
    response = stored.get(f"{REVISIONS}/{name}")

    assert response.status_code == 404
    assert response.json()["error"] == "revision_not_found"
    assert set(response.json()) == {"error", "message"}


def test_a_revision_of_another_slot_is_not_found(stored: TestClient) -> None:
    # Numbers count per slot: slot 3 has no revision 1 although slot 2 has.
    assert stored.get("/api/v1/slots/3/revisions/1").json()["error"] == "revision_not_found"


@pytest.mark.parametrize("slot", ["0", "10", "01", "abc"])
def test_the_history_of_no_slot_is_refused(stored: TestClient, slot: str) -> None:
    for response in (
        stored.get(f"/api/v1/slots/{slot}/revisions"),
        stored.get(f"/api/v1/slots/{slot}/revisions/1"),
        stored.post(f"/api/v1/slots/{slot}/restore", json={"revision": 1}),
    ):
        assert response.status_code == 404
        assert response.json()["error"] == "invalid_slot"
    assert rows(stored) == [(3, 1, "Guest3"), (2, 1, "Staff2"), (1, 1, "Guest1")]


def test_the_history_routes_take_only_their_own_methods(stored: TestClient) -> None:
    for method, path, allowed in (
        ("POST", REVISIONS, "GET"),
        ("DELETE", f"{REVISIONS}/1", "GET"),
        ("PUT", f"{REVISIONS}/1", "GET"),
        ("GET", RESTORE, "POST"),
        ("DELETE", RESTORE, "POST"),
    ):
        response = stored.request(method, path)

        assert response.status_code == 405, (method, path)
        assert response.json()["error"] == "method_not_allowed"
        assert response.headers["allow"] == allowed
    # No revision can be deleted or written by a route.
    assert rows(stored) == [(3, 1, "Guest3"), (2, 1, "Staff2"), (1, 1, "Guest1")]


def test_the_list_is_at_most_the_history_limit(repository: Repository, tmp_path: Path) -> None:
    """T-011: the 51st revision drops the oldest, as the list route shows it."""
    for number in range(1, 52):
        scene = scene_text(element("a", number))
        repository.flush_head(SLOT, 1, scene, f"Guest{number}", history_seconds=0)

    with application(repository, tmp_path) as client:
        listed = rows(client)

        assert len(listed) == 50
        assert [revision for revision, _, _ in listed] == list(range(51, 1, -1))
        assert client.get(f"{REVISIONS}/1").json()["error"] == "revision_not_found"
        oldest = client.get(f"{REVISIONS}/2").json()
        assert oldest["scene"]["elements"] == [element("a", 2)]


# Restore.


def test_restoring_an_older_revision_switches_every_connection_and_can_be_undone(
    repository: Repository, tmp_path: Path
) -> None:
    """T-011 at the socket: restore an older revision, then the one from before the restore."""
    with application(repository, tmp_path) as client:
        with (
            client.websocket_connect(f"/collab?slot={SLOT}") as one,
            client.websocket_connect(f"/collab?slot={SLOT}") as two,
        ):
            hello(one, "Guest1"), hello(two, "Staff2")
            received(one)
            draw(one, 1, A)
            assert received(two)["elements"] == [A]
            draw(two, 1, B)
            assert received(one)["elements"] == [B]
            assert rows(client) == [(2, 1, "Staff2"), (1, 1, "Guest1")]

            response = client.post(RESTORE, json={"revision": 1, "displayName": "Guest1"})

            assert response.status_code == 200
            assert "set-cookie" not in response.headers
            restored = response.json()
            assert (restored["revision"], restored["epoch"]) == (3, 2)
            assert set(restored) == {"revision", "epoch", "savedAt"}
            # Every connection is sent the scene of the new epoch: b is gone.
            for socket in (one, two):
                assert received(socket) == {
                    "type": "scene",
                    "epoch": 2,
                    "elements": [A],
                    "files": [],
                }
            stored = head(client)
            assert stored["scene"] == {**EMPTY_SCENE, "elements": [A]}
            assert (stored["epoch"], stored["editorLabel"]) == (2, "Guest1")
            assert stored["savedAt"] == restored["savedAt"]
            assert client.get(f"/api/v1/slots/{SLOT}").json()["epoch"] == 2
            # The restore is a revision itself, by whoever restored.
            assert rows(client) == [(3, 2, "Guest1"), (2, 1, "Staff2"), (1, 1, "Guest1")]
            assert client.get(f"{REVISIONS}/3").json()["scene"] == stored["scene"]

            # The revision from before the restore: the later drawing returns.
            again = client.post(RESTORE, json={"revision": 2, "displayName": "Staff2"})

            assert (again.json()["revision"], again.json()["epoch"]) == (4, 3)
            for socket in (one, two):
                assert received(socket) == {
                    "type": "scene",
                    "epoch": 3,
                    "elements": [A, B],
                    "files": [],
                }
            assert head(client)["scene"]["elements"] == [A, B]
            assert rows(client)[0] == (4, 3, "Staff2")
        # The other slots were not touched.
        assert head(client, 1)["epoch"] == 1 and rows(client, 1) == []


def test_a_restore_first_records_the_scene_it_replaces(
    repository: Repository, tmp_path: Path
) -> None:
    # No timer writes here and no row is due: the second drawing is only in
    # the room when the restore arrives.
    with application(
        repository, tmp_path, head_flush_seconds=NEVER, history_interval_seconds=NEVER
    ) as client:
        with client.websocket_connect(f"/collab?slot={SLOT}") as one:
            hello(one, "Guest1")
            one.send_json({"type": "elements", "epoch": 1, "elements": [A]})
            one.send_json({"type": "rename", "displayName": "guest1"})
            assert received(one)["type"] == "presence"
        # Leaving wrote the head, and the slot's first row.
        assert rows(client) == [(1, 1, "Guest1")]

        with client.websocket_connect(f"/collab?slot={SLOT}") as two:
            hello(two, "Staff2")
            two.send_json({"type": "elements", "epoch": 1, "elements": [B], "seq": 7})
            two.send_json({"type": "rename", "displayName": "bea"})
            assert received(two)["type"] == "presence"
            assert head(client)["scene"]["elements"] == [A]

            response = client.post(RESTORE, json={"revision": 1, "displayName": "Guest3"})

            assert response.json()["epoch"] == 2
            # The new epoch is the answer to what was sent for the old scene:
            # no `saved` comes before the scene, or after it.
            assert received(two) == {"type": "scene", "epoch": 2, "elements": [A], "files": []}
            # Row 2 is the scene that was replaced, by whoever drew it last.
            assert rows(client) == [(3, 2, "Guest3"), (2, 1, "Staff2"), (1, 1, "Guest1")]
            assert client.get(f"{REVISIONS}/2").json()["scene"]["elements"] == [A, B]

            client.post(RESTORE, json={"revision": 2})

            assert received(two)["elements"] == [A, B]
            two.send_json({"type": "rename", "displayName": "cy"})
            assert received(two)["type"] == "presence"


def test_a_scene_a_revision_already_holds_is_not_recorded_twice(stored: TestClient) -> None:
    # The newest row holds the head, so the restore adds its own row and no other.
    response = stored.post(RESTORE, json={"revision": 1})

    assert (response.json()["revision"], response.json()["epoch"]) == (4, 2)
    assert rows(stored) == [(4, 2, "System"), (3, 1, "Guest3"), (2, 1, "Staff2"), (1, 1, "Guest1")]


def test_drawing_goes_on_at_the_new_epoch(
    repository: Repository, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    with (
        application(repository, tmp_path) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as one,
        client.websocket_connect(f"/collab?slot={SLOT}") as two,
    ):
        hello(one, "Guest1"), hello(two, "Staff2")
        received(one)
        draw(one, 1, A)
        received(two)
        draw(one, 2, B)
        received(two)
        assert client.post(RESTORE, json={"revision": 1}).json()["epoch"] == 2
        assert received(one)["epoch"] == 2 and received(two)["epoch"] == 2

        # An edit made for the scene that went is not applied. Its sender
        # is sent the scene again, and nobody else hears of it.
        stale = {"type": "elements", "epoch": 1, "elements": [element("b", 2)], "seq": 3}
        one.send_json(stale)
        assert received(one) == {"type": "scene", "epoch": 2, "elements": [A], "files": []}

        # One for the new scene is, and is saved at the new epoch.
        moved = element("a", 2, type="rectangle", index="a0", x=40)
        saved = draw(one, 4, moved, epoch=2)
        assert saved["epoch"] == 2
        assert received(two) == {"type": "elements", "epoch": 2, "elements": [moved]}
        stored = head(client)
        assert (stored["epoch"], stored["scene"]["elements"]) == (2, [moved])
        # The row of the restore, and then the edit's.
        assert [(row[0], row[1]) for row in rows(client)] == [(4, 2), (3, 2), (2, 1), (1, 1)]
    # No flush was refused for naming the old epoch.
    assert "was not saved" not in caplog.text


def test_a_restore_brings_an_image_back_with_its_file(
    repository: Repository, tmp_path: Path
) -> None:
    picture = element("picture", 1, type="image", fileId=FILE_ID, index="a5")
    with (
        application(repository, tmp_path) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as socket,
    ):
        hello(socket)
        draw(socket, 1, A)
        client.post(
            f"/api/v1/slots/{SLOT}/assets", content=PNG, headers={"Content-Type": "image/png"}
        )
        socket.send_json({"type": "files", "epoch": 1, "files": [FILE]})
        draw(socket, 2, picture)
        with_picture = rows(client)[0][0]

        client.post(RESTORE, json={"revision": 1})

        # The scene from before the image names no file.
        assert received(socket) == {"type": "scene", "epoch": 2, "elements": [A], "files": []}
        assert head(client)["files"] == []

        client.post(RESTORE, json={"revision": with_picture})

        scene = received(socket)
        assert (scene["epoch"], scene["elements"]) == (3, [A, picture])
        assert scene["files"] == [FILE]
        assert head(client)["files"] == [FILE]
        assert client.get(f"/api/v1/assets/{PNG_HASH}").content == PNG


def test_a_slot_nobody_has_open_can_be_restored(stored: TestClient) -> None:
    response = stored.post(RESTORE, json={"revision": 2, "displayName": "Guest1"})

    assert (response.status_code, response.json()["epoch"]) == (200, 2)
    assert head(stored)["scene"]["elements"] == [A, B]
    # Whoever opens the slot next is on the new epoch, with that scene.
    with stored.websocket_connect(f"/collab?slot={SLOT}") as socket:
        welcome, scene = hello(socket)
        assert welcome["epoch"] == 2
        assert scene == {"type": "scene", "epoch": 2, "elements": [A, B], "files": []}


def test_a_viewer_is_sent_the_restored_scene_too(written: Repository, tmp_path: Path) -> None:
    with (
        application(written, tmp_path, **GATED) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as viewer,
    ):
        assert hello(viewer)[0]["viewOnly"] is True

        client.post(RESTORE, json={"revision": 1}, headers={PASS_HEADER: PASS})

        assert received(viewer) == {"type": "scene", "epoch": 2, "elements": [A], "files": []}


@pytest.mark.parametrize(
    ("sent", "label"),
    [
        ("McKinley7", "McKinley7"),
        ("  john smith ", "john smith"),
        ("", "System"),
        ("x" * 41, "System"),
        (None, "System"),
        (7, "System"),
        (["Guest1"], "System"),
    ],
)
def test_the_row_of_a_restore_carries_the_label_the_browser_stores(
    stored: TestClient, sent: object, label: str
) -> None:
    # As `hello` takes a label: as written, and not title-cased again.
    response = stored.post(RESTORE, json={"revision": 1, "displayName": sent})

    assert response.status_code == 200
    assert rows(stored)[0] == (4, 2, label)
    assert head(stored)["editorLabel"] == label


def test_a_restore_without_a_name_is_by_system(stored: TestClient) -> None:
    assert stored.post(RESTORE, json={"revision": 1}).status_code == 200

    assert rows(stored)[0] == (4, 2, "System")


# What a restore refuses. Nothing is changed by any of these.


def unchanged(client: TestClient) -> None:
    assert rows(client) == [(3, 1, "Guest3"), (2, 1, "Staff2"), (1, 1, "Guest1")]
    stored = head(client)
    assert (stored["epoch"], stored["scene"]["elements"]) == (1, [A, B, C])
    assert stored["editorLabel"] == "Guest3"


@pytest.mark.parametrize(
    "revision", [0, -1, 1.5, 1.0, "1", True, None, [1], {"n": 1}, MAX_REVISION + 1, 10**30]
)
def test_a_revision_that_is_not_a_whole_number_from_one_is_refused(
    stored: TestClient, revision: object
) -> None:
    response = stored.post(RESTORE, json={"revision": revision})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_revision"
    unchanged(stored)


def test_a_restore_body_without_a_revision_is_refused(stored: TestClient) -> None:
    response = stored.post(RESTORE, json={"displayName": "Guest1"})

    assert (response.status_code, response.json()["error"]) == (422, "invalid_revision")
    unchanged(stored)


@pytest.mark.parametrize("body", [b"", b"1", b'"1"', b"[1]", b"{", b"null", b'{"revision": NaN'])
def test_a_restore_body_that_is_not_a_json_object_is_refused(
    stored: TestClient, body: bytes
) -> None:
    response = stored.post(RESTORE, content=body)

    assert (response.status_code, response.json()["error"]) == (400, "bad_request")
    unchanged(stored)


def test_a_restore_body_that_is_too_large_is_refused(stored: TestClient) -> None:
    body = json.dumps({"revision": 1, "displayName": "x" * 5000})

    response = stored.post(RESTORE, content=body)

    assert (response.status_code, response.json()["error"]) == (413, "payload_too_large")
    unchanged(stored)


@pytest.mark.parametrize("revision", [4, 99, MAX_REVISION])
def test_restoring_a_revision_the_slot_does_not_have_is_not_found(
    stored: TestClient, revision: int
) -> None:
    with stored.websocket_connect(f"/collab?slot={SLOT}") as socket:
        hello(socket)

        response = stored.post(RESTORE, json={"revision": revision})

        assert (response.status_code, response.json()["error"]) == (404, "revision_not_found")
        # Nobody was sent a scene: the next thing the socket hears is its own rename.
        socket.send_json({"type": "rename", "displayName": "bea"})
        assert received(socket)["type"] == "presence"
    unchanged(stored)


def test_a_restore_from_another_site_changes_nothing(stored: TestClient) -> None:
    response = stored.post(
        RESTORE, json={"revision": 1}, headers={"Origin": "https://evil.example"}
    )

    assert (response.status_code, response.json()["error"]) == (403, "bad_origin")
    unchanged(stored)


# The edit gate (docs/TEST-PLAN.md T-008, the history).


def test_with_a_token_a_client_without_it_reads_the_history_and_cannot_restore(
    written: Repository, tmp_path: Path
) -> None:
    with application(written, tmp_path, **GATED) as client:
        with (
            client.websocket_connect(f"/collab?slot={SLOT}") as editor,
            client.websocket_connect(f"/collab?slot={SLOT}") as viewer,
        ):
            assert hello(editor, "Guest1", PASS)[0]["viewOnly"] is False
            assert hello(viewer, "Staff2")[0]["viewOnly"] is True
            received(editor)

            # Reading needs no pass.
            assert len(rows(client)) == 3
            assert client.get(f"{REVISIONS}/1").json()["scene"]["elements"] == [A]

            for headers in ({}, {PASS_HEADER: "wrong"}, {PASS_HEADER: ""}):
                refused = client.post(RESTORE, json={"revision": 1}, headers=headers)

                assert (refused.status_code, refused.json()["error"]) == (403, "view_only")
                assert "set-cookie" not in refused.headers
            unchanged(client)
            # Neither connection was sent a scene: the next thing each hears
            # is the editor's rename.
            editor.send_json({"type": "rename", "displayName": "bea"})
            assert received(editor)["type"] == "presence"
            assert received(viewer)["type"] == "presence"

            allowed = client.post(
                RESTORE,
                json={"revision": 1, "displayName": "Guest1"},
                headers={PASS_HEADER: PASS},
            )

            assert (allowed.status_code, allowed.json()["epoch"]) == (200, 2)
            for socket in (editor, viewer):
                assert received(socket)["elements"] == [A]
        assert PASS not in json.dumps(client.get(REVISIONS).json())


def test_without_a_token_configured_anyone_restores(stored: TestClient) -> None:
    # A header nobody asked for is ignored.
    response = stored.post(RESTORE, json={"revision": 1}, headers={PASS_HEADER: "anything"})

    assert response.status_code == 200


def test_the_token_is_checked_before_the_body_is_read(written: Repository, tmp_path: Path) -> None:
    with application(written, tmp_path, **GATED) as client:
        response = client.post(RESTORE, content=b"{")

        assert response.json()["error"] == "view_only"


# The cap.


def test_the_oldest_revision_can_be_restored_when_the_history_is_full(tmp_path: Path) -> None:
    # Recording the scene that is going drops the oldest row, which is the one
    # being restored. Its scene was read first.
    with Repository(tmp_path / "segl.sqlite", history_limit=3) as repository:
        repository.bootstrap()
        for label, elements in (("Guest1", [A]), ("Staff2", [A, B]), ("Guest3", [A, B, C])):
            repository.flush_head(SLOT, 1, scene_text(*elements), label, history_seconds=0)
        with (
            application(
                repository, tmp_path, head_flush_seconds=NEVER, history_interval_seconds=NEVER
            ) as client,
            client.websocket_connect(f"/collab?slot={SLOT}") as socket,
        ):
            hello(socket, "Guest1")
            later = element("d", 1, index="a3")
            socket.send_json({"type": "elements", "epoch": 1, "elements": [later]})
            socket.send_json({"type": "rename", "displayName": "bea"})
            received(socket)

            response = client.post(RESTORE, json={"revision": 1})

            assert (response.status_code, response.json()["revision"]) == (200, 5)
            assert received(socket)["elements"] == [A]
            # Three rows are kept: the newest of before, the scene that
            # was replaced, and the restore.
            assert rows(client) == [(5, 2, "System"), (4, 1, "Guest1"), (3, 1, "Guest3")]
            assert client.get(f"{REVISIONS}/4").json()["scene"]["elements"] == [A, B, C, later]
            assert client.get(f"{REVISIONS}/1").json()["error"] == "revision_not_found"


# A request that goes away.


def test_a_restore_whose_request_is_cancelled_still_reaches_the_room(
    written: Repository, tmp_path: Path
) -> None:
    # The database is written in a worker thread, which a cancelled request
    # does not stop. The room has to follow it to the new epoch.
    entered, gate = threading.Event(), threading.Event()
    replace_head = written.replace_head

    def held(*arguments: Any, **options: Any) -> Any:
        entered.set()
        gate.wait(5)
        return replace_head(*arguments, **options)

    written.replace_head = held

    async def scenario() -> None:
        rooms = Rooms(written, make_settings(), AssetStore(tmp_path / "assets"))
        room = await rooms.room(SLOT)
        request = asyncio.create_task(rooms.restore(SLOT, 1, "Guest1"))
        async with asyncio.timeout(5):
            while not entered.is_set():
                await asyncio.sleep(0.005)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert room.epoch == 1

        gate.set()
        async with asyncio.timeout(5):
            while room.epoch != 2:
                await asyncio.sleep(0.005)
        assert list(room.elements) == ["a"]
        await asyncio.wait_for(rooms.close(), 10)

    asyncio.run(scenario())
    assert written.get_head(SLOT).epoch == 2


def test_restoring_a_revision_that_is_not_there_raises_before_anything_is_written(
    written: Repository, tmp_path: Path
) -> None:
    async def scenario() -> None:
        rooms = Rooms(written, make_settings(), AssetStore(tmp_path / "assets"))
        with pytest.raises(RevisionNotFound):
            await rooms.restore(SLOT, 9, "Guest1")
        await asyncio.wait_for(rooms.close(), 10)

    asyncio.run(scenario())
    assert [row.revision for row in written.list_revisions(SLOT)] == [3, 2, 1]
    assert written.get_head(SLOT).epoch == 1


# From running processes.


def send(socket: ClientConnection, seq: int, *elements: dict[str, Any], epoch: int = 1) -> None:
    """Send elements on a real socket, and wait for the ``saved`` that answers them."""
    message = {"type": "elements", "epoch": epoch, "elements": list(elements), "seq": seq}
    socket.send(json.dumps(message))
    saved = next_message(socket)
    assert (saved["type"], saved["seq"]) == ("saved", seq), saved


def restore_body(revision: int, name: str | None = None) -> bytes:
    return json.dumps({"revision": revision, "displayName": name}).encode()


def test_a_restore_survives_a_kill_and_so_does_the_scene_it_replaced(tmp_path: Path) -> None:
    """A restore after a crash, and a crash after a restore."""
    config = f"head_flush_seconds = {SOON}\nhistory_interval_seconds = {NEVER}\n"
    scene_path = f"/api/v1/slots/{SLOT}/scene"
    with running_segl(tmp_path, config) as server, server.socket(f"/collab?slot={SLOT}") as one:
        say_hello(one, "Guest1")
        send(one, 1, A)
        # In the head, and in no history row: the slot has its first row,
        # and the next is an hour away.
        send(one, 2, B)
        assert [row["revision"] for row in server.get(REVISIONS).json()["revisions"]] == [1]
        server.kill()

    with running_segl(tmp_path, config) as server:
        assert server.get(scene_path).json()["scene"]["elements"] == [A, B]
        with server.socket(f"/collab?slot={SLOT}") as two:
            assert say_hello(two, "Staff2")[1]["elements"] == [A, B]

            reply = server.post(RESTORE, body=restore_body(1, "Staff2"))

            assert reply.status == 200
            assert "Set-Cookie" not in reply.headers
            assert (reply.json()["revision"], reply.json()["epoch"]) == (3, 2)
            assert next_message(two) == {"type": "scene", "epoch": 2, "elements": [A], "files": []}
            listed = server.get(REVISIONS).json()["revisions"]
            # Row 2 is the head the crash left, under the name that saved it.
            assert [(row["revision"], row["epoch"], row["authorLabel"]) for row in listed] == [
                (3, 2, "Staff2"),
                (2, 1, "Guest1"),
                (1, 1, "Guest1"),
            ]
            before = server.get(scene_path).json()
            assert (before["epoch"], before["scene"]["elements"]) == (2, [A])
            # The restore was on the disk before the route answered.
            server.kill()

    with running_segl(tmp_path, config) as server:
        assert server.get(scene_path).json() == before
        assert server.get(f"/api/v1/slots/{SLOT}").json()["epoch"] == 2
        with server.socket(f"/collab?slot={SLOT}") as three:
            welcome, scene = say_hello(three, "Guest3")
            assert (welcome["epoch"], scene["elements"]) == (2, [A])

            assert server.post(RESTORE, body=restore_body(2, "Guest3")).json()["epoch"] == 3

            assert next_message(three)["elements"] == [A, B]
            send(three, 1, C, epoch=3)
        assert server.get(scene_path).json()["scene"]["elements"] == [A, B, C]
        assert "was not saved" not in server.log()
        assert "Traceback" not in server.log()


def test_with_a_token_a_running_server_gates_the_restore(tmp_path: Path) -> None:
    """T-008 from a running process, with the codes in the TOML file."""
    config = f"{GATED_TOML}head_flush_seconds = {SOON}\nhistory_interval_seconds = {EVERY_FLUSH}\n"
    with running_segl(tmp_path, config) as server:
        with (
            server.socket(f"/collab?slot={SLOT}") as editor,
            server.socket(f"/collab?slot={SLOT}") as viewer,
        ):
            say_hello(editor, "Guest1", edit_pass=PASS)
            assert say_hello(viewer, "Staff2")[0]["viewOnly"] is True
            next_message(editor)
            send(editor, 1, A)
            assert next_message(viewer)["elements"] == [A]
            send(editor, 2, B)
            assert next_message(viewer)["elements"] == [B]

            # The viewer reads the history, and cannot restore it.
            assert len(server.get(REVISIONS).json()["revisions"]) == 2
            refused = server.post(RESTORE, body=restore_body(1, "Staff2"))
            assert (refused.status, refused.json()["error"]) == (403, "view_only")
            assert server.get(f"/api/v1/slots/{SLOT}").json()["epoch"] == 1

            allowed = server.post(RESTORE, {PASS_HEADER: PASS}, restore_body(1, "Guest1"))
            assert (allowed.status, allowed.json()["epoch"]) == (200, 2)
            # The first thing either hears after the drawing is the restored scene.
            for socket in (editor, viewer):
                assert next_message(socket) == {
                    "type": "scene",
                    "epoch": 2,
                    "elements": [A],
                    "files": [],
                }
        assert PASS not in server.log()
        assert_no_secrets(server.log())
        # The log has the route, and no scene and no name.
        server.logged_line(f"POST {RESTORE}")
        assert "rectangle" not in server.log() and "Guest1" not in server.log()


# Through nginx, with the files in deploy/nginx/.


def test_the_history_and_a_restore_through_nginx_at_board_and_at_a_host_root(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    config = f"head_flush_seconds = {SOON}\nhistory_interval_seconds = {EVERY_FLUSH}\n"
    with running_mount(tools, certificate, tmp_path, config) as mount:
        for site, prefix, slot in ((BOARD_SITE, "/board", 1), (ROOT_SITE, "", 2)):
            origin = mount.origin(site)
            api = f"{prefix}/api/v1/slots/{slot}"
            with (
                mount.socket(site, f"{prefix}/collab?slot={slot}", origin=origin) as one,
                mount.socket(site, f"{prefix}/collab?slot={slot}", origin=origin) as two,
            ):
                say_hello(one, "Guest1"), say_hello(two, "Staff2")
                next_message(one)
                send(one, 1, A)
                assert next_message(two)["elements"] == [A]
                send(one, 2, B)
                assert next_message(two)["elements"] == [B]

                listed = mount.get(site, f"{api}/revisions")
                assert listed.status == 200
                assert "Set-Cookie" not in listed.headers
                assert [row["revision"] for row in listed.json()["revisions"]] == [2, 1]
                first = mount.get(site, f"{api}/revisions/1")
                assert first.json()["scene"]["elements"] == [A]

                # A page on another site cannot restore.
                for other in ("https://evil.example", f"https://{site}"):
                    refused = mount.post(site, f"{api}/restore", {"Origin": other}, restore_body(1))
                    assert (refused.status, refused.json()["error"]) == (403, "bad_origin"), other
                assert mount.get(site, api).json()["epoch"] == 1

                restored = mount.post(
                    site, f"{api}/restore", {"Origin": origin}, restore_body(1, "Guest1")
                )
                assert (restored.status, restored.json()["epoch"]) == (200, 2)
                assert "Set-Cookie" not in restored.headers
                for socket in (one, two):
                    assert next_message(socket) == {
                        "type": "scene",
                        "epoch": 2,
                        "elements": [A],
                        "files": [],
                    }

        # Outside /board/ the routes are nginx's to answer, and segl never sees them.
        outside = mount.get(BOARD_SITE, "/api/v1/slots/1/revisions")
        assert outside.status == 404
        assert b"revisions" not in outside.body
        mount.segl.logged_line("POST /api/v1/slots/1/restore")
        assert "/board/api" not in mount.segl.log()
