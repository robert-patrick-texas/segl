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

"""Reading a scene document that is handed in: JSON import (S-011, D2-031).

The body of ``POST api/v1/slots/{n}/import`` is the file the editor's own
export writes, a ``.excalidraw`` file. Of that document segl takes two things:
the elements, and the files of the images among them. The editor writes each
file into the document as a ``data:`` URL. segl keeps files outside a scene
(D2-028), so the bytes come out here, for the caller to store as an upload is
stored. Everything else in the document is left: its ``appState`` holds the
background and the grid, which a slot does not share.

Nothing here touches a database, a folder, or a socket.
"""

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote_to_bytes

from segl.assets import MEDIA_TYPES
from segl.reconcile import Element, adopt_element, ordered
from segl.room import FILE_ID

# What the editor writes as the `type` of a scene document, and looks for
# before it opens one.
DOCUMENT_TYPE = "excalidraw"


class NotJson(ValueError):
    """The body is not a JSON object."""


class InvalidDocument(ValueError):
    """The body is JSON, and is not a scene document segl can take.

    The text says what is wrong, for the response. It never repeats anything
    from the document.
    """


class TooLarge(ValueError):
    """The document's elements, or one of its files, are over a limit."""


@dataclass(frozen=True)
class ImportedFile:
    """The file of an image, as a document carried it."""

    file_id: str
    media_type: str
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class ImportedScene:
    """What an import takes from a document."""

    # In drawing order, each as a room keeps an element.
    elements: list[Element] = field(repr=False)
    # The files those elements name that the document holds.
    files: list[ImportedFile]


def _not_json(constant: str) -> None:
    # NaN and Infinity, which Python would read and write back out.
    raise ValueError(constant)


def _strict(element: Element) -> str:
    """Return an element as the JSON a room writes.

    Raises:
        ValueError: When it holds a number JSON has no way to write. Python
            reads ``1e999`` as infinity, and would write it as ``Infinity``,
            which no browser can parse.
    """
    return json.dumps(element, separators=(",", ":"), allow_nan=False)


def data_url_bytes(url: object) -> bytes | None:
    """Return the bytes a ``data:`` URL holds, or None when the value is not one.

    The editor writes base64. The percent-encoded form is read too, as the
    browser's side reads it (``web/src/collab/dataurl.ts``).
    """
    if not isinstance(url, str) or not url.startswith("data:"):
        return None
    header, comma, payload = url[5:].partition(",")
    if not comma:
        return None
    parameters = [parameter.strip().lower() for parameter in header.split(";")[1:]]
    if "base64" not in parameters:
        return unquote_to_bytes(payload)
    try:
        return base64.b64decode(payload, validate=True)
    except binascii.Error, ValueError:
        return None


def _elements(document: dict[str, Any], max_scene_bytes: int) -> list[Element]:
    listed = document.get("elements")
    if listed is None:
        # The editor opens a document without the key as an empty scene.
        return []
    if not isinstance(listed, list):
        raise InvalidDocument("its elements are not a list")
    elements: list[Element] = []
    seen: set[str] = set()
    size = 0
    for place, value in enumerate(listed, start=1):
        element = adopt_element(value)
        if element is None:
            raise InvalidDocument(f"element {place} is not an object with an id")
        if element["id"] in seen:
            raise InvalidDocument(f"element {place} has the id of an earlier one")
        seen.add(element["id"])
        try:
            size += len(_strict(element))
        except (ValueError, RecursionError) as exc:
            raise InvalidDocument(f"element {place} holds a number that is not JSON") from exc
        if size > max_scene_bytes:
            raise TooLarge(f"The elements come to more than {max_scene_bytes} bytes.")
        elements.append(element)
    return ordered(elements)


def _files(
    document: dict[str, Any], elements: list[Element], max_asset_bytes: int
) -> list[ImportedFile]:
    held = document.get("files")
    if held is None:
        held = {}
    if not isinstance(held, dict):
        raise InvalidDocument("its files are not an object")
    files: list[ImportedFile] = []
    taken: set[str] = set()
    for element in elements:
        file_id = element.get("fileId")
        if not isinstance(file_id, str) or file_id in taken:
            continue
        entry = held.get(file_id)
        if entry is None:
            # An image without its file. The slot may hold the file already,
            # and if not, the image is a placeholder, as in the editor.
            continue
        taken.add(file_id)
        if FILE_ID.fullmatch(file_id) is None or not isinstance(entry, dict):
            raise InvalidDocument("an image names a file that is not one")
        media_type = entry.get("mimeType")
        if not isinstance(media_type, str) or media_type not in MEDIA_TYPES:
            raise InvalidDocument("an image's file is not of an image type segl takes")
        data = data_url_bytes(entry.get("dataURL"))
        if not data:
            raise InvalidDocument("an image's file is not a data URL with bytes in it")
        if len(data) > max_asset_bytes:
            raise TooLarge(f"The file of an image is larger than {max_asset_bytes} bytes.")
        files.append(ImportedFile(file_id, media_type, data))
    return files


def read_document(body: bytes, *, max_scene_bytes: int, max_asset_bytes: int) -> ImportedScene:
    """Return what an import takes from a request's body.

    The body is a scene document as the editor exports one. Its elements are
    taken whole or not at all: each is an object with a text ``id``, no two
    share one, and a missing ``version`` or ``versionNonce`` is filled in as
    the editor fills it. Of ``files``, the entries an element names are taken,
    and the rest are not read.

    Raises:
        NotJson: When the body is not a JSON object.
        InvalidDocument: When it is not a scene document, or a part of it is
            not what the editor writes.
        TooLarge: When the elements come to more than ``max_scene_bytes`` as
            a room writes them, or a file is over ``max_asset_bytes``.
    """
    try:
        document = json.loads(body, parse_constant=_not_json)
    except (ValueError, RecursionError) as exc:
        raise NotJson from exc
    if not isinstance(document, dict):
        raise NotJson
    if document.get("type") != DOCUMENT_TYPE:
        raise InvalidDocument(f'its type is not "{DOCUMENT_TYPE}"')
    elements = _elements(document, max_scene_bytes)
    return ImportedScene(elements, _files(document, elements, max_asset_bytes))
