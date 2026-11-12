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

Everything here runs on the event loop but the write itself, which a worker
thread does, turning the scene into JSON on the way.
"""

import asyncio
import contextlib
import logging

from starlette.concurrency import run_in_threadpool

from segl.repository import SYSTEM_LABEL, Flush, Repository, SlotFile
from segl.room import Room, Snapshot

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
        room.on_change = self._wake
        room.on_empty = self._on_empty

    async def close(self) -> None:
        """Write whatever is unwritten, for the last time, and stop."""
        self._closing = True
        self._now.set()
        self._wake()
        if self._task is not None:
            await self._task

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
                room.restore(snapshot)
            room.keep_waiting(waiting)
            self._emptied = self._emptied or emptied
            raise
        room.saved(waiting, self._saved_at)

    def _write(self, snapshot: Snapshot, record: bool) -> Flush:
        """Write one snapshot. This runs in a worker thread."""
        files = [
            SlotFile(entry["id"], entry["hash"], entry["mimeType"]) for entry in snapshot.files
        ]
        return self._repository.flush_head(
            self._room.slot,
            snapshot.epoch,
            snapshot.scene_json(),
            snapshot.editor_label or SYSTEM_LABEL,
            history_seconds=0 if record else self._history_seconds,
            files=files,
        )
