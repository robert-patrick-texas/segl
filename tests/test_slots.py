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

"""The slot routes over a temporary database, in process and from a running
``segl`` process (S-003)."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from harness import DISPLAY_NAMES_FILE, EMPTY_SCENE, make_settings, running_segl

from segl import cli
from segl.app import create_app
from segl.repository import Repository, StorageError

SAVED_AT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z")
INVALID_SLOT = {"error": "invalid_slot", "message": "Slots are numbered 1 to 9."}
DRAWN = '{"elements":[{"id":"a","version":1}],"appState":{"viewBackgroundColor":"#fff"}}'

# Not slots: outside 1 to 9, and spellings of a number that int() would take.
# The last two are an Arabic-Indic one, percent-encoded, and a fullwidth one.
NOT_SLOTS = ("0", "10", "-1", "99", "01", "+1", "1.0", "1e0", "abc", " 1", "%D9%A1", "\uff11")


@pytest.fixture
def client(repository: Repository) -> TestClient:
    return TestClient(create_app(make_settings(), repository))


def test_a_new_database_serves_nine_isolated_slots(tmp_path: Path) -> None:
    """The T03 acceptance test: boot a temporary database and read it over HTTP."""
    database = tmp_path / "data" / "segl.sqlite"
    with Repository(database) as repository:
        repository.bootstrap()
        client = TestClient(create_app(make_settings(database=database), repository))

        listed = client.get("/api/v1/slots").json()["slots"]
        assert [slot["title"] for slot in listed] == [f"Workspace {n}" for n in range(1, 10)]
        assert [slot["number"] for slot in listed] == list(range(1, 10))
        assert [client.get(f"/api/v1/slots/{n}").json()["title"] for n in range(1, 10)] == [
            f"Workspace {n}" for n in range(1, 10)
        ]

        # Every slot starts empty, and a scene written to one slot stays in it.
        for n in range(1, 10):
            assert client.get(f"/api/v1/slots/{n}/scene").json()["scene"] == EMPTY_SCENE
        repository.save_head(2, 1, DRAWN, "Bravo2")
        assert client.get("/api/v1/slots/2/scene").json()["scene"] == {
            "elements": [{"id": "a", "version": 1}],
            "appState": {"viewBackgroundColor": "#fff"},
        }
        for n in (1, 3, 4, 5, 6, 7, 8, 9):
            assert client.get(f"/api/v1/slots/{n}/scene").json()["scene"] == EMPTY_SCENE

        for n in (0, 10):
            for path in (f"/api/v1/slots/{n}", f"/api/v1/slots/{n}/scene"):
                refused = client.get(path)
                assert (refused.status_code, refused.json()) == (404, INVALID_SLOT)


def test_the_list_has_number_title_epoch_and_saved_time(client: TestClient) -> None:
    response = client.get("/api/v1/slots")

    assert response.status_code == 200
    assert set(response.json()) == {"slots"}
    slots = response.json()["slots"]
    assert len(slots) == 9
    for number, slot in enumerate(slots, start=1):
        assert set(slot) == {"number", "title", "epoch", "savedAt"}
        assert (slot["number"], slot["title"], slot["epoch"]) == (number, f"Workspace {number}", 1)
        assert SAVED_AT.fullmatch(slot["savedAt"])


def test_one_slot_is_its_entry_in_the_list(client: TestClient, repository: Repository) -> None:
    repository.rename_slot(4, "Data center east")

    listed = client.get("/api/v1/slots").json()["slots"]

    for number in range(1, 10):
        assert client.get(f"/api/v1/slots/{number}").json() == listed[number - 1]
    assert listed[3]["title"] == "Data center east"


def test_the_scene_route_returns_the_head(client: TestClient, repository: Repository) -> None:
    saved_at = repository.save_head(5, 1, DRAWN, "Echo5")

    response = client.get("/api/v1/slots/5/scene")

    assert response.status_code == 200
    assert response.json() == {
        "scene": {
            "elements": [{"id": "a", "version": 1}],
            "appState": {"viewBackgroundColor": "#fff"},
        },
        "epoch": 1,
        "savedAt": saved_at,
        "editorLabel": "Echo5",
        "files": [],
    }
    assert client.get("/api/v1/slots/5").json()["savedAt"] == saved_at


def test_a_new_slots_scene_is_the_editors_empty_scene(client: TestClient) -> None:
    body = client.get("/api/v1/slots/9/scene").json()

    assert body["scene"] == EMPTY_SCENE
    assert body["scene"]["elements"] == []
    assert (body["epoch"], body["editorLabel"], body["files"]) == (1, "System", [])
    assert SAVED_AT.fullmatch(body["savedAt"])


def test_a_replaced_scene_shows_its_new_epoch(client: TestClient, repository: Repository) -> None:
    repository.replace_head(6, DRAWN, "Foxtrot6")

    assert client.get("/api/v1/slots/6").json()["epoch"] == 2
    assert client.get("/api/v1/slots/6/scene").json()["epoch"] == 2
    assert client.get("/api/v1/slots/7/scene").json()["epoch"] == 1


@pytest.mark.parametrize("text", NOT_SLOTS)
@pytest.mark.parametrize("suffix", ["", "/scene"])
def test_anything_but_one_to_nine_is_an_invalid_slot(
    client: TestClient, text: str, suffix: str
) -> None:
    response = client.get(f"/api/v1/slots/{text}{suffix}")

    assert (response.status_code, response.json()) == (404, INVALID_SLOT)
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/slots"),
        ("PUT", "/api/v1/slots"),
        ("DELETE", "/api/v1/slots"),
        ("DELETE", "/api/v1/slots/1"),
        ("PUT", "/api/v1/slots/10"),
        ("DELETE", "/api/v1/slots/1/scene"),
    ],
)
def test_slots_have_no_create_or_delete_route(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)

    assert response.status_code == 405
    assert response.json()["error"] == "method_not_allowed"
    assert len(client.get("/api/v1/slots").json()["slots"]) == 9


def test_the_process_creates_its_database_and_keeps_it_across_restarts(tmp_path: Path) -> None:
    database = tmp_path / "segl.sqlite"

    with running_segl(tmp_path) as server:
        first = server.get("/api/v1/slots")
        assert first.status == 200
        assert [slot["title"] for slot in first.json()["slots"]] == [
            f"Workspace {n}" for n in range(1, 10)
        ]
        assert server.get("/api/v1/slots/1/scene").json()["scene"] == EMPTY_SCENE
        assert server.get("/api/v1/slots/10").json() == INVALID_SLOT
        assert database.is_file()

        # A second connection, while the server holds its own: WAL lets both in.
        with Repository(database) as writer:
            writer.rename_slot(3, "Core routers")
            saved_at = writer.save_head(2, 1, DRAWN, "Bravo2")
        assert server.get("/api/v1/slots/3").json()["title"] == "Core routers"

    with running_segl(tmp_path) as server:
        assert server.get("/api/v1/slots/3").json()["title"] == "Core routers"
        scene = server.get("/api/v1/slots/2/scene").json()
        assert scene["scene"]["elements"] == [{"id": "a", "version": 1}]
        assert (scene["savedAt"], scene["editorLabel"]) == (saved_at, "Bravo2")
        assert server.get("/api/v1/slots/1/scene").json()["scene"] == EMPTY_SCENE
        for reply in (server.get("/api/v1/slots"), server.get("/api/v1/slots/2/scene")):
            assert reply.headers["Set-Cookie"] is None


def test_the_application_closes_the_repository_when_it_shuts_down(
    repository: Repository,
) -> None:
    with TestClient(create_app(make_settings(), repository)) as client:
        assert client.get("/api/v1/slots").status_code == 200

    with pytest.raises(StorageError, match="closed database"):
        repository.list_slots()


def test_a_stopped_process_leaves_one_database_file(tmp_path: Path) -> None:
    """SIGTERM runs the shutdown that closes the database and folds its log in."""
    with running_segl(tmp_path) as server:
        assert server.get("/api/v1/slots").status == 200
        assert (tmp_path / "segl.sqlite-wal").is_file()

    assert sorted(path.name for path in tmp_path.glob("segl.sqlite*")) == ["segl.sqlite"]
    with Repository(tmp_path / "segl.sqlite") as reopened:
        assert len(reopened.list_slots()) == 9


def test_the_command_opens_the_configured_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "var" / "segl.sqlite"
    config = tmp_path / "segl.toml"
    config.write_text(
        f'database = "{database}"\nhistory_limit = 7\ndisplay_names = "{DISPLAY_NAMES_FILE}"\n'
        f'assets_dir = "{tmp_path / "var" / "assets"}"\n',
        encoding="utf-8",
    )
    seen: list[int] = []

    def fake_run(app: FastAPI, **options: object) -> None:
        # The slots are there before the server starts listening.
        seen.append(len(TestClient(app).get("/api/v1/slots").json()["slots"]))

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    assert cli.main(["--config", str(config)]) == 0
    assert seen == [9]
    with Repository(database, history_limit=7) as reopened:
        assert len(reopened.list_slots()) == 9


def test_the_command_reports_a_database_it_cannot_open_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "segl.sqlite"
    database.write_text("this is not a database, and it is long enough to have a header\n" * 4)
    config = tmp_path / "segl.toml"
    config.write_text(f'database = "{database}"\n', encoding="utf-8")
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **options: pytest.fail("segl served"))

    assert cli.main(["--config", str(config)]) == 1

    error = capsys.readouterr().err
    assert error.startswith(f"segl: cannot open the database {database}: ")
    assert error.count("\n") == 1


def test_the_command_refuses_a_database_from_a_newer_segl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "segl.sqlite"
    with closing(sqlite3.connect(database, autocommit=True)) as connection:
        connection.execute("PRAGMA user_version = 9999")
    config = tmp_path / "segl.toml"
    config.write_text(f'database = "{database}"\n', encoding="utf-8")
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **options: pytest.fail("segl served"))

    assert cli.main(["--config", str(config)]) == 1

    assert "has schema 9999" in capsys.readouterr().err
