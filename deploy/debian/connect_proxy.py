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

"""A small CONNECT proxy, for deploy/debian/systemd-test.sh.

It stands in for a site's own proxy on 127.0.0.1:2025. For each request it
prints the first line, such as ``CONNECT localhost:8443 HTTP/1.1``, opens
the tunnel, and passes bytes both ways. The install test counts those lines
to see that ``segl update`` went through it.
"""

import select
import socket
import socketserver


class Tunnel(socketserver.StreamRequestHandler):
    """One client: read its CONNECT, then carry its bytes."""

    def handle(self) -> None:
        request = self.rfile.readline().decode(errors="replace").strip()
        while self.rfile.readline().strip():
            pass
        print(request, flush=True)
        parts = request.split()
        if len(parts) != 3 or parts[0] != "CONNECT":
            self.wfile.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        host, _, port = parts[1].rpartition(":")
        try:
            upstream = socket.create_connection((host, int(port)), timeout=10)
        except OSError, ValueError:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        with upstream:
            self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            self.wfile.flush()
            pair = [self.connection, upstream]
            while True:
                ready, _, _ = select.select(pair, [], [], 60)
                if not ready:
                    return
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)


class Proxy(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    Proxy(("127.0.0.1", 2025), Tunnel).serve_forever()
