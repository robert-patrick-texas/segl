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

"""Which copy of an element the server keeps (docs/ARCHITECTURE.md, D2-025).

An element is the record the editor produces. The server reads three of its
fields, ``id``, ``version``, and ``versionNonce``, and ``index`` for the order.
Everything else is the editor's, and is stored and sent on as it arrived.

The rule is the one in ``reconcileElements``, the helper the pinned editor
exports and the browser calls: the copy with the higher ``version`` wins, and
on equal versions the copy with the lower ``versionNonce``. A deleted element
is an element whose ``isDeleted`` is true. It stays in the scene with its
version, so an older copy cannot bring it back.
``tests/reconcile_cases.json`` holds this module and the editor's helper to
one table of cases.
"""

from collections.abc import Iterable
from typing import Any

Element = dict[str, Any]


class BadElement(ValueError):
    """A value that is not an element the server can reconcile."""


def _is_integer(value: object) -> bool:
    # bool is an int in Python, and `true` is not a version.
    return isinstance(value, int) and not isinstance(value, bool)


def check_element(value: object) -> Element:
    """Return ``value`` as an element.

    Raises:
        BadElement: When it is not an object with a text ``id`` and whole-number
            ``version`` and ``versionNonce``.
    """
    if not isinstance(value, dict):
        raise BadElement("an element is a JSON object")
    identifier = value.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise BadElement("an element has a text id")
    if not _is_integer(value.get("version")) or not _is_integer(value.get("versionNonce")):
        raise BadElement(f"element {identifier!r} needs a whole-number version and versionNonce")
    return value


def adopt_element(value: object) -> Element | None:
    """Return an element of a stored scene as the room keeps it, or None.

    A stored scene may be older than the room, or imported. An object with an
    id is kept, and a missing ``version`` or ``versionNonce`` becomes 1 or 0,
    which is what the editor does when it loads such an element. Anything else
    is not an element and is left out.
    """
    if not isinstance(value, dict):
        return None
    identifier = value.get("id")
    if not isinstance(identifier, str) or not identifier:
        return None
    element = dict(value)
    if not _is_integer(element.get("version")):
        element["version"] = 1
    if not _is_integer(element.get("versionNonce")):
        element["versionNonce"] = 0
    return element


def wins(incoming: Element, stored: Element | None) -> bool:
    """Return whether ``incoming`` replaces the ``stored`` copy of the same element.

    A copy with the same version and nonce is the copy already held, and does
    not replace it.
    """
    if stored is None:
        return True
    if incoming["version"] != stored["version"]:
        return incoming["version"] > stored["version"]
    return incoming["versionNonce"] < stored["versionNonce"]


def merge(scene: dict[str, Element], incoming: Iterable[Element]) -> list[Element]:
    """Reconcile ``incoming`` into ``scene``, which is changed, and return the winners.

    The winners are the incoming elements that replaced a stored copy or were
    new, in the order they arrived. An element named twice is settled by the
    same rule.
    """
    winners: dict[str, Element] = {}
    for element in incoming:
        identifier = element["id"]
        if wins(element, scene.get(identifier)):
            scene[identifier] = element
            winners[identifier] = element
    return list(winners.values())


def ordered(elements: Iterable[Element]) -> list[Element]:
    """Return elements in drawing order, as the editor orders them.

    The order is the fractional ``index`` the editor gives each element, as
    text, and then the id. An element without one, from a scene older than the
    indices, keeps its place after those that have one.
    """
    indexed: list[Element] = []
    rest: list[Element] = []
    for element in elements:
        (indexed if isinstance(element.get("index"), str) else rest).append(element)
    indexed.sort(key=lambda element: (element["index"], element["id"]))
    return indexed + rest
