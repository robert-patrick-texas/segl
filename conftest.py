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

"""How many processes pytest runs the tests in.

`uv run pytest` runs the suite in several worker processes at once
(pytest-xdist, `-n auto` in pyproject.toml). This file says how many, with
scripts/capacity.py: one for each core that is idle now, less one, and no
more than there is memory for. On a machine that is busy with other work it
waits for room, and after ten minutes it goes ahead with what there is.

A run of a few named files stays in one process and does not wait: it is
over before workers would have started. A run of named files that hold no
more than a quarter of the suite's tests, as `scripts/suite.py --changed`
runs, does not wait either: it takes the workers there is room for now, and
one process when there is none. `-n 0` is one process for any run, and
`SEGL_TEST_GROUPS` and `SEGL_TEST_WAIT` are read as scripts/e2e.py reads them
(docs/DEVELOPMENT.md, checks).
"""

import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

import capacity
import pytest

ROOT = Path(__file__).resolve().parent
# Where the suite's test files are (pyproject.toml, testpaths).
TEST_FOLDERS = ("tests", "tools")
# A run that names no more than this many test files, and no folder, is small.
SMALL_RUN_FILES = 3
# A run of named files with no more than this share of the suite's tests is a
# part of it, and does not wait for room.
PART_OF_SUITE = 0.25
_TEST = re.compile(r"^\s*(?:async\s+)?def test_", flags=re.MULTILINE)


def named_files(args: Sequence[str], from_command_line: bool) -> set[str] | None:
    """Return the test files a run names, or None when it names a folder or nothing.

    ``args`` are the paths pytest was given, each with an optional
    ``::test`` after it. Without any, pytest runs the whole suite.
    """
    if not from_command_line:
        return None
    files = {arg.split("::", 1)[0] for arg in args}
    return files if files and all(Path(name).is_file() for name in files) else None


def is_small_run(args: Sequence[str], from_command_line: bool) -> bool:
    """Return whether the run names only a few test files."""
    files = named_files(args, from_command_line)
    return files is not None and len(files) <= SMALL_RUN_FILES


def count_tests(paths: Iterable[Path]) -> int:
    """Return how many test functions the files define, before any parameters."""
    return sum(len(_TEST.findall(path.read_text(encoding="utf-8"))) for path in paths)


def is_part_of_suite(args: Sequence[str], from_command_line: bool, root: Path = ROOT) -> bool:
    """Return whether the run names files with at most a quarter of the suite's tests."""
    files = named_files(args, from_command_line)
    if files is None:
        return False
    suite = [path for folder in TEST_FOLDERS for path in (root / folder).rglob("test_*.py")]
    return count_tests(Path(name) for name in files) <= PART_OF_SUITE * count_tests(suite)


def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """Return the number of worker processes. 0 is: run in this process."""
    from_command_line = config.args_source is pytest.Config.ArgsSource.ARGS
    if is_small_run(config.args, from_command_line):
        return 0
    if is_part_of_suite(config.args, from_command_line):
        # As many as fit now. A part of the suite is over in seconds, and a
        # wait for a busy machine took minutes.
        workers = capacity.wait_for_room(
            capacity.MOST_WORKERS,
            each=capacity.WORKER_BYTES,
            unit="pytest worker",
            environ={**os.environ, capacity.WAIT_SETTING: "0"},
        )
    else:
        workers = capacity.wait_for_room(
            capacity.MOST_WORKERS, each=capacity.WORKER_BYTES, unit="pytest worker"
        )
    # One worker is one process with the cost of starting another.
    return workers if workers > 1 else 0
