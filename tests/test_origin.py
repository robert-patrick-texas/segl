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

"""The Origin check: a mutation or a WebSocket handshake that a page on another
site started is refused with ``bad_origin`` (docs/SECURITY.md, T-012)."""

import pytest
from fastapi.testclient import TestClient
from harness import make_settings
from starlette.testclient import WebSocketDenialResponse

from segl.app import create_app
from segl.origin import origin_matches
from segl.repository import Repository

BAD_ORIGIN = {
    "error": "bad_origin",
    "message": "This request came from a page on another site.",
}


@pytest.fixture
def client(repository: Repository) -> TestClient:
    return TestClient(create_app(make_settings(), repository))


@pytest.mark.parametrize(
    ("origin", "host"),
    [
        ("https://dev.example.com", "dev.example.com"),
        ("https://dev.example.com:8443", "dev.example.com:8443"),
        ("http://127.0.0.1:8888", "127.0.0.1:8888"),
        ("http://localhost:5173", "localhost:5173"),
        # The port a browser leaves out is the scheme's own.
        ("https://dev.example.com", "dev.example.com:443"),
        ("https://dev.example.com:443", "dev.example.com"),
        ("http://dev.example.com", "dev.example.com:80"),
        # Names are compared without case.
        ("https://Dev.Example.com", "dev.EXAMPLE.com"),
        ("http://[::1]:8888", "[::1]:8888"),
        ("https://xn--bcher-kva.example", "xn--bcher-kva.example"),
    ],
)
def test_an_origin_that_names_the_host_matches(origin: str, host: str) -> None:
    assert origin_matches(origin, host)


@pytest.mark.parametrize(
    ("origin", "host"),
    [
        ("https://evil.example", "dev.example.com"),
        ("https://dev.example.com.evil.example", "dev.example.com"),
        ("https://evil.example/dev.example.com", "dev.example.com"),
        ("https://dev.example.com@evil.example", "evil.example"),
        ("https://sub.dev.example.com", "dev.example.com"),
        # The port is part of an origin.
        ("https://dev.example.com:8443", "dev.example.com"),
        ("https://dev.example.com", "dev.example.com:8443"),
        ("http://dev.example.com", "dev.example.com:443"),
        ("https://dev.example.com", "dev.example.com:80"),
        ("https://dev.example.com:444", "dev.example.com:443"),
        # What a sandboxed page, or a page opened from a file, sends.
        ("null", "dev.example.com"),
        ("", "dev.example.com"),
        ("dev.example.com", "dev.example.com"),
        ("//dev.example.com", "dev.example.com"),
        ("file://dev.example.com", "dev.example.com"),
        ("wss://dev.example.com", "dev.example.com"),
        ("https://dev.example.com/", "dev.example.com"),
        ("https://dev.example.com?x", "dev.example.com"),
        ("https://dev.example.com:port", "dev.example.com"),
        ("https://dev.example.com", "dev.example.com:port"),
        ("https://dev.example.com", "dev.example.com/path"),
        ("https://dev.example.com", ""),
        ("https://dev.example.com", None),
        ("https://", ""),
        ("https://[::1", "[::1"),
    ],
)
def test_an_origin_that_does_not_name_the_host_does_not_match(
    origin: str, host: str | None
) -> None:
    assert not origin_matches(origin, host)


def test_a_mutation_from_another_site_is_refused(client: TestClient) -> None:
    response = client.post("/api/v1/display-name", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert response.json() == BAD_ORIGIN
    assert "set-cookie" not in response.headers
    # No name was taken.
    assert client.post("/api/v1/display-name").json() == {"displayName": "Alpha1"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/display-name"),
        ("PATCH", "/api/v1/slots/4"),
        ("PUT", "/api/v1/slots/4"),
        ("DELETE", "/api/v1/slots/4"),
        ("POST", "/api/v1/slots/4/restore"),
        ("POST", "/api/v1/absent"),
        ("PATCH", "/api/v1/slots/99"),
    ],
)
def test_every_mutating_method_is_checked_whatever_the_path(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, headers={"Origin": "null"}, json={"title": "x"})

    assert response.status_code == 403
    assert response.json() == BAD_ORIGIN


def test_a_title_change_from_another_site_changes_nothing(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/slots/4", json={"title": "Taken over"}, headers={"Origin": "https://evil.example"}
    )

    assert response.json() == BAD_ORIGIN
    assert client.get("/api/v1/slots/4").json()["title"] == "Workspace 4"


def test_a_mutation_from_segls_own_page_passes(client: TestClient) -> None:
    # The test client sends `Host: testserver`.
    response = client.post("/api/v1/display-name", headers={"Origin": "http://testserver"})

    assert response.status_code == 200
    assert response.json() == {"displayName": "Alpha1"}


def test_a_request_without_an_origin_passes(client: TestClient) -> None:
    # Not a browser's cross-site request: curl, or a test.
    assert client.post("/api/v1/display-name").status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/slots", "/api/v1/slots/1/scene"])
def test_reading_is_not_checked(client: TestClient, path: str) -> None:
    # A read changes nothing, and another site's page cannot see the answer:
    # segl sends no CORS header that would let it.
    response = client.get(path, headers={"Origin": "https://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_two_origin_headers_must_both_match(client: TestClient) -> None:
    headers = [("Origin", "http://testserver"), ("Origin", "https://evil.example")]

    response = client.post("/api/v1/display-name", headers=headers)

    assert response.json() == BAD_ORIGIN


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://testserver:81"])
def test_a_websocket_from_another_site_is_refused_in_the_handshake(
    client: TestClient, origin: str
) -> None:
    with (
        pytest.raises(WebSocketDenialResponse) as refused,
        client.websocket_connect("/collab?slot=1", headers={"Origin": origin}),
    ):
        pass

    assert refused.value.status_code == 403
    assert refused.value.json() == BAD_ORIGIN
    assert "set-cookie" not in refused.value.headers


def test_a_websocket_from_segls_own_page_is_accepted(client: TestClient) -> None:
    with client.websocket_connect(
        "/collab?slot=1", headers={"Origin": "http://testserver"}
    ) as socket:
        socket.send_json({"type": "hello", "clientId": "c"})

        assert socket.receive_json()["type"] == "welcome"
