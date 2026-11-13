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

"""``internal_networks``: answer nobody outside them (docs/SECURITY.md, S-018).

When the site sets the list, every request and every WebSocket handshake from
an address outside it is refused here, before the Origin check and before any
route: the pages and the health route among them. A firewall, or nginx's
``allow`` and ``deny``, can do the same. This is the second check behind them.

The address is the one segl already believes: the connection's own, or the
``X-Forwarded-For`` value when the connection came from ``trusted_proxies``
(uvicorn settles that before the application is called). Loopback is always
inside, and an IPv4 address written as IPv6 is read as IPv4.
"""

import ipaddress
from collections.abc import Iterable, Sequence

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from segl.origin import refuse_websocket

OUTSIDE_NETWORK = "outside_network"
_MESSAGE = "This segl answers only its site's internal networks."

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def client_address(text: str) -> Address | None:
    """Return a client's address, or None when the text is not one.

    ``::ffff:10.1.2.3``, which is how an IPv6 socket names an IPv4 client, is
    ``10.1.2.3``.
    """
    try:
        address = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_inside(client: str, networks: Iterable[Network]) -> bool:
    """Return whether ``client`` is loopback or in one of ``networks``.

    Text that is not an address is outside: segl does not answer a client it
    cannot place.
    """
    address = client_address(client)
    if address is None:
        return False
    return address.is_loopback or any(address in network for network in networks)


class InternalNetworks:
    """ASGI middleware: refuse every client outside ``networks``.

    The refusal is ``403`` with ``outside_network``, in the error shape of
    docs/API.md. A WebSocket is refused during the handshake.
    """

    def __init__(self, app: ASGIApp, networks: Sequence[str]) -> None:
        self.app = app
        # Checked when the settings were read (segl.config).
        self.networks = tuple(ipaddress.ip_network(network) for network in networks)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        if client is not None and is_inside(client[0], self.networks):
            await self.app(scope, receive, send)
            return
        refusal = JSONResponse({"error": OUTSIDE_NETWORK, "message": _MESSAGE}, status_code=403)
        if scope["type"] == "http":
            await refusal(scope, receive, send)
        else:
            await refuse_websocket(WebSocket(scope, receive, send), refusal)
