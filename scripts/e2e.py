#!/usr/bin/env python3
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

"""Run all the browser tests, in as many groups at once as the machine has room for.

    python3 scripts/e2e.py [--report FILE] [-- arguments for `playwright test`]

`npm --prefix web run e2e` runs the tests one at a time, in one process, and
is the way to run one spec. This runs the whole suite. It splits the tests
into groups with Playwright's `--shard`, and runs the groups side by side.
Each group is a `playwright test` of its own with its own servers: the test
servers' ports all follow `SEGL_E2E_PORT` (web/e2e/sites.ts), and each group
gets a base of its own. Inside a group the tests still run one at a time and
share their slots, as they are written to.

scripts/capacity.py says how many groups: fewer on a busy machine, more
where there are more cores and memory, and it waits when there is no room.
`SEGL_TEST_GROUPS=1` is one group, as before.

The exit status is 0 when every group passed. `--report` writes one
Playwright JSON report for all the groups, which scripts/testplan.py reads.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import capacity

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
PORT_SETTING = "SEGL_E2E_PORT"
FIRST_PORT = 18950
# A group's servers take seven ports from its base (web/e2e/sites.ts).
PORTS_A_GROUP = 7
PORT_STEP = 10


def port_bases(groups: int, first: int) -> list[int]:
    """Return each group's port base."""
    return [first + PORT_STEP * index for index in range(groups)]


def busy_ports(bases: Sequence[int]) -> list[int]:
    """Return the ports the groups need that something already listens on."""
    taken = []
    for base in bases:
        for port in range(base, base + PORTS_A_GROUP):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    taken.append(port)
    return taken


def group_command(index: int, groups: int, extra: Sequence[str]) -> list[str]:
    """Return the `playwright test` of one group, counted from 1."""
    command = ["npx", "playwright", "test", "--reporter=list,json"]
    # Each group clears its output folder when it starts, so each has its own.
    command.append(f"--output=test-results/group-{index}")
    if groups > 1:
        command.append(f"--shard={index}/{groups}")
    return [*command, *extra]


def merge_reports(reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Return one Playwright JSON report with every group's suites and counts."""
    merged: dict[str, Any] = {"suites": [], "errors": [], "stats": {}}
    for report in reports:
        merged["suites"].extend(report.get("suites", []))
        merged["errors"].extend(report.get("errors", []))
        for key, value in report.get("stats", {}).items():
            if key == "startTime":
                merged["stats"][key] = min(merged["stats"].get(key, value), value)
            elif isinstance(value, (int, float)):
                # Counts add up. The groups ran side by side, so the time
                # that passed is the longest group's.
                joined = max if key == "duration" else (lambda a, b: a + b)
                merged["stats"][key] = joined(merged["stats"].get(key, 0), value)
    return merged


def _relay(stream: Any, label: str, log: Any) -> None:
    """Copy a group's output to its log, and to the terminal behind its label."""
    for line in stream:
        log.write(line)
        sys.stdout.write(f"{label}{line}")
        sys.stdout.flush()


def run_groups(groups: int, first_port: int, extra: Sequence[str], work: Path) -> list[int]:
    """Run the groups side by side. Return each one's exit status."""
    bases = port_bases(groups, first_port)
    taken = busy_ports(bases)
    if taken:
        ports = ", ".join(str(port) for port in taken)
        raise SystemExit(f"e2e: something already listens on port {ports}; is a run under way?")
    running: list[tuple[subprocess.Popen[str], threading.Thread, Any]] = []
    try:
        for index, base in enumerate(bases, start=1):
            env = {
                **os.environ,
                PORT_SETTING: str(base),
                "PLAYWRIGHT_JSON_OUTPUT_FILE": str(work / f"group-{index}.json"),
                # A terminal's colors and cursor moves do not survive a pipe.
                "FORCE_COLOR": "0",
            }
            log = (work / f"group-{index}.log").open("w", encoding="utf-8")
            process = subprocess.Popen(
                group_command(index, groups, extra),
                cwd=WEB,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Its own process group, so a stop reaches its test servers too.
                start_new_session=True,
            )
            label = f"[{index}] " if groups > 1 else ""
            thread = threading.Thread(target=_relay, args=(process.stdout, label, log), daemon=True)
            thread.start()
            running.append((process, thread, log))
        return [process.wait() for process, _thread, _log in running]
    except KeyboardInterrupt:
        # Playwright stops its servers on an interrupt.
        for process, _thread, _log in running:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
        raise
    finally:
        deadline = time.monotonic() + 20
        for process, thread, log in running:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
            thread.join(timeout=5)
            log.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command and return its exit status."""
    parser = argparse.ArgumentParser(
        prog="e2e.py", description="Run the browser tests, in several groups at once."
    )
    parser.add_argument("--report", type=Path, help="write one JSON report of every group here")
    parser.add_argument("playwright", nargs="*", help="arguments for `playwright test`, after --")
    args = parser.parse_args(argv)

    groups = capacity.wait_for_room()
    first_port = int(os.environ.get(PORT_SETTING, FIRST_PORT))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="segl-e2e-groups-") as folder:
        work = Path(folder)
        statuses = run_groups(groups, first_port, args.playwright, work)
        reports = []
        for index in range(1, groups + 1):
            path = work / f"group-{index}.json"
            if path.is_file():
                reports.append(json.loads(path.read_text(encoding="utf-8")))
        merged = merge_reports(reports)
        if args.report is not None and len(reports) == groups:
            # A group that left no report leaves none here: the reader then
            # fails every row that needs one, which is the truth.
            args.report.write_text(json.dumps(merged), encoding="utf-8")
    minutes = (time.monotonic() - started) / 60
    stats = merged["stats"]
    failed = [index for index, status in enumerate(statuses, start=1) if status != 0]
    print(
        f"e2e: {groups} group(s) in {minutes:.1f} minutes: "
        f"{stats.get('expected', 0)} passed, {stats.get('unexpected', 0)} failed, "
        f"{stats.get('flaky', 0)} flaky, {stats.get('skipped', 0)} skipped"
    )
    if failed:
        print(f"e2e: group(s) {', '.join(str(index) for index in failed)} failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
