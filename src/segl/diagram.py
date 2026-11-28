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

"""Slot 9's room: Diagram mode, drawio's editor (D2-039, D2-040).

The server cannot read a drawio patch: drawio's own code applies them, in
each browser. So the room numbers each patch it takes, in the order it takes
them, and sends it to every browser on the slot, the sender too. Each browser
applies the others' patches in that order.

A browser also sends its whole diagram, its XML, with the number of the last
patch it holds (``base``). The room keeps that copy only when its sender held
every patch before it: every patch after ``base`` is the sender's own. The
copy is slot 9's head, and the saver writes it by T16's rules. Such a patch
is ``exact``. When one is not, its sender sends a ``copy`` once it holds
everything up to it, and ``saved`` waits for a copy that holds the patch.

The pen: a browser that may edit can take it at any time, even from its
holder. While someone holds it, the room takes changes only from the holder,
and refuses the others with ``pen_held``. It is free again when its holder
gives it back or leaves.

A mark names one patch number, as a whiteboard's names one change (D2-037).
The scene route hands out the stored head's mark, ``hello`` hands it back, and
the room then sends the patches after it, or the whole diagram when it no
longer holds them.

A restore is a whiteboard's (D2-030): a new epoch with the revision's diagram,
which every browser loads. While someone holds the pen, only the holder
restores. Each browser's selection goes to the others, as a cursor does (T19).
The server reads the XML only to count the shapes and links, for the rule on a
big delete (``live_cells``).
"""

import json
import re
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any
from xml.parsers import expat

from segl.room import MAX_PAGE_LENGTH, NEEDS_CODE, Connection, Room, Snapshot, encode

# Slot 9 is Diagram mode. Slots 1 to 8 are whiteboards.
DIAGRAM_SLOT = 9

# The diagram a new slot 9 starts with. Every browser loads the same text, so
# its one page has the same id in each, and a patch names that page.
EMPTY_DIAGRAM = (
    '<mxfile><diagram id="segl-page-1" name="Page-1"><mxGraphModel><root>'
    '<mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>'
)

PEN_HELD = "Someone else holds the pen."

# The most cells a selection names. drawio's own sessions send none past it.
MAX_SELECTED_CELLS = 50

# The longest cell id a selection may name.
MAX_CELL_ID_LENGTH = 128

# The id a page gives a patch, so that it knows its own when it comes back.
_PATCH_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

# The largest whole number JavaScript counts exactly.
_MAX_NUMBER = 2**53 - 1


def diagram_document(xml: str) -> str:
    """Return slot 9's head as it is stored: a JSON document that holds the XML."""
    return encode({"diagram": xml})


def empty_diagram() -> str:
    """Return the head a new or cleared slot 9 starts with."""
    return diagram_document(EMPTY_DIAGRAM)


def diagram_of(scene_json: str) -> str:
    """Return the XML a stored head holds, or the empty diagram when it holds none."""
    document = json.loads(scene_json)
    xml = document.get("diagram") if isinstance(document, dict) else None
    return xml if isinstance(xml, str) else EMPTY_DIAGRAM


class PenHeld(Exception):
    """A restore of slot 9 from a connection that does not hold the pen, while another does."""


class _Uncountable(Exception):
    pass


def live_cells(xml: str) -> int | None:
    """Return how many shapes and links a diagram holds, or None when the server cannot tell.

    They are drawio's cells with ``vertex="1"`` or ``edge="1"``, on every
    page, also inside an ``<object>`` or ``<UserObject>``. The XML comes from a
    browser: a DOCTYPE, which could declare entities, makes it uncountable, so
    no entity is ever expanded. So does a page drawio wrote compressed, which
    is text in its ``<diagram>``, and XML that does not parse. This reads the
    whole text, so it runs in a worker thread.
    """
    cells = 0
    # The names of the elements open at this point.
    open_names: list[str] = []

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal cells
        open_names.append(name)
        if name == "mxCell" and "1" in (attributes.get("vertex"), attributes.get("edge")):
            cells += 1

    def end(name: str) -> None:
        open_names.pop()

    def text(data: str) -> None:
        if open_names[-1:] == ["diagram"] and data.strip():
            raise _Uncountable

    def doctype(*_: object) -> None:
        raise _Uncountable

    parser = expat.ParserCreate()
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = doctype
    try:
        parser.Parse(xml, True)
    except _Uncountable, expat.ExpatError, ValueError:
        # ValueError: half a surrogate pair, which JSON can carry and UTF-8 cannot.
        return None
    return cells


def _short_text(value: object, longest: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= longest


def parse_selection(value: object) -> dict[str, Any] | None:
    """Return a selection a browser sent, ``{"page", "cells"}``, or None for nothing selected.

    ``page`` is the id drawio gives the page, or null, as a cursor's. ``cells``
    is 1 to 50 of drawio's cell ids, each text of 1 to 128 characters.

    Raises:
        ValueError: When it is neither null nor such a selection.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError
    page, cells = value.get("page"), value.get("cells")
    if page is not None and not _short_text(page, MAX_PAGE_LENGTH):
        raise ValueError
    if not isinstance(cells, list) or not 1 <= len(cells) <= MAX_SELECTED_CELLS:
        raise ValueError
    if not all(_short_text(cell, MAX_CELL_ID_LENGTH) for cell in cells):
        raise ValueError
    return {"page": page, "cells": cells}


def _selection_message(connection: Connection) -> dict[str, Any]:
    """Return a connection's selection as the others are sent it."""
    return {"type": "selection", "connectionId": connection.id, "selection": connection.selection}


@dataclass(frozen=True)
class Patch:
    """One patch the room took, with its number."""

    n: int
    # The connection that sent it.
    sender: str
    # The page's own id for it.
    pid: str
    patch: dict[str, Any]
    checksum: int | None
    # Its sender held every patch before it, so its copy was kept.
    exact: bool

    def entry(self) -> dict[str, Any]:
        """Return the patch as a ``diagram`` message lists it."""
        return {
            "n": self.n,
            "pid": self.pid,
            "patch": self.patch,
            "checksum": self.checksum,
            "exact": self.exact,
        }


@dataclass(frozen=True)
class DiagramSnapshot(Snapshot):
    """What a head flush of slot 9 writes: the copy the room keeps."""

    def scene_json(self) -> str:
        """Return the head as it is stored, ``{"diagram": xml}``."""
        return encode(self.document)

    def live(self) -> int | None:
        """Return how many shapes and links the copy holds, or None when it cannot be counted."""
        return live_cells(self.document["diagram"])


def _number(value: object) -> int | None:
    """Return a whole number from 0 a message carries, or None."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_NUMBER:
        return None
    return value


def _checksum(value: object) -> tuple[bool, int | None]:
    """Return whether a checksum is usable, and the checksum: a whole number, or null."""
    if value is None:
        return True, None
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > _MAX_NUMBER:
        return False, None
    return True, value


class DiagramRoom(Room):
    """Slot 9's connections, its pen, and the diagram as the server holds it.

    The room holds the copy (``xml``) and the number of the newest patch it
    holds (``copy_count``), and every patch after the stored head's count, so
    that a page that loaded the stored head gets the patches since. It has no
    elements: for the rule on a big delete, the saver counts the copy's shapes
    and links.

    A cursor and a view name the page of the diagram they are on (T18). The
    room keeps each connection's newest selection, and sends it to the others
    (T19).
    """

    pages = True

    def __init__(
        self,
        slot: int,
        title: str,
        epoch: int,
        xml: str,
        *,
        max_scene_bytes: int | None = None,
        start: str | None = None,
        version: str | None = None,
    ) -> None:
        super().__init__(
            slot, title, epoch, [], max_scene_bytes=max_scene_bytes, start=start, version=version
        )
        self.xml = xml
        self.copy_count = 0
        # Every patch after count `trimmed`, oldest first. The others are in
        # the stored head.
        self.patches: list[Patch] = []
        self.trimmed = 0
        self.pen: Connection | None = None
        # By connection id: the number a connection is told `saved` with once
        # a kept copy holds its newest patch. A copy is kept only when it
        # holds every patch the room has taken, so the next one does.
        self._waiting: dict[str, int | None] = {}

    @classmethod
    def from_stored(
        cls,
        slot: int,
        title: str,
        epoch: int,
        scene_json: str,
        *,
        max_scene_bytes: int | None = None,
        start: str | None = None,
        version: str | None = None,
    ) -> DiagramRoom:
        """Build the room from slot 9's stored head."""
        return cls(
            slot,
            title,
            epoch,
            diagram_of(scene_json),
            max_scene_bytes=max_scene_bytes,
            start=start,
            version=version,
        )

    def snapshot(self) -> Snapshot:
        """Return the copy a head flush writes now, and count the room as written."""
        taken = DiagramSnapshot(
            epoch=self.epoch,
            document={"diagram": self.xml},
            elements=[],
            editor_label=self.editor_label,
            files=[],
            count=self.copy_count,
        )
        self.dirty = False
        return taken

    def take_back(self, snapshot: Snapshot) -> None:
        """Take back a snapshot that was not written: the room is dirty again."""
        self.dirty = True

    def live_counter(self) -> Callable[[], int | None]:
        """Return a count of the copy's shapes and links, for a worker thread to call."""
        xml = self.xml
        return lambda: live_cells(xml)

    def may_restore(self, connection_id: object) -> bool:
        """Whether a restore may go ahead: the pen is free, or this id's connection holds it."""
        return self.pen is None or self.pen.id == connection_id

    def replace(self, epoch: int, scene_json: str) -> None:
        """Put a stored diagram in place of the room's, at a new epoch: a restore (D2-030).

        The diagram is already slot 9's head, so the room has nothing to
        write. The old epoch's patches go, and nobody waits for a ``saved``
        for them: the new epoch says so. Every connection is sent the whole
        diagram, as a join's. The pen stays with its holder.
        """
        self.epoch = epoch
        self.xml = diagram_of(scene_json)
        self.patches = []
        # One change, and the head holds every change up to it.
        put_at = self._next_count()
        self.copy_count = self.trimmed = put_at
        self.written = (epoch, put_at)
        self.dirty = False
        self._waiting.clear()
        for connection in self.connections.values():
            connection.awaiting = None
        self._broadcast(self._diagram(None))

    def wrote(self, snapshot: Snapshot) -> None:
        """A flush wrote this copy: the patches it holds are in the stored head."""
        super().wrote(snapshot)
        self.patches = [patch for patch in self.patches if patch.n > snapshot.count]
        self.trimmed = max(self.trimmed, snapshot.count)

    def join(self, connection: Connection, mark: str | None = None) -> None:
        """Add a connection, tell it where it is and who holds the pen, and tell the others."""
        connection.id = self._new_id()
        self.connections[connection.id] = connection
        connection.send(
            {
                "type": "welcome",
                "slot": self.slot,
                "title": self.title,
                "epoch": self.epoch,
                "viewOnly": connection.view_only,
                "editEndsIn": connection.edit_ends_in(),
                "connectionId": connection.id,
                "participants": [other.participant() for other in self.connections.values()],
                "version": self.version,
                "pen": None if self.pen is None else self.pen.id,
            }
        )
        connection.send(self._diagram(self._since(mark)))
        # What the others have selected: they send it again only when it
        # changes. The new connection has selected nothing yet.
        for other in self.connections.values():
            if other.selection is not None:
                connection.send(_selection_message(other))
        self._broadcast(connection.presence(), skip=connection)

    def leave(self, connection: Connection) -> None:
        """Remove a connection. Its pen is free again, and nothing waits for its copy."""
        self._waiting.pop(connection.id, None)
        if self.pen is connection and self.connections.get(connection.id) is connection:
            self.pen = None
            self._broadcast({"type": "pen", "holder": None}, skip=connection)
        super().leave(connection)

    def receive(
        self, connection: Connection, message: object, uploaded: Collection[str] = ()
    ) -> None:
        """Act on one message from a joined connection. Slot 9 takes no files."""
        kind = message.get("type") if isinstance(message, dict) else None
        if not isinstance(message, dict) or not isinstance(kind, str):
            connection.error("bad_message", "A message is a JSON object with a type.")
        elif kind == "patch":
            self._patch(connection, message)
        elif kind == "copy":
            self._copy(connection, message)
        elif kind == "reload":
            connection.send(self._diagram(None))
        elif kind == "pen":
            self._pen(connection, message)
        elif kind == "presence":
            self._presence(connection, message)
        elif kind == "rename":
            self._rename(connection, message)
        elif kind == "follow":
            self._follow(connection, message)
        elif kind == "view":
            self._view(connection, message)
        elif kind == "selection":
            self._selection(connection, message)
        elif kind == "hello":
            connection.error("bad_message", "hello is the first message, and is sent once.")
        else:
            connection.error(
                "unknown_type", "Slot 9 is Diagram mode: segl does not know this type."
            )

    def _selection(self, connection: Connection, message: dict[str, Any]) -> None:
        """Keep a connection's newest selection, and send it to the others.

        Any connection may send one, a viewer too: it changes no diagram.
        """
        try:
            if "selection" not in message:
                raise ValueError
            connection.selection = parse_selection(message["selection"])
        except ValueError:
            connection.error("bad_message", "A selection is a page and 1 to 50 cell ids, or null.")
            return
        self._broadcast(_selection_message(connection), skip=connection)

    def _may_change(self, connection: Connection) -> bool:
        """Whether this connection may change the diagram now. Tell it when not."""
        if connection.may_not_edit():
            connection.error("view_only", NEEDS_CODE)
            return False
        if self.pen is not None and self.pen is not connection:
            connection.error("pen_held", PEN_HELD)
            return False
        return True

    def _fits(self, connection: Connection, xml: str) -> bool:
        """Whether a copy is within the slot's limit. A smaller one always is."""
        limit = self._max_scene_bytes
        # Counted as the head stores it: JSON text, in ASCII.
        size = len(json.dumps(xml))
        if limit is not None and size > limit and size > len(json.dumps(self.xml)):
            connection.error("scene_too_large", f"The slot's scene may be at most {limit} bytes.")
            return False
        return True

    def _patch(self, connection: Connection, message: dict[str, Any]) -> None:
        if not self._may_change(connection):
            return
        epoch, base = message.get("epoch"), _number(message.get("base"))
        pid, patch, xml = message.get("pid"), message.get("patch"), message.get("xml")
        usable, checksum = _checksum(message.get("checksum"))
        if (
            isinstance(epoch, bool)
            or not isinstance(epoch, int)
            or base is None
            or base > self.count
            or not isinstance(pid, str)
            or _PATCH_ID.fullmatch(pid) is None
            or not isinstance(patch, dict)
            or not usable
            or not isinstance(xml, str)
        ):
            connection.error(
                "bad_message", "patch needs an epoch, a base, a pid, a patch, and the xml."
            )
            return
        if epoch != self.epoch:
            connection.send(self._diagram(None))
            return
        if not self._fits(connection, xml):
            return
        exact = self._held(connection, base)
        taken = Patch(self._next_count(), connection.id, pid, patch, checksum, exact)
        self.patches.append(taken)
        self._waiting[connection.id] = self._seq(message)
        self.editor_label = connection.display_name
        if exact:
            self._keep(xml, taken.n)
        self._broadcast(
            {"type": "patch", "epoch": self.epoch, "mark": self.mark(), **taken.entry()}
        )

    def _copy(self, connection: Connection, message: dict[str, Any]) -> None:
        if not self._may_change(connection):
            return
        epoch, base, xml = message.get("epoch"), _number(message.get("base")), message.get("xml")
        if (
            isinstance(epoch, bool)
            or not isinstance(epoch, int)
            or base is None
            or base > self.count
            or not isinstance(xml, str)
        ):
            connection.error("bad_message", "copy needs an epoch, a base, and the xml.")
            return
        if epoch != self.epoch:
            connection.send(self._diagram(None))
            return
        if not self._fits(connection, xml):
            return
        # A copy that does not hold every patch is not kept. The newer one
        # its sender's next patch brings, or another browser's, will be. One
        # that holds every patch may hold more: a change outside the pages,
        # such as a page's background, which comes with no patch.
        if self._held(connection, base):
            self.editor_label = connection.display_name
            self._keep(xml, self.count)

    def _held(self, connection: Connection, base: int) -> bool:
        """Whether a connection that held patch ``base`` holds every patch the room took.

        The patches after ``base`` must all be its own. The room must still
        hold them to tell.
        """
        return base >= self.trimmed and all(
            patch.sender == connection.id for patch in self.patches if patch.n > base
        )

    def _keep(self, xml: str, count: int) -> None:
        """Keep a copy that holds every patch up to ``count``: the head to write."""
        self.xml = xml
        self.copy_count = count
        self.dirty = True
        # The copy holds every patch taken so far: everyone waiting is told
        # `saved` once it is written.
        for identifier, seq in self._waiting.items():
            waiting = self.connections.get(identifier)
            if waiting is not None and seq is not None:
                waiting.awaiting = seq
        self._waiting.clear()
        self.on_change()

    def _pen(self, connection: Connection, message: dict[str, Any]) -> None:
        take = message.get("take")
        if not isinstance(take, bool):
            connection.error("bad_message", "pen needs take, true or false.")
            return
        if take:
            if connection.may_not_edit():
                connection.error("view_only", NEEDS_CODE)
                return
            if self.pen is connection:
                return
            self.pen = connection
        elif self.pen is connection:
            self.pen = None
        else:
            # Only the holder gives the pen back.
            return
        self._broadcast({"type": "pen", "holder": None if self.pen is None else self.pen.id})

    @staticmethod
    def _seq(message: dict[str, Any]) -> int | None:
        seq = message.get("seq")
        return seq if isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0 else None

    def _diagram(self, since: int | None) -> dict[str, Any]:
        """Return the diagram: the patches after count ``since``, or the whole of it.

        The whole is the copy, with every patch after the count it holds.
        Patches after ``since`` are sent only while the room still has them.
        """
        whole = since is None or since < self.trimmed
        after = self.copy_count if whole else since
        message: dict[str, Any] = {
            "type": "diagram",
            "epoch": self.epoch,
            "whole": whole,
            "mark": self.mark(),
            "count": after,
            "patches": [patch.entry() for patch in self.patches if patch.n > after],
        }
        if whole:
            message["xml"] = self.xml
        return message
