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

"""The ``segl`` command: serve the application, or print the version."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from segl.app import create_app
from segl.config import ConfigError, load_settings
from segl.versions import app_version


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser(prog="segl", description="Serve segl until interrupted.")
    parser.add_argument("--version", action="version", version=f"segl {app_version()}")
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="TOML configuration file (docs/DEPLOY.md). Without it, development defaults apply.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command and return its exit status."""
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"segl: {exc}", file=sys.stderr)
        return 2
    uvicorn.run(create_app(), host=settings.host, port=settings.port)
    return 0
