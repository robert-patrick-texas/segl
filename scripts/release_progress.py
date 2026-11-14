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

"""Say on the terminal that a long command is still working.

`cut`, `upgrade`, and `publish` run commands that take minutes: the suite and
the install test. Each was silent until it ended. A `Progress` prints the
lines that mark a stage as they come, each with the time so far, and a
"still running" line when nothing was said for a while. `Runner.run` feeds it
(release_proc) and still keeps the whole output for the failure report.

Every line is plain text that ends with a newline. Nothing is redrawn, so the
output reads the same in a terminal and in a log.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

# How long a command may run with nothing said before a "still running" line.
QUIET_SECONDS = 30.0
# The longest piece of a command's own output that one line repeats.
WIDTH = 100
INDENT = "    "

# The suite: a wait for a busy machine, and each runner's totals.
SUITE_STAGES = re.compile(r"^(capacity:|e2e:|\s*Tests\s|=* ?\d+ (passed|failed))")
# deploy/debian/package-test.sh: the build's steps, the test's sections, a
# failed check, a wait for a busy machine, and the last line.
PACKAGE_STAGES = re.compile(r"^(==> |== |FAIL|capacity:|systemd-test:)")

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def say(text: str) -> None:
    """Print one line now. A pipe would hold it back otherwise."""
    print(text, flush=True)


def elapsed(seconds: float) -> str:
    """Return a length of time as minutes and seconds, such as ``3:07``."""
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def plain(text: str) -> str:
    """Return one line of output without colors, and no longer than WIDTH."""
    text = _ANSI.sub("", text).replace("\r", " ").strip()
    return text if len(text) <= WIDTH else text[: WIDTH - 1] + "…"


class Progress:
    """Prints what one running command is doing.

    Args:
        stages: Which lines of the command's output to print as they come.
            None prints none of them.
        write: Takes each line. The default prints it.
        clock: Returns seconds that only grow. The default is the machine's.
        every: The seconds of quiet before a "still running" line.
    """

    def __init__(
        self,
        stages: re.Pattern[str] | None = None,
        *,
        write: Callable[[str], None] = say,
        clock: Callable[[], float] = time.monotonic,
        every: float = QUIET_SECONDS,
    ) -> None:
        self.stages, self.write, self.clock, self.every = stages, write, clock, every
        self.started = clock()
        self.said = self.started
        self.last = ""

    def line(self, text: str) -> None:
        """Take one line of the command's output."""
        shown = plain(text)
        if shown:
            self.last = shown
        if shown and self.stages is not None and self.stages.search(_ANSI.sub("", text)):
            self._say(shown)
        else:
            self.tick()

    def tick(self) -> None:
        """Say that the command still runs, when nothing was said for a while."""
        if self.clock() - self.said >= self.every:
            self._say(f"still running: {self.last}" if self.last else "still running")

    def done(self, passed: bool = True) -> None:
        """Say that the command ended, how, and after how long."""
        self._say("done" if passed else "failed")

    def _say(self, text: str) -> None:
        self.said = self.clock()
        self.write(f"{INDENT}{elapsed(self.said - self.started)}  {text}")
