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

"""The head flushes of one room (docs/DATA-MODEL.md, "Flush and revision
rules"): when the saver writes, what it writes, and who is told.

Each test has a room over a real database in its folder, and no socket. The
intervals are short, or so long that only a leave or a stop can be the reason
for a write.
"""

import asyncio
import json
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from segl import saver as saver_module
from segl.repository import Flush, Repository, SlotFile, StorageError
from segl.room import Connection, Hello, Room
from segl.saver import Saver

SLOT = 2
START = datetime(2026, 11, 12, 9, 0, 0, tzinfo=UTC)
# Longer than any test: a write that happens was not caused by this interval.
NEVER = 3600.0
FILE = {"id": "f" * 40, "hash": "a" * 64, "mimeType": "image/png"}


def element(identifier: str, version: int, **more: object) -> dict[str, Any]:
    return {"id": identifier, "version": version, "versionNonce": 1, **more}


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Browser:
    """A connection in the room, and what the room sent it."""

    def __init__(self, room: Room, name: str | None = "Guest1") -> None:
        self.room = room
        self.received: list[dict[str, Any]] = []
        self.connection = Connection(
            lambda text: self.received.append(json.loads(text)),
            Hello("client-1", name, ""),
            view_only=False,
        )
        room.join(self.connection)

    def draw(self, *elements: dict[str, Any], seq: int | None = None) -> None:
        message: dict[str, Any] = {"type": "elements", "epoch": 1, "elements": list(elements)}
        if seq is not None:
            message["seq"] = seq
        self.room.receive(self.connection, message)

    def leave(self) -> None:
        self.room.leave(self.connection)

    def saved(self) -> list[dict[str, Any]]:
        return [message for message in self.received if message["type"] == "saved"]


class Setup:
    """A room, its saver, and the database under them."""

    def __init__(self, folder: Path, *, flush: float = 0.01, history: float = 1.0) -> None:
        self.clock = Clock()
        self.repository = Repository(folder / "segl.sqlite", clock=self.clock)
        self.repository.bootstrap()
        head = self.repository.get_head(SLOT)
        self.room = Room.from_head(SLOT, "Workspace 2", head.epoch, head.scene_json)
        self.saver = Saver(
            self.room,
            self.repository,
            head_flush_seconds=flush,
            history_interval_seconds=history,
            saved_at=head.saved_at,
        )
        # Every write the saver asked for, as (elements, label, history_seconds).
        self.writes: list[tuple[list[dict[str, Any]], str, float]] = []
        self._flush_head = self.repository.flush_head
        self.repository.flush_head = self._recording  # ty: ignore[invalid-assignment]
        # Set by a test to make the next writes fail, or wait.
        self.failures = 0
        self.gate: threading.Event | None = None
        # Set by a test for a database that never says the history has the head.
        self.never_recorded = False

    def _recording(self, n: int, epoch: int, scene_json: str, label: str, **options: Any) -> Flush:
        self.writes.append((json.loads(scene_json)["elements"], label, options["history_seconds"]))
        if self.gate is not None:
            self.gate.wait(5)
        if self.failures > 0:
            self.failures -= 1
            raise StorageError("the disk is full")
        flush = self._flush_head(n, epoch, scene_json, label, **options)
        return replace(flush, recorded=False) if self.never_recorded else flush

    async def settled(self) -> None:
        """Wait until the saver has nothing left to do."""
        while self.saver._task is not None and not self.saver._task.done():
            await asyncio.wait_for(asyncio.shield(self.saver._task), 5)

    def stored(self) -> list[dict[str, Any]]:
        return json.loads(self.repository.get_head(SLOT).scene_json)["elements"]

    def revisions(self) -> list[int]:
        return [row.revision for row in self.repository.list_revisions(SLOT)]


async def until(condition: Callable[[], bool], seconds: float = 5.0) -> None:
    """Wait for something a test expects, and fail the test rather than wait for ever."""
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.005)


def run(folder: Path, scenario: Callable[[Setup], Awaitable[None]], **options: float) -> Setup:
    """Run a scenario on an event loop of its own, and return the setup for the asserts."""

    async def main() -> Setup:
        setup = Setup(folder, **options)
        try:
            await scenario(setup)
        finally:
            setup.gate = None
            # A stop that does not end is a failure, not a test that never ends.
            await asyncio.wait_for(setup.saver.close(), 10)
        return setup

    return asyncio.run(main())


def test_an_edit_is_written_to_the_head_within_the_flush_interval(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room, "Bravo2")
        setup.clock.advance(5)
        browser.draw(element("a", 1, index="a0"), seq=1)
        # Not at once: the head is flushed, not written on every edit.
        assert setup.writes == []
        await setup.settled()

        head = setup.repository.get_head(SLOT)
        assert json.loads(head.scene_json)["elements"] == [element("a", 1, index="a0")]
        assert (head.editor_label, head.saved_at) == ("Bravo2", "2026-11-12T09:00:05.000Z")
        # The rest of the stored document is the head's own.
        assert json.loads(head.scene_json)["appState"]["viewBackgroundColor"] == "#ffffff"
        assert browser.saved() == [
            {"type": "saved", "epoch": 1, "savedAt": "2026-11-12T09:00:05.000Z", "seq": 1}
        ]
        assert not setup.room.dirty

    setup = run(tmp_path, scenario)
    # The stop wrote nothing more: one write, and the slots beside it untouched.
    assert len(setup.writes) == 1


def test_edits_in_one_interval_are_one_write(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        for version in range(1, 21):
            browser.draw(element("a", version), seq=version)
        await setup.settled()

        assert len(setup.writes) == 1
        assert setup.stored() == [element("a", 20)]
        # One answer, for the newest message.
        assert [message["seq"] for message in browser.saved()] == [20]

    run(tmp_path, scenario, flush=0.05)


def test_the_head_is_not_written_before_the_interval_is_over(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1), seq=1)
        await asyncio.sleep(0.05)

        assert setup.writes == []
        assert browser.saved() == []
        assert setup.room.dirty

    setup = run(tmp_path, scenario, flush=NEVER)
    # The stop is what wrote it.
    assert setup.stored() == [element("a", 1)]


def test_an_edit_during_a_write_is_in_the_next_one(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        setup.gate = threading.Event()
        browser.draw(element("a", 1), seq=1)
        await until(lambda: len(setup.writes) >= 1)
        # The first write is in the worker thread, holding a's first copy.
        browser.draw(element("a", 2), element("b", 1), seq=2)
        assert browser.saved() == []
        setup.gate.set()
        await setup.settled()

        assert [len(elements) for elements, _, _ in setup.writes] == [1, 2]
        assert setup.stored() == [element("a", 2), element("b", 1)]
        # Each answer names what its write held, and no more.
        assert [message["seq"] for message in browser.saved()] == [1, 2]

    run(tmp_path, scenario)


def test_the_last_connection_leaving_flushes_at_once_with_a_history_row(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        one, two = Browser(setup.room, "Alpha1"), Browser(setup.room, "Bravo2")
        one.draw(element("a", 1))
        one.leave()
        await asyncio.sleep(0.05)
        # Someone is still there, and the interval is far off.
        assert setup.writes == []

        two.leave()
        await setup.settled()

        assert setup.stored() == [element("a", 1)]
        assert setup.writes == [([element("a", 1)], "Alpha1", 0)]
        assert setup.revisions() == [1]

    setup = run(tmp_path, scenario, flush=NEVER)
    assert len(setup.writes) == 1


def test_leaving_records_a_head_the_history_does_not_have(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1))
        await setup.settled()
        # Less than a second later: the head is written, and the history waits.
        setup.clock.advance(0.3)
        browser.draw(element("a", 2))
        await setup.settled()
        assert (setup.stored(), setup.revisions()) == ([element("a", 2)], [1])

        setup.clock.advance(0.1)
        browser.leave()
        await setup.settled()

        assert setup.revisions() == [2, 1]
        newest = setup.repository.get_revision(SLOT, 2)
        assert json.loads(newest.scene_json)["elements"] == [element("a", 2)]
        # The head itself was not written again.
        assert setup.repository.get_head(SLOT).saved_at == "2026-11-12T09:00:00.300Z"

    run(tmp_path, scenario)


def test_a_slot_someone_only_looked_at_is_not_written(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        for _ in range(3):
            browser = Browser(setup.room)
            browser.room.receive(browser.connection, {"type": "presence", "cursor": None})
            browser.leave()
        await setup.settled()

        assert setup.saver._task is None

    setup = run(tmp_path, scenario)
    assert setup.writes == []
    assert setup.revisions() == []
    assert setup.repository.get_head(SLOT).editor_label == "System"


def test_coming_back_and_leaving_again_adds_no_second_history_row(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1))
        browser.leave()
        await setup.settled()
        setup.clock.advance(60)

        for _ in range(3):
            Browser(setup.room).leave()
            await setup.settled()

        assert setup.revisions() == [1]
        assert len(setup.writes) == 1

    run(tmp_path, scenario)


def test_history_rows_are_at_most_one_per_interval_while_editing(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        for version in range(1, 5):
            browser.draw(element("a", version))
            await setup.settled()
            setup.clock.advance(0.5)

        # Four flushes, half a second apart, with a two-second interval.
        assert len(setup.writes) == 4
        assert setup.revisions() == [1]
        assert {history for _, _, history in setup.writes} == {2.0}

        setup.clock.advance(1)
        browser.draw(element("a", 5))
        await setup.settled()
        assert setup.revisions() == [2, 1]

    run(tmp_path, scenario, history=2.0)


def test_stopping_writes_what_is_unwritten_with_a_history_row(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room, "Bravo2")
        browser.draw(element("a", 1), seq=1)
        # Still connected, as when segl is stopped under an open browser.

    setup = run(tmp_path, scenario, flush=NEVER)

    assert setup.writes == [([element("a", 1)], "Bravo2", 0)]
    assert setup.stored() == [element("a", 1)]
    assert setup.revisions() == [1]


def test_stopping_records_a_head_the_history_does_not_have(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1))
        await setup.settled()
        setup.clock.advance(0.3)
        browser.draw(element("a", 2))
        await setup.settled()
        assert setup.revisions() == [1]

    setup = run(tmp_path, scenario)

    assert setup.revisions() == [2, 1]


def test_stopping_twice_is_harmless(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        Browser(setup.room).draw(element("a", 1))
        await setup.saver.close()
        await setup.saver.close()

    assert len(run(tmp_path, scenario, flush=NEVER).writes) == 1


def test_an_edit_without_a_label_is_stored_as_system(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        Browser(setup.room, None).draw(element("a", 1))
        await setup.settled()

    setup = run(tmp_path, scenario)

    assert setup.repository.get_head(SLOT).editor_label == "System"
    assert setup.repository.get_revision(SLOT, 1).author_label == "System"


def test_a_question_about_a_clean_room_is_answered_without_a_write(tmp_path: Path) -> None:
    """A browser that reconnects sends an empty, numbered batch to learn it is saved."""

    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(seq=8)
        await setup.settled()

        assert browser.saved() == [
            {"type": "saved", "epoch": 1, "savedAt": "2026-11-12T09:00:00.000Z", "seq": 8}
        ]

    assert run(tmp_path, scenario).writes == []


def test_a_named_file_is_written_with_the_flush(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        message = {"type": "files", "epoch": 1, "files": [FILE], "seq": 1}
        setup.room.receive(browser.connection, message, (FILE["hash"],))
        await setup.settled()

        assert setup.repository.list_files(SLOT) == [SlotFile("f" * 40, "a" * 64, "image/png")]
        assert [message["seq"] for message in browser.saved()] == [1]
        # The scene had not changed, so the head was not written and has no history.
        assert setup.repository.get_head(SLOT).editor_label == "System"
        assert setup.revisions() == []

    run(tmp_path, scenario)


def test_a_write_that_fails_is_tried_again_and_nobody_is_told_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(saver_module, "RETRY_SECONDS", 0.05)

    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        setup.failures = 2
        message = {"type": "files", "epoch": 1, "files": [FILE]}
        setup.room.receive(browser.connection, message, (FILE["hash"],))
        browser.draw(element("secret-drawing", 1), seq=1)
        await until(lambda: len(setup.writes) >= 2)
        # Two writes failed. The room still owes everything, and says nothing.
        assert setup.room.dirty
        assert browser.saved() == []
        assert setup.stored() == []

        await setup.settled()

        assert len(setup.writes) == 3
        assert setup.stored() == [element("secret-drawing", 1)]
        assert len(setup.repository.list_files(SLOT)) == 1
        assert [message["seq"] for message in browser.saved()] == [1]

    with caplog.at_level(logging.ERROR, logger="segl.saver"):
        run(tmp_path, scenario)

    failures = [record for record in caplog.records if record.name == "segl.saver"]
    assert [record.getMessage() for record in failures] == ["slot 2 was not saved"] * 2
    # The slot and the cause, and never the scene.
    assert "the disk is full" in caplog.text
    assert "secret-drawing" not in caplog.text


def test_a_write_that_fails_while_stopping_is_not_tried_for_ever(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        Browser(setup.room).draw(element("a", 1))
        setup.failures = 1000

    setup = run(tmp_path, scenario, flush=NEVER)

    assert len(setup.writes) == 1
    assert setup.stored() == []


def test_a_history_row_that_cannot_be_added_is_asked_for_once(tmp_path: Path) -> None:
    """A leave, and a stop, end although the history never catches up with the head."""

    async def scenario(setup: Setup) -> None:
        setup.never_recorded = True
        browser = Browser(setup.room)
        browser.draw(element("a", 1))
        await setup.settled()
        browser.leave()
        await setup.settled()

        # The edit, and one more try for the leave. Not a write every interval.
        await asyncio.sleep(0.1)
        assert [history for _, _, history in setup.writes] == [1.0, 0]

    setup = run(tmp_path, scenario)
    # The stop asked for nothing more, and ended.
    assert len(setup.writes) == 2


def test_a_slot_that_empties_during_a_write_still_gets_its_history_row(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1))
        await setup.settled()
        setup.clock.advance(0.2)
        # A second edit, whose write is held in the worker thread.
        setup.gate = threading.Event()
        browser.draw(element("a", 2))
        await until(lambda: len(setup.writes) >= 2)
        browser.leave()
        setup.gate.set()
        await setup.settled()

        # The write under way was an ordinary one. The leave got a flush of its own.
        assert [history for _, _, history in setup.writes] == [1.0, 1.0, 0]
        assert setup.revisions() == [2, 1]

    run(tmp_path, scenario)


def test_the_saver_is_how_the_room_reports(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        assert setup.room.on_change == setup.saver._wake
        assert setup.room.on_empty == setup.saver._on_empty

    run(tmp_path, scenario)
