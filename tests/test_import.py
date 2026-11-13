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

"""JSON import (S-011): the import route and the document it takes
(docs/API.md, and docs/TEST-PLAN.md T-009).

First the reader alone: what it takes from a document and what it refuses.
Then the route in process, with sockets that draw, are sent the imported scene,
and go on drawing. Then ``segl`` processes that are killed and started again,
and nginx in front of one. ``tests/test_saver.py`` covers how an import takes
its turn with the head flushes, and ``web/e2e/import.spec.ts`` runs T-009 in a
browser, with the editor's own export.
"""

import asyncio
import base64
import hashlib
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

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

from segl.app import create_app, header_name
from segl.assets import AssetStore
from segl.collab import Rooms
from segl.importing import (
    ImportedFile,
    InvalidDocument,
    NotJson,
    TooLarge,
    data_url_bytes,
    read_document,
)
from segl.repository import Repository
from segl.room import encode

# A pass a segl with ``GATED`` takes, issued as the tests are collected.
PASS = issue_pass()
SLOT = 2
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
PNG_HASH = hashlib.sha256(PNG).hexdigest()
JPEG = b"\xff\xd8\xff\xe0" + bytes(range(200))
FILE_ID = "f" * 40
OTHER_ID = "e" * 40
FILE = {"id": FILE_ID, "hash": PNG_HASH, "mimeType": "image/png"}
# Short enough for a test to wait for.
SOON = 0.02
# Shorter than the time between two flushes: every flush that changes the
# scene adds a history row.
EVERY_FLUSH = 0.001
# Longer than any test.
NEVER = 3600

IMPORT = f"/api/v1/slots/{SLOT}/import"
REVISIONS = f"/api/v1/slots/{SLOT}/revisions"
NAME_HEADER = "X-Segl-Display-Name"


def element(identifier: str, version: int, nonce: int = 1, **more: object) -> dict[str, Any]:
    return {"id": identifier, "version": version, "versionNonce": nonce, **more}


A = element("a", 1, type="rectangle", index="a0")
B = element("b", 1, type="ellipse", index="a1")
C = element("c", 1, type="diamond", index="a2")
PICTURE = element("picture", 1, type="image", fileId=FILE_ID, index="a5")


def data_url(data: bytes, media_type: str = "image/png") -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode()}"


def held_file(file_id: str, data: bytes, media_type: str = "image/png") -> dict[str, Any]:
    """Return a file as the editor writes it into an exported document."""
    return {
        "mimeType": media_type,
        "id": file_id,
        "dataURL": data_url(data, media_type),
        "created": 1794474000000,
        "lastRetrieved": 1794474000000,
    }


def document(*elements: object, files: object = None, **more: object) -> dict[str, Any]:
    """Return a scene document as the editor's export writes one."""
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "segl",
        "elements": list(elements),
        "appState": {"gridSize": 20, "viewBackgroundColor": "#ffffff"},
        "files": {} if files is None else files,
        **more,
    }


def body_of(value: object) -> bytes:
    """Return a document as the bytes of a file: UTF-8, as the editor saves it."""
    return json.dumps(value, ensure_ascii=False, indent=2).encode()


def read(value: object, *, scene: int = 100_000, asset: int = 10_000) -> Any:
    body = value if isinstance(value, bytes) else body_of(value)
    return read_document(body, max_scene_bytes=scene, max_asset_bytes=asset)


# The reader.


def test_a_document_gives_its_elements_and_the_files_they_name() -> None:
    taken = read(document(A, PICTURE, B, files={FILE_ID: held_file(FILE_ID, PNG)}))

    # In drawing order, which the editor keeps in `index`.
    assert taken.elements == [A, B, PICTURE]
    assert taken.files == [ImportedFile(FILE_ID, "image/png", PNG)]


def test_an_empty_document_is_an_empty_scene() -> None:
    taken = read(document())

    assert (taken.elements, taken.files) == ([], [])


@pytest.mark.parametrize(
    "value",
    [
        {"type": "excalidraw"},
        {"type": "excalidraw", "elements": None, "files": None},
        # Whatever else a document holds is not read.
        {"type": "excalidraw", "elements": [], "appState": 5, "version": "x", "source": []},
    ],
)
def test_a_document_without_elements_is_an_empty_scene(value: dict[str, Any]) -> None:
    assert read(value).elements == []


def test_an_element_without_a_version_gets_the_editors_default() -> None:
    taken = read(document({"id": "old", "type": "rectangle"}, {"id": "odd", "version": "7"}))

    assert taken.elements == [
        {"id": "old", "type": "rectangle", "version": 1, "versionNonce": 0},
        {"id": "odd", "version": 1, "versionNonce": 0},
    ]


def test_elements_without_an_index_keep_their_place_after_those_with_one() -> None:
    first, second = element("y", 1), element("x", 1)

    assert read(document(first, B, second, A)).elements == [A, B, first, second]


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"nope",
        b"[]",
        b'"text"',
        b"null",
        b"7",
        b'{"type": "excalidraw"',
        b'{"type": "excalidraw", "elements": [NaN]}',
        b'{"type": "excalidraw", "x": Infinity}',
        b'{"type": "excalidraw", "x": "\xff"}',
        b"[" * 100_000,
    ],
)
def test_a_body_that_is_not_a_json_object_is_not_json(body: bytes) -> None:
    with pytest.raises(NotJson):
        read(body)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"elements": []},
        {"type": "excalidrawlib", "libraryItems": []},
        {"type": "Excalidraw", "elements": []},
        {"type": ["excalidraw"], "elements": []},
        document(elements={"id": "a"}),
        document(elements="a"),
        document(elements=0),
        document(A, 7),
        document(A, None),
        document(A, [B]),
        document({"version": 1}),
        document({"id": ""}),
        document({"id": 7}),
        document(A, B, {**A, "version": 2}),
        document(files=[]),
        document(files="x"),
    ],
)
def test_what_is_not_a_scene_document_is_refused(value: dict[str, Any]) -> None:
    with pytest.raises(InvalidDocument):
        read(value)


def test_a_number_json_cannot_write_is_refused() -> None:
    # Python reads 1e999 as infinity, and would hand every browser `Infinity`.
    body = b'{"type": "excalidraw", "elements": [{"id": "a", "x": 1e999}]}'

    with pytest.raises(InvalidDocument, match="element 1 holds a number"):
        read(body)
    with pytest.raises(InvalidDocument):
        read(body.replace(b"1e999", b"[[-1e999]]"))


def test_a_refusal_does_not_repeat_the_document() -> None:
    with pytest.raises(InvalidDocument) as refusal:
        read(document(A, {"id": "", "text": "SECRET"}))

    assert str(refusal.value) == "element 2 is not an object with an id"


def test_the_elements_are_limited_as_a_room_writes_them() -> None:
    elements = [element(f"e{number}", 1, text="x" * 50) for number in range(10)]
    size = sum(len(encode(each)) for each in elements)

    assert read(document(*elements), scene=size).elements == elements
    with pytest.raises(TooLarge, match=f"more than {size - 1} bytes"):
        read(document(*elements), scene=size - 1)


def test_text_outside_ascii_counts_as_it_is_stored() -> None:
    # Two bytes in the file, and six in a stored scene, which is ASCII.
    text = "é" * 300
    wide = element("wide", 1, text=text)
    body = body_of(document(wide))
    assert len(body) < 1000 < len(encode(wide))

    with pytest.raises(TooLarge):
        read(body, scene=1000)
    assert read(body, scene=len(encode(wide))).elements == [wide]


def test_only_the_files_an_element_names_are_read() -> None:
    files = {
        FILE_ID: held_file(FILE_ID, PNG),
        "not named": "not a file at all",
        OTHER_ID: {"mimeType": "text/html", "dataURL": "x"},
    }

    assert read(document(PICTURE, files=files)).files == [ImportedFile(FILE_ID, "image/png", PNG)]


def test_a_deleted_image_brings_its_file_and_two_images_bring_one() -> None:
    deleted = {**PICTURE, "isDeleted": True}
    twin = {**PICTURE, "id": "twin"}

    taken = read(document(deleted, twin, files={FILE_ID: held_file(FILE_ID, PNG)}))

    assert taken.files == [ImportedFile(FILE_ID, "image/png", PNG)]


def test_an_image_whose_file_the_document_lacks_is_taken_without_one() -> None:
    odd = {**PICTURE, "id": "odd", "fileId": "not an id segl would take", "index": "a6"}

    taken = read(document(PICTURE, odd, {**A, "fileId": 7}, files={OTHER_ID: "unnamed"}))

    assert [each["id"] for each in taken.elements] == ["a", "picture", "odd"]
    assert taken.files == []


def test_a_file_keeps_the_type_its_entry_gives() -> None:
    files = {FILE_ID: {"mimeType": "image/jpeg", "dataURL": data_url(JPEG, "image/png")}}

    assert read(document(PICTURE, files=files)).files == [ImportedFile(FILE_ID, "image/jpeg", JPEG)]


@pytest.mark.parametrize(
    "entry",
    [
        "text",
        7,
        [],
        {},
        {"mimeType": "image/png"},
        {"dataURL": data_url(PNG)},
        {"mimeType": "text/html", "dataURL": data_url(PNG, "text/html")},
        {"mimeType": ["image/png"], "dataURL": data_url(PNG)},
        {"mimeType": "image/png", "dataURL": "https://example.com/a.png"},
        {"mimeType": "image/png", "dataURL": "data:image/png;base64"},
        {"mimeType": "image/png", "dataURL": "data:image/png;base64,"},
        {"mimeType": "image/png", "dataURL": "data:image/png;base64,not base64!"},
        {"mimeType": "image/png", "dataURL": "data:image/png;base64,é"},
        {"mimeType": "image/png", "dataURL": 7},
    ],
)
def test_a_named_file_that_is_not_one_refuses_the_document(entry: object) -> None:
    with pytest.raises(InvalidDocument):
        read(document(PICTURE, files={FILE_ID: entry}))


def test_a_file_under_an_id_segl_would_not_take_refuses_the_document() -> None:
    name = "../../etc/passwd"
    picture = {**PICTURE, "fileId": name}

    with pytest.raises(InvalidDocument, match="names a file that is not one"):
        read(document(picture, files={name: held_file(name, PNG)}))


def test_a_file_is_limited_as_an_upload_is() -> None:
    files = {FILE_ID: held_file(FILE_ID, PNG)}

    assert read(document(PICTURE, files=files), asset=len(PNG)).files[0].data == PNG
    with pytest.raises(TooLarge, match=f"larger than {len(PNG) - 1} bytes"):
        read(document(PICTURE, files=files), asset=len(PNG) - 1)


@pytest.mark.parametrize(
    ("url", "data"),
    [
        (data_url(PNG), PNG),
        ("data:image/png;BASE64,AAEC", b"\x00\x01\x02"),
        ("data:image/svg+xml;charset=utf-8;base64,PHN2Zy8+", b"<svg/>"),
        ("data:;base64,AAEC", b"\x00\x01\x02"),
        # Percent-encoded, which the editor does not write and a browser reads.
        ("data:image/svg+xml,%3Csvg%2F%3E", b"<svg/>"),
        ("data:,plain", b"plain"),
        ("data:image/png;base64,", b""),
        ("data:image/png;base64,AAE", None),
        ("data:image/png;base64,AA EC", None),
        ("data:image/png;base64", None),
        ("image/png;base64,AAEC", None),
        ("", None),
        (None, None),
        (b"data:,x", None),
    ],
)
def test_a_data_url_is_read_for_its_bytes(url: object, data: bytes | None) -> None:
    assert data_url_bytes(url) == data


@pytest.mark.parametrize(
    ("header", "name"),
    [
        ("Guest1", "Guest1"),
        ("John%20Smith", "John Smith"),
        ("Jos%C3%A9", "José"),
        ("%20%20Bea%20", "Bea"),
        ("x" * 40, "x" * 40),
        ("x" * 41, None),
        ("%FF", None),
        ("%20", None),
        ("", None),
        (None, None),
    ],
)
def test_the_name_header_is_the_stored_label_percent_encoded(
    header: str | None, name: str | None
) -> None:
    assert header_name(header) == name


# The route, in process.


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
def drawn(repository: Repository, tmp_path: Path) -> Iterator[TestClient]:
    """An application whose slot 2 holds a and b, in two revisions. Nobody has it open."""
    for label, elements in (("Guest1", [A]), ("Staff2", [A, B])):
        scene = json.dumps({**EMPTY_SCENE, "elements": elements}, separators=(",", ":"))
        repository.flush_head(SLOT, 1, scene, label, history_seconds=0)
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


def headers_for(name: str | None = None, edit_pass: str | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if name is not None:
        headers[NAME_HEADER] = quote(name)
    if edit_pass is not None:
        headers[PASS_HEADER] = edit_pass
    return headers


def send_file(
    client: TestClient,
    value: object,
    name: str | None = None,
    *,
    edit_pass: str | None = None,
    path: str = IMPORT,
) -> Any:
    """Post a document to the import route, as the page posts a chosen file."""
    body = value if isinstance(value, bytes) else body_of(value)
    return client.post(path, content=body, headers=headers_for(name, edit_pass))


def test_a_drawing_is_exported_cleared_and_imported_back(
    repository: Repository, tmp_path: Path
) -> None:
    """T-009 at the socket: clear the slot with an empty document, then import the drawing."""
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
            # What an export holds of the scene: its elements, in a document.
            exported = document(*head(client)["scene"]["elements"])
            assert exported["elements"] == [A, B]

            cleared = send_file(client, document(), "Guest1")

            assert cleared.status_code == 200
            assert "set-cookie" not in cleared.headers
            assert set(cleared.json()) == {"revision", "epoch", "savedAt"}
            assert (cleared.json()["revision"], cleared.json()["epoch"]) == (3, 2)
            for socket in (one, two):
                assert received(socket) == {
                    "type": "scene",
                    "epoch": 2,
                    "elements": [],
                    "files": [],
                }
            stored = head(client)
            assert stored["scene"] == {**EMPTY_SCENE, "elements": []}
            assert (stored["epoch"], stored["editorLabel"]) == (2, "Guest1")
            assert stored["savedAt"] == cleared.json()["savedAt"]

            back = send_file(client, exported, "Staff2")

            assert (back.json()["revision"], back.json()["epoch"]) == (4, 3)
            for socket in (one, two):
                assert received(socket) == {
                    "type": "scene",
                    "epoch": 3,
                    "elements": [A, B],
                    "files": [],
                }
            # The drawing is back, and a new revision holds it.
            stored = head(client)
            assert stored["scene"] == {**EMPTY_SCENE, "elements": [A, B]}
            assert client.get(f"/api/v1/slots/{SLOT}").json()["epoch"] == 3
            assert rows(client) == [
                (4, 3, "Staff2"),
                (3, 2, "Guest1"),
                (2, 1, "Staff2"),
                (1, 1, "Guest1"),
            ]
            assert client.get(f"{REVISIONS}/4").json()["scene"] == stored["scene"]
        # The other slots were not touched.
        assert head(client, 1)["epoch"] == 1 and rows(client, 1) == []


def test_an_import_first_records_the_scene_it_replaces(
    repository: Repository, tmp_path: Path
) -> None:
    # The slot has a history row already, and the next is an hour away. With no
    # flush on a timer either, what is in the room when the import arrives is
    # nowhere else, and no row is due for it.
    scene = json.dumps({**EMPTY_SCENE, "elements": [A]}, separators=(",", ":"))
    repository.flush_head(SLOT, 1, scene, "Guest1", history_seconds=0)
    with (
        application(
            repository, tmp_path, head_flush_seconds=NEVER, history_interval_seconds=NEVER
        ) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as socket,
    ):
        hello(socket, "Staff2")
        socket.send_json({"type": "elements", "epoch": 1, "elements": [B], "seq": 1})

        response = send_file(client, document(C), "Guest3")

        assert (response.json()["revision"], response.json()["epoch"]) == (3, 2)
        # The scene, and no `saved`: the new epoch is the answer.
        assert received(socket) == {"type": "scene", "epoch": 2, "elements": [C], "files": []}
        assert rows(client) == [(3, 2, "Guest3"), (2, 1, "Staff2"), (1, 1, "Guest1")]
        assert client.get(f"{REVISIONS}/2").json()["scene"]["elements"] == [A, B]
        # So the import can be undone: the scene it replaced is a restore away.
        client.post(f"/api/v1/slots/{SLOT}/restore", json={"revision": 2})
        assert received(socket)["elements"] == [A, B]


def test_an_import_brings_its_images_with_their_files(
    repository: Repository, tmp_path: Path
) -> None:
    files = {FILE_ID: held_file(FILE_ID, PNG), "unnamed": "not read"}
    with (
        application(repository, tmp_path) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as socket,
    ):
        hello(socket)

        response = send_file(client, document(A, PICTURE, files=files), "Guest1")

        assert response.status_code == 200
        scene = received(socket)
        assert (scene["epoch"], scene["elements"], scene["files"]) == (2, [A, PICTURE], [FILE])
        # The bytes are stored as an upload's are, and served the same way.
        asset = client.get(f"/api/v1/assets/{PNG_HASH}")
        assert asset.content == PNG
        assert asset.headers["content-type"] == "application/octet-stream"
        assert [path.name for path in (tmp_path / "assets").iterdir()] == [PNG_HASH]
        stored = head(client)
        assert stored["files"] == [FILE]
        # A stored scene holds no file: the list beside it says which bytes.
        assert "files" not in stored["scene"]
        assert "base64" not in json.dumps(stored["scene"])
        assert client.get(f"{REVISIONS}/1").json()["files"] == [FILE]
        assert [file.hash for file in repository.list_files(SLOT)] == [PNG_HASH]

        # A scene without the image names no file, and the list keeps it.
        send_file(client, document(A))
        assert received(socket)["files"] == []
        client.post(f"/api/v1/slots/{SLOT}/restore", json={"revision": 1})
        assert received(socket)["files"] == [FILE]


def test_an_imported_file_keeps_its_type_and_each_image_its_own_file(
    repository: Repository, tmp_path: Path
) -> None:
    photo = {**PICTURE, "id": "photo", "fileId": OTHER_ID, "index": "a6"}
    files = {OTHER_ID: held_file(OTHER_ID, JPEG, "image/jpeg"), FILE_ID: held_file(FILE_ID, PNG)}
    with (
        application(repository, tmp_path) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as socket,
    ):
        hello(socket)

        send_file(client, document(PICTURE, photo, files=files))

        jpeg_hash = hashlib.sha256(JPEG).hexdigest()
        # In the order the elements name them.
        assert received(socket)["files"] == [
            FILE,
            {"id": OTHER_ID, "hash": jpeg_hash, "mimeType": "image/jpeg"},
        ]
        assert client.get(f"/api/v1/assets/{jpeg_hash}").content == JPEG
        assert head(client)["files"] == [
            FILE,
            {"id": OTHER_ID, "hash": jpeg_hash, "mimeType": "image/jpeg"},
        ]


def test_a_file_id_the_slot_already_has_keeps_its_bytes(
    repository: Repository, tmp_path: Path
) -> None:
    with (
        application(repository, tmp_path) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as socket,
    ):
        hello(socket)
        client.post(
            f"/api/v1/slots/{SLOT}/assets", content=PNG, headers={"Content-Type": "image/png"}
        )
        socket.send_json({"type": "files", "epoch": 1, "files": [FILE], "seq": 1})
        assert received(socket)["type"] == "saved"

        # The same id with other bytes, and the same id with none.
        other = {FILE_ID: held_file(FILE_ID, JPEG, "image/jpeg")}
        send_file(client, document(PICTURE, files=other))
        assert received(socket)["files"] == [FILE]
        send_file(client, document(PICTURE))
        assert received(socket)["files"] == [FILE]

        assert head(client)["files"] == [FILE]


def test_only_the_elements_and_the_files_of_a_document_are_stored(client: TestClient) -> None:
    dark = document(
        B,
        A,
        appState={"viewBackgroundColor": "#000000", "gridModeEnabled": True, "theme": "dark"},
        source="https://excalidraw.com",
        version=1,
        extra="kept nowhere",
    )

    assert send_file(client, dark).status_code == 200

    # The slot's own document, with the file's elements in drawing order: the
    # background and the grid are not shared, so an import does not bring them.
    assert head(client)["scene"] == {**EMPTY_SCENE, "elements": [A, B]}


def test_an_element_from_an_older_editor_is_stored_with_a_version(client: TestClient) -> None:
    send_file(client, document({"id": "old", "type": "rectangle"}))

    assert head(client)["scene"]["elements"] == [
        {"id": "old", "type": "rectangle", "version": 1, "versionNonce": 0}
    ]


def test_drawing_goes_on_at_the_epoch_of_the_import(repository: Repository, tmp_path: Path) -> None:
    with (
        application(repository, tmp_path) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as one,
        client.websocket_connect(f"/collab?slot={SLOT}") as two,
    ):
        hello(one), hello(two)
        received(one)
        send_file(client, document(A))
        received(one), received(two)

        # Sent for the scene that went: answered with the scene, and applied nowhere.
        one.send_json({"type": "elements", "epoch": 1, "elements": [C], "seq": 1})
        assert received(one) == {"type": "scene", "epoch": 2, "elements": [A], "files": []}

        saved = draw(one, 2, B, epoch=2)
        assert saved["epoch"] == 2
        assert received(two) == {"type": "elements", "epoch": 2, "elements": [B]}
        assert head(client)["scene"]["elements"] == [A, B]


def test_a_slot_nobody_has_open_can_be_imported_to(drawn: TestClient) -> None:
    response = send_file(drawn, document(C), "Guest3")

    assert (response.json()["revision"], response.json()["epoch"]) == (3, 2)
    assert rows(drawn) == [(3, 2, "Guest3"), (2, 1, "Staff2"), (1, 1, "Guest1")]
    with drawn.websocket_connect(f"/collab?slot={SLOT}") as socket:
        welcome, scene = hello(socket)
        assert (welcome["epoch"], scene["elements"]) == (2, [C])


@pytest.mark.parametrize(
    ("name", "label"),
    [("Bravo2", "Bravo2"), ("José Ana", "José Ana"), (None, "System"), ("x" * 41, "System")],
)
def test_the_row_of_an_import_carries_the_label_the_browser_stores(
    drawn: TestClient, name: str | None, label: str
) -> None:
    send_file(drawn, document(), name)

    assert rows(drawn)[0] == (3, 2, label)
    assert head(drawn)["editorLabel"] == label


def unchanged(client: TestClient) -> None:
    """Assert that the slot of ``drawn`` is as the fixture made it."""
    assert client.get(f"/api/v1/slots/{SLOT}").json()["epoch"] == 1
    assert rows(client) == [(2, 1, "Staff2"), (1, 1, "Guest1")]
    stored = head(client)
    assert (stored["epoch"], stored["scene"]["elements"], stored["files"]) == (1, [A, B], [])


@pytest.mark.parametrize(
    ("body", "status", "error"),
    [
        (b"", 400, "bad_request"),
        (b"[]", 400, "bad_request"),
        (b"not json", 400, "bad_request"),
        (b'{"type": "excalidraw", "elements": [NaN]}', 400, "bad_request"),
        (b"{}", 422, "invalid_document"),
        (b'{"type": "excalidrawlib", "libraryItems": []}', 422, "invalid_document"),
        (body_of(document(elements="x")), 422, "invalid_document"),
        (body_of(document(A, {"id": ""})), 422, "invalid_document"),
        (body_of(document(A, A)), 422, "invalid_document"),
        (b'{"type": "excalidraw", "elements": [{"id": "a", "x": 1e999}]}', 422, "invalid_document"),
        (body_of(document(PICTURE, files={FILE_ID: {"mimeType": "text/html"}})), 422, None),
        (body_of(document(PICTURE, files={FILE_ID: "SECRET"})), 422, "invalid_document"),
    ],
)
def test_a_body_that_is_not_a_scene_document_changes_nothing(
    drawn: TestClient, tmp_path: Path, body: bytes, status: int, error: str | None
) -> None:
    with drawn.websocket_connect(f"/collab?slot={SLOT}") as socket:
        hello(socket)

        response = send_file(drawn, body, "Guest3")

        assert response.status_code == status
        assert response.json()["error"] == (error or "invalid_document")
        assert "SECRET" not in response.text
        # Nobody was sent a scene: the next thing the socket hears is its own rename.
        socket.send_json({"type": "rename", "displayName": "bea"})
        assert received(socket)["type"] == "presence"
    unchanged(drawn)
    assert not (tmp_path / "assets").exists()


def test_the_refusal_says_what_is_wrong_with_the_document(drawn: TestClient) -> None:
    response = send_file(drawn, document(A, {"id": ""}))

    assert response.json() == {
        "error": "invalid_document",
        "message": "That is not an Excalidraw scene: element 2 is not an object with an id.",
    }


def test_a_body_over_the_scene_limit_is_refused(repository: Repository, tmp_path: Path) -> None:
    pad = document(A)
    exact = body_of({**pad, "source": "x" * (2000 - len(body_of({**pad, "source": ""})))})
    assert len(exact) == 2000
    with application(repository, tmp_path, max_scene_bytes=2000) as client:
        over = send_file(client, exact + b" ")

        assert (over.status_code, over.json()["error"]) == (413, "payload_too_large")
        assert over.json()["message"] == "The body is larger than 2000 bytes."
        assert head(client)["epoch"] == 1

        def pieces() -> Iterator[bytes]:
            # No Content-Length: the body is counted as it arrives.
            yield exact[:1000]
            yield exact[1000:] + b" "

        streamed = client.post(IMPORT, content=pieces())
        assert (streamed.status_code, streamed.json()["error"]) == (413, "payload_too_large")
        assert head(client)["epoch"] == 1

        # A body of exactly the limit is taken.
        assert send_file(client, exact).status_code == 200
        assert head(client)["scene"]["elements"] == [A]


def test_elements_over_the_limit_as_they_are_stored_are_refused(
    repository: Repository, tmp_path: Path
) -> None:
    wide = element("wide", 1, text="é" * 300)
    body = body_of(document(wide))
    assert len(body) < 1000 < len(encode(wide))
    with application(repository, tmp_path, max_scene_bytes=1000) as client:
        response = send_file(client, body)

        assert (response.status_code, response.json()["error"]) == (413, "payload_too_large")
        assert response.json()["message"] == "The elements come to more than 1000 bytes."
        assert (head(client)["epoch"], rows(client)) == (1, [])


def test_a_file_over_the_asset_limit_refuses_the_import(
    repository: Repository, tmp_path: Path
) -> None:
    files = {FILE_ID: held_file(FILE_ID, PNG), OTHER_ID: held_file(OTHER_ID, JPEG, "image/jpeg")}
    other = {**PICTURE, "id": "other", "fileId": OTHER_ID}
    with application(repository, tmp_path, max_asset_bytes=len(PNG) - 1) as client:
        response = send_file(client, document(other, PICTURE, files=files))

        assert (response.status_code, response.json()["error"]) == (413, "payload_too_large")
        assert (head(client)["epoch"], rows(client)) == (1, [])
        # Not even the file that fits was stored.
        assert not (tmp_path / "assets").exists()


def test_an_import_from_another_site_changes_nothing(drawn: TestClient) -> None:
    response = drawn.post(
        IMPORT, content=body_of(document()), headers={"Origin": "https://evil.example"}
    )

    assert (response.status_code, response.json()["error"]) == (403, "bad_origin")
    unchanged(drawn)


@pytest.mark.parametrize("slot", ["0", "10", "01", "x"])
def test_an_import_to_no_slot_is_refused(drawn: TestClient, slot: str) -> None:
    response = send_file(drawn, document(), path=f"/api/v1/slots/{slot}/import")

    assert (response.status_code, response.json()["error"]) == (404, "invalid_slot")
    unchanged(drawn)


def test_the_import_route_takes_only_post(drawn: TestClient) -> None:
    for method in ("GET", "PUT", "PATCH", "DELETE"):
        response = drawn.request(method, IMPORT)

        assert (response.status_code, response.json()["error"]) == (405, "method_not_allowed")
        assert response.headers["allow"] == "POST"
    unchanged(drawn)


# The edit gate (docs/TEST-PLAN.md T-008, the import).


def test_with_a_token_a_client_without_it_cannot_import(
    repository: Repository, tmp_path: Path
) -> None:
    with (
        application(repository, tmp_path, **GATED) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as editor,
        client.websocket_connect(f"/collab?slot={SLOT}") as viewer,
    ):
        hello(editor, "Guest1", PASS)
        assert hello(viewer, "Staff2")[0]["viewOnly"] is True
        received(editor)
        draw(editor, 1, A)
        assert received(viewer)["elements"] == [A]

        for edit_pass in (None, "", "wrong", PASS[:-1]):
            refused = send_file(client, document(C), "Staff2", edit_pass=edit_pass)
            assert (refused.status_code, refused.json()["error"]) == (403, "view_only"), edit_pass
        assert (head(client)["epoch"], rows(client)) == (1, [(1, 1, "Guest1")])
        assert not (tmp_path / "assets").exists()

        allowed = send_file(client, document(C), "Guest1", edit_pass=PASS)

        assert (allowed.status_code, allowed.json()["epoch"]) == (200, 2)
        # The viewer is sent the imported scene too.
        for socket in (editor, viewer):
            assert received(socket) == {"type": "scene", "epoch": 2, "elements": [C], "files": []}


def test_without_a_token_configured_anyone_imports(drawn: TestClient) -> None:
    assert send_file(drawn, document(), edit_pass="anything").status_code == 200


def test_the_token_is_checked_before_the_body_is_read(
    repository: Repository, tmp_path: Path
) -> None:
    with application(repository, tmp_path, **GATED, max_scene_bytes=100) as client:
        # Too large, and not JSON: neither is looked at for a client that may not edit.
        refused = send_file(client, b"x" * 500)

        assert (refused.status_code, refused.json()["error"]) == (403, "view_only")
        assert send_file(client, b"x" * 500, edit_pass=PASS).status_code == 413


# With the rooms alone.


def test_an_import_whose_request_is_cancelled_still_reaches_the_room(
    repository: Repository, tmp_path: Path
) -> None:
    # The database is written in a worker thread, which a cancelled request
    # does not stop. The room has to follow it to the new epoch.
    entered, gate = threading.Event(), threading.Event()
    replace_head = repository.replace_head

    def held(*arguments: Any, **options: Any) -> Any:
        entered.set()
        gate.wait(5)
        return replace_head(*arguments, **options)

    repository.replace_head = held

    async def scenario() -> None:
        rooms = Rooms(repository, make_settings(), AssetStore(tmp_path / "assets"))
        room = await rooms.room(SLOT)
        request = asyncio.create_task(rooms.import_scene(SLOT, [A], [FILE], "Guest1"))
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
        assert room.files == {FILE_ID: FILE}
        await asyncio.wait_for(rooms.close(), 10)

    asyncio.run(scenario())
    assert repository.get_head(SLOT).epoch == 2
    assert [file.file_id for file in repository.list_files(SLOT)] == [FILE_ID]


# From running processes.


def send(socket: ClientConnection, seq: int, *elements: dict[str, Any], epoch: int = 1) -> None:
    """Send elements on a real socket, and wait for the ``saved`` that answers them."""
    message = {"type": "elements", "epoch": epoch, "elements": list(elements), "seq": seq}
    socket.send(json.dumps(message))
    saved = next_message(socket)
    assert (saved["type"], saved["seq"]) == ("saved", seq), saved


def test_an_import_survives_a_kill_and_so_do_its_files(tmp_path: Path) -> None:
    """T-009 against a process, and a crash right after the route answered."""
    config = f"head_flush_seconds = {SOON}\nhistory_interval_seconds = {NEVER}\n"
    scene_path = f"/api/v1/slots/{SLOT}/scene"
    files = {FILE_ID: held_file(FILE_ID, PNG)}
    with running_segl(tmp_path, config) as server, server.socket(f"/collab?slot={SLOT}") as one:
        say_hello(one, "Guest1")
        send(one, 1, A)
        # In the head, and in no history row: the next row is an hour away.
        send(one, 2, B)
        exported = document(*server.get(scene_path).json()["scene"]["elements"], PICTURE)
        exported["files"] = files

        cleared = server.post(IMPORT, headers_for("Guest1"), body_of(document()))

        assert (cleared.status, cleared.json()["epoch"]) == (200, 2)
        assert "Set-Cookie" not in cleared.headers
        assert next_message(one) == {"type": "scene", "epoch": 2, "elements": [], "files": []}

        back = server.post(IMPORT, headers_for("José"), body_of(exported))

        assert (back.status, back.json()["revision"], back.json()["epoch"]) == (200, 4, 3)
        scene = next_message(one)
        assert (scene["epoch"], scene["elements"], scene["files"]) == (3, [A, B, PICTURE], [FILE])
        listed = server.get(REVISIONS).json()["revisions"]
        # Row 2 is the drawing the first import replaced, which no row held.
        assert [(row["revision"], row["epoch"], row["authorLabel"]) for row in listed] == [
            (4, 3, "José"),
            (3, 2, "Guest1"),
            (2, 1, "Guest1"),
            (1, 1, "Guest1"),
        ]
        before = server.get(scene_path).json()
        assert before["scene"]["elements"] == [A, B, PICTURE]
        # The log has the route, and no element, no name, and no file.
        server.logged_line(f"POST {IMPORT}")
        for text in ("rectangle", "Jos", "Guest1", "base64", FILE_ID):
            assert text not in server.log(), text
        # The import and its file were on the disk before the route answered.
        server.kill()

    with running_segl(tmp_path, config) as server:
        assert server.get(scene_path).json() == before
        assert server.get(f"/api/v1/assets/{PNG_HASH}").body == PNG
        with server.socket(f"/collab?slot={SLOT}") as two:
            welcome, scene = say_hello(two, "Staff2")
            assert (welcome["epoch"], scene["files"]) == (3, [FILE])
            send(two, 1, C, epoch=3)
        assert "was not saved" not in server.log()
        assert "Traceback" not in server.log()


def test_with_a_token_a_running_server_gates_the_import(tmp_path: Path) -> None:
    """T-008 from a running process, with the codes in the TOML file."""
    config = (
        f"{GATED_TOML}head_flush_seconds = {SOON}\n"
        f"history_interval_seconds = {EVERY_FLUSH}\nmax_scene_bytes = 4000\n"
    )
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

            refused = server.post(IMPORT, headers_for("Staff2"), body_of(document(C)))
            assert (refused.status, refused.json()["error"]) == (403, "view_only")
            assert server.get(f"/api/v1/slots/{SLOT}").json()["epoch"] == 1

            # With a pass, the configured limit is the one that answers.
            large = body_of(document(element("big", 1, text="x" * 4000)))
            over = server.post(IMPORT, headers_for("Guest1", PASS), large)
            assert (over.status, over.json()["error"]) == (413, "payload_too_large")

            allowed = server.post(IMPORT, headers_for("Guest1", PASS), body_of(document(C)))
            assert (allowed.status, allowed.json()["epoch"]) == (200, 2)
            for socket in (editor, viewer):
                assert next_message(socket) == {
                    "type": "scene",
                    "epoch": 2,
                    "elements": [C],
                    "files": [],
                }
        assert PASS not in server.log()
        assert_no_secrets(server.log())


# Through nginx, with the files in deploy/nginx/.


def test_an_import_through_nginx_at_board_and_at_a_host_root(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    config = (
        f"head_flush_seconds = {SOON}\nhistory_interval_seconds = {EVERY_FLUSH}\n"
        "max_scene_bytes = 3000000\n"
    )
    # A file of about two megabytes, most of it one image's bytes.
    large = bytes(range(256)) * 6000
    large_hash = hashlib.sha256(large).hexdigest()
    exported = body_of(document(A, B, PICTURE, files={FILE_ID: held_file(FILE_ID, large)}))
    assert 2_000_000 < len(exported) < 3_000_000
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
                send(one, 1, C)
                assert next_message(two)["elements"] == [C]

                # A page on another site cannot import.
                for other in ("https://evil.example", f"https://{site}"):
                    refused = mount.post(site, f"{api}/import", {"Origin": other}, exported)
                    assert (refused.status, refused.json()["error"]) == (403, "bad_origin"), other
                assert mount.get(site, api).json()["epoch"] == 1

                headers = {**headers_for("Guest1"), "Origin": origin}
                imported = mount.post(site, f"{api}/import", headers, exported)

                assert (imported.status, imported.json()["epoch"]) == (200, 2)
                assert "Set-Cookie" not in imported.headers
                file = {"id": FILE_ID, "hash": large_hash, "mimeType": "image/png"}
                for socket in (one, two):
                    assert next_message(socket) == {
                        "type": "scene",
                        "epoch": 2,
                        "elements": [A, B, PICTURE],
                        "files": [file],
                    }
                fetched = mount.get(site, f"{prefix}/api/v1/assets/{large_hash}")
                assert fetched.body == large
                newest = mount.get(site, f"{api}/revisions").json()["revisions"][0]
                assert (newest["epoch"], newest["authorLabel"]) == (2, "Guest1")

                # Over segl's limit and under nginx's: segl's answer comes through.
                over = mount.post(site, f"{api}/import", headers, exported + b" " * 1_000_000)
                assert (over.status, over.json()["error"]) == (413, "payload_too_large")
                assert mount.get(site, api).json()["epoch"] == 2

        # Outside /board/ the route is nginx's to answer, and segl never sees it.
        small = body_of(document(A))
        outside = mount.post(BOARD_SITE, "/api/v1/slots/1/import", headers_for(), small)
        assert outside.status == 404
        assert b"error" not in outside.body
        mount.segl.logged_line("POST /api/v1/slots/1/import")
        assert "/board/api" not in mount.segl.log()
