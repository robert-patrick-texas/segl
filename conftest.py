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
over before workers would have started. `-n 0` does the same for any run,
and `SEGL_TEST_GROUPS` and `SEGL_TEST_WAIT` are read as scripts/e2e.py reads
them (docs/DEVELOPMENT.md, checks).
"""

from collections.abc import Sequence
from pathlib import Path

import capacity
import pytest

# A run that names no more than this many test files, and no folder, is small.
SMALL_RUN_FILES = 3


def is_small_run(args: Sequence[str], from_command_line: bool) -> bool:
    """Return whether the run names only a few test files.

    ``args`` are the paths pytest was given, each with an optional
    ``::test`` after it. Without any, pytest runs the whole suite.
    """
    if not from_command_line:
        return False
    files = {arg.split("::", 1)[0] for arg in args}
    return len(files) <= SMALL_RUN_FILES and all(Path(name).is_file() for name in files)


def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """Return the number of worker processes. 0 is: run in this process."""
    from_command_line = config.args_source is pytest.Config.ArgsSource.ARGS
    if is_small_run(config.args, from_command_line):
        return 0
    workers = capacity.wait_for_room(
        capacity.MOST_WORKERS, each=capacity.WORKER_BYTES, unit="pytest worker"
    )
    # One worker is one process with the cost of starting another.
    return workers if workers > 1 else 0
