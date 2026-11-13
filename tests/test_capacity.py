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

"""scripts/capacity.py: how many groups of tests fit on the machine right now."""

from pathlib import Path

import capacity
import pytest
from capacity import GROUP_BYTES, Machine, room, wait_for_room

GIB = 1024**3


def machine(cores: int, busy: float, free_gib: float | None) -> Machine:
    return Machine(cores, busy, None if free_gib is None else int(free_gib * GIB))


@pytest.mark.parametrize(
    ("cores", "busy", "free_gib", "groups"),
    [
        # The development host, idle: one core is kept for everything else.
        (4, 0.2, 7.6, 3),
        # Another session is using a core, then two, then three.
        (4, 1.0, 7.6, 2),
        (4, 2.1, 7.6, 1),
        (4, 3.0, 7.6, 0),
        (4, 4.0, 7.6, 0),
        # More cores and memory: more groups, up to the most that helps.
        (8, 0.3, 30.0, 6),
        (16, 0.0, 60.0, 6),
        (8, 3.6, 30.0, 3),
        # Memory is what runs out.
        (8, 0.0, 3.2, 2),
        (4, 0.0, 1.6, 1),
        (4, 0.0, 1.0, 0),
        # A machine with one core has none to spare, and still runs a group.
        (1, 0.1, 4.0, 1),
        (1, 0.9, 4.0, 0),
        (2, 0.0, 4.0, 1),
        # Where memory cannot be read, the cores decide.
        (4, 0.0, None, 3),
    ],
)
def test_the_groups_that_fit(cores: int, busy: float, free_gib: float | None, groups: int) -> None:
    assert room(machine(cores, busy, free_gib)) == groups


def test_a_caller_can_ask_for_fewer_groups_than_fit() -> None:
    assert room(machine(16, 0.0, 60.0), most=2) == 2


def test_a_group_is_counted_at_what_one_was_seen_to_take() -> None:
    assert GIB <= GROUP_BYTES <= 3 * GIB
    assert room(Machine(8, 0.0, 2 * GROUP_BYTES)) == 2
    assert room(Machine(8, 0.0, 2 * GROUP_BYTES - 1)) == 1


def stat_file(folder: Path, name: str, idle: int, busy: int) -> Path:
    # user nice system idle iowait irq softirq steal
    path = folder / name
    path.write_text(f"cpu  {busy} 0 0 {idle} 0 0 0 0\ncpu0 0 0 0 0 0 0 0 0\n")
    return path


def test_busy_cores_are_measured_now_and_not_over_the_last_minute(tmp_path: Path) -> None:
    stat = stat_file(tmp_path, "stat", idle=1000, busy=1000)

    def a_second_passes(_seconds: float) -> None:
        # Since the first reading: 100 ticks idle and 300 busy, on 4 cores.
        stat_file(tmp_path, "stat", idle=1100, busy=1300)

    assert capacity.busy_cores(4, stat, a_second_passes) == pytest.approx(3.0)


def test_waiting_on_a_disk_is_not_a_busy_core(tmp_path: Path) -> None:
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 0 0 100 100 0 0 0\n")

    def a_second_passes(_seconds: float) -> None:
        stat.write_text("cpu  100 0 0 150 150 0 0 0\n")

    assert capacity.busy_cores(4, stat, a_second_passes) == 0.0


def test_a_machine_without_proc_stat_goes_by_its_load_average(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capacity.os, "getloadavg", lambda: (2.5, 1.0, 1.0))
    slept: list[float] = []

    assert capacity.busy_cores(4, tmp_path / "absent", slept.append) == 2.5
    assert capacity.busy_cores(2, tmp_path / "absent", slept.append) == 2.0
    assert slept == []


def test_free_memory_is_what_a_new_program_could_have(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       10178048 kB\nMemFree:  1000 kB\nMemAvailable:    8000000 kB\n"
    )

    assert capacity.free_bytes(meminfo) == 8000000 * 1024
    assert capacity.free_bytes(tmp_path / "absent") is None
    meminfo.write_text("MemTotal: 1 kB\n")
    assert capacity.free_bytes(meminfo) is None


def test_this_machine_can_be_measured() -> None:
    seen = capacity.look()

    assert seen.cores >= 1
    assert 0.0 <= seen.busy_cores <= seen.cores
    assert "cores busy" in seen.summary


class Looks:
    """A machine that is busy for the first looks, then has room."""

    def __init__(self, *machines: Machine) -> None:
        self.machines = list(machines)
        self.count = 0

    def __call__(self) -> Machine:
        self.count += 1
        return self.machines.pop(0) if len(self.machines) > 1 else self.machines[0]


BUSY = machine(4, 3.8, 7.0)
IDLE = machine(4, 0.2, 7.0)


def test_with_room_it_starts_at_once() -> None:
    said: list[str] = []
    slept: list[float] = []

    assert wait_for_room(environ={}, look=Looks(IDLE), sleep=slept.append, say=said.append) == 3
    assert slept == []
    assert said == ["capacity: 3 group(s) at once (0.2 of 4 cores busy, 7.0 GiB of memory free)"]


def test_on_a_busy_machine_it_waits_and_starts_when_there_is_room() -> None:
    said: list[str] = []
    slept: list[float] = []
    looks = Looks(BUSY, BUSY, machine(4, 2.0, 7.0))

    assert wait_for_room(environ={}, look=looks, sleep=slept.append, say=said.append) == 1
    assert slept == [15, 15]
    assert said[0] == (
        "capacity: no room now (3.8 of 4 cores busy, 7.0 GiB of memory free); "
        "waiting up to 600 seconds"
    )
    assert len(said) == 2, "it says once that it waits"


def test_after_the_limit_it_runs_one_group_anyway() -> None:
    said: list[str] = []
    slept: list[float] = []

    groups = wait_for_room(
        environ={"SEGL_TEST_WAIT": "40"}, look=Looks(BUSY), sleep=slept.append, say=said.append
    )

    assert groups == 1
    assert slept == [15, 15, 10]
    assert said[-1].startswith("capacity: still busy after 40 seconds")
    assert said[-1].endswith("running 1 group")


def test_a_wait_of_zero_does_not_wait() -> None:
    slept: list[float] = []

    groups = wait_for_room(
        environ={"SEGL_TEST_WAIT": "0"}, look=Looks(BUSY), sleep=slept.append, say=lambda _: None
    )

    assert groups == 1
    assert slept == []


def test_a_set_number_of_groups_is_taken_without_measuring() -> None:
    looks = Looks(BUSY)
    said: list[str] = []
    slept: list[float] = []

    groups = wait_for_room(
        environ={"SEGL_TEST_GROUPS": "5"}, look=looks, sleep=slept.append, say=said.append
    )

    assert groups == 5
    assert looks.count == 0
    assert slept == []
    assert said == ["capacity: 5 group(s), set by SEGL_TEST_GROUPS"]


@pytest.mark.parametrize("value", ["0", "two", "-1", "1.5"])
def test_a_number_of_groups_that_is_not_one_is_refused(value: str) -> None:
    with pytest.raises(SystemExit, match="SEGL_TEST_GROUPS"):
        wait_for_room(environ={"SEGL_TEST_GROUPS": value}, look=Looks(IDLE), say=lambda _: None)


def test_a_wait_that_is_not_a_number_is_refused() -> None:
    with pytest.raises(SystemExit, match="SEGL_TEST_WAIT must be a whole number"):
        wait_for_room(environ={"SEGL_TEST_WAIT": "soon"}, look=Looks(IDLE), say=lambda _: None)
