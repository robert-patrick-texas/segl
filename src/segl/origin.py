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

"""The Origin check (docs/SECURITY.md).

A browser sends ``Origin`` with every request that changes something, and with
every WebSocket handshake. When that header is present it has to name the host
the request was sent to, which is the ``Host`` header. A page on another site
that makes a visitor's browser call segl is refused here, before any route runs.
A request without ``Origin``, such as one from ``curl``, is not a browser's
cross-site request and passes.
"""

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

# Methods that change nothing. Every other method is a mutation.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# The port a browser leaves out of Origin and Host.
_DEFAULT_PORTS = {"http": 80, "https": 443}

BAD_ORIGIN = "bad_origin"
_MESSAGE = "This request came from a page on another site."


def origin_matches(origin: str, host: str | None) -> bool:
    """Return whether an ``Origin`` value names the host in ``Host``, port included.

    ``https://dev.example.com`` matches ``dev.example.com`` and
    ``dev.example.com:443``. It does not match ``dev.example.com:8443``, another
    name, or no ``Host`` at all. An origin that is not ``http`` or ``https``,
    such as the ``null`` of a sandboxed page, matches nothing.
    """
    if not host:
        return False
    try:
        asked = urlsplit(origin)
        default = _DEFAULT_PORTS[asked.scheme]
        # Only scheme://host[:port]. Anything more is not an origin.
        if asked.path or asked.query or asked.fragment or asked.username is not None:
            return False
        # Host has no scheme, so its missing port is read as the origin's.
        sent_to = urlsplit(f"//{host}")
        if sent_to.path or sent_to.query or sent_to.fragment or sent_to.username is not None:
            return False
        return (
            bool(asked.hostname)
            and asked.hostname == sent_to.hostname
            and (asked.port or default) == (sent_to.port or default)
        )
    except KeyError, ValueError:
        # Not http or https, or a port that is not a number.
        return False


def _values(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> list[str]:
    return [value.decode("latin-1") for key, value in headers if key == name]


def request_origin_matches(scope: Scope) -> bool:
    """Return whether a request's ``Origin`` headers, when it has any, all match its ``Host``."""
    origins = _values(scope["headers"], b"origin")
    if not origins:
        return True
    hosts = _values(scope["headers"], b"host")
    host = hosts[0] if len(hosts) == 1 else None
    return all(origin_matches(origin, host) for origin in origins)


class OriginCheck:
    """ASGI middleware: refuse a cross-site mutation or WebSocket handshake.

    The refusal is ``403`` with ``bad_origin``, in the error shape of
    docs/API.md. A WebSocket is refused during the handshake, so the browser
    never has an open socket.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        checked = scope["type"] == "websocket" or (
            scope["type"] == "http" and scope["method"] not in SAFE_METHODS
        )
        if not checked or request_origin_matches(scope):
            await self.app(scope, receive, send)
            return
        refusal = JSONResponse({"error": BAD_ORIGIN, "message": _MESSAGE}, status_code=403)
        if scope["type"] == "http":
            await refusal(scope, receive, send)
        else:
            await refuse_websocket(WebSocket(scope, receive, send), refusal)


async def refuse_websocket(websocket: WebSocket, refusal: JSONResponse) -> None:
    """Answer a WebSocket handshake with an HTTP error instead of accepting it."""
    if "websocket.http.response" in websocket.scope.get("extensions", {}):
        await websocket.send_denial_response(refusal)
    else:
        # A server without the extension can only close. 1008 is "policy violation".
        await websocket.close(code=1008)
