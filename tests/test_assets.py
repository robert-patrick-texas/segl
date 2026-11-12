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

"""Uploaded files (docs/API.md, "Uploaded files"; docs/SECURITY.md): the store
under ``assets_dir``, the upload route, and the route that serves the bytes,
in process and through nginx."""

import asyncio
import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from harness import (
    BOARD_SITE,
    DISPLAY_NAMES_FILE,
    ROOT_SITE,
    NginxTools,
    make_settings,
    running_mount,
)

from segl import cli
from segl.app import _body as read_body
from segl.app import create_app
from segl.assets import MEDIA_TYPES, AssetsError, AssetStore, is_hash
from segl.repository import Repository

TOKEN = "correct-horse-battery"
# The start of a PNG file, and bytes that are certainly not one.
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
PNG_HASH = hashlib.sha256(PNG).hexdigest()
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.domain)</script></svg>'
LIMIT = 4096


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path / "var" / "assets"


@pytest.fixture
def store(folder: Path) -> AssetStore:
    return AssetStore(folder)


@pytest.fixture
def client(repository: Repository, folder: Path) -> Iterator[TestClient]:
    settings = make_settings(assets_dir=folder, max_asset_bytes=LIMIT)
    with TestClient(create_app(settings, repository)) as client:
        yield client


@pytest.fixture
def gated(repository: Repository, folder: Path) -> Iterator[TestClient]:
    settings = make_settings(assets_dir=folder, edit_token=TOKEN)
    with TestClient(create_app(settings, repository)) as client:
        yield client


def upload(client: TestClient, body: bytes = PNG, kind: str = "image/png", slot: object = 3):
    return client.post(f"/api/v1/slots/{slot}/assets", content=body, headers={"Content-Type": kind})


# The store.


def test_a_file_is_stored_under_the_hash_of_its_bytes(store: AssetStore, folder: Path) -> None:
    name = store.save(PNG)

    assert name == PNG_HASH
    assert (folder / PNG_HASH).read_bytes() == PNG
    assert store.path(name) == folder / PNG_HASH
    assert store.has(name)
    # Nothing else was left in the folder, which did not exist before.
    assert os.listdir(folder) == [PNG_HASH]


def test_bytes_already_stored_are_left_alone(store: AssetStore, folder: Path) -> None:
    store.save(PNG)
    written = (folder / PNG_HASH).stat().st_mtime_ns
    os.utime(folder / PNG_HASH, ns=(written - 10**9, written - 10**9))

    assert store.save(PNG) == PNG_HASH

    assert (folder / PNG_HASH).stat().st_mtime_ns == written - 10**9
    assert os.listdir(folder) == [PNG_HASH]


def test_different_bytes_are_different_files(store: AssetStore, folder: Path) -> None:
    assert store.save(PNG) != store.save(SVG)
    assert sorted(os.listdir(folder)) == sorted([PNG_HASH, hashlib.sha256(SVG).hexdigest()])


def test_a_write_that_fails_leaves_no_half_a_file(
    store: AssetStore, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(source: object, target: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "replace", fail)

    with pytest.raises(OSError, match="no space left"):
        store.save(PNG)

    assert os.listdir(folder) == []
    assert not store.has(PNG_HASH)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
        "../" + "a" * 61,
        "a" * 60 + "/../",
        "." * 64,
        "a" * 64 + "\n",
        # A digit, and not one of 0 to 9.
        chr(0x661) * 64,
        ".upload-abc",
    ],
)
def test_a_name_that_is_not_a_hash_is_no_path(store: AssetStore, name: str) -> None:
    assert not is_hash(name)
    assert store.path(name) is None
    assert not store.has(name)


@pytest.mark.parametrize("value", [None, 7, b"a" * 64, ["a" * 64]])
def test_only_text_is_a_hash(value: object) -> None:
    assert not is_hash(value)


def test_present_says_which_of_some_names_are_stored(store: AssetStore) -> None:
    store.save(PNG)

    assert store.present([PNG_HASH, "b" * 64, "../etc/passwd"]) == frozenset({PNG_HASH})
    assert store.present([]) == frozenset()


def test_a_folder_is_not_a_stored_file(store: AssetStore, folder: Path) -> None:
    (folder / ("c" * 64)).mkdir(parents=True)

    assert not store.has("c" * 64)


def test_prepare_makes_the_folder(store: AssetStore, folder: Path) -> None:
    store.prepare()

    assert folder.is_dir()
    assert os.listdir(folder) == []
    store.prepare()


def test_a_folder_that_cannot_be_made_is_refused_by_name(tmp_path: Path) -> None:
    (tmp_path / "var").write_text("a file where the folder should be", encoding="utf-8")

    with pytest.raises(AssetsError, match="cannot store uploaded files in") as refused:
        AssetStore(tmp_path / "var" / "assets").prepare()

    assert str(tmp_path / "var" / "assets") in str(refused.value)


def test_the_command_stops_when_it_cannot_store_uploaded_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    served: list[object] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **options: served.append(app))
    (tmp_path / "blocked").write_text("a file", encoding="utf-8")
    config = tmp_path / "segl.toml"
    config.write_text(
        f'database = "{tmp_path / "segl.sqlite"}"\n'
        f'display_names = "{DISPLAY_NAMES_FILE}"\n'
        f'assets_dir = "{tmp_path / "blocked" / "assets"}"\n',
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config)]) == 1

    # One line, and nothing was served.
    error = capsys.readouterr().err
    assert error.startswith("segl: cannot store uploaded files in ")
    assert error.count("\n") == 1
    assert served == []


def test_the_media_types_are_the_editors_image_types() -> None:
    # IMAGE_MIME_TYPES of @excalidraw/excalidraw 0.18.1 (D2-028).
    assert sorted(MEDIA_TYPES) == [
        "image/avif",
        "image/bmp",
        "image/gif",
        "image/jfif",
        "image/jpeg",
        "image/png",
        "image/svg+xml",
        "image/webp",
        "image/x-icon",
    ]


# The upload route.


def test_an_upload_is_answered_with_its_hash_and_can_be_fetched(
    client: TestClient, folder: Path
) -> None:
    response = upload(client)

    assert response.status_code == 200
    assert response.json() == {"hash": PNG_HASH, "mediaType": "image/png"}
    assert "set-cookie" not in response.headers
    assert (folder / PNG_HASH).read_bytes() == PNG

    fetched = client.get(f"/api/v1/assets/{PNG_HASH}")
    assert fetched.status_code == 200
    assert fetched.content == PNG
    assert "set-cookie" not in fetched.headers


def test_the_same_bytes_uploaded_to_two_slots_are_one_file(
    client: TestClient, folder: Path
) -> None:
    assert upload(client, slot=1).json() == upload(client, slot=9).json()
    assert os.listdir(folder) == [PNG_HASH]


@pytest.mark.parametrize("kind", sorted(MEDIA_TYPES))
def test_every_image_type_of_the_editor_is_taken(client: TestClient, kind: str) -> None:
    response = upload(client, kind=kind)

    assert response.status_code == 200
    assert response.json()["mediaType"] == kind


@pytest.mark.parametrize(
    ("sent", "answered"),
    [("IMAGE/PNG", "image/png"), ("image/svg+xml; charset=utf-8", "image/svg+xml")],
)
def test_the_type_is_read_without_its_case_or_parameters(
    client: TestClient, sent: str, answered: str
) -> None:
    assert upload(client, kind=sent).json()["mediaType"] == answered


@pytest.mark.parametrize(
    "kind", ["text/html", "application/octet-stream", "application/json", "image/tiff", "image", ""]
)
def test_an_upload_that_is_not_an_image_type_is_refused(
    client: TestClient, folder: Path, kind: str
) -> None:
    response = upload(client, kind=kind)

    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_media_type"
    assert not folder.exists()


def test_an_upload_without_a_type_is_refused(client: TestClient, folder: Path) -> None:
    response = client.post("/api/v1/slots/3/assets", content=PNG)

    assert response.status_code == 415
    assert not folder.exists()


def test_an_upload_of_exactly_the_limit_is_taken(client: TestClient) -> None:
    assert upload(client, b"x" * LIMIT).status_code == 200


def test_an_upload_over_the_limit_is_refused_by_its_declared_length(
    client: TestClient, folder: Path
) -> None:
    response = upload(client, b"x" * (LIMIT + 1))

    assert response.status_code == 413
    assert response.json() == {
        "error": "payload_too_large",
        "message": f"The body is larger than {LIMIT} bytes.",
    }
    assert not folder.exists()


def test_a_body_declared_too_long_is_refused_before_any_of_it_is_read() -> None:
    async def receive() -> dict[str, object]:
        raise AssertionError("the body was read")

    scope = {"type": "http", "method": "POST", "headers": [(b"content-length", b"4097")]}

    refused = asyncio.run(read_body(Request(scope, receive), LIMIT))

    assert isinstance(refused, JSONResponse)
    assert refused.status_code == 413


def test_an_upload_over_the_limit_is_refused_when_no_length_was_declared(
    client: TestClient, folder: Path
) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(LIMIT // 512 + 1):
            yield b"x" * 512

    response = client.post(
        "/api/v1/slots/3/assets", content=chunks(), headers={"Content-Type": "image/png"}
    )

    assert response.request.headers.get("content-length") is None
    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"
    assert not folder.exists()


def test_an_empty_upload_is_refused(client: TestClient, folder: Path) -> None:
    response = upload(client, b"")

    assert response.status_code == 400
    assert response.json() == {"error": "bad_request", "message": "The body is the file's bytes."}
    assert not folder.exists()


@pytest.mark.parametrize("slot", ["0", "10", "01", "abc"])
def test_an_upload_for_no_slot_is_refused(client: TestClient, folder: Path, slot: str) -> None:
    response = upload(client, slot=slot)

    assert response.status_code == 404
    assert response.json()["error"] == "invalid_slot"
    assert not folder.exists()


def test_with_a_token_an_upload_needs_it(gated: TestClient, folder: Path) -> None:
    """S-008: asset writes require the token. Reading a file does not."""
    for headers in ({}, {"X-Segl-Edit-Token": "correct-horse"}, {"X-Segl-Edit-Token": ""}):
        refused = gated.post(
            "/api/v1/slots/3/assets", content=PNG, headers={"Content-Type": "image/png", **headers}
        )
        assert refused.status_code == 403
        assert refused.json() == {"error": "view_only", "message": "Editing needs the edit token."}
    assert not folder.exists()

    allowed = gated.post(
        "/api/v1/slots/3/assets",
        content=PNG,
        headers={"Content-Type": "image/png", "X-Segl-Edit-Token": TOKEN},
    )

    assert allowed.status_code == 200
    assert TOKEN not in allowed.text
    assert gated.get(f"/api/v1/assets/{PNG_HASH}").content == PNG


def test_an_upload_from_a_page_on_another_site_is_refused(client: TestClient, folder: Path) -> None:
    response = client.post(
        "/api/v1/slots/3/assets",
        content=PNG,
        headers={"Content-Type": "image/png", "Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "bad_origin"
    assert not folder.exists()


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
def test_the_upload_path_takes_only_post(client: TestClient, method: str) -> None:
    response = client.request(method, "/api/v1/slots/3/assets")

    assert response.status_code == 405
    assert response.json()["error"] == "method_not_allowed"
    assert response.headers["allow"] == "POST"


# The route that serves the bytes.


def test_a_file_is_served_as_bytes_that_a_browser_will_not_run(client: TestClient) -> None:
    """An uploaded SVG with a script in it must never be a page of this site."""
    name = upload(client, SVG, "image/svg+xml").json()["hash"]

    response = client.get(f"/api/v1/assets/{name}")

    assert response.content == SVG
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    # Named by its content, so a copy never goes stale.
    assert response.headers["cache-control"] == "max-age=31536000, immutable"
    assert response.headers["content-length"] == str(len(SVG))


@pytest.mark.parametrize(
    "name",
    [
        "b" * 64,
        "a" * 63,
        "A" * 64,
        "secret.txt",
        ".upload-abc",
        "..%2Fsegl.sqlite",
        "%2e%2e%2f%2e%2e%2fsegl.toml",
        "a" * 64 + ".png",
    ],
)
def test_a_name_that_is_not_a_stored_hash_is_not_found(
    client: TestClient, folder: Path, name: str
) -> None:
    upload(client)
    # Files segl did not store under a hash are not served, wherever they are.
    (folder / "secret.txt").write_text("not an upload", encoding="utf-8")
    (folder / ".upload-abc").write_text("half an upload", encoding="utf-8")
    (folder.parent / "segl.sqlite").write_text("the database", encoding="utf-8")

    response = client.get(f"/api/v1/assets/{name}")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert "not an upload" not in response.text


def test_a_deeper_path_is_not_an_asset(client: TestClient) -> None:
    upload(client)

    assert client.get(f"/api/v1/assets/{PNG_HASH}/x").status_code == 404
    assert client.get(f"/api/v1/assets/x/{PNG_HASH}").status_code == 404
    assert client.get("/api/v1/assets/").status_code == 404
    assert client.get("/api/v1/assets").status_code == 404


def test_reading_a_file_needs_no_token(gated: TestClient, store: AssetStore) -> None:
    store.save(PNG)

    assert gated.get(f"/api/v1/assets/{PNG_HASH}").content == PNG


def test_a_file_cannot_be_changed_or_deleted_over_http(client: TestClient, folder: Path) -> None:
    upload(client)

    for method in ("PUT", "POST", "PATCH", "DELETE"):
        response = client.request(method, f"/api/v1/assets/{PNG_HASH}", content=b"other")
        assert response.status_code == 405, method
    assert (folder / PNG_HASH).read_bytes() == PNG


def test_a_request_for_part_of_a_file_is_answered(client: TestClient) -> None:
    upload(client)

    response = client.get(f"/api/v1/assets/{PNG_HASH}", headers={"Range": "bytes=0-7"})

    assert response.status_code == 206
    assert response.content == PNG[:8]


# Through nginx, with the files in deploy/nginx/.


def test_an_image_is_uploaded_and_fetched_through_nginx_at_board_and_at_a_host_root(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    config = "max_asset_bytes = 2000000\n"
    with running_mount(tools, certificate, tmp_path, config) as mount:
        for site, prefix, body in ((BOARD_SITE, "/board", PNG), (ROOT_SITE, "", SVG)):
            origin = mount.origin(site)
            headers = {"Content-Type": "image/png", "Origin": origin}
            path = f"{prefix}/api/v1/slots/4/assets"

            stored = mount.post(site, path, headers, body)

            assert stored.status == 200
            assert "Set-Cookie" not in stored.headers
            name = stored.json()["hash"]
            assert name == hashlib.sha256(body).hexdigest()
            fetched = mount.get(site, f"{prefix}/api/v1/assets/{name}")
            assert (fetched.status, fetched.body) == (200, body)
            assert fetched.headers["Content-Type"] == "application/octet-stream"
            # Once: the site example sends it for every answer, and drops segl's own.
            assert fetched.headers.get_all("X-Content-Type-Options") == ["nosniff"]
            assert "Set-Cookie" not in fetched.headers

            # A megabyte passes nginx, which allows 52 MiB, and segl takes it.
            large = os.urandom(1_000_000)
            assert mount.post(site, path, headers, large).status == 200
            # Above segl's own limit, segl is the one that answers.
            refused = mount.post(site, path, headers, os.urandom(2_000_001))
            assert (refused.status, refused.json()["error"]) == (413, "payload_too_large")

            # A page on another site may not upload.
            foreign = mount.post(site, path, {**headers, "Origin": "https://evil.example"}, body)
            assert (foreign.status, foreign.json()["error"]) == (403, "bad_origin")

        # segl saw the paths without /board.
        mount.segl.logged_line("POST /api/v1/slots/4/assets")
        assert "/board/api" not in mount.segl.log()
        # Outside the mount there is no such path: nginx answers, not segl.
        outside = mount.get(BOARD_SITE, f"/api/v1/assets/{PNG_HASH}")
        assert outside.status == 404
        assert b"not_found" not in outside.body
