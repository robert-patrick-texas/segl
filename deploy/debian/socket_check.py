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

"""Draw one element on a slot through nginx, and wait until segl has saved it.

deploy/debian/systemd-test.sh runs this with the package's own interpreter,
/opt/segl/venv/bin/python3, so it also shows that the packaged Python speaks
TLS and has the packaged ``websockets``.

Usage: socket_check.py WSS_BASE SLOT ELEMENT_ID CA_FILE
       socket_check.py wss://dev.example.com/board 2 package-test-1 /etc/ssl/certs/x.pem

It prints ``saved`` and exits 0, or says what went wrong and exits 1.
"""

import json
import ssl
import sys
from typing import Any
from urllib.parse import urlsplit

from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin

SECONDS = 10


def receive(socket: ClientConnection, wanted: str) -> dict[str, Any]:
    """Return the next message of type ``wanted``, skipping the others."""
    while True:
        message = json.loads(socket.recv(timeout=SECONDS))
        if message["type"] == "error":
            raise SystemExit(f"socket_check: segl answered {message}")
        if message["type"] == wanted:
            return message


def main(argv: list[str]) -> int:
    """Run the check and return the exit status."""
    base, slot, element_id, ca_file = argv
    context = ssl.create_default_context(cafile=ca_file)
    # The tests' WebSocket client is held at TLS 1.2 (docs/ROADMAP.md, "Held
    # until a dependency moves"). nginx still offers TLS 1.3 to a browser.
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    # What a browser on that site would send. segl refuses another origin.
    origin = Origin(f"https://{urlsplit(base).netloc}")
    with connect(
        f"{base}/collab?slot={slot}", ssl=context, origin=origin, open_timeout=SECONDS
    ) as socket:
        hello = {"type": "hello", "clientId": "package-test", "displayName": None, "editToken": ""}
        socket.send(json.dumps(hello))
        welcome = receive(socket, "welcome")
        if welcome["viewOnly"]:
            raise SystemExit("socket_check: this connection may not edit")
        receive(socket, "scene")
        element = {"id": element_id, "version": 1, "versionNonce": 1, "type": "rectangle"}
        batch = {"type": "elements", "epoch": welcome["epoch"], "elements": [element], "seq": 1}
        socket.send(json.dumps(batch))
        saved = receive(socket, "saved")
        if saved["seq"] != 1:
            raise SystemExit(f"socket_check: segl saved message {saved['seq']}, not 1")
    print("saved")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1:]))
