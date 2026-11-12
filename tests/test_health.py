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

"""The health route, in process and from a running ``segl`` process."""

from pathlib import Path

from fastapi.testclient import TestClient
from harness import make_settings, running_segl

from segl.app import create_app
from segl.repository import Repository


def test_health_answers_ok(repository: Repository) -> None:
    response = TestClient(create_app(make_settings(), repository)).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "set-cookie" not in response.headers


def test_generated_documentation_pages_are_off(repository: Repository) -> None:
    client = TestClient(create_app(make_settings(), repository))

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_process_serves_health_on_the_configured_bind(tmp_path: Path) -> None:
    with running_segl(tmp_path) as server:
        reply = server.get("/api/v1/health")

        assert reply.status == 200
        assert reply.json() == {"status": "ok"}
        assert f"127.0.0.1:{server.port}" in server.logged_line("Uvicorn running on")
