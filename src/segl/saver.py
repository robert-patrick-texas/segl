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

"""Writing a room's scene to its slot's head (docs/DATA-MODEL.md, "Flush and
revision rules").

A room says when it has changed. Its ``Saver`` then writes the head within
``head_flush_seconds``, at once when the last connection leaves, and a last
time when segl stops. The repository decides, in the same transaction, whether
the flush also adds a history row. After the write, the connections whose
edits it held are sent ``saved``.

The saver also puts another scene in the room's place: a revision's, for a
restore (``replace``), or a document's, for an import (``put``). That is a
write of the same slot, and it starts a new epoch, so it takes its turn with
the flushes: one lock, and one of them at a time.

Everything here runs on the event loop but the write itself, which a worker
thread does, turning the scene into JSON on the way.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence

from starlette.concurrency import run_in_threadpool

from segl.reconcile import Element
from segl.repository import SYSTEM_LABEL, Flush, Replacement, Repository, SlotFile
from segl.room import FileEntry, Room, Snapshot, encode

logger = logging.getLogger("segl.saver")

# How long after a write failed the next one is tried.
RETRY_SECONDS = 5.0


class Saver:
    """The head flushes of one room."""

    def __init__(
        self,
        room: Room,
        repository: Repository,
        *,
        head_flush_seconds: float,
        history_interval_seconds: float,
        saved_at: str,
    ) -> None:
        """``saved_at`` is when the slot's head was last written."""
        self._room = room
        self._repository = repository
        self._flush_seconds = head_flush_seconds
        self._history_seconds = history_interval_seconds
        self._saved_at = saved_at
        # Set to flush without waiting: the slot emptied, or segl is stopping.
        self._now = asyncio.Event()
        # The slot emptied, and the flush for it has not succeeded yet.
        self._emptied = False
        self._closing = False
        # The head holds a scene that the newest history row does not.
        self._unrecorded = False
        self._task: asyncio.Task[None] | None = None
        # Held by whatever is writing the slot: a flush, or a replacement.
        self._lock = asyncio.Lock()
        room.on_change = self._wake
        room.on_empty = self._on_empty

    async def close(self) -> None:
        """Write whatever is unwritten, for the last time, and stop."""
        self._closing = True
        self._now.set()
        self._wake()
        if self._task is not None:
            await self._task

    async def replace(self, scene_json: str, editor_label: str) -> Replacement:
        """Put a stored scene in the room's place, at a new epoch: a restore.

        First what the room holds is written, with a history row whatever the
        age of the newest one, so that the scene being replaced can be
        restored in its turn. Then the new head, the new epoch, and the row
        for it. Then the room, and every connection is sent the scene.

        An edit that arrives while this is being written was made on the scene
        that is going, and goes with it. When a write fails, the room is as it
        was and the error is raised.
        """
        async with self._lock:
            return await self._swap_in(
                lambda: scene_json,
                editor_label,
                [],
                lambda epoch: self._room.replace(epoch, scene_json),
            )

    async def put(
        self, elements: list[Element], files: Sequence[FileEntry], editor_label: str
    ) -> Replacement:
        """Put these elements in the room's place, at a new epoch: an import.

        The steps are a restore's, and so is what happens to an edit that
        arrives meanwhile and to a write that fails. The scene is the slot's
        own document with these elements, in the order given. ``files`` are
        the ones the elements name whose bytes are stored. Those the slot does
        not have yet join its list in the write that starts the epoch.
        """
        async with self._lock:
            room = self._room
            # The room gets a new document with a new scene and never changes
            # one, so the worker thread may read this one.
            document = room.document
            new = [entry for entry in files if entry["id"] not in room.files]
            return await self._swap_in(
                lambda: encode({**document, "elements": elements}),
                editor_label,
                new,
                lambda epoch: room.put(epoch, document, elements, new),
            )

    async def _swap_in(
        self,
        scene: Callable[[], str],
        editor_label: str,
        files: Sequence[FileEntry],
        arrive: Callable[[int], None],
    ) -> Replacement:
        """Write the room's scene and then the one in its place. The caller holds the lock.

        ``scene`` returns the new scene as it is stored, and is called in the
        worker thread. ``arrive`` takes the new epoch and gives the room the scene.
        """
        room = self._room
        waiting = room.take_waiting()
        # Always, and not only when the room is dirty: after a crash the
        # head may hold a scene that no history row does.
        snapshot = room.snapshot()
        try:
            replacement = await run_in_threadpool(self._swap, snapshot, scene, editor_label, files)
        except BaseException:
            room.take_back(snapshot)
            room.keep_waiting(waiting)
            # The flush that would have told them is the next one.
            self._wake()
            raise
        self._saved_at = replacement.saved_at
        self._unrecorded = False
        # Nobody is told `saved`: the new epoch tells every browser that
        # what it sent for the old scene has nothing left to wait for.
        arrive(replacement.epoch)
        return replacement

    def _on_empty(self) -> None:
        self._emptied = True
        self._now.set()
        self._wake()
        if self._task is None or self._task.done():
            # Nothing is owed, such as to a slot someone only looked at. While
            # a write is under way, what is owed is known only once it ends,
            # and the work then looks again.
            self._emptied = False
            self._now.clear()

    def _wake(self) -> None:
        """Start the work, unless it is already going on."""
        if self._due() and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._work())

    def _due(self) -> bool:
        # A slot that emptied, or a stop, also owes a history row for a head
        # that has none.
        return self._room.unsettled or ((self._emptied or self._closing) and self._unrecorded)

    async def _work(self) -> None:
        """Flush until there is nothing left to write and nobody left to tell."""
        wait = self._flush_seconds
        while self._due():
            if not self._now.is_set():
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(wait):
                        await self._now.wait()
            self._now.clear()
            try:
                await self._flush()
                wait = self._flush_seconds
            except Exception:
                # The slot and no more: a scene is never logged (docs/SECURITY.md).
                logger.exception("slot %d was not saved", self._room.slot)
                if self._closing:
                    return
                wait = max(self._flush_seconds, RETRY_SECONDS)
        # The slot may have emptied during the last write, with nothing left to do for it.
        self._emptied = False
        self._now.clear()

    async def _flush(self) -> None:
        # After a replacement that is under way, and before the next one.
        async with self._lock:
            await self._flush_now()

    async def _flush_now(self) -> None:
        room = self._room
        # The slot may empty again while this flush is being written.
        emptied, self._emptied = self._emptied, False
        # A history row whatever the age of the newest one.
        record = emptied or self._closing
        waiting = room.take_waiting()
        snapshot = room.snapshot() if room.dirty or (record and self._unrecorded) else None
        try:
            if snapshot is not None:
                flush = await run_in_threadpool(self._write, snapshot, record)
                self._saved_at = flush.saved_at
                # A flush that was told to record has done what can be done, so
                # a leave or a stop never asks twice for the same history row.
                self._unrecorded = not (flush.recorded or record)
        except BaseException:
            # Also when this task is cancelled before the worker thread ran.
            if snapshot is not None:
                room.take_back(snapshot)
            room.keep_waiting(waiting)
            self._emptied = self._emptied or emptied
            raise
        room.saved(waiting, self._saved_at)

    def _swap(
        self,
        snapshot: Snapshot,
        scene: Callable[[], str],
        editor_label: str,
        files: Sequence[FileEntry],
    ) -> Replacement:
        """Write the scene that is going, and then the one in its place. A worker thread."""
        self._write(snapshot, record=True)
        return self._repository.replace_head(
            self._room.slot, scene(), editor_label, files=_slot_files(files)
        )

    def _write(self, snapshot: Snapshot, record: bool) -> Flush:
        """Write one snapshot. This runs in a worker thread."""
        return self._repository.flush_head(
            self._room.slot,
            snapshot.epoch,
            snapshot.scene_json(),
            snapshot.editor_label or SYSTEM_LABEL,
            history_seconds=0 if record else self._history_seconds,
            files=_slot_files(snapshot.files),
        )


def _slot_files(files: Sequence[FileEntry]) -> list[SlotFile]:
    """Return a room's file entries as the repository stores them."""
    return [SlotFile(entry["id"], entry["hash"], entry["mimeType"]) for entry in files]
