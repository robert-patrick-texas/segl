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

"""``segl slot clear N``: empty slots for good (docs/DEPLOY.md, "Clearing a slot").

A slot's scene, title, history, and file rows go, and so do the image files
under ``assets_dir`` that no other slot names. The slot's epoch goes up, as a
restore's does, so a browser that was open on it takes the empty board when
it reconnects.

A running segl holds each open slot's scene in memory and would write it
back. So with the package's settings and its unit running, the command stops
the unit first and starts it after, as ``segl update`` does. Otherwise it
refuses while anything answers on segl's port.
"""

import argparse
import os
import socket
import sys
import syslog
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from segl.assets import AssetStore
from segl.config import ConfigError, Settings, load_settings
from segl.repository import Repository, SlotContents, StorageError
from segl.update.command import config_option
from segl.update.paths import INSTALLED, SERVICE
from segl.update.process import Runner, run_command, tail

PREFIX = "segl slot clear"
USAGE = 2
# How long a started unit has to answer on its port.
START_SECONDS = 30.0


def slot_number(text: str) -> int:
    """Return a slot number as the command line gives it.

    Raises:
        argparse.ArgumentTypeError: When it is not one of 1 to 9.
    """
    if text not in {str(number) for number in range(1, 10)}:
        raise argparse.ArgumentTypeError(f"{text!r} is not a slot: the slots are 1 to 9")
    return int(text)


def add_command(commands: argparse._SubParsersAction) -> None:
    """Add ``segl slot clear`` to the list of commands."""
    slot = commands.add_parser("slot", help="work on the slots")
    actions = slot.add_subparsers(dest="slot_command", metavar="ACTION", required=True)
    clear = actions.add_parser(
        "clear",
        help="empty slots for good: the scene, the title, the history, and the files",
        description="Empty each slot named for good: its scene, its title, its whole "
        "history, and its files, with the image files no other slot names. It says what "
        "goes and asks for each number to be typed back. With the package's settings, it "
        "stops segl's unit first and starts it after. A clear cannot be undone.",
    )
    config_option(clear)
    clear.add_argument(
        "slots", nargs="+", type=slot_number, metavar="N", help="a slot number, 1 to 9"
    )
    clear.add_argument("--yes", action="store_true", help="clear without asking")


def _typed(question: str) -> str | None:
    """Return the line typed at the terminal, or None when there is no terminal."""
    if not sys.stdin.isatty():
        return None
    try:
        return input(question)
    except EOFError:
        return None


def _answers(host: str, port: int) -> bool:
    """Return whether anything takes a connection on segl's port."""
    if host in ("", "0.0.0.0"):
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _to_log(line: str) -> None:
    """Write a line to segl's log: the system log, as the unit's own lines (``segl``)."""
    syslog.openlog("segl", syslog.LOG_PID)
    syslog.syslog(syslog.LOG_NOTICE, line)
    syslog.closelog()


@dataclass
class Host:
    """What the command needs of the machine it runs on. Tests replace each part."""

    # Looked up when a Host is made, so that a test can put each one aside.
    run: Runner = field(default_factory=lambda: run_command)
    is_root: Callable[[], bool] = field(default=lambda: os.geteuid() == 0)
    answers: Callable[[str, int], bool] = field(default_factory=lambda: _answers)
    typed: Callable[[str], str | None] = field(default_factory=lambda: _typed)
    say: Callable[[str], None] = print
    log: Callable[[str], None] = field(default_factory=lambda: _to_log)
    sleep: Callable[[float], None] = time.sleep


def amount(size: int) -> str:
    """Return a number of bytes as a person reads it."""
    if size < 1024:
        return f"{size} bytes" if size != 1 else "1 byte"
    if size < 1024**2:
        return f"{size / 1024:.1f} KiB"
    return f"{size / 1024**2:.1f} MiB"


def _counted(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def describe(contents: SlotContents) -> str:
    """Return the line that says what a clear removes from one slot."""
    slot = contents.slot
    return (
        f"Slot {slot.number} ({slot.title}): {_counted(contents.elements, 'element')}, "
        f"{_counted(contents.revisions, 'revision')}, {_counted(contents.files, 'file')}."
    )


def run(args: argparse.Namespace, host: Host | None = None) -> int:
    """Run ``segl slot clear`` as parsed, and return its exit status."""
    host = host or Host()
    config: Path = getattr(args, "config", None) or INSTALLED.config_file
    try:
        settings = load_settings(config)
    except ConfigError as exc:
        host.say(f"{PREFIX}: {exc}")
        return USAGE
    return Clear(settings, config, host).clear(args.slots, yes=args.yes)


class Clear:
    """One run of the command."""

    def __init__(self, settings: Settings, config: Path, host: Host) -> None:
        self.settings = settings
        self.config = config
        self.host = host
        self.store = AssetStore(settings.assets_dir)

    def clear(self, slots: Sequence[int], *, yes: bool) -> int:
        """Clear these slots in number order. Return 0, or 1 when not all was done, or 2."""
        slots = sorted(set(slots))
        say = self.host.say
        settings = self.settings
        if not settings.database.is_file():
            say(f"{PREFIX}: there is no database at {settings.database}: nothing to clear")
            return 1
        unit = self.config == INSTALLED.config_file and self._unit("is-active", "--quiet") == 0
        if unit and not self.host.is_root():
            say(f"{PREFIX}: stopping {SERVICE} needs root: sudo segl slot clear ...")
            return USAGE
        if not unit and self.host.answers(settings.host, settings.port):
            say(
                f"{PREFIX}: segl answers on {settings.host}:{settings.port}. Stop it first: "
                "a running segl holds each open slot in memory, and would write it back."
            )
            return 1
        try:
            with Repository(settings.database, history_limit=settings.history_limit) as repo:
                contents = [repo.slot_contents(number) for number in slots]
                outside = repo.hashes_named_outside(slots)
        except StorageError as exc:
            say(f"{PREFIX}: {exc}")
            return 1
        unnamed = frozenset().union(*(each.hashes for each in contents)) - outside
        for each in contents:
            say(describe(each))
        size = sum(self.store.size(name) for name in unnamed)
        whose = "this slot names" if len(slots) == 1 else "these slots name"
        if unnamed:
            say(f"Image files only {whose}: {len(unnamed)}, {amount(size)}. They go too.")
        else:
            say(f"Image files only {whose}: none.")
        say("A clear cannot be undone.")
        if not yes and not self._confirmed(slots):
            say("Nothing was cleared.")
            return 1
        if unit:
            say(f"Stopping {SERVICE}.")
            stopped = self.host.run(["systemctl", "stop", SERVICE], None, None)
            if stopped.code != 0:
                say(f"{PREFIX}: {SERVICE} did not stop: {tail(stopped.output)}")
                say("Nothing was cleared.")
                return 1
        try:
            status = self._clear(contents)
        finally:
            # Also after a failure: the boards come back, cleared or not.
            started = not unit or self._start()
        return status if started else 1

    def _confirmed(self, slots: Sequence[int]) -> bool:
        for number in slots:
            typed = self.host.typed(f"Type {number} to clear slot {number}: ")
            if typed is None:
                self.host.say("There is no terminal to ask at: add --yes to clear.")
                return False
            if typed.strip() != str(number):
                self.host.say(f"That is not {number}.")
                return False
        return True

    def _clear(self, contents: Sequence[SlotContents]) -> int:
        """Clear each slot, and delete the files no slot names after it. Return 0 or 1."""
        say = self.host.say
        settings = self.settings
        deleted, freed = 0, 0
        try:
            with Repository(settings.database, history_limit=settings.history_limit) as repo:
                # As segl does when it starts: a database it knows, at its newest schema.
                repo.bootstrap()
                for each in contents:
                    number = each.slot.number
                    done = repo.clear_slot(number)
                    files = sorted(done.unnamed)
                    for name in files:
                        freed += self.store.size(name)
                        self.store.remove(name)
                    deleted += len(files)
                    say(f"Cleared slot {number}. It is empty, at epoch {done.epoch}.")
                    self.host.log(
                        f"slot {number} cleared by segl slot clear: {each.elements} elements, "
                        f"{each.revisions} revisions, {each.files} files, and "
                        f"{len(files)} image files deleted"
                    )
        except (StorageError, OSError) as exc:
            say(f"{PREFIX}: {exc}")
            return 1
        finally:
            if deleted:
                say(f"Deleted {_counted(deleted, 'image file')}, {amount(freed)}.")
        return 0

    def _start(self) -> bool:
        """Start the unit again, and wait for segl to answer. Return whether it does."""
        say = self.host.say
        say(f"Starting {SERVICE}.")
        # Starts that failed count against the unit's limit, which would refuse this one.
        self._unit("reset-failed")
        started = self.host.run(["systemctl", "start", SERVICE], None, None)
        if started.code != 0:
            say(f"{PREFIX}: {SERVICE} did not start; see `journalctl -u segl`")
            return False
        waited = 0.0
        while not self.host.answers(self.settings.host, self.settings.port):
            if waited >= START_SECONDS or self._unit("is-failed", "--quiet") == 0:
                say(f"{PREFIX}: segl does not answer; see `journalctl -u segl`")
                return False
            self.host.sleep(0.5)
            waited += 0.5
        say("segl answers again.")
        return True

    def _unit(self, *action: str) -> int:
        return self.host.run(["systemctl", *action, SERVICE], None, None).code
