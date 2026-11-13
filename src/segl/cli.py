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
import time
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from segl.access import PASS_AHEAD_SECONDS
from segl.app import create_app
from segl.assets import AssetsError
from segl.config import ConfigError, load_settings
from segl.names import DisplayNamesError
from segl.repository import Repository, StorageError
from segl.versions import app_version
from segl.web import WebBuildError


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
    ended = settings.access_passes_after_seconds
    if ended is not None and ended > time.time() + PASS_AHEAD_SECONDS:
        # Most likely a slip with the time zone. segl still starts: the codes
        # are read, and the passes they buy are stamped with that time.
        print(
            "segl: access_passes_after is ahead of this server's clock: "
            "no pass lets a browser edit until then",
            file=sys.stderr,
        )
    # The database is opened, migrated, and given its nine slots before the
    # port is, so a database segl cannot use stops it here with one line. So
    # does a display-name file without words, which create_app reads, and a
    # folder for uploaded files that segl cannot write in. The application
    # closes the database at shutdown. The `with` covers a stop before that.
    try:
        with Repository(settings.database, history_limit=settings.history_limit) as repository:
            repository.bootstrap()
            app = create_app(settings, repository)
            app.state.assets.prepare()
            if app.state.web_build is None:
                # The API still answers, which is all the Vite dev server needs.
                print(
                    f"segl: no web application in {settings.web_dir} "
                    "(build it with `npm --prefix web run build`); serving the API only",
                    file=sys.stderr,
                )
            uvicorn.run(
                app,
                host=settings.host,
                port=settings.port,
                # X-Forwarded-For and X-Forwarded-Proto count only when the connection
                # comes from one of these addresses, which is nginx (docs/SECURITY.md).
                proxy_headers=True,
                forwarded_allow_ips=list(settings.trusted_proxies),
                # The WebSocket at /collab. A message may be a whole scene.
                # uvicorn pings each connection every 20 seconds by default.
                ws="websockets-sansio",
                ws_max_size=settings.max_scene_bytes,
            )
    except (StorageError, DisplayNamesError, WebBuildError, AssetsError) as exc:
        print(f"segl: {exc}", file=sys.stderr)
        return 1
    return 0
