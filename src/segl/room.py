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

"""One slot's room: who is connected, and the scene they share.

The room is plain state with no I/O of its own. A connection hands it each
message the browser sent (``Room.receive``), and the room answers by calling
``Connection.deliver`` with JSON text for whoever should get it. The WebSocket
route (``segl.collab``) owns the sockets. Every method runs on the event loop,
so nothing here takes a lock. The messages are the ones in docs/API.md.
"""

import hmac
import json
import math
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from segl.names import MAX_NAME_LENGTH, title_case_name
from segl.reconcile import BadElement, Element, adopt_element, check_element, merge, ordered

_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def encode(message: dict[str, Any]) -> str:
    """Return a message as the JSON text that goes on the socket."""
    # ASCII only: a lone surrogate in an element's text stays an escape.
    return json.dumps(message, separators=(",", ":"))


def may_edit(configured: str, given: str | None) -> bool:
    """Return whether a client that sent ``given`` may edit.

    With no token configured, everyone may. Otherwise the two are compared in
    constant time, and a missing token is a wrong one.
    """
    if not configured:
        return True
    return hmac.compare_digest((given or "").encode(), configured.encode())


def stored_name(value: object) -> str | None:
    """Return the label a browser sent in ``hello``, or None when it has none.

    The label is the one the browser stores: a name the server assigned, such
    as ``McKinley7``, or one a person typed, which the browser title-cased. It
    is kept as written, without the spaces around it.
    """
    if not isinstance(value, str):
        return None
    name = value.strip()
    return name if 1 <= len(name) <= MAX_NAME_LENGTH else None


@dataclass(frozen=True)
class Hello:
    """The first message of a connection."""

    client_id: str
    display_name: str | None
    edit_token: str


def parse_hello(message: object) -> Hello | None:
    """Return the fields of a ``hello`` message, or None when it is not one."""
    if not isinstance(message, dict) or message.get("type") != "hello":
        return None
    client_id = message.get("clientId")
    if not isinstance(client_id, str) or _CLIENT_ID.fullmatch(client_id) is None:
        return None
    token = message.get("editToken", "")
    if not isinstance(token, str):
        return None
    return Hello(client_id, stored_name(message.get("displayName")), token)


class Connection:
    """One WebSocket in a room.

    It has no color. The editor draws a connection's cursor in a color it works
    out from the connection id, the same in every browser, and takes no other.
    """

    def __init__(self, deliver: Callable[[str], None], hello: Hello, *, view_only: bool) -> None:
        """``deliver`` takes JSON text for this connection's browser and never blocks."""
        self.deliver = deliver
        self.client_id = hello.client_id
        self.display_name = hello.display_name
        self.view_only = view_only
        # The room sets this when the connection joins.
        self.id = ""
        self.cursor: dict[str, float] | None = None

    def send(self, message: dict[str, Any]) -> None:
        self.deliver(encode(message))

    def error(self, code: str, message: str) -> None:
        self.send({"type": "error", "error": code, "message": message})

    def participant(self) -> dict[str, Any]:
        """Return this connection as the participant list names it."""
        return {"connectionId": self.id, "displayName": self.display_name}

    def presence(self) -> dict[str, Any]:
        return {"type": "presence", **self.participant(), "cursor": self.cursor}


def _cursor(value: object) -> dict[str, float] | None:
    """Return a cursor a browser sent as ``{"x", "y"}``, in scene coordinates.

    Raises:
        ValueError: When it is not two finite numbers.
    """
    if not isinstance(value, dict):
        raise ValueError
    point: dict[str, float] = {}
    for axis in ("x", "y"):
        number = value.get(axis)
        if isinstance(number, bool) or not isinstance(number, int | float):
            raise ValueError
        if not math.isfinite(number):
            raise ValueError
        point[axis] = number
    return point


class Room:
    """The connections on one slot, and the scene as the server holds it.

    The scene starts as the slot's head. Until T07 writes it back, an edit
    lives here, in memory: it outlasts every browser leaving the slot, and a
    restart of segl loses it.
    """

    def __init__(self, slot: int, title: str, epoch: int, elements: list[Element]) -> None:
        self.slot = slot
        self.title = title
        self.epoch = epoch
        self.elements: dict[str, Element] = {element["id"]: element for element in elements}
        # In the order they joined, which is the order of the participant list.
        self.connections: dict[str, Connection] = {}

    @classmethod
    def from_head(cls, slot: int, title: str, epoch: int, scene_json: str) -> Room:
        """Build the room from the stored scene document of the slot's head."""
        document = json.loads(scene_json)
        stored = document.get("elements") if isinstance(document, dict) else None
        adopted = [adopt_element(value) for value in stored] if isinstance(stored, list) else []
        return cls(slot, title, epoch, [element for element in adopted if element is not None])

    def join(self, connection: Connection) -> None:
        """Add a connection, tell it where it is, and tell the others it came."""
        connection.id = self._new_id()
        self.connections[connection.id] = connection
        connection.send(
            {
                "type": "welcome",
                "slot": self.slot,
                "title": self.title,
                "epoch": self.epoch,
                "viewOnly": connection.view_only,
                "connectionId": connection.id,
                "participants": [other.participant() for other in self.connections.values()],
            }
        )
        connection.send(self._scene())
        self._broadcast(connection.presence(), skip=connection)

    def leave(self, connection: Connection) -> None:
        """Remove a connection and tell the others. Leaving twice is harmless."""
        if self.connections.pop(connection.id, None) is None:
            return
        self._broadcast({"type": "presence-end", "connectionId": connection.id})

    def retitle(self, title: str) -> None:
        """Take the slot's new title, which is already stored, and tell every connection."""
        self.title = title
        self._broadcast({"type": "slot", "slot": self.slot, "title": title})

    def receive(self, connection: Connection, message: object) -> None:
        """Act on one message from a joined connection."""
        kind = message.get("type") if isinstance(message, dict) else None
        if not isinstance(message, dict) or not isinstance(kind, str):
            connection.error("bad_message", "A message is a JSON object with a type.")
        elif kind == "elements":
            self._elements(connection, message)
        elif kind == "presence":
            self._presence(connection, message)
        elif kind == "rename":
            self._rename(connection, message)
        elif kind == "hello":
            connection.error("bad_message", "hello is the first message, and is sent once.")
        else:
            connection.error("unknown_type", "segl does not know this message type.")

    def _elements(self, connection: Connection, message: dict[str, Any]) -> None:
        if connection.view_only:
            # Dropped. The scene is unchanged, and nobody is told.
            connection.error("view_only", "Editing needs the edit token.")
            return
        epoch, sent = message.get("epoch"), message.get("elements")
        if isinstance(epoch, bool) or not isinstance(epoch, int) or not isinstance(sent, list):
            connection.error("bad_message", "elements needs an epoch and a list of elements.")
            return
        if epoch != self.epoch:
            # From before a restore or an import. The browser gets the scene
            # it should be on, and its elements are not applied.
            connection.send(self._scene())
            return
        try:
            # All of them, or none: a batch is one edit.
            elements = [check_element(value) for value in sent]
        except BadElement as exc:
            connection.error("bad_message", f"{exc}.")
            return
        winners = merge(self.elements, elements)
        if winners:
            self._broadcast(
                {"type": "elements", "epoch": self.epoch, "elements": winners}, skip=connection
            )

    def _presence(self, connection: Connection, message: dict[str, Any]) -> None:
        cursor = message.get("cursor")
        try:
            connection.cursor = None if cursor is None else _cursor(cursor)
        except ValueError:
            connection.error("bad_message", "A cursor is an x and a y, or null.")
            return
        self._broadcast(connection.presence(), skip=connection)

    def _rename(self, connection: Connection, message: dict[str, Any]) -> None:
        typed = message.get("displayName")
        name = title_case_name(typed) if isinstance(typed, str) else None
        if name is None:
            connection.error("invalid_name", f"A name is 1 to {MAX_NAME_LENGTH} characters.")
            return
        connection.display_name = name
        # The sender too: its own entry in the list is the server's spelling.
        self._broadcast(connection.presence())

    def _scene(self) -> dict[str, Any]:
        return {
            "type": "scene",
            "epoch": self.epoch,
            "elements": ordered(self.elements.values()),
            # The head's uploaded files. T07 adds them.
            "files": [],
        }

    def _broadcast(self, message: dict[str, Any], skip: Connection | None = None) -> None:
        text = encode(message)
        # A copy: delivering may end a connection that has fallen behind.
        for connection in list(self.connections.values()):
            if connection is not skip:
                connection.deliver(text)

    def _new_id(self) -> str:
        while True:
            identifier = secrets.token_urlsafe(9)
            if identifier not in self.connections:
                return identifier
