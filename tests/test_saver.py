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
from segl.repository import Flush, Replacement, Repository, SlotFile, StorageError
from segl.room import Connection, Hello, Room, encode
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

    def draw(self, *elements: dict[str, Any], seq: int | None = None, epoch: int = 1) -> None:
        message: dict[str, Any] = {"type": "elements", "epoch": epoch, "elements": list(elements)}
        if seq is not None:
            message["seq"] = seq
        self.room.receive(self.connection, message)

    def leave(self) -> None:
        self.room.leave(self.connection)

    def saved(self) -> list[dict[str, Any]]:
        return [message for message in self.received if message["type"] == "saved"]

    def scenes(self) -> list[dict[str, Any]]:
        """Return the scenes sent since the one that came with the welcome."""
        return [message for message in self.received if message["type"] == "scene"][1:]


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


# A restore: another scene in the room's place, at a new epoch.


def scene_text(*elements: dict[str, Any]) -> str:
    """Return a stored scene with these elements, as a history row holds one."""
    return json.dumps({"type": "excalidraw", "elements": list(elements)}, separators=(",", ":"))


def test_a_replacement_writes_the_new_scene_and_sends_it_to_the_room(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        one, two = Browser(setup.room, "Alpha1"), Browser(setup.room, "Bravo2")
        one.draw(element("a", 1, index="a0"), seq=1)
        await setup.settled()
        setup.clock.advance(5)

        replacement = await setup.saver.replace(scene_text(element("z", 3, index="a0")), "Bravo2")

        assert replacement == Replacement(epoch=2, revision=2, saved_at="2026-11-12T09:00:05.000Z")
        head = setup.repository.get_head(SLOT)
        assert (head.epoch, head.editor_label, head.saved_at) == (2, "Bravo2", replacement.saved_at)
        assert json.loads(head.scene_json) == {
            "type": "excalidraw",
            "elements": [element("z", 3, index="a0")],
        }
        # The room is that scene now, and both connections were sent it.
        assert (setup.room.epoch, list(setup.room.elements)) == (2, ["z"])
        expected = {
            "type": "scene",
            "epoch": 2,
            "elements": [element("z", 3, index="a0")],
            "files": [],
        }
        assert one.scenes() == [expected] and two.scenes() == [expected]
        assert not setup.room.dirty
        # Row 1 is the first drawing, which the newest row already held, and
        # row 2 is the replacement.
        assert [(row.revision, row.epoch) for row in setup.repository.list_revisions(SLOT)] == [
            (2, 2),
            (1, 1),
        ]

        # Drawing goes on, and is written at the new epoch.
        two.draw(element("y", 1, index="a1"), seq=1, epoch=2)
        await setup.settled()
        assert two.saved()[-1] == {
            "type": "saved",
            "epoch": 2,
            "savedAt": "2026-11-12T09:00:05.000Z",
            "seq": 1,
        }
        assert [each["id"] for each in setup.stored()] == ["z", "y"]

    run(tmp_path, scenario)


def test_a_replacement_first_records_what_the_room_holds(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room, "Alpha1")
        browser.draw(element("a", 1), seq=1)
        await setup.settled()
        # In the room and nowhere else: its flush has not had its turn.
        other = Browser(setup.room, "Bravo2")
        other.draw(element("b", 1), seq=4)
        assert setup.stored() == [element("a", 1)]

        await setup.saver.replace(scene_text(element("z", 1)), "Charlie3")

        # The room's scene was written with a history row, whatever the age
        # of the newest one, and then the replacement.
        assert setup.writes[-1] == ([element("a", 1), element("b", 1)], "Bravo2", 0)
        listed = setup.repository.list_revisions(SLOT)
        assert [(row.revision, row.epoch, row.author_label) for row in listed] == [
            (3, 2, "Charlie3"),
            (2, 1, "Bravo2"),
            (1, 1, "Alpha1"),
        ]
        going = json.loads(setup.repository.get_revision(SLOT, 2).scene_json)
        assert going["elements"] == [element("a", 1), element("b", 1)]
        # Nobody is told `saved` for the scene that went: the new epoch says it.
        assert other.saved() == []
        assert other.connection.awaiting is None
        assert other.received[-1]["type"] == "scene"

    setup = run(tmp_path, scenario)
    # Nothing was left to write: the flush that was due found a clean room.
    assert len(setup.writes) == 2
    assert setup.stored() == [element("z", 1)]
    assert len(setup.repository.list_revisions(SLOT)) == 3


def test_a_replacement_records_a_head_the_history_does_not_have(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room, "Alpha1")
        browser.draw(element("a", 1), seq=1)
        await setup.settled()
        browser.draw(element("a", 2), seq=2)
        await setup.settled()
        # The head has the second copy, and the history only the first.
        assert setup.revisions() == [1]
        # As after a restart: a room and a saver that know nothing of that.
        head = setup.repository.get_head(SLOT)
        room = Room.from_head(SLOT, "Workspace 2", head.epoch, head.scene_json)
        saver = Saver(
            room,
            setup.repository,
            head_flush_seconds=NEVER,
            history_interval_seconds=NEVER,
            saved_at=head.saved_at,
        )

        await saver.replace(scene_text(element("z", 1)), "Bravo2")

        listed = setup.repository.list_revisions(SLOT)
        # By whoever saved that head, not by `System`.
        assert [(row.revision, row.author_label) for row in listed] == [
            (3, "Bravo2"),
            (2, "Alpha1"),
            (1, "Alpha1"),
        ]
        going = json.loads(setup.repository.get_revision(SLOT, 2).scene_json)
        assert going["elements"] == [element("a", 2)]
        await asyncio.wait_for(saver.close(), 10)
        # The first room is stale now. A test's own, and nothing writes it.
        setup.room.dirty = False

    run(tmp_path, scenario)


def test_a_replacement_waits_for_the_write_that_is_under_way(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        # The first write is held in its worker thread, and no other: a
        # replacement that did not wait for it would write straight past it.
        entered, held = threading.Event(), threading.Event()
        flush_head = setup.repository.flush_head

        def first_held(*arguments: Any, **options: Any) -> Flush:
            if not entered.is_set():
                entered.set()
                held.wait(5)
            return flush_head(*arguments, **options)

        setup.repository.flush_head = first_held
        browser.draw(element("a", 1), seq=1)
        await until(entered.is_set)
        # The flush is in the worker thread, at epoch 1.
        replacing = asyncio.create_task(setup.saver.replace(scene_text(element("z", 1)), "Bravo2"))
        await asyncio.sleep(0.05)
        assert not replacing.done()
        # Nothing has reached the database: the flush is held, and the
        # replacement has not asked for a write of its own.
        assert setup.writes == []
        assert (setup.room.epoch, setup.repository.get_slot(SLOT).epoch) == (1, 1)

        held.set()
        await asyncio.wait_for(replacing, 5)
        await setup.settled()

        # First the flush, with its answer, and then the scene.
        assert [message["type"] for message in browser.received[2:]] == ["saved", "scene"]
        assert browser.saved() == [
            {"type": "saved", "epoch": 1, "savedAt": browser.saved()[0]["savedAt"], "seq": 1}
        ]
        assert setup.stored() == [element("z", 1)]
        assert setup.repository.get_head(SLOT).epoch == 2

    with caplog.at_level(logging.ERROR, logger="segl.saver"):
        run(tmp_path, scenario)
    # No write named an epoch the slot had left.
    assert caplog.records == []


def test_a_flush_waits_for_the_replacement_that_is_under_way(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1), seq=1)
        await setup.settled()
        setup.gate = threading.Event()
        replacing = asyncio.create_task(setup.saver.replace(scene_text(element("z", 1)), "Bravo2"))
        await until(lambda: len(setup.writes) == 2)
        # The replacement is in the worker thread. An edit for the scene that
        # is going arrives, and its flush comes due.
        browser.draw(element("b", 1), seq=2)
        await asyncio.sleep(0.05)
        assert len(setup.writes) == 2

        setup.gate.set()
        await asyncio.wait_for(replacing, 5)
        await setup.settled()

        # The edit went with the scene it was made on. No flush wrote it, and
        # the browser hears of the new scene and not of a save.
        assert setup.stored() == [element("z", 1)]
        assert [message["type"] for message in browser.received[2:]] == ["saved", "scene"]
        assert browser.connection.awaiting is None
        assert not setup.room.unsettled

    with caplog.at_level(logging.ERROR, logger="segl.saver"):
        setup = run(tmp_path, scenario)
    assert caplog.records == []
    # Two writes in all: the first drawing, and the room before it was replaced.
    assert len(setup.writes) == 2


def test_a_replacement_takes_over_from_a_write_that_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(saver_module, "RETRY_SECONDS", 0.1)

    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room, "Alpha1")
        setup.failures = 1
        browser.draw(element("a", 1), seq=1)
        await until(lambda: len(setup.writes) == 1)
        await until(lambda: setup.room.dirty)
        # The flush failed, and the next try is a tenth of a second away.

        await setup.saver.replace(scene_text(element("z", 1)), "Bravo2")

        # The replacement wrote what the failed flush could not, with its row.
        going = json.loads(setup.repository.get_revision(SLOT, 1).scene_json)
        assert going["elements"] == [element("a", 1)]
        await setup.settled()
        await asyncio.sleep(0.2)
        # The try that was waiting found nothing to write.
        assert len(setup.writes) == 2
        assert setup.stored() == [element("z", 1)]

    with caplog.at_level(logging.ERROR, logger="segl.saver"):
        run(tmp_path, scenario)
    # One failure was logged: the first flush, and nothing about an epoch.
    assert len(caplog.records) == 1
    assert "the disk is full" in caplog.text


def test_a_replacement_that_cannot_record_the_room_changes_nothing(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room, "Alpha1")
        browser.draw(element("a", 1), seq=1)
        setup.failures = 1

        with pytest.raises(StorageError):
            await setup.saver.replace(scene_text(element("z", 1)), "Bravo2")

        # The room is as it was, still to be written, and nobody was sent a scene.
        assert (setup.room.epoch, list(setup.room.elements)) == (1, ["a"])
        assert setup.room.dirty
        assert browser.connection.awaiting == 1
        assert browser.scenes() == []
        assert setup.repository.get_slot(SLOT).epoch == 1
        assert setup.revisions() == []

    setup = run(tmp_path, scenario, flush=NEVER)
    # The stop wrote the drawing, and told the browser.
    assert setup.stored() == [element("a", 1)]
    assert setup.repository.get_head(SLOT).epoch == 1


def test_a_replacement_that_cannot_be_written_leaves_the_room_on_its_scene(
    tmp_path: Path,
) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room, "Alpha1")
        browser.draw(element("a", 1), seq=1)

        def failing(*arguments: Any, **options: Any) -> Replacement:
            raise StorageError("the disk is full")

        setup.repository.replace_head = failing

        with pytest.raises(StorageError):
            await setup.saver.replace(scene_text(element("z", 1)), "Bravo2")

        # What the room held was written on the way, and that stays.
        assert setup.stored() == [element("a", 1)]
        assert (setup.room.epoch, list(setup.room.elements)) == (1, ["a"])
        assert setup.repository.get_slot(SLOT).epoch == 1
        assert browser.scenes() == []
        # The browser is still owed its answer, and the saver knows.
        assert browser.connection.awaiting == 1
        await until(lambda: browser.saved() != [])
        assert browser.saved()[0]["seq"] == 1
        assert not setup.room.unsettled

    run(tmp_path, scenario, flush=0.01)


def test_a_file_named_during_a_replacement_is_still_written(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1), seq=1)
        await setup.settled()
        setup.gate = threading.Event()
        replacing = asyncio.create_task(setup.saver.replace(scene_text(element("z", 1)), "Bravo2"))
        await until(lambda: len(setup.writes) == 2)
        setup.room.receive(
            browser.connection, {"type": "files", "epoch": 1, "files": [FILE]}, [FILE["hash"]]
        )

        setup.gate.set()
        await asyncio.wait_for(replacing, 5)
        await setup.settled()

        # A file id keeps its bytes whatever the scene, so the list has it.
        assert setup.repository.list_files(SLOT) == [
            SlotFile(FILE["id"], FILE["hash"], FILE["mimeType"])
        ]
        assert setup.stored() == [element("z", 1)]
        assert not setup.room.dirty

    run(tmp_path, scenario)


def test_two_replacements_at_once_are_two_epochs_in_one_order(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        first = asyncio.create_task(setup.saver.replace(scene_text(element("y", 1)), "Alpha1"))
        second = asyncio.create_task(setup.saver.replace(scene_text(element("z", 1)), "Bravo2"))

        one, two = await asyncio.wait_for(asyncio.gather(first, second), 5)

        assert (one.epoch, two.epoch) == (2, 3)
        assert [scene["epoch"] for scene in browser.scenes()] == [2, 3]
        # The last one written is the one every browser was sent last.
        assert setup.stored() == [element("z", 1)]
        assert browser.scenes()[-1]["elements"] == [element("z", 1)]
        assert setup.room.epoch == setup.repository.get_slot(SLOT).epoch == 3

    run(tmp_path, scenario)


def test_after_a_replacement_a_question_is_answered_with_its_time(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1), seq=1)
        await setup.settled()
        setup.clock.advance(5)
        await setup.saver.replace(scene_text(element("z", 1)), "Bravo2")
        setup.clock.advance(5)

        # An empty numbered batch asks whether everything is saved. It is, and
        # nothing is written for the answer.
        browser.draw(seq=2, epoch=2)
        await setup.settled()

        assert browser.saved()[-1] == {
            "type": "saved",
            "epoch": 2,
            "savedAt": "2026-11-12T09:00:05.000Z",
            "seq": 2,
        }
        assert len(setup.writes) == 2

    run(tmp_path, scenario)


def test_a_replacement_leaves_nothing_owed_to_the_history(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1), seq=1)
        await setup.settled()
        browser.draw(element("a", 2), seq=2)
        await setup.settled()
        # The head is ahead of the history: a leave, or a stop, would owe it a row.
        assert setup.revisions() == [1]

        await setup.saver.replace(scene_text(element("z", 1)), "Bravo2")

        assert setup.revisions() == [3, 2, 1]
        browser.leave()
        await asyncio.sleep(0.05)
        await setup.settled()

    setup = run(tmp_path, scenario)
    # Neither the leave nor the stop wrote again: the replacement kept both scenes.
    assert len(setup.writes) == 3
    assert setup.revisions() == [3, 2, 1]


# An import: the same steps, with a document's elements and files (D2-031).

PICTURE = element("picture", 1, type="image", fileId=FILE["id"], index="a1")
STORED_FILE = SlotFile(FILE["id"], FILE["hash"], FILE["mimeType"])


def test_an_import_writes_its_scene_and_its_files_and_sends_them_to_the_room(
    tmp_path: Path,
) -> None:
    async def scenario(setup: Setup) -> None:
        one, two = Browser(setup.room, "Alpha1"), Browser(setup.room, "Bravo2")
        one.draw(element("a", 1, index="a0"), seq=1)
        await setup.settled()
        before = setup.repository.get_head(SLOT).scene_json
        setup.clock.advance(5)
        imported = [element("z", 3, index="a0"), PICTURE]

        replacement = await setup.saver.put(imported, [FILE], "Bravo2")

        assert replacement == Replacement(epoch=2, revision=2, saved_at="2026-11-12T09:00:05.000Z")
        head = setup.repository.get_head(SLOT)
        assert (head.epoch, head.editor_label, head.saved_at) == (2, "Bravo2", replacement.saved_at)
        # The slot's own document, with the imported elements in its list.
        assert json.loads(head.scene_json) == {**json.loads(before), "elements": imported}
        assert setup.repository.get_revision(SLOT, 2).scene_json == head.scene_json
        assert setup.repository.list_files(SLOT) == [STORED_FILE]
        expected = {"type": "scene", "epoch": 2, "elements": imported, "files": [FILE]}
        assert one.scenes() == [expected] and two.scenes() == [expected]
        assert (setup.room.epoch, list(setup.room.elements)) == (2, ["z", "picture"])
        assert not setup.room.unsettled
        # What the room would write next is the text the head holds.
        assert setup.room.snapshot().scene_json() == head.scene_json

        two.draw(element("y", 1, index="a2"), seq=1, epoch=2)
        await setup.settled()
        assert two.saved()[-1]["epoch"] == 2
        assert [each["id"] for each in setup.stored()] == ["z", "picture", "y"]

    setup = run(tmp_path, scenario)
    # The first drawing, the room before it was replaced, the drawing after,
    # and at the stop the history row that drawing was owed.
    assert len(setup.writes) == 4
    assert setup.revisions() == [3, 2, 1]


def test_an_import_first_records_what_the_room_holds(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room, "Alpha1")
        browser.draw(element("a", 1), seq=1)
        await setup.settled()
        other = Browser(setup.room, "Bravo2")
        other.draw(element("b", 1), seq=4)

        await setup.saver.put([], [], "Charlie3")

        listed = setup.repository.list_revisions(SLOT)
        assert [(row.revision, row.epoch, row.author_label) for row in listed] == [
            (3, 2, "Charlie3"),
            (2, 1, "Bravo2"),
            (1, 1, "Alpha1"),
        ]
        going = json.loads(setup.repository.get_revision(SLOT, 2).scene_json)
        assert going["elements"] == [element("a", 1), element("b", 1)]
        assert setup.stored() == []
        assert other.saved() == [] and other.connection.awaiting is None
        assert other.scenes()[-1]["elements"] == []

    run(tmp_path, scenario)


def test_an_import_that_cannot_be_written_leaves_the_room_and_its_files(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room, "Alpha1")
        browser.draw(element("a", 1), seq=1)

        def failing(*arguments: Any, **options: Any) -> Replacement:
            raise StorageError("the disk is full")

        setup.repository.replace_head = failing

        with pytest.raises(StorageError):
            await setup.saver.put([PICTURE], [FILE], "Bravo2")

        assert (setup.room.epoch, list(setup.room.elements)) == (1, ["a"])
        # The room does not name a file the slot's list was not given.
        assert setup.room.files == {}
        assert setup.repository.list_files(SLOT) == []
        assert browser.scenes() == []
        await until(lambda: browser.saved() != [])
        assert not setup.room.unsettled

    run(tmp_path, scenario, flush=0.01)


def test_an_import_leaves_a_file_id_the_slot_has_with_its_bytes(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        message = {"type": "files", "epoch": 1, "files": [FILE], "seq": 1}
        setup.room.receive(browser.connection, message, (FILE["hash"],))
        await setup.settled()
        other = {**FILE, "hash": "c" * 64}

        await setup.saver.put([PICTURE], [other], "Bravo2")

        assert setup.repository.list_files(SLOT) == [STORED_FILE]
        assert browser.scenes()[-1]["files"] == [FILE]

    run(tmp_path, scenario)


def test_a_file_named_during_an_import_gives_way_to_the_imports(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        browser.draw(element("a", 1), seq=1)
        await setup.settled()
        setup.gate = threading.Event()
        importing = asyncio.create_task(setup.saver.put([PICTURE], [FILE], "Bravo2"))
        await until(lambda: len(setup.writes) == 2)
        # The import is in the worker thread, and the same file id is named
        # on the socket with other bytes.
        other = {**FILE, "hash": "c" * 64}
        setup.room.receive(
            browser.connection, {"type": "files", "epoch": 1, "files": [other]}, [other["hash"]]
        )

        setup.gate.set()
        await asyncio.wait_for(importing, 5)
        await setup.settled()

        # The list was given the import's bytes first, and the room says the same.
        assert setup.repository.list_files(SLOT) == [STORED_FILE]
        assert setup.room.files == {FILE["id"]: FILE}
        assert browser.scenes()[-1]["files"] == [FILE]
        assert not setup.room.dirty

    run(tmp_path, scenario)


def test_an_import_and_a_restore_at_once_are_two_epochs_in_one_order(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        first = asyncio.create_task(setup.saver.put([element("y", 1)], [], "Alpha1"))
        second = asyncio.create_task(setup.saver.replace(scene_text(element("z", 1)), "Bravo2"))

        one, two = await asyncio.wait_for(asyncio.gather(first, second), 5)

        assert (one.epoch, two.epoch) == (2, 3)
        assert [scene["epoch"] for scene in browser.scenes()] == [2, 3]
        assert setup.stored() == [element("z", 1)]
        assert setup.room.epoch == setup.repository.get_slot(SLOT).epoch == 3

    run(tmp_path, scenario)


def test_an_import_waits_for_the_write_that_is_under_way(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        # Only the first write is held, in its worker thread: an import that
        # did not wait for it would write straight past it.
        entered, held = threading.Event(), threading.Event()
        flush_head = setup.repository.flush_head

        def first_held(*arguments: Any, **options: Any) -> Flush:
            if not entered.is_set():
                entered.set()
                held.wait(5)
            return flush_head(*arguments, **options)

        setup.repository.flush_head = first_held
        browser.draw(element("a", 1), seq=1)
        await until(entered.is_set)
        importing = asyncio.create_task(setup.saver.put([element("z", 1)], [], "Bravo2"))
        await asyncio.sleep(0.05)
        assert not importing.done()
        assert setup.repository.get_slot(SLOT).epoch == 1
        assert setup.revisions() == []

        held.set()
        await asyncio.wait_for(importing, 5)

        assert setup.revisions() == [2, 1]
        assert setup.stored() == [element("z", 1)]

    run(tmp_path, scenario)


def test_an_imported_scene_is_stored_as_the_room_would_write_it(tmp_path: Path) -> None:
    async def scenario(setup: Setup) -> None:
        browser = Browser(setup.room)
        text = "caf\u00e9 \ud83d\ude00"
        await setup.saver.put([element("z", 1, text=text, index="a0")], [], "Bravo2")
        head = setup.repository.get_head(SLOT)
        # ASCII, as every stored scene is.
        assert head.scene_json.isascii()
        assert encode({"text": text})[9:-1] in head.scene_json

        # A leave owes the history nothing: the import's row holds this scene.
        browser.leave()
        await asyncio.sleep(0.05)
        await setup.settled()

    setup = run(tmp_path, scenario)
    assert setup.revisions() == [1]
    # Nothing was written for the leave or the stop.
    assert len(setup.writes) == 1
