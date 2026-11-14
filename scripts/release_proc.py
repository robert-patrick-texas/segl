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

import os
import queue
import subprocess
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from release_progress import Progress

# How often a watched command that prints nothing is looked at.
WATCH_SECONDS = 1.0


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

    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = True,
        capture: bool = True,
        stdin: str | None = None,
        progress: Progress | None = None,
    ) -> Result:
        """Run one command and wait for it.

        Args:
            argv: The program and its arguments.
            check: Raise when the exit status is not 0.
            capture: Keep the output. False leaves it on the terminal, for a
                program that asks something there, such as a passphrase.
            stdin: Text to give the program on its standard input.
            progress: Is given each line of output as it comes, for a command
                that takes minutes. The output is kept all the same, with
                standard error among standard output, in the order written.

        Raises:
            CommandError: When the program is missing, or exits with a status
                other than 0 while ``check`` is true.
        """
        if progress is not None:
            return self._watched(argv, check, stdin, progress)
        try:
            done = subprocess.run(
                list(argv),
                cwd=self.cwd,
                capture_output=capture,
                text=True,
                check=False,
                input=stdin,
            )
        except FileNotFoundError as exc:
            raise CommandError(f"command not found: {argv[0]}") from exc
        result = Result(done.returncode, done.stdout or "", done.stderr or "")
        if check and result.returncode != 0:
            last = result.stderr.strip().splitlines()[-1:]
            suffix = f": {last[0]}" if last else ""
            raise CommandError(f"{' '.join(argv[:3])} exited with status {done.returncode}{suffix}")
        return result

    def _watched(
        self, argv: Sequence[str], check: bool, stdin: str | None, progress: Progress
    ) -> Result:
        """Run one command and hand each line it prints to ``progress``."""
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=self.cwd,
                stdin=subprocess.PIPE if stdin is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                # Python holds its output back from a pipe otherwise.
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except FileNotFoundError as exc:
            raise CommandError(f"command not found: {argv[0]}") from exc
        assert process.stdout is not None
        output = process.stdout
        lines: queue.Queue[str | None] = queue.Queue()

        def read() -> None:
            for line in output:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=read, daemon=True).start()
        kept: list[str] = []
        try:
            if stdin is not None and process.stdin is not None:
                process.stdin.write(stdin)
                process.stdin.close()
            while True:
                try:
                    line = lines.get(timeout=WATCH_SECONDS)
                except queue.Empty:
                    progress.tick()
                    continue
                if line is None:
                    break
                kept.append(line)
                progress.line(line)
            returncode = process.wait()
        except BaseException:
            process.kill()
            process.wait()
            raise
        result = Result(returncode, "".join(kept))
        if check and returncode != 0:
            last = result.stdout.strip().splitlines()[-1:]
            suffix = f": {last[0]}" if last else ""
            raise CommandError(f"{' '.join(argv[:3])} exited with status {returncode}{suffix}")
        return result
