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

"""Run other programs: an argument list each, and never a shell."""

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

# The exit status of a program that could not be started, as a shell gives it.
NOT_FOUND = 127


@dataclass(frozen=True)
class RunResult:
    """How a program ended."""

    code: int
    # Standard output and standard error together.
    output: str


Runner = Callable[[Sequence[str], bytes | None, Mapping[str, str] | None], RunResult]
"""Runs a program, with optional standard input and extra environment."""


def run_command(
    args: Sequence[str],
    stdin: bytes | None = None,
    env: Mapping[str, str] | None = None,
) -> RunResult:
    """Run a program and wait for it. One that cannot start ends with 127."""
    try:
        done = subprocess.run(
            list(args),
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, **env} if env else None,
            check=False,
        )
    except OSError as exc:
        return RunResult(NOT_FOUND, f"{args[0]}: {exc}")
    return RunResult(done.returncode, done.stdout.decode(errors="replace"))


def tail(output: str, lines: int = 3) -> str:
    """Return the last lines of a program's output on one line, for a message."""
    kept = [line.strip() for line in output.strip().splitlines() if line.strip()]
    return " / ".join(kept[-lines:]) or "no output"
