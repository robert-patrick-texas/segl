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

"""Access codes, and the pass a code buys (docs/ARCHITECTURE.md, "Edit gate"; D2-033).

A site lists codes, words, or phrases in ``access_codes``. With one or more,
editing needs a pass. A browser sends a code to ``POST api/v1/access`` and is
issued one: the time of issue, and a signature over that time and the code
under ``access_secret``, as ``<issued>.<signature>``. The browser sends the
pass back in the ``X-Segl-Edit-Token`` header and in the socket's ``hello``.

The server keeps no list of passes. It takes one whose signature fits a code
that is still in the list, that was issued at or after ``access_passes_after``,
that is not from more than five minutes ahead of this server's clock, and that
is younger than ``access_pass_hours`` as that is set now.

This is texas2step's access code in its simplest form. It is not
authentication: a pass says that someone knew a code, and nothing about who.
"""

import base64
import hashlib
import hmac
import math
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

# The fewest letters and digits a code may have.
MIN_CODE_CHARACTERS = 8
# The longest entry of ``access_codes``, as written. A person has to type it.
MAX_CODE_LENGTH = 256
# The fewest characters ``access_secret`` may have.
MIN_SECRET_CHARACTERS = 32

# How far ahead of this server's clock a pass may be stamped.
PASS_AHEAD_SECONDS = 300.0

# Wrong codes in a row from one client address before it has to wait, and the wait.
WRONG_CODES = 5
LOCK_SECONDS = 900.0

# A pass: Unix seconds, a dot, and 18 bytes of signature in base64url. It is
# printable ASCII, which is all a browser can send in a request header.
_PASS = re.compile(r"([0-9]{1,12})\.([A-Za-z0-9_-]{24})")
_SIGNATURE_BYTES = 18


def normalize(text: str) -> str:
    """Return a code as it is compared: ``Maple River 42`` is ``maple.river.42``.

    Lowercase letters and digits, with any run of other characters as one
    dot. So the case, the spaces, and the punctuation a person types do not
    matter.
    """
    return ".".join(re.findall(r"[a-z0-9]+", text.lower()))


def letters_and_digits(code: str) -> int:
    """Return how many letters and digits a normalized code has."""
    return len(code.replace(".", ""))


@dataclass(frozen=True)
class Admission:
    """Whether a request or a connection may edit, and until when."""

    may_edit: bool
    # When the pass ends, in Unix seconds. None when it does not: this segl
    # asks for no code, or its passes have no limit.
    until: float | None = None


VIEWER = Admission(may_edit=False)
EVERYONE = Admission(may_edit=True)


class Access:
    """The codes of one segl, and the passes they buy.

    ``codes`` are in their normal form. With none, everyone may edit and no
    pass is looked at. ``pass_seconds`` is how long a pass lasts from its
    issue, or None for no limit. ``passes_after`` is a time in Unix seconds, or
    None: a pass issued before it is refused.
    """

    def __init__(
        self,
        codes: Sequence[str],
        secret: str,
        *,
        pass_seconds: float | None = None,
        passes_after: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._codes = tuple(codes)
        self._secret = secret.encode()
        self._pass_seconds = pass_seconds
        self._passes_after = passes_after
        self.clock = clock

    @property
    def required(self) -> bool:
        """Return whether editing needs a pass."""
        return bool(self._codes)

    def code(self, text: str) -> str | None:
        """Return the code of the list that ``text`` is, or None.

        Compared in the normal form, in constant time, and against every code
        in the list, so the time taken says nothing about which one fit.
        """
        given = normalize(text).encode()
        found = None
        for code in self._codes:
            if hmac.compare_digest(given, code.encode()):
                found = code
        return found

    def issue(self, code: str) -> tuple[str, float | None]:
        """Return a new pass bought with ``code``, and when it ends, or None for never.

        ``code`` is one of the list, as ``Access.code`` returned it. It goes
        into what is signed, so taking it out of the list ends the pass.
        """
        issued = int(self.clock())
        if self._passes_after is not None:
            # Never stamped before the time passes were ended at, also when
            # the site wrote that time a little ahead of this clock.
            issued = max(issued, math.ceil(self._passes_after))
        return f"{issued}.{self._sign(issued, code)}", self._ends(issued)

    def admit(self, given: str | None) -> Admission:
        """Return whether a browser that sent ``given`` as its pass may edit."""
        if not self._codes:
            return EVERYONE
        issued = self._issued(given or "")
        if issued is None:
            return VIEWER
        now = self.clock()
        if self._passes_after is not None and issued < self._passes_after:
            return VIEWER
        if issued > now + PASS_AHEAD_SECONDS:
            return VIEWER
        until = self._ends(issued)
        if until is not None and now >= until:
            return VIEWER
        return Admission(may_edit=True, until=until)

    def _ends(self, issued: int) -> float | None:
        return None if self._pass_seconds is None else issued + self._pass_seconds

    def _sign(self, issued: int, code: str) -> str:
        # A code in its normal form holds no "|".
        signed = f"pass|{issued}|{code}".encode()
        mac = hmac.new(self._secret, signed, hashlib.sha256).digest()[:_SIGNATURE_BYTES]
        return base64.urlsafe_b64encode(mac).decode()

    def _issued(self, text: str) -> int | None:
        """Return when a pass was issued, or None when no code in the list signed it."""
        match = _PASS.fullmatch(text)
        if match is None:
            return None
        issued, signature = int(match[1]), match[2].encode()
        fits = False
        # Every code, so the time taken says nothing about which one it was.
        for code in self._codes:
            if hmac.compare_digest(signature, self._sign(issued, code).encode()):
                fits = True
        return issued if fits else None


class CodeLimit:
    """Wrong codes, counted per client address.

    After ``tries`` wrong codes in a row, the address waits ``lock`` seconds
    from the last of them, whatever it sends. A right code starts the count
    again, and so does ``lock`` seconds without a wrong one. The count is in
    memory, so a restart forgets it. Any thread may call these.
    """

    def __init__(
        self,
        tries: int = WRONG_CODES,
        lock: float = LOCK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tries = tries
        self._lock_seconds = lock
        self.clock = clock
        self._lock = threading.Lock()
        # For each client: how many wrong codes in a row, and when the last one came.
        self._wrong: dict[str, tuple[int, float]] = {}
        self._next_sweep = clock() + lock

    def wait(self, client: str) -> float:
        """Return the seconds ``client`` has to wait before a code of its is read, or 0."""
        now = self.clock()
        with self._lock:
            if now >= self._next_sweep:
                self._sweep(now)
            count, last = self._wrong.get(client, (0, now))
            if count < self._tries or now - last >= self._lock_seconds:
                return 0.0
            return last + self._lock_seconds - now

    def wrong(self, client: str) -> bool:
        """Count a wrong code from ``client``. Return whether it now has to wait."""
        now = self.clock()
        with self._lock:
            count, last = self._wrong.get(client, (0, now))
            if now - last >= self._lock_seconds:
                # The wait is over, or the earlier wrong codes are long ago.
                count = 0
            self._wrong[client] = (count + 1, now)
            return count + 1 >= self._tries

    def right(self, client: str) -> None:
        """Forget the wrong codes of ``client``: it sent a right one."""
        with self._lock:
            self._wrong.pop(client, None)

    def clients(self) -> int:
        """Return how many client addresses are being counted."""
        with self._lock:
            return len(self._wrong)

    def _sweep(self, now: float) -> None:
        # Once a wait's length, forget every client whose last wrong code is that old.
        for client in [
            client for client, (_, last) in self._wrong.items() if now - last >= self._lock_seconds
        ]:
            del self._wrong[client]
        self._next_sweep = now + self._lock_seconds
