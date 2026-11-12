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

"""``trusted_proxies`` decides whose X-Forwarded-For the running server believes.

No route reports the client address yet (the display-name limit is T05), so
these tests read it from the access log of a real ``segl`` process.
"""

from pathlib import Path

from harness import running_segl

FORWARDED = {"X-Forwarded-For": "203.0.113.9"}


def test_a_trusted_proxy_names_the_client(tmp_path: Path) -> None:
    # The default trusts 127.0.0.1, which is where this request comes from.
    with running_segl(tmp_path) as server:
        assert server.get("/api/v1/health?probe=trusted", FORWARDED).status == 200

        line = server.logged_line("probe=trusted")

    assert "203.0.113.9:" in line


def test_an_untrusted_connection_cannot_name_the_client(tmp_path: Path) -> None:
    with running_segl(tmp_path, "trusted_proxies = []\n") as server:
        assert server.get("/api/v1/health?probe=untrusted", FORWARDED).status == 200

        line = server.logged_line("probe=untrusted")

    assert "127.0.0.1:" in line
    assert "203.0.113.9" not in line


def test_a_trusted_network_names_the_client(tmp_path: Path) -> None:
    with running_segl(tmp_path, 'trusted_proxies = ["127.0.0.0/8"]\n') as server:
        assert server.get("/api/v1/health?probe=network", FORWARDED).status == 200

        line = server.logged_line("probe=network")

    assert "203.0.113.9:" in line
