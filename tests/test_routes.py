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

"""The config route, the error shape, and what segl never sends: a cookie, or
an absolute redirect."""

import pytest
from fastapi.testclient import TestClient
from harness import GATED, assert_no_secrets, make_settings

from segl.app import create_app
from segl.repository import Repository

ROUTES = (
    "/api/v1/health",
    "/api/v1/config",
    "/api/v1/slots",
    "/api/v1/slots/1",
    "/api/v1/slots/1/scene",
)


@pytest.fixture
def client(repository: Repository) -> TestClient:
    return TestClient(create_app(make_settings(), repository), follow_redirects=False)


def test_config_says_no_token_is_needed_by_default(client: TestClient) -> None:
    response = client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json() == {"editRequired": False}


def test_config_says_a_code_is_needed_and_sends_none(repository: Repository) -> None:
    client = TestClient(create_app(make_settings(**GATED), repository))

    response = client.get("/api/v1/config")

    assert response.json() == {"editRequired": True}
    assert_no_secrets(response.text)
    assert_no_secrets(str(response.headers))


@pytest.mark.parametrize("path", [*ROUTES, "/api/v1/absent", "/api/v1/slots/0"])
def test_no_response_sets_a_cookie(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("path", ROUTES)
def test_every_route_answers(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"


@pytest.mark.parametrize("path", ROUTES)
def test_a_trailing_slash_is_not_redirected(client: TestClient, path: str) -> None:
    """Starlette's slash redirect is absolute, and would leave a path mount."""
    response = client.get(f"{path}/")

    assert response.status_code == 404
    assert "location" not in response.headers
    assert response.json()["error"] == "not_found"


@pytest.mark.parametrize("path", ["/api/v1/absent", "/absent", "/api/v1/slots/1/absent"])
def test_an_unknown_path_is_an_error_in_the_api_shape(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "message": "Not Found."}


def test_a_method_the_path_does_not_take_is_an_error_in_the_api_shape(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.json() == {"error": "method_not_allowed", "message": "Method Not Allowed."}
    assert response.headers["allow"] == "GET"


def test_a_failure_inside_segl_is_an_error_that_says_nothing_of_the_cause(
    repository: Repository,
) -> None:
    client = TestClient(create_app(make_settings(), repository), raise_server_exceptions=False)
    repository.close()

    response = client.get("/api/v1/slots")

    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "message": "segl could not complete the request.",
    }
    assert "sqlite" not in response.text.lower()
