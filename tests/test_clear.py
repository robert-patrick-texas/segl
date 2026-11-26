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

"""``segl slot clear`` (docs/TEST-PLAN.md T-023, docs/DEPLOY.md "Clearing a slot").

The command runs against a real database and a real folder of images. What
it needs of the machine, systemctl, root, the port, the terminal, and the
log, is a stand-in (``Host``), except in the test of a port that answers.
``web/e2e/lasting.spec.ts`` clears a slot under a browser, and
``deploy/debian/systemd-test.sh`` clears one on the installed package.
"""

import json
import socket
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from harness import EMPTY_SCENE, make_settings

from segl import cli
from segl.app import create_app
from segl.assets import AssetStore
from segl.clear import Clear, Host, amount, run, slot_number
from segl.config import Settings
from segl.repository import Repository, SlotFile, load_empty_scene
from segl.update.paths import INSTALLED, SERVICE
from segl.update.process import RunResult

SLOT = 3
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(200))
GIF = b"GIF89a" + bytes(range(100))


def scene(*elements: dict[str, Any]) -> str:
    return json.dumps({**EMPTY_SCENE, "elements": list(elements)}, separators=(",", ":"))


def element(identifier: str, version: int = 1, **more: object) -> dict[str, Any]:
    return {"id": identifier, "version": version, "versionNonce": 1, **more}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(database=tmp_path / "segl.sqlite", assets_dir=tmp_path / "assets")


@dataclass
class Board:
    """Slot 3 drawn on, with two images, one of which slot 5 names too."""

    settings: Settings
    own: str
    shared: str


@pytest.fixture
def board(settings: Settings) -> Board:
    store = AssetStore(settings.assets_dir)
    own, shared = store.save(PNG), store.save(GIF)
    with Repository(settings.database) as repository:
        repository.bootstrap()
        repository.rename_slot(SLOT, "Workshop")
        files = [SlotFile("f1", own, "image/png"), SlotFile("f2", shared, "image/gif")]
        drawn = [element("a"), element("b"), element("c")]
        repository.flush_head(SLOT, 1, scene(*drawn), "Guest1", history_seconds=0, files=files)
        # c is deleted: the head keeps it, marked so.
        drawn[2] = element("c", 2, isDeleted=True)
        repository.flush_head(SLOT, 1, scene(*drawn), "Guest1", history_seconds=0)
        other = [SlotFile("f9", shared, "image/gif")]
        repository.flush_head(5, 1, scene(element("x")), "Staff2", history_seconds=0, files=other)
    return Board(settings, own, shared)


@dataclass
class FakeHost:
    """A machine with or without segl's unit. Records what the command did."""

    settings: Settings
    unit_running: bool = False
    root: bool = True
    listening: bool = False
    answers_after_start: bool = True
    stop_fails: bool = False
    typed_lines: list[str | None] = field(default_factory=list)
    said: list[str] = field(default_factory=list)
    logged: list[str] = field(default_factory=list)
    # Each systemctl call, with slot 3's title at that moment.
    calls: list[tuple[str, str]] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    def host(self) -> Host:
        return Host(
            run=self.run,
            is_root=lambda: self.root,
            answers=self.answers,
            typed=self.typed,
            say=self.said.append,
            log=self.logged.append,
            sleep=lambda seconds: None,
        )

    def run(
        self, args: Sequence[str], stdin: bytes | None, env: Mapping[str, str] | None
    ) -> RunResult:
        assert args[0] == "systemctl" and args[-1] == SERVICE, args
        action = args[1]
        with Repository(self.settings.database) as repository:
            self.calls.append((action, repository.get_slot(SLOT).title))
        if action == "is-active":
            return RunResult(0 if self.unit_running else 3, "")
        if action == "stop":
            if self.stop_fails:
                return RunResult(1, "Job for segl.service failed")
            self.unit_running = False
        if action == "start":
            self.unit_running = True
        if action == "is-failed":
            return RunResult(1, "")
        return RunResult(0, "")

    def answers(self, host: str, port: int) -> bool:
        assert (host, port) == (self.settings.host, self.settings.port)
        return self.listening or (self.unit_running and self.answers_after_start)

    def typed(self, question: str) -> str | None:
        self.questions.append(question)
        return self.typed_lines.pop(0)


def clear(fake: FakeHost, *slots: int, yes: bool = False, config: Path | None = None) -> int:
    return Clear(fake.settings, config or Path("/srv/segl.toml"), fake.host()).clear(
        list(slots), yes=yes
    )


def state(settings: Settings, slot: int = SLOT) -> tuple[str, int, int, int, str]:
    """A slot's title, epoch, revisions, file rows, and head."""
    with Repository(settings.database) as repository:
        found = repository.get_slot(slot)
        return (
            found.title,
            found.epoch,
            len(repository.list_revisions(slot)),
            len(repository.list_files(slot)),
            repository.get_head(slot).scene_json,
        )


# The write itself.


def test_a_clear_removes_the_scene_title_history_and_files_and_raises_the_epoch(
    board: Board,
) -> None:
    assert state(board.settings)[:4] == ("Workshop", 1, 2, 2)
    before_5 = state(board.settings, 5)

    with Repository(board.settings.database) as repository:
        cleared = repository.clear_slot(SLOT)

        assert cleared.epoch == 2
        # The GIF is slot 5's too, so only the PNG is named by nobody now.
        assert cleared.unnamed == {board.own}
        head = repository.get_head(SLOT)
        assert (head.epoch, head.editor_label) == (2, "System")
    assert state(board.settings) == ("Workspace 3", 2, 0, 0, load_empty_scene())
    assert state(board.settings, 5) == before_5


def test_what_a_clear_would_remove_is_counted_first(board: Board) -> None:
    with Repository(board.settings.database) as repository:
        contents = repository.slot_contents(SLOT)
        outside = repository.hashes_named_outside([SLOT])

    # Two live elements: the deleted one is not counted.
    assert (contents.elements, contents.revisions, contents.files) == (2, 2, 2)
    assert contents.slot.title == "Workshop"
    assert contents.hashes == {board.own, board.shared}
    assert outside == {board.shared}


# The command.


def test_with_yes_the_command_clears_says_each_step_and_logs_it(board: Board) -> None:
    fake = FakeHost(board.settings)
    store = AssetStore(board.settings.assets_dir)

    assert clear(fake, SLOT, yes=True) == 0

    assert state(board.settings) == ("Workspace 3", 2, 0, 0, load_empty_scene())
    # The bytes no other slot names are gone. Slot 5's stay.
    assert not store.has(board.own)
    assert store.has(board.shared)
    assert fake.said == [
        "Slot 3 (Workshop): 2 elements, 2 revisions, 2 files.",
        f"Image files only this slot names: 1, {amount(len(PNG))}. They go too.",
        "A clear cannot be undone.",
        "Cleared slot 3. It is empty, at epoch 2.",
        f"Deleted 1 image file, {amount(len(PNG))}.",
    ]
    assert fake.logged == [
        "slot 3 cleared by segl slot clear: 2 elements, 2 revisions, 2 files, "
        "and 1 image files deleted"
    ]
    assert fake.questions == []
    # No unit on this machine: systemctl was not asked to do anything.
    assert fake.calls == []


def test_the_number_must_be_typed_back(board: Board) -> None:
    before = state(board.settings)
    wrong = FakeHost(board.settings, typed_lines=["4"])

    assert clear(wrong, SLOT) == 1

    assert wrong.questions == ["Type 3 to clear slot 3: "]
    assert wrong.said[-2:] == ["That is not 3.", "Nothing was cleared."]
    assert state(board.settings) == before

    right = FakeHost(board.settings, typed_lines=[" 3\n"])
    assert clear(right, SLOT) == 0
    assert state(board.settings)[:4] == ("Workspace 3", 2, 0, 0)


def test_without_a_terminal_nothing_is_cleared_unless_yes_is_given(board: Board) -> None:
    before = state(board.settings)
    fake = FakeHost(board.settings, typed_lines=[None])

    assert clear(fake, SLOT) == 1

    assert "There is no terminal to ask at: add --yes to clear." in fake.said
    assert state(board.settings) == before
    assert AssetStore(board.settings.assets_dir).has(board.own)


def test_each_slot_is_typed_back_before_any_is_cleared(board: Board) -> None:
    before = (state(board.settings), state(board.settings, 5))
    fake = FakeHost(board.settings, typed_lines=["3", "6"])

    assert clear(fake, SLOT, 5) == 1

    assert fake.questions == ["Type 3 to clear slot 3: ", "Type 5 to clear slot 5: "]
    assert (state(board.settings), state(board.settings, 5)) == before


def test_slots_cleared_together_take_the_images_only_they_name(board: Board) -> None:
    fake = FakeHost(board.settings)
    store = AssetStore(board.settings.assets_dir)
    both = amount(len(PNG) + len(GIF))

    assert clear(fake, 5, SLOT, yes=True) == 0

    assert f"Image files only these slots name: 2, {both}. They go too." in fake.said
    assert not store.has(board.own) and not store.has(board.shared)
    assert fake.said[-1] == f"Deleted 2 image files, {both}."
    assert [line.split(":")[0] for line in fake.logged] == [
        "slot 3 cleared by segl slot clear",
        "slot 5 cleared by segl slot clear",
    ]


def test_without_the_unit_it_refuses_while_segl_answers_on_its_port(board: Board) -> None:
    # A real listener on segl's port, and the command's own way of looking.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        settings = replace(board.settings, port=port)
        fake = FakeHost(settings)
        host = replace(fake.host(), answers=Host().answers)
        before = state(settings)

        status = Clear(settings, Path("/srv/segl.toml"), host).clear([SLOT], yes=True)

    assert status == 1
    assert fake.said == [
        f"segl slot clear: segl answers on 127.0.0.1:{port}. Stop it first: a running "
        "segl holds each open slot in memory, and would write it back."
    ]
    assert state(settings) == before
    # Once nothing answers there, it clears.
    assert Clear(settings, Path("/srv/segl.toml"), host).clear([SLOT], yes=True) == 0


def test_with_the_package_settings_it_stops_the_unit_clears_and_starts_it(board: Board) -> None:
    fake = FakeHost(board.settings, unit_running=True, typed_lines=["3"])

    assert clear(fake, SLOT, config=INSTALLED.config_file) == 0

    # The unit stopped while the slot still held its drawing, and started on the empty one.
    assert fake.calls == [
        ("is-active", "Workshop"),
        ("stop", "Workshop"),
        ("reset-failed", "Workspace 3"),
        ("start", "Workspace 3"),
    ]
    steps = [line for line in fake.said if line.split()[0] in ("Stopping", "Starting", "Cleared")]
    assert steps == [
        f"Stopping {SERVICE}.",
        "Cleared slot 3. It is empty, at epoch 2.",
        f"Starting {SERVICE}.",
    ]
    assert fake.said[-1] == "segl answers again."


def test_stopping_the_unit_needs_root(board: Board) -> None:
    before = state(board.settings)
    fake = FakeHost(board.settings, unit_running=True, root=False)

    assert clear(fake, SLOT, yes=True, config=INSTALLED.config_file) == 2

    assert fake.said == [
        f"segl slot clear: stopping {SERVICE} needs root: sudo segl slot clear ..."
    ]
    assert state(board.settings) == before


def test_a_unit_that_does_not_stop_leaves_the_slot_as_it_was(board: Board) -> None:
    before = state(board.settings)
    fake = FakeHost(board.settings, unit_running=True, stop_fails=True)

    assert clear(fake, SLOT, yes=True, config=INSTALLED.config_file) == 1

    assert fake.said[-1] == "Nothing was cleared."
    assert state(board.settings) == before
    assert [action for action, _ in fake.calls] == ["is-active", "stop"]


def test_a_unit_that_does_not_answer_after_the_clear_fails_the_command(board: Board) -> None:
    fake = FakeHost(board.settings, unit_running=True, answers_after_start=False)

    assert clear(fake, SLOT, yes=True, config=INSTALLED.config_file) == 1

    # The slot was cleared all the same: the clear is done before the start.
    assert state(board.settings)[:2] == ("Workspace 3", 2)
    assert fake.said[-1] == "segl slot clear: segl does not answer; see `journalctl -u segl`"


def test_a_unit_that_is_not_running_is_left_stopped(board: Board) -> None:
    fake = FakeHost(board.settings, unit_running=False)

    assert clear(fake, SLOT, yes=True, config=INSTALLED.config_file) == 0

    assert [action for action, _ in fake.calls] == ["is-active"]
    assert state(board.settings)[:2] == ("Workspace 3", 2)


def test_a_database_from_a_newer_segl_is_refused_and_segl_is_started_again(
    board: Board,
) -> None:
    with closing(sqlite3.connect(board.settings.database)) as connection:
        connection.execute("PRAGMA user_version = 99")
    fake = FakeHost(board.settings, unit_running=True)

    assert clear(fake, SLOT, yes=True, config=INSTALLED.config_file) == 1

    assert [action for action, _ in fake.calls] == ["is-active", "stop", "reset-failed", "start"]
    assert any("a newer segl wrote it" in line for line in fake.said)
    assert state(board.settings)[:3] == ("Workshop", 1, 2)
    assert AssetStore(board.settings.assets_dir).has(board.own)


def test_with_no_database_there_is_nothing_to_clear(settings: Settings) -> None:
    fake = FakeHost(settings)

    assert clear(fake, SLOT, yes=True) == 1

    assert fake.said == [
        f"segl slot clear: there is no database at {settings.database}: nothing to clear"
    ]
    assert not settings.database.exists()


@pytest.mark.parametrize("text", ["0", "10", "-1", "03", "x", ""])
def test_a_slot_outside_1_to_9_is_refused(text: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["slot", "clear", "1", text])

    assert stopped.value.code == 2
    assert "the slots are 1 to 9" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("size", "said"),
    [
        (0, "0 bytes"),
        (1, "1 byte"),
        (1010, "1010 bytes"),
        (1024, "1.0 KiB"),
        (1010 * 1024, "1010.0 KiB"),
        (1024**2, "1.0 MiB"),
        (5 * 1024**2 + 1024**2 // 2, "5.5 MiB"),
    ],
)
def test_sizes_are_said_in_bytes_kib_and_mib(size: int, said: str) -> None:
    assert amount(size) == said


def test_slot_numbers_are_read_as_given() -> None:
    assert [slot_number(str(number)) for number in range(1, 10)] == list(range(1, 10))


def test_the_command_line_clears_a_slot(
    board: Board, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "segl.toml"
    config.write_text(
        f'bind = "127.0.0.1:1"\n'
        f"database = {json.dumps(str(board.settings.database))}\n"
        f"assets_dir = {json.dumps(str(board.settings.assets_dir))}\n",
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config), "slot", "clear", "3", "--yes"]) == 0

    assert "Cleared slot 3. It is empty, at epoch 2." in capsys.readouterr().out
    assert state(board.settings)[:4] == ("Workspace 3", 2, 0, 0)


def test_settings_segl_cannot_read_refuse_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "segl.toml"
    config.write_text("history_limit = 0\n", encoding="utf-8")
    fake = FakeHost(make_settings())

    status = run(_args(config), fake.host())

    assert status == 2
    assert fake.said[0].startswith("segl slot clear: ")
    assert "history_limit" in fake.said[0]


def _args(config: Path) -> Any:
    return cli.build_parser().parse_args(["slot", "clear", "3", "--config", str(config)])


# What a browser that was open on the slot is sent.


def test_after_a_clear_a_browser_that_comes_back_takes_the_empty_board(
    board: Board, tmp_path: Path
) -> None:
    settings = board.settings
    with Repository(settings.database) as repository:
        repository.clear_slot(SLOT)
    with (
        Repository(settings.database) as repository,
        TestClient(create_app(settings, repository)) as client,
        client.websocket_connect(f"/collab?slot={SLOT}") as page,
    ):
        # A page that held the old board, at epoch 1, with no mark of this process.
        page.send_json(
            {"type": "hello", "clientId": "c1", "displayName": "Guest1", "editToken": ""}
        )
        assert page.receive_json()["type"] == "welcome"
        scene_message = page.receive_json()

        assert (scene_message["type"], scene_message["epoch"]) == ("scene", 2)
        assert (scene_message["whole"], scene_message["elements"]) == (True, [])
        # What it still sends for the old board is for another epoch. It is
        # not taken, and the page is sent the empty board again.
        page.send_json({"type": "elements", "epoch": 1, "elements": [element("a", 9)], "seq": 1})
        again = page.receive_json()
        assert (again["type"], again["epoch"], again["elements"]) == ("scene", 2, [])
        assert client.get(f"/api/v1/slots/{SLOT}/scene").json()["scene"]["elements"] == []


@pytest.fixture(autouse=True)
def _no_real_host(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test here asks the real systemctl or writes to the real system log."""
    monkeypatch.setattr("segl.clear._to_log", lambda line: None)
    monkeypatch.setattr(
        "segl.clear.run_command",
        lambda *args: pytest.fail(f"systemctl was run for real: {args}"),
    )
    yield
