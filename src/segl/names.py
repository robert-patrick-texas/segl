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

"""Display names (docs/ARCHITECTURE.md, "Display names").

Three parts: the word file a site may replace, the limit on how often one
client address may be given a name (docs/SECURITY.md), and the title case of a
name a person types. The counter behind ``Alpha1``, ``Bravo2`` is in SQLite
(``Repository.allocate_display_name``).
"""

import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

# One word of the file: 1 to 10 ASCII letters.
_WORD = re.compile(r"[A-Za-z]{1,10}")

# Names one client address may be given in any ``WINDOW_SECONDS``.
ALLOCATIONS_PER_WINDOW = 30
WINDOW_SECONDS = 60.0

# The longest name a person may give themselves, in characters.
MAX_NAME_LENGTH = 40


class DisplayNamesError(Exception):
    """The display-name file is missing, or holds something segl cannot use."""


def parse_display_names(text: str, source: str = "the display-name file") -> tuple[str, ...]:
    """Return the words of a display-name file, in the file's order.

    Blank lines and lines that start with ``#`` are skipped. Spaces around a
    word, and the line endings of any system, are dropped. The spelling is
    kept, and so is a word the file has twice.

    Raises:
        DisplayNamesError: When a line is not 1 to 10 ASCII letters, or no
            word is left. ``source`` names the file in the message.
    """
    words: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        word = line.strip()
        if not word or word.startswith("#"):
            continue
        if _WORD.fullmatch(word) is None:
            raise DisplayNamesError(
                f"{source}, line {number}: {word!r} is not a word of 1 to 10 ASCII letters"
            )
        words.append(word)
    if not words:
        raise DisplayNamesError(f"{source} has no words; it needs one word on a line")
    return tuple(words)


def load_display_names(path: Path) -> tuple[str, ...]:
    """Read the file ``display_names`` names. It is text, and is never run as code.

    Raises:
        DisplayNamesError: When the file cannot be read, or ``parse_display_names``
            refuses it.
    """
    try:
        # utf-8-sig: an editor on Windows may have put a byte order mark first.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise DisplayNamesError(f"cannot read the display-name file {path}: {exc}") from exc
    return parse_display_names(text, f"the display-name file {path}")


class AllocationLimit:
    """At most ``limit`` admitted calls from one client in any ``window`` seconds.

    The count is in memory, so a restart forgets it. A call that is refused is
    not counted: a client that keeps asking is admitted again as soon as its
    oldest admitted call is ``window`` seconds old. Any thread may call ``admit``.
    """

    def __init__(
        self,
        limit: int = ALLOCATIONS_PER_WINDOW,
        window: float = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._lock = threading.Lock()
        # The times of each client's admitted calls inside the window, oldest first.
        self._admitted: dict[str, deque[float]] = {}
        self._next_sweep = clock() + window

    def admit(self, client: str) -> float:
        """Count a call from ``client`` and return 0, or refuse it.

        A refusal returns the seconds until that client's next call would be
        admitted, which is above 0.
        """
        now = self._clock()
        with self._lock:
            if now >= self._next_sweep:
                self._sweep(now)
            calls = self._admitted.setdefault(client, deque())
            while calls and now - calls[0] >= self._window:
                calls.popleft()
            if len(calls) >= self._limit:
                return calls[0] + self._window - now
            calls.append(now)
            return 0.0

    def clients(self) -> int:
        """Return how many client addresses are being counted."""
        with self._lock:
            return len(self._admitted)

    def _sweep(self, now: float) -> None:
        # Once a window, forget every client whose calls have all aged out, so
        # the table holds the addresses of the last two windows at most.
        for client in [
            client
            for client, calls in self._admitted.items()
            if not calls or now - calls[-1] >= self._window
        ]:
            del self._admitted[client]
        self._next_sweep = now + self._window


def retry_after(seconds: float) -> str:
    """Return a wait as a ``Retry-After`` value: whole seconds, 1 or more."""
    return str(max(1, math.ceil(seconds)))


def title_case_name(text: str) -> str | None:
    """Return a name a person typed as segl shows it, or None when it is not usable.

    The words are split on whitespace and joined with one space. Each gets an
    uppercase first character and a lowercase rest: ``john smith`` becomes
    ``John Smith``, and ``NASA`` becomes ``Nasa``. The result is 1 to 40
    characters. The web application applies the same rule
    (``web/src/names.ts``), and ``tests/display_name_cases.json`` holds both to
    one table. A name from the word file is never passed through here, so
    ``McKinley`` stays as the file spells it.

    Applying the rule to its own result changes nothing, so the browser and
    the server can each apply it to the same name.
    """
    name = " ".join(_title_word(word) for word in text.split())
    return name if 1 <= len(name) <= MAX_NAME_LENGTH else None


def _title_word(word: str) -> str:
    # A few characters are more than one when uppercased: ß is SS. Only the
    # first of those stays uppercase, so ßeta is Sseta, and stays Sseta.
    head = word[:1].upper()
    return head[:1] + (head[1:] + word[1:]).lower()
