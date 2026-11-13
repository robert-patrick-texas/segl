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

"""``internal_networks`` (S-018, D2-033; docs/TEST-PLAN.md T-020).

With the list set, segl answers nobody outside it: every route of the sweep,
the pages and the health route among them, and the WebSocket handshake. In
process, where the test says which address the client has, and against a real
process that trusts ``127.0.0.1`` and is sent ``X-Forwarded-For``, as nginx
sends it. Through the test nginx every client is ``127.0.0.1``, and inside.
"""

import asyncio
import ipaddress
import json
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from harness import (
    BOARD_SITE,
    GATED,
    PASS_HEADER,
    ROOT_SITE,
    NginxTools,
    issue_pass,
    make_settings,
    running_mount,
    running_segl,
    say_hello,
)
from starlette.testclient import WebSocketDenialResponse
from test_sweep import (
    ELSEWHERE,
    MUTATIONS,
    OWN,
    READS,
    SOCKET,
    SWEEP,
    Call,
    ask,
    assert_plain,
    named,
    state,
)
from test_web import make_build
from websockets.exceptions import InvalidStatus

from segl.app import create_app
from segl.networks import InternalNetworks, client_address, is_inside
from segl.origin import OriginCheck
from segl.repository import Repository

NETWORKS = ("10.0.0.0/8", "192.168.4.0/24", "2001:db8::/32", "203.0.113.9/32")
PARSED = tuple(ipaddress.ip_network(network) for network in NETWORKS)
INSIDE = ["10.1.2.3", "10.255.255.255", "192.168.4.1", "2001:db8::17", "203.0.113.9"]
OUTSIDE = ["11.0.0.1", "192.168.5.1", "2001:db9::1", "203.0.113.10", "198.51.100.7", "8.8.8.8"]
REFUSAL = {
    "error": "outside_network",
    "message": "This segl answers only its site's internal networks.",
}


# The address, and whether it is inside.


@pytest.mark.parametrize("address", INSIDE)
def test_an_address_in_a_listed_network_is_inside(address: str) -> None:
    assert is_inside(address, PARSED)


@pytest.mark.parametrize("address", OUTSIDE)
def test_any_other_address_is_outside(address: str) -> None:
    assert not is_inside(address, PARSED)


@pytest.mark.parametrize("address", ["127.0.0.1", "127.8.9.10", "::1", "::ffff:127.0.0.1"])
def test_loopback_is_inside_whatever_the_list(address: str) -> None:
    assert is_inside(address, PARSED)
    assert is_inside(address, ())


@pytest.mark.parametrize(
    ("written", "read"),
    [
        # How an IPv6 socket names an IPv4 client.
        ("::ffff:10.1.2.3", "10.1.2.3"),
        ("::ffff:11.0.0.1", "11.0.0.1"),
        ("::FFFF:0a01:0203", "10.1.2.3"),
        (" 10.1.2.3 ", "10.1.2.3"),
        ("2001:DB8::17", "2001:db8::17"),
    ],
)
def test_an_ipv4_address_written_as_ipv6_is_read_as_ipv4(written: str, read: str) -> None:
    assert client_address(written) == ipaddress.ip_address(read)
    assert is_inside(written, PARSED) is is_inside(read, PARSED)


def test_an_ipv4_network_written_as_ipv6_is_not_what_lets_an_ipv4_client_in() -> None:
    mapped = (ipaddress.ip_network("::ffff:10.0.0.0/104"),)

    # The client is read as IPv4, so the network has to be written as IPv4 too.
    assert not is_inside("::ffff:10.1.2.3", mapped)
    assert not is_inside("10.1.2.3", mapped)


@pytest.mark.parametrize(
    "text",
    ["", "testclient", "unknown", "10.1.2", "10.1.2.3:443", "10.1.2.3, 127.0.0.1", "localhost"],
)
def test_text_that_is_not_an_address_is_outside(text: str) -> None:
    assert client_address(text) is None
    assert not is_inside(text, PARSED)
    assert not is_inside(text, ())


def test_an_address_with_a_zone_is_placed_by_its_address() -> None:
    link_local = (ipaddress.ip_network("fe80::/10"),)

    assert is_inside("fe80::1%eth0", link_local)
    assert not is_inside("fe80::1%eth0", PARSED)


# The middleware, asked as a server asks it.


def call(scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the check over one ASGI scope, and return what it sent, or what got through."""
    sent: list[dict[str, Any]] = []

    async def downstream(scope: Any, receive: Any, send: Any) -> None:
        sent.append({"type": "reached the application"})

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Any) -> None:
        sent.append(dict(message))

    asyncio.run(InternalNetworks(downstream, NETWORKS)(scope, receive, send))
    return sent


def http_scope(**more: Any) -> dict[str, Any]:
    return {"type": "http", "method": "GET", "path": "/api/v1/health", "headers": [], **more}


def test_a_request_from_inside_reaches_the_application() -> None:
    assert call(http_scope(client=("10.1.2.3", 50000))) == [{"type": "reached the application"}]


def test_a_request_from_outside_is_answered_by_the_check_itself() -> None:
    start, body = call(http_scope(client=("198.51.100.7", 50000)))

    assert (start["type"], start["status"]) == ("http.response.start", 403)
    assert json.loads(body["body"]) == REFUSAL
    assert b"set-cookie" not in dict(start["headers"])


@pytest.mark.parametrize("client", [None, ("", 0), ("/run/segl.sock", 0)])
def test_a_request_with_no_client_address_is_outside(client: tuple[str, int] | None) -> None:
    # A server that names no client, as one that listens on a Unix socket.
    scope = http_scope() if client is None else http_scope(client=client)

    assert call(scope)[0]["status"] == 403
    assert call(http_scope(client=None))[0]["status"] == 403


def test_what_is_not_a_request_is_not_the_checks_business() -> None:
    # The server's own start and stop of the application.
    assert call({"type": "lifespan"}) == [{"type": "reached the application"}]


# In process: the test says which address the client has.


def application(repository: Repository, folder: Path, **settings: Any) -> FastAPI:
    settings.setdefault("web_dir", make_build(folder / "dist"))
    settings.setdefault("assets_dir", folder / "assets")
    settings.setdefault("internal_networks", NETWORKS)
    return create_app(make_settings(**settings), repository)


@pytest.fixture
def app(repository: Repository, tmp_path: Path) -> FastAPI:
    return application(repository, tmp_path)


@contextmanager
def from_address(app: FastAPI, address: str) -> Generator[TestClient]:
    """A client of the application whose address is ``address``.

    The client is not entered. Leaving an entered one stops the application,
    which closes the database, and a test here asks one application from
    several addresses.
    """
    yield TestClient(app, client=(address, 50000))


@pytest.fixture
def inside(app: FastAPI) -> Iterator[TestClient]:
    with from_address(app, "10.1.2.3") as client:
        yield client


def test_the_check_runs_before_the_origin_check(app: FastAPI) -> None:
    # The last one added is the first to run.
    assert [each.cls for each in app.user_middleware] == [InternalNetworks, OriginCheck]


def test_without_the_setting_there_is_no_such_check(repository: Repository, tmp_path: Path) -> None:
    app = application(repository, tmp_path, internal_networks=())

    assert [each.cls for each in app.user_middleware] == [OriginCheck]
    for address in (*INSIDE, *OUTSIDE):
        with from_address(app, address) as client:
            assert client.get("/api/v1/health").status_code == 200, address


@pytest.mark.parametrize("address", [*INSIDE, "127.0.0.1", "::1", "::ffff:10.9.8.7"])
def test_an_address_inside_is_answered_as_ever(app: FastAPI, address: str) -> None:
    with from_address(app, address) as client:
        for call in (*MUTATIONS, *READS):
            response = ask(client, call, Origin=OWN)

            assert response.status_code == call.open_status, (call, response.text)
        with client.websocket_connect(SOCKET.path, headers={"Origin": OWN}) as socket:
            socket.send_json({"type": "hello", "clientId": "c", "displayName": None})
            assert socket.receive_json()["viewOnly"] is False


@pytest.mark.parametrize("call", named((*MUTATIONS, *READS)))
def test_every_route_refuses_an_address_outside_and_sets_no_cookie(
    app: FastAPI, inside: TestClient, call: Call
) -> None:
    # What the reads ask for is there: the refusal is not a 404 in disguise.
    for made in MUTATIONS:
        assert ask(inside, made, Origin=OWN).status_code == made.open_status
    before = state(inside)

    for address in OUTSIDE:
        with from_address(app, address) as outside:
            response = ask(outside, call, Origin=OWN)

            assert response.status_code == 403, (address, call)
            assert response.json() == REFUSAL
            assert response.headers["content-type"] == "application/json"
            assert_plain(response.headers, f"{call.path} from {address}")
    assert state(inside) == before


def test_the_sweep_is_the_whole_of_what_is_refused(app: FastAPI) -> None:
    # Every route there is, and paths there are none for.
    with from_address(app, "198.51.100.7") as outside:
        for path in ("/nope", "/api/v1/nope", "/s/1/x", "/api/v1/slots/10", "/access/"):
            response = outside.get(path)

            assert (response.status_code, response.json()) == (403, REFUSAL), path
        assert len(SWEEP) >= 20


@pytest.mark.parametrize("address", OUTSIDE)
def test_the_handshake_refuses_an_address_outside(app: FastAPI, address: str) -> None:
    with (
        from_address(app, address) as outside,
        pytest.raises(WebSocketDenialResponse) as refused,
        outside.websocket_connect(SOCKET.path, headers={"Origin": OWN}),
    ):
        pass

    assert (refused.value.status_code, refused.value.json()) == (403, REFUSAL)
    assert_plain(refused.value.headers, f"the handshake from {address}")


def test_a_client_segl_cannot_place_is_outside(app: FastAPI) -> None:
    # The test client's own name for itself is not an address.
    nameless = TestClient(app)

    assert nameless.get("/api/v1/health").status_code == 403
    assert nameless.get("/").json() == REFUSAL


def test_outside_is_said_before_another_site_is(app: FastAPI) -> None:
    with from_address(app, "198.51.100.7") as outside:
        for call in MUTATIONS:
            response = ask(outside, call, Origin=ELSEWHERE)

            assert (response.status_code, response.json()["error"]) == (403, "outside_network")
        with (
            pytest.raises(WebSocketDenialResponse) as refused,
            outside.websocket_connect(SOCKET.path, headers={"Origin": ELSEWHERE}),
        ):
            pass
    assert refused.value.json()["error"] == "outside_network"
    # And from inside, another site is still another site.
    with from_address(app, "10.1.2.3") as client:
        assert ask(client, MUTATIONS[0], Origin=ELSEWHERE).json()["error"] == "bad_origin"


def test_a_pass_does_not_let_an_address_outside_in(repository: Repository, tmp_path: Path) -> None:
    # The two are apart: the networks say who is answered, the codes who edits.
    app = application(repository, tmp_path, **GATED)
    edit_pass = {PASS_HEADER: issue_pass()}

    with from_address(app, "198.51.100.7") as outside:
        for call in (*MUTATIONS, *READS):
            response = ask(outside, call, Origin=OWN, **edit_pass)
            assert (response.status_code, response.json()["error"]) == (403, "outside_network")
    with from_address(app, "10.1.2.3") as client:
        # Inside without a pass is a viewer, and with one an editor.
        patch = MUTATIONS[0]
        assert ask(client, patch, Origin=OWN).json()["error"] == "view_only"
        assert ask(client, patch, Origin=OWN, **edit_pass).status_code == 200
        assert client.get("/api/v1/config").json() == {"editRequired": True}


def test_a_refused_code_from_outside_is_not_a_wrong_code(
    repository: Repository, tmp_path: Path
) -> None:
    app = application(repository, tmp_path, **GATED)
    wrong = {"code": "a wrong code"}

    with from_address(app, "198.51.100.7") as outside:
        for _ in range(8):
            assert outside.post("/api/v1/access", json=wrong).json()["error"] == "outside_network"

    assert cast(Any, app.state).code_limit.clients() == 0


# A real process, which believes X-Forwarded-For from 127.0.0.1.


def networks_toml(*networks: str) -> str:
    return f"internal_networks = {json.dumps(list(networks))}\n"


def test_a_real_process_answers_the_networks_in_its_toml_and_nobody_else(tmp_path: Path) -> None:
    build = make_build(tmp_path / "dist")
    config = networks_toml("10.0.0.0/8", "2001:db8::/32") + f'web_dir = "{build}"\n'
    with running_segl(tmp_path, config) as server:
        for address in ("10.1.2.3", "2001:db8::17", "::ffff:10.1.2.3"):
            sent = {"X-Forwarded-For": address}
            assert server.get("/api/v1/health", sent).json() == {"status": "ok"}, address
            assert server.get("/s/1", sent).status == 200
            assert server.post("/api/v1/display-name", sent).status == 200
            with server.socket("/collab?slot=1", headers=sent) as socket:
                assert say_hello(socket, "Guest1")[0]["viewOnly"] is False

        for address in ("198.51.100.7", "2001:db9::1", "::ffff:198.51.100.7", "unknown"):
            sent = {"X-Forwarded-For": address}
            for path in ("/api/v1/health", "/", "/s/1", "/access", "/api/v1/slots", "/nope"):
                reply = server.get(path, sent)
                assert (reply.status, reply.json()) == (403, REFUSAL), (address, path)
                assert reply.headers["Set-Cookie"] is None
            refused_post = server.post("/api/v1/display-name", sent)
            assert (refused_post.status, refused_post.json()) == (403, REFUSAL)
            with pytest.raises(InvalidStatus) as refused:
                server.socket("/collab?slot=1", headers=sent)
            assert refused.value.response.status_code == 403
            assert json.loads(refused.value.response.body) == REFUSAL
            assert refused.value.response.headers.get("Set-Cookie") is None

        # This host itself, with no proxy in between, is loopback, and inside.
        assert server.get("/api/v1/health").json() == {"status": "ok"}
        # The refused calls for a name took none: the three inside took 1 to 3.
        assert server.post("/api/v1/display-name").json() == {"displayName": "Staff4"}


def test_a_proxy_segl_does_not_trust_makes_every_client_look_like_the_proxy(
    tmp_path: Path,
) -> None:
    # docs/DEPLOY.md: the proxy has to be in trusted_proxies. Here it is not,
    # so segl sees 127.0.0.1 for a client the proxy says is outside, and
    # answers it.
    config = networks_toml("10.0.0.0/8") + "trusted_proxies = []\n"
    with running_segl(tmp_path, config) as server:
        for address in ("198.51.100.7", "10.1.2.3"):
            reply = server.get("/api/v1/health", {"X-Forwarded-For": address})
            assert reply.json() == {"status": "ok"}, address


def test_through_the_test_nginx_every_client_is_inside(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    # nginx overwrites X-Forwarded-For with the address it sees, 127.0.0.1.
    with running_mount(tools, certificate, tmp_path, networks_toml("10.0.0.0/8")) as mount:
        for site, prefix in ((BOARD_SITE, "/board"), (ROOT_SITE, "")):
            reply = mount.get(site, f"{prefix}/api/v1/health", {"X-Forwarded-For": "198.51.100.7"})
            assert (reply.status, reply.json()) == (200, {"status": "ok"})
            with mount.socket(site, f"{prefix}/collab?slot=1", origin=mount.origin(site)) as socket:
                assert say_hello(socket, "Guest1")[0]["viewOnly"] is False
        assert "198.51.100.7" not in mount.segl.log()
