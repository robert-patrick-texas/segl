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

"""Keep what `publish` prints in a log file as well as on the terminal.

The maintainer runs `publish` at their own terminal, since signing asks for
the key's passphrase. The log lets the run be read afterwards without a copy
and paste. Each run adds to the log under a line that names the version, the
time, and HEAD, so a run that failed is kept beside the one after it.

A program that writes to the terminal itself, as `ssh-keygen` does when it
asks for the passphrase, is not in the log.
"""

from __future__ import annotations

import contextlib
import sys
import traceback
from collections.abc import Generator
from pathlib import Path
from typing import TextIO


class Tee:
    """A text stream that writes to two others."""

    def __init__(self, first: TextIO, second: TextIO) -> None:
        self.first, self.second = first, second

    def write(self, text: str) -> int:
        self.first.write(text)
        self.second.write(text)
        return len(text)

    def flush(self) -> None:
        self.first.flush()
        self.second.flush()


@contextlib.contextmanager
def logged(path: Path, header: str) -> Generator[None, None, None]:
    """Copy all that is printed inside the block to ``path``, after ``header``.

    An error that ends the block goes in the log too. Python prints it on the
    terminal as it ends.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        log.write(f"{header}\n")
        log.flush()
        terminal = sys.stdout
        sys.stdout = Tee(terminal, log)
        try:
            yield
        except BaseException:
            log.write(traceback.format_exc())
            raise
        finally:
            sys.stdout = terminal
