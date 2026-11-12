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

"""The config route, and what segl never sends: a cookie, or an absolute redirect."""

import pytest
from fastapi.testclient import TestClient
from harness import make_settings

from segl.app import create_app

ROUTES = ("/api/v1/health", "/api/v1/config")


def test_config_says_no_token_is_needed_by_default() -> None:
    response = TestClient(create_app(make_settings())).get("/api/v1/config")

    assert response.status_code == 200
    assert response.json() == {"editRequired": False}


def test_config_says_a_token_is_needed_and_does_not_send_it() -> None:
    client = TestClient(create_app(make_settings(edit_token="correct-horse")))

    response = client.get("/api/v1/config")

    assert response.json() == {"editRequired": True}
    assert "correct-horse" not in response.text
    assert "correct-horse" not in str(response.headers)


@pytest.mark.parametrize("path", [*ROUTES, "/api/v1/absent"])
def test_no_response_sets_a_cookie(path: str) -> None:
    response = TestClient(create_app(make_settings())).get(path)

    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("path", ROUTES)
def test_a_trailing_slash_is_not_redirected(path: str) -> None:
    """Starlette's slash redirect is absolute, and would leave a path mount."""
    client = TestClient(create_app(make_settings()), follow_redirects=False)

    response = client.get(f"{path}/")

    assert response.status_code == 404
    assert "location" not in response.headers
