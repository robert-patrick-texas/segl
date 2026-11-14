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

"""T-012, as one walk over every route segl has (docs/TEST-PLAN.md, S-007).

Each route is asked three ways: as segl's own page asks, as a page of another
site asks, and as a browser without a pass asks. No answer sets a cookie, and
none tells a browser that another site may read it. A mutation and a WebSocket
upgrade from another site are ``bad_origin``, and a mutation without a pass is
``view_only`` on a segl that asks for an access code.

The walk is a table, ``SWEEP``, and a test holds the table to the routes the
application registers. A route that is added and not listed here fails it.

The other test files check a cookie beside what they test. This one is the
sweep: in process over every route, and through nginx, with the files in
deploy/nginx/, in front of a real ``python -m segl --config`` process that
has access codes. tests/test_networks.py walks the same table from outside
``internal_networks``.
"""

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from harness import (
    ACCESS_CODE,
    BOARD_SITE,
    GATED,
    GATED_TOML,
    PASS_HEADER,
    ROOT_SITE,
    Mount,
    NginxTools,
    Reply,
    assert_no_secrets,
    issue_pass,
    make_settings,
    next_message,
    running_mount,
    say_hello,
)
from starlette.routing import Mount as StaticMount
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import WebSocketDenialResponse
from test_web import make_build
from websockets.exceptions import InvalidStatus

from segl.app import create_app
from segl.origin import OriginCheck
from segl.repository import Repository

# A pass a segl with ``GATED`` takes, issued as the tests are collected.
PASS = issue_pass()
ACCESS_ROUTE = "/api/v1/access"

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
PNG_HASH = hashlib.sha256(PNG).hexdigest()

RECTANGLE = {
    "id": "swept-1",
    "type": "rectangle",
    "version": 1,
    "versionNonce": 1,
    "index": "a0",
    "isDeleted": False,
}
SCENE_FILE = json.dumps({"type": "excalidraw", "version": 2, "elements": [RECTANGLE]}).encode()

# Another site, as a browser names one in ``Origin``.
ELSEWHERE = "https://evil.example"


@dataclass(frozen=True)
class Call:
    """One request of the walk."""

    # ``WS`` is a WebSocket upgrade.
    method: str
    # The path as the application registers it.
    route: str
    # The path the walk asks for, under segl's root.
    path: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None
    # Whether it changes something: any method but GET, and the upgrade.
    mutation: bool = False
    # Whether it needs a pass on a segl that asks for an access code.
    gated: bool = False
    # What a segl without access codes answers: it has no code to take.
    open_status: int = 200


def _json(body: object) -> bytes:
    return json.dumps(body).encode()


JSON = {"Content-Type": "application/json"}

# In the order of a visit: what the reads at the end ask for, the mutations
# before them have made. A slot's first revision is the import: the scene a
# slot starts with is not history. The restore then puts that revision back.
MUTATIONS = (
    Call(
        "PATCH", "/api/v1/slots/{n}", "/api/v1/slots/1", JSON, _json({"title": "Core"}), True, True
    ),
    Call(
        "POST",
        "/api/v1/slots/{n}/assets",
        "/api/v1/slots/1/assets",
        {"Content-Type": "image/png"},
        PNG,
        True,
        True,
    ),
    Call("POST", "/api/v1/slots/{n}/import", "/api/v1/slots/1/import", {}, SCENE_FILE, True, True),
    Call(
        "POST",
        "/api/v1/slots/{n}/restore",
        "/api/v1/slots/1/restore",
        JSON,
        _json({"revision": 1, "displayName": "Guest1"}),
        True,
        True,
    ),
    # A name needs no pass: a viewer has one too.
    Call("POST", "/api/v1/display-name", "/api/v1/display-name", mutation=True),
    # Nor does the route that issues one: it takes a code.
    Call(
        "POST",
        ACCESS_ROUTE,
        ACCESS_ROUTE,
        JSON,
        _json({"code": ACCESS_CODE}),
        mutation=True,
        open_status=404,
    ),
)
SOCKET = Call("WS", "/collab", "/collab?slot=1", mutation=True)
READS = (
    Call("GET", "/api/v1/health", "/api/v1/health"),
    Call("GET", "/api/v1/version", "/api/v1/version"),
    Call("GET", "/api/v1/config", "/api/v1/config"),
    Call("GET", "/api/v1/slots", "/api/v1/slots"),
    Call("GET", "/api/v1/slots/{n}", "/api/v1/slots/1"),
    Call("GET", "/api/v1/slots/{n}/scene", "/api/v1/slots/1/scene"),
    Call("GET", "/api/v1/slots/{n}/revisions", "/api/v1/slots/1/revisions"),
    Call("GET", "/api/v1/slots/{n}/revisions/{revision}", "/api/v1/slots/1/revisions/1"),
    Call("GET", "/api/v1/assets/{name}", f"/api/v1/assets/{PNG_HASH}"),
    # The web application: its pages, and the files of its build.
    Call("GET", "/", "/"),
    Call("GET", "/s", "/s"),
    Call("GET", "/access", "/access"),
    Call("GET", "/s/", "/s/"),
    Call("GET", "/s/{n}", "/s/1"),
    Call("GET", "/favicon.svg", "/favicon.svg"),
    Call("GET", "/assets", "/assets/index-Dw_CZwxO.js"),
    Call("GET", "/fonts", "/fonts/Virgil/Virgil-Regular.woff2"),
)
SWEEP = (*MUTATIONS, SOCKET, *READS)


def named(calls: tuple[Call, ...]) -> list[Any]:
    return [pytest.param(call, id=f"{call.method} {call.path}") for call in calls]


def assert_plain(headers: Mapping[str, str] | Any, what: str) -> None:
    """No cookie, and nothing that lets a page of another site read the answer."""
    names = {name.lower() for name in headers}
    assert "set-cookie" not in names, what
    assert not {name for name in names if name.startswith("access-control-")}, what


def application(repository: Repository, folder: Path, **settings: Any) -> TestClient:
    settings.setdefault("web_dir", make_build(folder / "dist"))
    settings.setdefault("assets_dir", folder / "assets")
    return TestClient(create_app(make_settings(**settings), repository))


@pytest.fixture
def client(repository: Repository, tmp_path: Path) -> Iterator[TestClient]:
    with application(repository, tmp_path) as client:
        yield client


@pytest.fixture
def gated(repository: Repository, tmp_path: Path) -> Iterator[TestClient]:
    with application(repository, tmp_path, **GATED) as client:
        yield client


# What a test client's page would send: the client's host is ``testserver``.
OWN = "http://testserver"


def ask(client: TestClient, call: Call, **more: str) -> httpx2.Response:
    return client.request(
        call.method, call.path, headers={**call.headers, **more}, content=call.body
    )


def assert_secret_free(call: Call, body: bytes) -> None:
    """No answer holds a code or the secret, and only the access route's holds a pass."""
    text = body.decode("utf-8", errors="replace")
    if call.route == ACCESS_ROUTE:
        text = text.replace(json.loads(body)["pass"], "")
    assert_no_secrets(text, call.path)


def state(client: TestClient) -> dict[str, Any]:
    """What a mutation would change, read back over HTTP."""
    return {
        "slot": client.get("/api/v1/slots/1").json(),
        "scene": client.get("/api/v1/slots/1/scene").json(),
        "revisions": client.get("/api/v1/slots/1/revisions").json(),
        "asset": client.get(f"/api/v1/assets/{PNG_HASH}").status_code,
    }


# The table against the application.


def test_the_sweep_names_every_route_the_application_has(client: TestClient) -> None:
    registered: set[tuple[str, str]] = set()
    for route in cast(FastAPI, client.app).routes:
        if isinstance(route, StaticMount):
            registered.add(("GET", route.path))
        elif isinstance(route, WebSocketRoute):
            registered.add(("WS", route.path))
        else:
            assert isinstance(route, Route), route
            registered.update((method, route.path) for method in (route.methods or set()))

    # A new route joins SWEEP, with the request that reaches it.
    assert {(call.method, call.route) for call in SWEEP} == registered - {
        ("HEAD", path) for _, path in registered
    }


def test_every_call_that_is_not_a_read_is_marked_a_mutation() -> None:
    assert [call for call in SWEEP if (call.method != "GET") != call.mutation] == []
    # Every mutation needs a pass but the name and the route that issues one,
    # and the socket says so in `welcome`.
    assert [call.path for call in MUTATIONS if not call.gated] == [
        "/api/v1/display-name",
        ACCESS_ROUTE,
    ]
    assert [call.path for call in SWEEP if call.open_status != 200] == [ACCESS_ROUTE]


def test_the_only_middleware_is_the_origin_check(client: TestClient) -> None:
    # No session middleware and no CORS middleware (docs/SECURITY.md). With
    # internal_networks set there is a second one (tests/test_networks.py).
    middleware = cast(FastAPI, client.app).user_middleware

    assert [each.cls for each in middleware] == [OriginCheck]


# As segl's own page asks.


def test_no_answer_to_segls_own_page_sets_a_cookie(client: TestClient) -> None:
    for call in (*MUTATIONS, *READS):
        response = ask(client, call, Origin=OWN)

        assert response.status_code == call.open_status, (call, response.text)
        assert_plain(response.headers, call.path)

    with client.websocket_connect(SOCKET.path, headers={"Origin": OWN}) as socket:
        assert_plain(dict(socket.extra_headers or []), "the handshake")
        socket.send_json({"type": "hello", "clientId": "c", "displayName": None})
        assert socket.receive_json()["viewOnly"] is False


def test_the_walk_did_what_it_asked_for(client: TestClient) -> None:
    # So that the test above is about answers to requests that worked.
    for call in MUTATIONS:
        assert ask(client, call, Origin=OWN).status_code == call.open_status

    after = state(client)
    assert after["slot"]["title"] == "Core"
    # The import, and then the restore of the import's own revision.
    assert after["slot"]["epoch"] == 3
    assert after["asset"] == 200
    assert [row["revision"] for row in after["revisions"]["revisions"]] == [2, 1]
    assert [each["id"] for each in after["scene"]["scene"]["elements"]] == ["swept-1"]


# As a page of another site asks.


@pytest.mark.parametrize("call", named(MUTATIONS))
def test_a_mutation_from_another_site_is_bad_origin_and_changes_nothing(
    client: TestClient, call: Call
) -> None:
    before = state(client)

    response = ask(client, call, Origin=ELSEWHERE)

    assert (response.status_code, response.json()["error"]) == (403, "bad_origin")
    assert_plain(response.headers, call.path)
    assert state(client) == before
    # A refused call for a name took no name.
    assert client.post("/api/v1/display-name").json() == {"displayName": "Alpha1"}


@pytest.mark.parametrize(
    "origin", [ELSEWHERE, "null", "http://testserver:81", "http://testserver.evil.example"]
)
def test_a_websocket_upgrade_from_another_site_is_bad_origin(
    client: TestClient, origin: str
) -> None:
    with (
        pytest.raises(WebSocketDenialResponse) as refused,
        client.websocket_connect(SOCKET.path, headers={"Origin": origin}),
    ):
        pass

    assert (refused.value.status_code, refused.value.json()["error"]) == (403, "bad_origin")
    assert_plain(refused.value.headers, "the refused handshake")


@pytest.mark.parametrize("call", named(READS))
def test_a_read_from_another_site_is_answered_and_not_made_readable(
    client: TestClient, call: Call
) -> None:
    # A browser lets a page fetch it and keeps the answer from the page: segl
    # sends no CORS header. Two of the reads need what a mutation made.
    for made in MUTATIONS:
        ask(client, made, Origin=OWN)

    response = ask(client, call, Origin=ELSEWHERE)

    assert response.status_code == 200
    assert_plain(response.headers, call.path)


def test_a_preflight_is_given_no_permission(client: TestClient) -> None:
    # What a browser asks before a cross-site PATCH, or a POST of JSON.
    asking = {
        "Origin": ELSEWHERE,
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "content-type,x-segl-edit-token",
    }
    for call in (*MUTATIONS, *READS):
        response = client.options(call.path, headers=asking)

        assert response.status_code in (404, 405), call.path
        assert_plain(response.headers, call.path)


# As a browser without a pass asks.

# A pass signed with another secret, as one from another segl is.
FORGED = issue_pass(secret="another-secret-of-thirty-two-chars!")


# The names are fixed. A pass holds the second of its issue, and pytest's
# workers must all give a test the same name (the root conftest.py).
@pytest.mark.parametrize(
    "sent",
    [None, "", "wrong", ACCESS_CODE, PASS[:-1], PASS + "x", PASS.swapcase(), f" {PASS}x", FORGED],
    ids=[
        "nothing",
        "empty",
        "wrong",
        "the-code",
        "pass-cut-short",
        "pass-with-more",
        "pass-in-other-case",
        "pass-after-a-space",
        "pass-of-another-secret",
    ],
)
def test_a_gated_mutation_without_a_pass_is_view_only_and_changes_nothing(
    gated: TestClient, sent: str | None
) -> None:
    before = state(gated)
    edit_pass = {} if sent is None else {PASS_HEADER: sent}

    for call in MUTATIONS:
        response = ask(gated, call, Origin=OWN, **edit_pass)

        if call.gated:
            assert (response.status_code, response.json()["error"]) == (403, "view_only"), call
        else:
            assert response.status_code == 200, call
        assert_plain(response.headers, call.path)
    assert state(gated) == before


def test_a_pass_opens_every_gated_mutation_and_no_answer_sets_a_cookie(
    gated: TestClient,
) -> None:
    for call in (*MUTATIONS, *READS):
        response = ask(gated, call, Origin=OWN, **{PASS_HEADER: PASS})

        assert response.status_code == 200, (call, response.text)
        assert_plain(response.headers, call.path)
        # No code and no secret is in an answer, the pages and their config
        # among them, and a pass is in the one answer that issues it.
        assert_secret_free(call, response.content)


def test_a_pass_does_not_help_a_page_of_another_site(gated: TestClient) -> None:
    before = state(gated)

    for call in MUTATIONS:
        response = ask(gated, call, Origin=ELSEWHERE, **{PASS_HEADER: PASS})

        assert (response.status_code, response.json()["error"]) == (403, "bad_origin"), call
    assert state(gated) == before


@pytest.mark.parametrize(
    ("sent", "view_only"),
    [("", True), ("wrong", True), (ACCESS_CODE, True), (PASS, False)],
    ids=["empty", "wrong", "the-code", "a-pass"],
)
def test_a_handshake_on_a_gated_segl_sets_no_cookie_whoever_asks(
    gated: TestClient, sent: str, view_only: bool
) -> None:
    with gated.websocket_connect(SOCKET.path, headers={"Origin": OWN}) as socket:
        assert_plain(dict(socket.extra_headers or []), "the handshake")
        socket.send_json({"type": "hello", "clientId": "c", "displayName": None, "editToken": sent})
        welcome = socket.receive_json()

    assert welcome["viewOnly"] is view_only
    assert_no_secrets(json.dumps(welcome))


# What segl refuses for other reasons.

REFUSALS = [
    ("GET", "/nope", {}, None, 404),
    ("GET", "/api/v1/nope", {}, None, 404),
    ("GET", "/api/v1/health/", {}, None, 404),
    ("GET", "/s/1/x", {}, None, 404),
    ("GET", "/access/", {}, None, 404),
    ("GET", "/api/v1/access", {}, None, 405),
    ("POST", "/access", {}, None, 405),
    # A segl without access codes has none to take.
    ("POST", "/api/v1/access", JSON, _json({"code": "anything"}), 404),
    ("GET", "/api/v1/slots/10", {}, None, 404),
    ("GET", "/api/v1/slots/1/revisions/99", {}, None, 404),
    ("GET", "/api/v1/assets/" + "0" * 64, {}, None, 404),
    ("GET", "/assets/absent.js", {}, None, 404),
    ("DELETE", "/api/v1/slots/1", {}, None, 405),
    ("POST", "/api/v1/health", {}, None, 405),
    ("PUT", "/s/1", {}, None, 405),
    ("PATCH", "/api/v1/slots/1", JSON, b"not json", 400),
    ("PATCH", "/api/v1/slots/1", JSON, _json({"title": ""}), 422),
    ("PATCH", "/api/v1/slots/1", JSON, b" " * 5000, 413),
    ("POST", "/api/v1/slots/1/assets", {"Content-Type": "text/html"}, b"<p>", 415),
    ("POST", "/api/v1/slots/1/import", {}, b"[]", 400),
    ("POST", "/api/v1/slots/1/import", {}, _json({"type": "other"}), 422),
    ("POST", "/api/v1/slots/1/restore", JSON, _json({"revision": 99}), 404),
]


@pytest.mark.parametrize(
    ("method", "path", "headers", "body", "status"),
    [pytest.param(*each, id=f"{each[0]} {each[1]} {each[4]}") for each in REFUSALS],
)
def test_a_refusal_sets_no_cookie_either(
    client: TestClient,
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: bytes | None,
    status: int,
) -> None:
    response = client.request(method, path, headers={**headers, "Origin": OWN}, content=body)

    assert response.status_code == status, response.text
    assert_plain(response.headers, f"{method} {path}")
    # Every refusal has the one shape.
    assert set(response.json()) == {"error", "message"}


def test_the_name_limit_refusal_sets_no_cookie(client: TestClient) -> None:
    for _ in range(30):
        assert client.post("/api/v1/display-name").status_code == 200

    refused = client.post("/api/v1/display-name")

    assert (refused.status_code, refused.json()["error"]) == (429, "rate_limited")
    assert_plain(refused.headers, "the 31st name")


@pytest.mark.parametrize("path", ["/collab", "/collab?slot=10", "/collab?slot=x"])
def test_a_handshake_for_no_slot_sets_no_cookie(client: TestClient, path: str) -> None:
    with (
        pytest.raises(WebSocketDenialResponse) as refused,
        client.websocket_connect(path, headers={"Origin": OWN}),
    ):
        pass

    assert refused.value.status_code >= 400
    assert_plain(refused.value.headers, path)


def test_the_refusals_of_the_access_route_set_no_cookie(gated: TestClient) -> None:
    # A wrong code, five times, and then the wait (tests/test_access.py).
    asked = [
        gated.post(ACCESS_ROUTE, json={"code": "a wrong code"}, headers={"Origin": OWN})
        for _ in range(6)
    ]

    assert [each.status_code for each in asked] == [403] * 5 + [429]
    assert [each.json()["error"] for each in asked] == ["wrong_code"] * 5 + ["rate_limited"]
    for each in asked:
        assert_plain(each.headers, "a wrong code")
        assert set(each.json()) == {"error", "message"}


# Through nginx, in front of a real process that has access codes.


def send(mount: Mount, site: str, prefix: str, call: Call, **more: str) -> Reply:
    headers = {**call.headers, **more}
    path = prefix + call.path
    if call.method == "GET":
        return mount.get(site, path, headers)
    if call.method == "POST":
        return mount.post(site, path, headers, call.body)
    assert call.method == "PATCH"
    return mount.patch(site, path, json.loads(call.body or b"null"), headers)


def test_the_walk_through_nginx_at_board_and_at_a_host_root(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    # T-012 as docs/TEST-PLAN.md words it, on both site examples.
    build = make_build(tmp_path / "dist")
    config = f'{GATED_TOML}web_dir = "{build}"\n'
    with running_mount(tools, certificate, tmp_path, config) as mount:
        # nginx's own answers: its redirect, and its 404 outside the mount.
        for path, status in (("/board", 301), ("/api/v1/health", 404), ("/s/1", 404)):
            reply = mount.get(BOARD_SITE, path)
            assert reply.status == status, path
            assert_plain(reply.headers, f"nginx {path}")

        for site, prefix in ((BOARD_SITE, "/board"), (ROOT_SITE, "")):
            origin = mount.origin(site)
            collab = prefix + SOCKET.path
            mine = {"Origin": origin, PASS_HEADER: PASS}

            # Both sites are the one segl, so the second finds what the first left.
            before = mount.get(site, f"{prefix}/api/v1/slots/1").json()

            # A WebSocket handshake: no cookie, and without a pass a viewer.
            with mount.socket(site, collab, origin=origin) as viewer:
                assert viewer.response is not None
                assert viewer.response.status_code == 101
                assert_plain(viewer.response.headers, "the handshake")
                welcome, _ = say_hello(viewer, "Guest1")
                assert welcome["viewOnly"] is True

                # A view-only mutation, each of them, and the two calls that need no pass.
                for call in MUTATIONS:
                    for edit_pass in ({}, {PASS_HEADER: "wrong"}, {PASS_HEADER: ACCESS_CODE}):
                        reply = send(mount, site, prefix, call, Origin=origin, **edit_pass)
                        if call.gated:
                            assert (reply.status, reply.json()["error"]) == (403, "view_only"), call
                        else:
                            assert reply.status == 200, call
                        assert_plain(reply.headers, f"{site} {call.path} without a pass")

                # The Origin refusals: with a pass, from another site, and
                # from the site's name without its port.
                for other in (ELSEWHERE, f"https://{site}"):
                    for call in MUTATIONS:
                        reply = send(mount, site, prefix, call, **{**mine, "Origin": other})
                        assert (reply.status, reply.json()["error"]) == (403, "bad_origin"), call
                        assert_plain(reply.headers, f"{site} {call.path} from {other}")
                    with pytest.raises(InvalidStatus) as refused:
                        mount.socket(site, collab, origin=other)
                    assert refused.value.response.status_code == 403
                    assert json.loads(refused.value.response.body)["error"] == "bad_origin"
                    assert_plain(refused.value.response.headers, f"the handshake from {other}")

                # Nothing of all that reached the slot.
                assert mount.get(site, f"{prefix}/api/v1/slots/1").json() == before

                # With a pass, from the site's own page: every route there is.
                for call in (*MUTATIONS, *READS):
                    reply = send(mount, site, prefix, call, **mine)
                    assert reply.status == 200, (site, call, reply.body[:200])
                    assert_plain(reply.headers, f"{site} {call.path}")
                    assert_secret_free(call, reply.body)
                # The viewer on the socket was sent the first of it, the title,
                # and nothing of what was refused before.
                assert next_message(viewer) == {"type": "slot", "slot": 1, "title": "Core"}

            # The config says that a code is needed, and not what one is.
            assert mount.get(site, f"{prefix}/api/v1/config").json() == {"editRequired": True}

            # The title back, by the pass, so the walk changes it again at the next site.
            mount.patch(site, f"{prefix}/api/v1/slots/1", {"title": "Workspace 1"}, mine)

        # The code went in a body, and the pass in a header and in `hello`:
        # no log has either, or the secret.
        assert_no_secrets(mount.segl.log())
        for log in ("access.log", "error.log"):
            assert_no_secrets((mount.prefix / log).read_text(encoding="utf-8"), log)
