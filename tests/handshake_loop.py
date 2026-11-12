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

"""Many WebSocket handshakes through one test nginx, to see whether any is lost.

The harness holds its client to TLS 1.2 (``running_mount``), because under
TLS 1.3 the ``websockets`` sync client sometimes lost its request on a busy
machine (docs/ROADMAP.md, "Held until a dependency moves"). This is the
measurement behind the hold, and the way to find out whether a newer release
of the client lets it go::

    uv run python tests/handshake_loop.py 3000 --busy 8            # as held
    uv run python tests/handshake_loop.py 3000 --busy 8 --tls13    # without the hold

``--busy`` is how many processes keep the processor busy meanwhile: the loss
shows only on a machine with too much to do, such as a CI runner. A handshake
that is lost takes a minute, which is nginx's wait for the request, so the
loop stops at the second one. The exit status is 0 when none was lost.
"""

import argparse
import multiprocessing
import ssl
import sys
import tempfile
import time
from multiprocessing.synchronize import Event
from pathlib import Path

from harness import BOARD_SITE, find_nginx_tools, make_certificate, running_mount, say_hello

# One lost handshake could be anything. Two are the failure.
STOP_AFTER = 2


def _burn(stop: Event) -> None:
    """Keep one processor busy until told to stop."""
    while not stop.is_set():
        sum(number * number for number in range(20000))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("count", type=int, help="how many handshakes to make")
    parser.add_argument("--busy", type=int, default=0, help="processes that keep the CPU busy")
    parser.add_argument("--tls13", action="store_true", help="let the client speak TLS 1.3")
    arguments = parser.parse_args(argv)
    tools = find_nginx_tools()
    if isinstance(tools, str):
        print(tools, file=sys.stderr)
        return 2

    stop = multiprocessing.Event()
    burners = [
        multiprocessing.Process(target=_burn, args=(stop,), daemon=True)
        for _ in range(arguments.busy)
    ]
    made, lost, version = 0, 0, None
    try:
        for burner in burners:
            burner.start()
        with tempfile.TemporaryDirectory() as work:
            folder = Path(work)
            certificate = make_certificate(tools, folder / "certificate")
            with running_mount(tools, certificate, folder / "mount") as mount:
                if arguments.tls13:
                    mount.tls.maximum_version = ssl.TLSVersion.MAXIMUM_SUPPORTED
                origin = mount.origin(BOARD_SITE)
                while made < arguments.count and lost < STOP_AFTER:
                    began = time.monotonic()
                    made += 1
                    try:
                        with mount.socket(BOARD_SITE, "/board/collab?slot=1", origin=origin) as one:
                            version = one.socket.version()  # ty: ignore[missing-attribute]
                            say_hello(one)
                    except AssertionError as failure:
                        lost += 1
                        seconds = time.monotonic() - began
                        print(f"handshake {made} was lost after {seconds:.0f} seconds:")
                        print(str(failure), flush=True)
    finally:
        stop.set()
        for burner in burners:
            burner.join(5)
    print(f"{made} handshakes over {version}: {lost} not answered")
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
