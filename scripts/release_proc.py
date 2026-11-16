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

import contextlib
import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from release_progress import Progress

# How often a watched command that prints nothing is looked at.
WATCH_SECONDS = 1.0
# How long a watched command that was told to stop has before it is killed.
# scripts/e2e.py gives its groups 20 seconds to stop their servers.
STOP_SECONDS = 30.0


class CommandError(RuntimeError):
    """A command was missing or exited with a status other than 0."""


@dataclass(frozen=True)
class Result:
    """The exit status and output of one finished command."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    # Ended because it was told to stop (`cancel`), not on its own.
    stopped: bool = False

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
        cancel: threading.Event | None = None,
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
            cancel: Stops a watched command when it is set: the suite stops
                the commands beside one that failed.

        Raises:
            CommandError: When the program is missing, or exits with a status
                other than 0 while ``check`` is true.
        """
        if progress is not None:
            return self._watched(argv, check, stdin, progress, cancel)
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
        self,
        argv: Sequence[str],
        check: bool,
        stdin: str | None,
        progress: Progress,
        cancel: threading.Event | None,
    ) -> Result:
        """Run one command and hand each line it prints to ``progress``.

        The command runs in a process group of its own, so that a stop reaches
        what it started too: pytest's workers, and the browser tests' servers.
        """
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
                start_new_session=True,
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
        told: float | None = None
        try:
            if stdin is not None and process.stdin is not None:
                process.stdin.write(stdin)
                process.stdin.close()
            while True:
                if cancel is not None and cancel.is_set():
                    told = _stop(process, told)
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
            told = _stop(process, None)
            while process.poll() is None:
                time.sleep(0.1)
                told = _stop(process, told)
            raise
        result = Result(returncode, "".join(kept), stopped=told is not None)
        if told is not None:
            # Whatever it started that has not stopped by now is ended here.
            _signal(process, signal.SIGKILL)
        if check and returncode != 0:
            last = result.stdout.strip().splitlines()[-1:]
            suffix = f": {last[0]}" if last else ""
            raise CommandError(f"{' '.join(argv[:3])} exited with status {returncode}{suffix}")
        return result


def _signal(process: subprocess.Popen[str], number: int) -> None:
    """Send a signal to a watched command's process group."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, number)


def _stop(process: subprocess.Popen[str], told: float | None) -> float:
    """Tell a watched command to stop, as Ctrl+C would, then kill it after a while.

    Returns when it was first told, for the next call.
    """
    if told is None:
        _signal(process, signal.SIGINT)
        return time.monotonic()
    if time.monotonic() - told >= STOP_SECONDS:
        _signal(process, signal.SIGKILL)
    return told
