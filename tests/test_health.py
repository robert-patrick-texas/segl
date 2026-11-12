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

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi.testclient import TestClient

from segl.app import create_app


def test_health_answers_ok() -> None:
    response = TestClient(create_app()).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "set-cookie" not in response.headers


def test_generated_documentation_pages_are_off() -> None:
    client = TestClient(create_app())

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def fetch_health(port: int, process: subprocess.Popen[str]) -> dict[str, str]:
    """Poll the health route until the process answers, exits, or ten seconds pass."""
    url = f"http://127.0.0.1:{port}/api/v1/health"
    deadline = time.monotonic() + 10
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return json.load(response)
        except urllib.error.URLError, ConnectionError:
            if process.poll() is not None or time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def serve(config: Path) -> tuple[subprocess.Popen[str], int]:
    """Start ``segl --config`` with ``bind`` set to a free loopback port, when the file exists."""
    port = free_port()
    if config.is_file():
        config.write_text(f'bind = "127.0.0.1:{port}"\n', encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "segl", "--config", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, port


def stop(process: subprocess.Popen[str]) -> str:
    process.terminate()
    try:
        output, _ = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
    return output


def test_process_serves_health_on_the_configured_bind(tmp_path: Path) -> None:
    config = tmp_path / "segl.toml"
    config.touch()
    process, port = serve(config)
    try:
        assert fetch_health(port, process) == {"status": "ok"}
    finally:
        output = stop(process)
    assert f"127.0.0.1:{port}" in output
