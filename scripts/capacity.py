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

"""How many groups of tests this machine can run at once, right now.

A group is one run of the browser tests with servers and a browser of its
own (scripts/e2e.py). Each is counted at a core and `GROUP_BYTES` of memory.
The count follows what is free at this moment: more cores and more memory
give more groups, and a machine that is busy with other work gives fewer.
When there is no room for even one, `wait_for_room` waits for the other
work to end, and after a limit runs one group anyway.

The scripts run under the host's python3, so this is the standard library
alone (docs/DEVELOPMENT.md).
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# What a group is counted at. Three groups took 2.8 GiB together on the
# development host, 0.95 GiB each: a browser, two segl processes, and two
# nginx. This is that and half again (docs/DEVELOPMENT.md, the browser tests
# in groups).
GROUP_BYTES = 1536 * 1024 * 1024
# More groups than this gain little: a group has servers to start, and the
# longest single spec file sets the floor.
MOST_GROUPS = 6
# A machine with more than one core keeps this many free for everything else.
SPARE_CORES = 1
# How long to wait for room before running one group anyway, and how often
# to look again.
WAIT_SECONDS = 600
LOOK_EVERY = 15
# How long the busy cores are measured over.
SAMPLE_SECONDS = 1.0

GROUPS_SETTING = "SEGL_TEST_GROUPS"
WAIT_SETTING = "SEGL_TEST_WAIT"


@dataclass(frozen=True)
class Machine:
    """What the machine has, and how much of it is in use now."""

    cores: int
    busy_cores: float
    free_bytes: int | None  # None where it cannot be read

    @property
    def summary(self) -> str:
        memory = "unknown" if self.free_bytes is None else f"{self.free_bytes / 1024**3:.1f} GiB"
        return f"{self.busy_cores:.1f} of {self.cores} cores busy, {memory} of memory free"


def core_count() -> int:
    """Return the cores this process may use."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # not Linux
        return os.cpu_count() or 1


def _cpu_times(stat: Path) -> tuple[int, int] | None:
    """Return (idle, total) clock ticks of all cores since boot."""
    try:
        fields = stat.read_text(encoding="ascii").splitlines()[0].split()
    except (OSError, IndexError):
        return None
    if not fields or fields[0] != "cpu":
        return None
    ticks = [int(field) for field in fields[1:]]
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)  # idle and iowait
    return idle, sum(ticks)


def busy_cores(
    cores: int,
    stat: Path = Path("/proc/stat"),
    sleep: Callable[[float], None] = time.sleep,
) -> float:
    """Return how many cores were in use over the last second.

    This is what is running now. The load average is the last minute's, and
    would count the test run that has just ended as other people's work.
    """
    first = _cpu_times(stat)
    if first is None:
        try:
            return min(float(cores), os.getloadavg()[0])
        except OSError:
            return 0.0
    sleep(SAMPLE_SECONDS)
    second = _cpu_times(stat)
    if second is None or second[1] <= first[1]:
        return 0.0
    idle = (second[0] - first[0]) / (second[1] - first[1])
    return max(0.0, cores * (1 - idle))


def free_bytes(meminfo: Path = Path("/proc/meminfo")) -> int | None:
    """Return the memory a new program could have, or None where it is unknown."""
    try:
        for line in meminfo.read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def look() -> Machine:
    """Measure the machine. Takes about a second."""
    cores = core_count()
    return Machine(cores, busy_cores(cores), free_bytes())


def room(machine: Machine, most: int = MOST_GROUPS) -> int:
    """Return how many groups fit on the machine now. 0 means: wait."""
    spare = SPARE_CORES if machine.cores > 1 else 0
    # Half a busy core is rounded away: something is always running a little.
    by_cores = math.floor(machine.cores - machine.busy_cores + 0.5) - spare
    by_memory = most if machine.free_bytes is None else machine.free_bytes // GROUP_BYTES
    return max(0, min(most, by_cores, by_memory))


def _setting(name: str, environ: dict[str, str]) -> int | None:
    """Return a whole number of 0 or more from the environment, or None."""
    text = environ.get(name, "").strip()
    if not text:
        return None
    if not text.isdecimal():
        raise SystemExit(f"{name} must be a whole number, not {text!r}")
    return int(text)


def wait_for_room(
    most: int = MOST_GROUPS,
    *,
    environ: dict[str, str] | None = None,
    look: Callable[[], Machine] = look,
    sleep: Callable[[float], None] = time.sleep,
    say: Callable[[str], None] = print,
) -> int:
    """Return how many groups to run, 1 or more, waiting while there is no room.

    `SEGL_TEST_GROUPS` sets the count and skips the measuring. `SEGL_TEST_WAIT`
    is the most seconds to wait, 600 unless set, and 0 is no wait.
    """
    environ = dict(os.environ) if environ is None else environ
    fixed = _setting(GROUPS_SETTING, environ)
    if fixed is not None:
        if fixed < 1:
            raise SystemExit(f"{GROUPS_SETTING} must be 1 or more")
        say(f"capacity: {fixed} group(s), set by {GROUPS_SETTING}")
        return fixed
    limit = _setting(WAIT_SETTING, environ)
    limit = WAIT_SECONDS if limit is None else limit
    waited = 0
    while True:
        machine = look()
        groups = room(machine, most)
        if groups >= 1:
            say(f"capacity: {groups} group(s) at once ({machine.summary})")
            return groups
        if waited >= limit:
            say(f"capacity: still busy after {waited} seconds ({machine.summary}); running 1 group")
            return 1
        if waited == 0:
            say(f"capacity: no room now ({machine.summary}); waiting up to {limit} seconds")
        step = min(LOOK_EVERY, limit - waited)
        sleep(step)
        waited += step
