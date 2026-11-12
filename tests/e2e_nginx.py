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

"""nginx for the browser tests, from the same harness the mount tests use.

``web/playwright.config.ts`` starts segl itself, then this script, which puts
nginx in front of it with the files in deploy/nginx/ (``harness.install_nginx``)
and keeps it running until the script is stopped.

Each site example gets an nginx of its own, on its own loopback port:
``site-board.example.conf`` (segl at ``/board/``) on ``--board-port``, and
``site-root.example.conf`` (segl at the host root) on ``--root-port``. With one
site to an instance, the browser reaches it as ``https://127.0.0.1:<port>/``
and needs no name for it. tests/test_mount.py covers the site names and
verifies the certificate.

    uv run python tests/e2e_nginx.py --prefix /tmp/x --upstream-port 18950 \
        --board-port 18951 --root-port 18952
"""

import argparse
import shutil
import signal
import sys
import threading
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path
from types import FrameType

import harness
from harness import BOARD_SITE, ROOT_SITE, NginxTools

# Playwright waits for this line before it runs a test.
READY = "nginx is serving"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run nginx in front of a segl test server.")
    parser.add_argument("--prefix", type=Path, required=True, help="A folder to run in.")
    parser.add_argument("--upstream-port", type=int, required=True, help="Where segl listens.")
    parser.add_argument("--board-port", type=int, required=True, help="HTTPS, segl at /board/.")
    parser.add_argument("--root-port", type=int, required=True, help="HTTPS, segl at /.")
    return parser


# Set by SIGTERM or an interrupt. Playwright signals the whole process group,
# so the signal can arrive more than once.
_stopping = threading.Event()


def _stop(signum: int, frame: FrameType | None) -> None:
    _stopping.set()


def main(argv: Sequence[str] | None = None) -> int:
    """Serve until SIGTERM or an interrupt. Return the exit status."""
    args = build_parser().parse_args(argv)
    tools = harness.find_nginx_tools()
    if not isinstance(tools, NginxTools):
        print(f"e2e_nginx: {tools}", file=sys.stderr)
        return 1
    prefix: Path = args.prefix.resolve()
    shutil.rmtree(prefix, ignore_errors=True)
    certificate, key = harness.make_certificate(tools, prefix / "certificate")
    ports = {BOARD_SITE: args.board_port, ROOT_SITE: args.root_port}
    for site, port in ports.items():
        harness.install_nginx(
            prefix / site,
            sites=(site,),
            upstream_port=args.upstream_port,
            # The examples' port-80 servers only redirect. Nothing asks for them here.
            http_port=harness.free_port(),
            https_port=port,
            certificate=certificate,
            key=key,
        )
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    with ExitStack() as running:
        for site, port in ports.items():
            running.enter_context(harness.running_nginx(tools, prefix / site, port))
        print(
            f"{READY} https://127.0.0.1:{args.board_port}/board/ "
            f"and https://127.0.0.1:{args.root_port}/",
            flush=True,
        )
        _stopping.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
