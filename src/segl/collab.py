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

"""The collaboration WebSocket, ``/collab?slot=N`` (docs/API.md, "WebSocket").

``Rooms`` holds the nine rooms and loads each from its head the first time it
is asked for. ``serve`` runs one connection: it waits for ``hello``, joins the
room, and then passes each message to ``Room.receive`` until the browser goes.

What the room has for a browser goes into that connection's outbox, and one
task per connection writes it to the socket. A broadcast therefore never waits
for a slow browser. A browser that falls too far behind is disconnected, and
gets the whole scene again when it reconnects.
"""

import asyncio
import contextlib
import json
from collections import deque
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from segl.config import Settings
from segl.origin import refuse_websocket
from segl.repository import SLOT_NUMBERS, Repository, Slot
from segl.room import Connection, Room, encode, may_edit, parse_hello

# How long a new connection has to say hello.
HELLO_SECONDS = 10.0

# What may wait for one browser before segl stops waiting for it. The text is
# ASCII (`room.encode`), so its length is its size in bytes.
OUTBOX_MESSAGES = 1024
OUTBOX_BYTES = 16 * 1024 * 1024

# Close codes (RFC 6455): the browser broke the protocol, or it should try again.
POLICY_VIOLATION = 1008
TRY_AGAIN_LATER = 1013

# A message this long is parsed off the event loop, in a worker thread.
_PARSE_INLINE_CHARACTERS = 64 * 1024

_SLOT_TEXTS = {str(number): number for number in SLOT_NUMBERS}


class Rooms:
    """The room of each slot, made from the slot's head when first needed.

    A room stays for the life of the process, so the nine of them are all
    there will ever be.
    """

    def __init__(self, repository: Repository) -> None:
        self._repository = repository
        self._rooms: dict[int, Room] = {}
        self._locks = {number: asyncio.Lock() for number in SLOT_NUMBERS}

    async def room(self, slot: int) -> Room:
        """Return the room of slot 1 to 9."""
        async with self._locks[slot]:
            room = self._rooms.get(slot)
            if room is None:
                # The repository blocks, so it is called from a worker thread.
                room = await run_in_threadpool(self._load, slot)
                self._rooms[slot] = room
            return room

    async def retitle(self, slot: int, title: str) -> Slot:
        """Store a slot's new title, and tell the slot's room.

        The lock keeps two changes in one order in the database and on the
        sockets, so the last title stored is the last one every browser shows.
        """
        async with self._locks[slot]:
            renamed = await run_in_threadpool(self._repository.rename_slot, slot, title)
            room = self._rooms.get(slot)
            if room is not None:
                room.retitle(renamed.title)
            return renamed

    def _load(self, slot: int) -> Room:
        found = self._repository.get_slot(slot)
        head = self._repository.get_head(slot)
        return Room.from_head(slot, found.title, head.epoch, head.scene_json)


class _Outbox:
    """Text waiting to be written to one socket."""

    def __init__(self) -> None:
        self._texts: deque[str] = deque()
        self._bytes = 0
        self._ready = asyncio.Event()
        # Set when the browser fell too far behind. Nothing more is kept for it.
        self.overflowed = False

    def put(self, text: str) -> None:
        if self.overflowed:
            return
        # One message of any size is always taken: a scene may be larger than the limit.
        too_many = len(self._texts) >= OUTBOX_MESSAGES
        too_much = bool(self._texts) and self._bytes + len(text) > OUTBOX_BYTES
        if too_many or too_much:
            self.overflowed = True
            self._texts.clear()
        else:
            self._texts.append(text)
            self._bytes += len(text)
        self._ready.set()

    async def get(self) -> str | None:
        """Return the next text, or None once the outbox has overflowed."""
        while not self._texts and not self.overflowed:
            self._ready.clear()
            await self._ready.wait()
        if self.overflowed:
            return None
        text = self._texts.popleft()
        self._bytes -= len(text)
        return text


def _not_json(constant: str) -> None:
    # Python would read NaN and Infinity, and write them back out. They are
    # not JSON, and a browser that was sent one could not parse the message.
    raise ValueError(constant)


def parse_message(text: str) -> object:
    """Return a message's JSON.

    Raises:
        ValueError: When the text is not JSON as a browser reads it.
    """
    return json.loads(text, parse_constant=_not_json)


async def _read(websocket: WebSocket) -> object:
    """Return the next message as parsed JSON, or None when it is not JSON text.

    Raises:
        WebSocketDisconnect: When the browser has gone.
    """
    received = await websocket.receive()
    if received["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(received.get("code", 1005))
    text = received.get("text")
    if text is None:
        # A binary frame.
        return None
    try:
        if len(text) > _PARSE_INLINE_CHARACTERS:
            return await run_in_threadpool(parse_message, text)
        return parse_message(text)
    except ValueError, RecursionError:
        return None


async def _write(websocket: WebSocket, outbox: _Outbox) -> None:
    while True:
        text = await outbox.get()
        if text is None:
            await websocket.close(code=TRY_AGAIN_LATER)
            return
        await websocket.send_text(text)


async def _receive(websocket: WebSocket, room: Room, connection: Connection) -> None:
    while True:
        room.receive(connection, await _read(websocket))


async def serve(websocket: WebSocket, rooms: Rooms, settings: Settings) -> None:
    """Run one ``/collab`` connection from its handshake to its end."""
    slot = _SLOT_TEXTS.get(websocket.query_params.get("slot", ""))
    if slot is None:
        refusal: dict[str, Any] = {"error": "invalid_slot", "message": "Slots are numbered 1 to 9."}
        await refuse_websocket(websocket, JSONResponse(refusal, status_code=404))
        return
    room = await rooms.room(slot)
    await websocket.accept()
    try:
        async with asyncio.timeout(HELLO_SECONDS):
            hello = parse_hello(await _read(websocket))
    except TimeoutError, WebSocketDisconnect:
        hello = None
    if hello is None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.send_text(
                encode(
                    {
                        "type": "error",
                        "error": "bad_message",
                        "message": "The first message is hello, with a clientId.",
                    }
                )
            )
            await websocket.close(code=POLICY_VIOLATION)
        return

    outbox = _Outbox()
    connection = Connection(
        outbox.put, hello, view_only=not may_edit(settings.edit_token, hello.edit_token)
    )
    room.join(connection)
    # Two tasks, so that a browser that stops reading does not stop segl
    # hearing that it left. The first to end ends the connection.
    tasks = {
        asyncio.create_task(_receive(websocket, room, connection)),
        asyncio.create_task(_write(websocket, outbox)),
    }
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        room.leave(connection)
        for task in tasks:
            task.cancel()
        # Not gather: when this task is itself being cancelled, gather raises
        # a child's CancelledError in its place, which has lost the
        # canceller's message, and the canceller no longer knows it as its own.
        await asyncio.wait(tasks)
    for task in tasks:
        error = None if task.cancelled() else task.exception()
        # The browser going away is how a connection normally ends.
        if error is not None and not isinstance(error, WebSocketDisconnect | RuntimeError):
            raise error
    if outbox.overflowed:
        return
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await websocket.close()
