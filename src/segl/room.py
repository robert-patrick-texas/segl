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

The room does not write its scene anywhere either. It says when there is
something to write (``on_change``, ``on_empty``), and ``segl.saver`` takes a
``Snapshot`` of it and writes the slot's head.
"""

import hmac
import json
import math
import re
import secrets
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from typing import Any

from segl.assets import MEDIA_TYPES, is_hash
from segl.names import MAX_NAME_LENGTH, title_case_name
from segl.reconcile import BadElement, Element, adopt_element, check_element, ordered, winners

_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

# The editor's id for an image's file: 40 hex digits, or 40 characters of its
# own alphabet when the browser could not hash the file.
_FILE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

# The most files one `files` message may name.
MAX_FILES_IN_MESSAGE = 256

# The highest number a browser may give a message: the largest whole number
# JavaScript counts exactly.
_MAX_SEQ = 2**53 - 1

# One of a slot's files, as the messages carry it: `id`, `hash`, `mimeType`.
FileEntry = dict[str, str]


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


def parse_files(value: object) -> list[FileEntry] | None:
    """Return the files a ``files`` message names, or None when it is not such a list.

    Each is the editor's file id, the SHA-256 the upload route answered with,
    and one of the image types the editor takes.
    """
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FILES_IN_MESSAGE:
        return None
    files: list[FileEntry] = []
    for entry in value:
        if not isinstance(entry, dict):
            return None
        identifier, name, media_type = entry.get("id"), entry.get("hash"), entry.get("mimeType")
        if not isinstance(identifier, str) or _FILE_ID.fullmatch(identifier) is None:
            return None
        # A list is not text, and cannot be looked up in a set at all.
        if not is_hash(name) or not isinstance(media_type, str) or media_type not in MEDIA_TYPES:
            return None
        files.append({"id": identifier, "hash": name, "mimeType": media_type})
    return files


@dataclass(frozen=True)
class Snapshot:
    """What a head flush writes: a room's scene at one moment.

    ``elements`` is a list of its own, and an element in it is never changed
    afterwards, so a worker thread may turn it into JSON while the room goes on.
    """

    epoch: int
    document: dict[str, Any]
    elements: list[Element]
    # The display name behind the newest change, or None when it had none.
    editor_label: str | None
    # The files named since the last flush, which the slot's file list lacks.
    files: list[FileEntry]

    def scene_json(self) -> str:
        """Return the scene document as it is stored: the head's own, with these elements."""
        return encode({**self.document, "elements": self.elements})


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
        # The number of this connection's newest message that is waiting to
        # be called saved, or None when none is.
        self.awaiting: int | None = None

    def send(self, message: dict[str, Any]) -> None:
        self.deliver(encode(message))

    def error(self, code: str, message: str) -> None:
        self.send({"type": "error", "error": code, "message": message})

    def participant(self) -> dict[str, Any]:
        """Return this connection as the participant list names it."""
        return {"connectionId": self.id, "displayName": self.display_name}

    def presence(self) -> dict[str, Any]:
        return {"type": "presence", **self.participant(), "cursor": self.cursor}


def named_files(files: Iterable[FileEntry], elements: Iterable[object]) -> list[FileEntry]:
    """Return the files, of a slot's list, that these elements name.

    An image element names its file in ``fileId``. A deleted one counts: an
    undo in some browser may bring it back.
    """
    named = set()
    for element in elements:
        file_id = element.get("fileId") if isinstance(element, dict) else None
        if isinstance(file_id, str):
            named.add(file_id)
    return [entry for entry in files if entry["id"] in named]


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


def _nothing() -> None:
    return None


def parse_scene(scene_json: str) -> tuple[dict[str, Any], list[Element]]:
    """Return a stored scene document with its element list emptied, and its elements.

    The document is a head's or a revision's. What in its list is not an
    element is left out.
    """
    document = json.loads(scene_json)
    if not isinstance(document, dict):
        document = {}
    stored = document.get("elements")
    if "elements" in document:
        # Its place among the keys is kept, so that a room nobody changed
        # is stored as the very text it came from.
        document["elements"] = []
    adopted = [adopt_element(value) for value in stored] if isinstance(stored, list) else []
    return document, [element for element in adopted if element is not None]


class Room:
    """The connections on one slot, and the scene as the server holds it.

    The scene starts as the slot's head, and an edit changes it here, in
    memory. The room is ``dirty`` from an edit until a head flush has taken a
    ``snapshot`` of it. It stays for the life of the process, so a drawing
    outlasts every browser leaving the slot.
    """

    def __init__(
        self,
        slot: int,
        title: str,
        epoch: int,
        elements: list[Element],
        *,
        document: dict[str, Any] | None = None,
        files: Iterable[FileEntry] = (),
        max_scene_bytes: int | None = None,
    ) -> None:
        """``document`` is the stored scene document, with its element list emptied.

        ``files`` is the slot's file list. ``max_scene_bytes`` is the most the
        elements may come to, as JSON, or None for no limit.
        """
        self.slot = slot
        self.title = title
        self.epoch = epoch
        self.elements: dict[str, Element] = {element["id"]: element for element in elements}
        self.document: dict[str, Any] = dict(document or {})
        self.files: dict[str, FileEntry] = {entry["id"]: entry for entry in files}
        # The display name behind the newest change. A flush writes only after
        # a change, so the label the head had when the room was loaded is
        # never the one to write.
        self.editor_label: str | None = None
        # In the order they joined, which is the order of the participant list.
        self.connections: dict[str, Connection] = {}
        # True from a change to the scene until a snapshot is taken of it.
        self.dirty = False
        # Called when there is something to write, or someone to tell that
        # their edit is saved, and when the last connection has left.
        self.on_change: Callable[[], None] = _nothing
        self.on_empty: Callable[[], None] = _nothing
        self._new_files: list[FileEntry] = []
        self._max_scene_bytes = max_scene_bytes
        # The size of each element as JSON, and their sum.
        self._sizes = {identifier: len(encode(each)) for identifier, each in self.elements.items()}
        self.size = sum(self._sizes.values())

    @classmethod
    def from_head(
        cls,
        slot: int,
        title: str,
        epoch: int,
        scene_json: str,
        *,
        files: Iterable[FileEntry] = (),
        max_scene_bytes: int | None = None,
    ) -> Room:
        """Build the room from the stored scene document of the slot's head."""
        document, elements = parse_scene(scene_json)
        return cls(
            slot,
            title,
            epoch,
            elements,
            document=document,
            files=files,
            max_scene_bytes=max_scene_bytes,
        )

    @property
    def unsettled(self) -> bool:
        """Whether a flush has something to write, or someone to tell."""
        return self.dirty or any(each.awaiting is not None for each in self.connections.values())

    def snapshot(self) -> Snapshot:
        """Return what a head flush writes now, and count the room as written.

        A flush that then fails gives the snapshot to ``take_back``.
        """
        taken = Snapshot(
            epoch=self.epoch,
            document=self.document,
            elements=ordered(self.elements.values()),
            editor_label=self.editor_label,
            files=self._new_files,
        )
        self.dirty = False
        self._new_files = []
        return taken

    def take_back(self, snapshot: Snapshot) -> None:
        """Take back a snapshot that was not written: the room is dirty again."""
        self.dirty = True
        self._new_files = snapshot.files + self._new_files

    def take_waiting(self) -> list[tuple[Connection, int]]:
        """Return each connection waiting to hear of a save, with the number it is told."""
        waiting: list[tuple[Connection, int]] = []
        for connection in self.connections.values():
            if connection.awaiting is not None:
                waiting.append((connection, connection.awaiting))
                connection.awaiting = None
        return waiting

    def keep_waiting(self, waiting: list[tuple[Connection, int]]) -> None:
        """Put back connections whose flush failed. A newer number stays."""
        for connection, seq in waiting:
            if connection.awaiting is None:
                connection.awaiting = seq

    def saved(self, waiting: list[tuple[Connection, int]], saved_at: str) -> None:
        """Tell the connections of a flush that everything up to their number is saved."""
        for connection, seq in waiting:
            if self.connections.get(connection.id) is connection:
                message = {"type": "saved", "epoch": self.epoch, "savedAt": saved_at, "seq": seq}
                connection.send(message)

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
        if not self.connections:
            self.on_empty()

    def replace(self, epoch: int, scene_json: str) -> None:
        """Put a stored scene in place of the room's, at a new epoch, and tell everyone.

        This is a restore or an import, and the scene is already the slot's
        head. Every connection is sent it, and puts it in place of its own.
        What a connection sent for the scene that went has nothing left to
        wait for: the new epoch says so, and no ``saved`` follows.
        """
        document, elements = parse_scene(scene_json)
        self.epoch = epoch
        self.document = document
        self.elements = {element["id"]: element for element in elements}
        self._sizes = {identifier: len(encode(each)) for identifier, each in self.elements.items()}
        self.size = sum(self._sizes.values())
        self.editor_label = None
        # A file that was named and is not yet in the slot's stored list still
        # has to be written: its id keeps those bytes whatever the scene.
        self.dirty = bool(self._new_files)
        for connection in self.connections.values():
            connection.awaiting = None
        self._broadcast(self._scene())
        if self.dirty:
            self.on_change()

    def retitle(self, title: str) -> None:
        """Take the slot's new title, which is already stored, and tell every connection."""
        self.title = title
        self._broadcast({"type": "slot", "slot": self.slot, "title": title})

    def receive(
        self, connection: Connection, message: object, uploaded: Collection[str] = ()
    ) -> None:
        """Act on one message from a joined connection.

        ``uploaded`` is the hashes a ``files`` message names whose bytes are
        stored. The room reads no disk, so its caller looks.
        """
        kind = message.get("type") if isinstance(message, dict) else None
        if not isinstance(message, dict) or not isinstance(kind, str):
            connection.error("bad_message", "A message is a JSON object with a type.")
        elif kind == "elements":
            self._elements(connection, message)
        elif kind == "files":
            self._files(connection, message, uploaded)
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
        won = winners(self.elements, elements)
        if won:
            texts = {identifier: encode(each) for identifier, each in won.items()}
            grown = sum(len(text) for text in texts.values()) - sum(
                self._sizes.get(identifier, 0) for identifier in won
            )
            limit = self._max_scene_bytes
            if limit is not None and grown > 0 and self.size + grown > limit:
                # A batch that makes the scene smaller is always taken, so a
                # full slot can be emptied.
                connection.error(
                    "scene_too_large", f"The slot's scene may be at most {limit} bytes."
                )
                return
            self.elements.update(won)
            self._sizes.update({identifier: len(text) for identifier, text in texts.items()})
            self.size += grown
            self._changed(connection)
            # The message, from the texts the sizes were taken from.
            head = encode({"type": "elements", "epoch": self.epoch})
            self._send_text(f'{head[:-1]},"elements":[{",".join(texts.values())}]}}', connection)
        self._heard(connection, message)

    def _files(
        self, connection: Connection, message: dict[str, Any], uploaded: Collection[str]
    ) -> None:
        if connection.view_only:
            connection.error("view_only", "Editing needs the edit token.")
            return
        epoch, files = message.get("epoch"), parse_files(message.get("files"))
        if isinstance(epoch, bool) or not isinstance(epoch, int) or files is None:
            connection.error("bad_message", "files needs an epoch and a list of files.")
            return
        if epoch != self.epoch:
            connection.send(self._scene())
            return
        if any(entry["hash"] not in uploaded for entry in files):
            # All of them, or none. The browser uploads the bytes and says so again.
            connection.error("unknown_file", "Upload a file's bytes before naming it.")
            return
        # A file id the slot already has keeps the bytes it had.
        new = [entry for entry in files if entry["id"] not in self.files]
        if new:
            for entry in new:
                self.files[entry["id"]] = entry
            self._new_files.extend(new)
            self._changed(connection)
            self._broadcast({"type": "files", "epoch": self.epoch, "files": new}, skip=connection)
        self._heard(connection, message)

    def _changed(self, connection: Connection) -> None:
        """The scene changed, and this connection changed it."""
        self.dirty = True
        self.editor_label = connection.display_name
        self.on_change()

    def _heard(self, connection: Connection, message: dict[str, Any]) -> None:
        """Note the number on a message that was taken, to answer with ``saved``."""
        seq = message.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool) and 0 <= seq <= _MAX_SEQ:
            connection.awaiting = seq
            self.on_change()

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
        elements = ordered(self.elements.values())
        return {
            "type": "scene",
            "epoch": self.epoch,
            "elements": elements,
            "files": named_files(self.files.values(), elements),
        }

    def _broadcast(self, message: dict[str, Any], skip: Connection | None = None) -> None:
        self._send_text(encode(message), skip)

    def _send_text(self, text: str, skip: Connection | None = None) -> None:
        # A copy: delivering may end a connection that has fallen behind.
        for connection in list(self.connections.values()):
            if connection is not skip:
                connection.deliver(text)

    def _new_id(self) -> str:
        while True:
            identifier = secrets.token_urlsafe(9)
            if identifier not in self.connections:
                return identifier
