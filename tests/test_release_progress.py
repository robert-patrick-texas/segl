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

"""What the release script says while a long command runs."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import release_proc
from release_proc import CommandError, Result, Runner
from release_progress import (
    PACKAGE_STAGES,
    QUIET_SECONDS,
    SUITE_STAGES,
    WIDTH,
    Progress,
    elapsed,
    plain,
)
from release_upgrade import run_commands

EVERY_LINE = re.compile("")
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class Clock:
    """Seconds that a test moves."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def watcher(stages: re.Pattern[str] | None = None, every: float = 30.0):
    """Return a progress on a clock the test moves, and the lines it wrote."""
    clock, said = Clock(), []
    return Progress(stages, write=said.append, clock=clock, every=every), clock, said


def python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0:00"), (9.99, "0:09"), (67.9, "1:07"), (600, "10:00"), (3723, "62:03"), (-3, "0:00")],
)
def test_a_time_is_minutes_and_seconds(seconds: float, text: str) -> None:
    assert elapsed(seconds) == text


def test_a_repeated_line_has_no_colors_and_a_limit() -> None:
    assert plain("\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m738 passed\x1b[39m\n") == (
        "Tests  738 passed"
    )
    assert plain("one\rtwo  \n") == "one two"
    long = plain("x" * (WIDTH + 50))
    assert len(long) == WIDTH
    assert long.endswith("…")
    assert plain("x" * WIDTH) == "x" * WIDTH


def test_a_stage_line_is_said_with_the_time_so_far() -> None:
    progress, clock, said = watcher(PACKAGE_STAGES)

    progress.line("==> installing Python 3.15.2\n")
    progress.line("PASS  the unit is active\n")
    clock.now += 65
    progress.line("== install\n")

    assert said == ["    0:00  ==> installing Python 3.15.2", "    1:05  == install"]


def test_no_line_is_said_without_stages() -> None:
    progress, _, said = watcher(None)

    progress.line("==> installing Python 3.15.2\n")

    assert said == []


def test_a_quiet_command_says_that_it_still_runs_with_its_last_line() -> None:
    progress, clock, said = watcher(PACKAGE_STAGES, every=30)

    progress.line("PASS  apt has its package lists\n")
    clock.now += 29.9
    progress.tick()
    assert said == [], "not before the 30 seconds"
    clock.now += 0.1
    progress.tick()
    assert said == ["    0:30  still running: PASS  apt has its package lists"]
    clock.now += 29
    progress.tick()
    assert len(said) == 1, "the 30 seconds count from the last thing said"
    clock.now += 1
    progress.tick()
    assert said[1] == "    1:00  still running: PASS  apt has its package lists"


def test_a_command_that_printed_nothing_still_says_that_it_runs() -> None:
    progress, clock, said = watcher()

    clock.now += 45
    progress.tick()

    assert said == ["    0:45  still running"]


def test_lines_that_are_not_stages_do_not_keep_it_quiet() -> None:
    # The install test prints a PASS line every second or so. None is a stage.
    progress, clock, said = watcher(PACKAGE_STAGES, every=30)

    for number in range(40):
        clock.now += 1
        progress.line(f"PASS  check {number}\n")

    assert said == ["    0:30  still running: PASS  check 29"]


def test_a_stage_line_starts_the_quiet_time_again() -> None:
    progress, clock, said = watcher(PACKAGE_STAGES, every=30)

    clock.now += 20
    progress.line("== install\n")
    clock.now += 20
    progress.tick()

    assert said == ["    0:20  == install"]


def test_an_empty_line_is_not_the_last_line() -> None:
    progress, clock, said = watcher(every=30)

    progress.line("building\n")
    progress.line("\n")
    progress.line("   \n")
    clock.now += 30
    progress.tick()

    assert said == ["    0:30  still running: building"]


def test_the_end_is_said_with_its_time() -> None:
    progress, clock, said = watcher()

    clock.now += 34
    progress.done()
    progress.done(False)

    assert said == ["    0:34  done", "    0:34  failed"]


def test_the_default_quiet_time_is_thirty_seconds() -> None:
    assert QUIET_SECONDS == 30
    assert Progress().every == 30


@pytest.mark.parametrize(
    "line",
    [
        "capacity: 3 pytest worker(s) at once (0.2 of 4 cores busy, 7.2 GiB of memory free)",
        "capacity: no room now (4.0 of 4 cores busy, 7.4 GiB of memory free); waiting up to 600 s",
        "e2e: 3 group(s) in 4.1 minutes: 240 passed, 0 failed, 0 flaky, 0 skipped",
        "1924 passed in 33.96s",
        "============================ 1924 passed in 40.05s =============================",
        "2 failed, 1922 passed in 41.10s",
        "\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m738 passed\x1b[39m\x1b[22m (738)",
    ],
)
def test_the_suite_says_a_wait_and_each_total(line: str) -> None:
    progress, _, said = watcher(SUITE_STAGES)

    progress.line(line + "\n")

    assert len(said) == 1


@pytest.mark.parametrize(
    "line",
    [
        "tests/test_access.py ................................................... [  2%]",
        "[1]   82 passed (4.1m)",
        "All checks passed!",
        "  ok 14 [board] e2e/collab.spec.ts:20:1 two people draw (1.2s)",
        "",
    ],
)
def test_the_suite_says_no_other_line(line: str) -> None:
    progress, _, said = watcher(SUITE_STAGES)

    progress.line(line + "\n")

    assert said == []


@pytest.mark.parametrize(
    "line",
    [
        "==> building the web application (npm ci --ignore-scripts, npm run build)",
        "== a release that does not start is taken out again",
        "FAIL  the unit is active",
        "capacity: 1 job(s) at once (0.9 of 4 cores busy, 7.2 GiB of memory free)",
        "systemd-test: all 218 checks passed",
    ],
)
def test_the_install_test_says_its_steps_a_failed_check_and_its_end(line: str) -> None:
    progress, _, said = watcher(PACKAGE_STAGES)

    progress.line(line + "\n")

    assert said == [f"    0:00  {line}"]


@pytest.mark.parametrize(
    "line",
    ["PASS  it is Ubuntu 26.04", "      (12 s)", "#24 54.13 tests/test_e2e_nginx.py ..", " == no"],
)
def test_the_install_test_says_no_other_line(line: str) -> None:
    progress, _, said = watcher(PACKAGE_STAGES)

    progress.line(line + "\n")

    assert said == []


def test_a_watched_command_keeps_its_whole_output_in_the_order_written(tmp_path: Path) -> None:
    progress, _, said = watcher(EVERY_LINE)
    code = "import sys\nprint('one')\nprint('two', file=sys.stderr)\nprint('three')\nsys.exit(3)\n"

    result = Runner(tmp_path).run(python(code), check=False, progress=progress)

    assert result == Result(3, "one\ntwo\nthree\n")
    assert result.output == "one\ntwo\nthree\n"
    assert said == ["    0:00  one", "    0:00  two", "    0:00  three"]


def test_a_watched_command_that_fails_raises_with_its_last_line(tmp_path: Path) -> None:
    code = "import sys; print('working'); print('no such unit', file=sys.stderr); sys.exit(2)"

    with pytest.raises(CommandError, match=r"exited with status 2: no such unit$"):
        Runner(tmp_path).run(python(code), progress=Progress(write=lambda _: None))


def test_a_watched_command_that_is_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="command not found: segl-no-such-command"):
        Runner(tmp_path).run(["segl-no-such-command"], progress=Progress())


def test_a_watched_command_runs_in_the_repository_and_reads_its_input(tmp_path: Path) -> None:
    code = "import os, sys; print(os.getcwd()); print(sys.stdin.read().upper())"

    result = Runner(tmp_path).run(python(code), stdin="asked\n", progress=Progress())

    assert result.stdout == f"{tmp_path}\nASKED\n\n"


def test_a_line_is_said_when_it_is_printed_and_not_at_the_end(tmp_path: Path) -> None:
    # Python holds its output back from a pipe. The runner asks it not to.
    seen: list[tuple[str, float]] = []

    class Timed(Progress):
        def line(self, text: str) -> None:
            seen.append((text.strip(), time.monotonic()))

    code = "import time; print('first'); time.sleep(0.8); print('second')"

    Runner(tmp_path).run(python(code), progress=Timed())

    assert [text for text, _ in seen] == ["first", "second"]
    assert seen[1][1] - seen[0][1] > 0.5, "the first line came while the command still ran"


def test_a_silent_command_is_looked_at_while_it_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release_proc, "WATCH_SECONDS", 0.05)
    said: list[str] = []
    progress = Progress(write=said.append, every=0.2)

    result = Runner(tmp_path).run(
        python("import time; time.sleep(0.9); print('end')"), progress=progress
    )

    assert result.stdout == "end\n"
    assert 2 <= len(said) <= 5, said
    assert all(line.endswith("still running") for line in said)


def test_a_watched_command_is_stopped_when_the_script_is_interrupted(tmp_path: Path) -> None:
    # Ctrl+C, or any error while it runs: the command does not outlive the script.
    pids: list[int] = []

    class Interrupted(Progress):
        def line(self, text: str) -> None:
            pids.append(int(text))
            raise KeyboardInterrupt

    code = "import os, time; print(os.getpid()); time.sleep(60)"
    began = time.monotonic()

    with pytest.raises(KeyboardInterrupt):
        Runner(tmp_path).run(python(code), progress=Interrupted())

    assert time.monotonic() - began < 10
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)


def test_a_line_reaches_a_pipe_when_it_is_said(tmp_path: Path) -> None:
    # `release.py publish | tee log` must not hold the lines back to the end.
    code = (
        "import sys, time\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "from release_progress import say\n"
        "say('first')\n"
        "time.sleep(0.8)\n"
        "say('second')\n"
    )
    # No PYTHONUNBUFFERED here: the line must come because `say` sends it.
    environment = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    process = subprocess.Popen(
        python(code), stdout=subprocess.PIPE, text=True, cwd=tmp_path, env=environment
    )
    assert process.stdout is not None

    first = process.stdout.readline()
    seen = time.monotonic()
    rest = process.stdout.read()
    ended = time.monotonic()
    process.wait()

    assert (first, rest) == ("first\n", "second\n")
    assert ended - seen > 0.5, "the first line came while the script still ran"


def test_the_suite_names_each_command_and_says_how_it_ended(
    tmp_path: Path, fake_runner, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = fake_runner(
        tmp_path,
        {
            ("uv", "run", "ruff"): "All checks passed!\n",
            (
                "uv",
                "run",
                "pytest",
            ): "capacity: 3 pytest worker(s) at once\n....\n4 passed in 0.10s\n",
        },
    )

    failure = run_commands(runner, [("uv", "run", "ruff", "check", "."), ("uv", "run", "pytest")])

    assert failure is None
    assert capsys.readouterr().out.splitlines() == [
        "  uv run ruff check .",
        "    0:00  done",
        "  uv run pytest",
        "    0:00  capacity: 3 pytest worker(s) at once",
        "    0:00  4 passed in 0.10s",
        "    0:00  done",
    ]


def test_the_suite_says_which_command_failed_and_stops_there(
    tmp_path: Path, fake_runner, capsys: pytest.CaptureFixture[str]
) -> None:
    failed = Result(1, "FAILED tests/test_health.py::test_health_answers_ok - boom\n")
    runner = fake_runner(tmp_path, {("uv", "run", "pytest"): failed})

    failure = run_commands(runner, [("uv", "run", "pytest"), ("uv", "run", "ty", "check")])

    assert failure == "tests/test_health.py::test_health_answers_ok"
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["  uv run pytest", "    0:00  failed"]
    assert out[2] == "  `uv run pytest` failed:"
    assert "  uv run ty check" not in out
    assert runner.calls == [["uv", "run", "pytest"]]
