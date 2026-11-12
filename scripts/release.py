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

"""Prepare and publish a segl release from versions.toml. See docs/RELEASING.md.

    python3 scripts/release.py check [--gate]
    python3 scripts/release.py upgrade
    python3 scripts/release.py notes
    python3 scripts/release.py cut
    python3 scripts/release.py publish

The work is in the sibling ``release_*`` modules. This file is the command line.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import release_notes
import release_publish
import release_upgrade
from release_components import Sources, gate_passes, load_versions, report
from release_proc import Runner

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ("check", "upgrade", "notes", "cut", "publish")


def cmd_check(root: Path, sources: Sources, gate: bool) -> int:
    """Print each component beside its newest release. Change nothing."""
    doc = load_versions(root)
    print(f"segl {doc['project']['version']}  Python {doc['runtime']['python']}")
    statuses = report(root, sources)
    for status in statuses:
        print(status.line)
    if not gate:
        return 0
    blocking = [status for status in statuses if status.blocks]
    if blocking:
        print(f"gate: {len(blocking)} component(s) are not current or held")
    else:
        print("gate: every component is current or held")
    return 0 if gate_passes(statuses) else 1


def cmd_notes(root: Path, runner: Runner) -> int:
    """Print the release-note body."""
    doc = load_versions(root)
    sys.stdout.write(release_notes.preview(root, runner, doc))
    sys.stdout.flush()
    if str(doc["project"]["version"]) == release_publish.UNPUBLISHED:
        print(
            "\nPreview only. project.version is 0.0.0, which is not a publishable release.",
            file=sys.stderr,
        )
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and publish a segl release")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument(
        "--gate",
        action="store_true",
        help="with check, exit 1 unless every component is current or held",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    runner = Runner(root)
    sources = Sources(runner)
    if args.command == "check":
        return cmd_check(root, sources, args.gate)
    if args.command == "upgrade":
        return release_upgrade.upgrade(root, runner, sources)
    if args.command == "notes":
        return cmd_notes(root, runner)
    if args.command == "cut":
        return release_publish.cut(root, runner, sources)
    return release_publish.publish(root, runner, sources)


if __name__ == "__main__":
    raise SystemExit(main())
