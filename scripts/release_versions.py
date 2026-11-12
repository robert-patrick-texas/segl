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

"""Parse and order version strings: CPython, PyPI, npm, and GitHub release tags.

A pre-release never counts as the newest release (docs/RELEASING.md). That
covers PEP 440 markers (``a``, ``b``, ``rc``, ``dev``) and SemVer suffixes
such as ``-beta.1``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_VERSION = re.compile(r"^\s*v?(?P<release>\d+(?:\.\d+)*)(?P<suffix>[^+\s]*)(?:\+\S*)?\s*$")
_POST = re.compile(r"^[-_.]?post[-_.]?(\d*)$", re.IGNORECASE)


@dataclass(frozen=True)
class Version:
    """One parsed version."""

    text: str
    release: tuple[int, ...]
    post: int
    stable: bool

    @property
    def key(self) -> tuple[tuple[int, ...], int]:
        """Return a sort key in which ``1.0`` equals ``1.0.0``."""
        release = self.release
        while len(release) > 1 and release[-1] == 0:
            release = release[:-1]
        return release, self.post


def parse_version(text: str) -> Version | None:
    """Return the parsed version, or None when ``text`` is not a version."""
    match = _VERSION.match(text)
    if match is None:
        return None
    release = tuple(int(part) for part in match["release"].split("."))
    suffix = match["suffix"]
    if not suffix:
        return Version(text.strip(), release, -1, True)
    post = _POST.match(suffix)
    if post:
        return Version(text.strip(), release, int(post[1] or 0), True)
    return Version(text.strip(), release, -1, False)


def newest_stable(texts: Iterable[str]) -> str | None:
    """Return the newest version that is not a pre-release, as it was written."""
    stable = [v for v in map(parse_version, texts) if v is not None and v.stable]
    return max(stable, key=lambda v: v.key).text if stable else None


def is_newer(candidate: str, than: str) -> bool:
    """Report whether ``candidate`` is a later release than ``than``."""
    a, b = parse_version(candidate), parse_version(than)
    if a is None or b is None:
        return False
    return a.key > b.key


def within_pin(pin: str, latest: str) -> bool:
    """Report whether ``latest`` is inside a pin written at reduced precision.

    An Actions tag such as ``v7`` stays current while 7.y.z is the newest series.
    """
    a, b = parse_version(pin), parse_version(latest)
    if a is None or b is None:
        return False
    return b.release[: len(a.release)] == a.release


def at_precision(pin: str, latest: str) -> str:
    """Return ``latest`` written with as many parts as ``pin``, keeping a ``v``."""
    a, b = parse_version(pin), parse_version(latest)
    if a is None or b is None:
        return latest
    parts = ".".join(str(part) for part in b.release[: len(a.release)])
    return ("v" if pin.strip().startswith("v") else "") + parts
