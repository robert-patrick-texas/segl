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

"""Run the commands a release needs: git, gh, uv, npm, and cloc.

Every command is an argument list and never passes through a shell. Tests
replace the runner with a fake, so no test talks to GitHub or pushes.
The pattern follows Sunstone's tools/release.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class CommandError(RuntimeError):
    """A command was missing or exited with a status other than 0."""


@dataclass(frozen=True)
class Result:
    """The exit status and output of one finished command."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def output(self) -> str:
        """Return standard output followed by standard error."""
        return self.stdout + self.stderr


class Runner:
    """Runs commands in the repository."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def run(self, argv: Sequence[str], *, check: bool = True) -> Result:
        """Run one command and wait for it.

        Raises:
            CommandError: When the program is missing, or exits with a status
                other than 0 while ``check`` is true.
        """
        try:
            done = subprocess.run(
                list(argv), cwd=self.cwd, capture_output=True, text=True, check=False
            )
        except FileNotFoundError as exc:
            raise CommandError(f"command not found: {argv[0]}") from exc
        result = Result(done.returncode, done.stdout or "", done.stderr or "")
        if check and result.returncode != 0:
            last = result.stderr.strip().splitlines()[-1:]
            suffix = f": {last[0]}" if last else ""
            raise CommandError(f"{' '.join(argv[:3])} exited with status {done.returncode}{suffix}")
        return result
