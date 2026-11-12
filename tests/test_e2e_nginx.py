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

"""``tests/e2e_nginx.py``, the nginx that ``web/playwright.config.ts`` starts
in front of segl for the browser tests.

Playwright only reports that its servers did not start, so the script is
checked here: one nginx for each site example, a line on stdout when both
answer, and nothing left running after SIGTERM.
"""

import signal
import socket
import ssl
import subprocess
import sys
from pathlib import Path

import e2e_nginx
import harness
import pytest
from harness import ROOT


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _get(port: int, path: str) -> harness.Reply:
    """GET over TLS by address, as the browser tests do. The certificate names the sites."""
    insecure = ssl.create_default_context()
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    return harness.fetch(port, path, site="127.0.0.1", tls=insecure)


def test_each_site_example_is_served_on_its_own_port_until_sigterm(tmp_path: Path) -> None:
    harness.nginx_tools_or_skip()
    board_port, root_port = harness.free_port(), harness.free_port()
    with harness.running_segl(tmp_path / "segl") as segl:
        command = [sys.executable, str(ROOT / "tests" / "e2e_nginx.py")]
        command += ["--prefix", str(tmp_path / "proxy"), "--upstream-port", str(segl.port)]
        command += ["--board-port", str(board_port), "--root-port", str(root_port)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert process.stdout is not None
            ready = process.stdout.readline().decode()
            assert ready.startswith(e2e_nginx.READY), ready
            assert f"https://127.0.0.1:{board_port}/board/" in ready
            assert f"https://127.0.0.1:{root_port}/" in ready

            # segl at /board/ on one port, and at the host root on the other.
            assert _get(board_port, "/board/api/v1/health").json() == {"status": "ok"}
            assert _get(root_port, "/api/v1/health").json() == {"status": "ok"}
            redirect = _get(board_port, "/board")
            assert (redirect.status, redirect.headers["Location"]) == (301, "/board/")
            # Outside the mount, nginx answers and segl is not asked.
            assert _get(board_port, "/api/v1/health").status == 404
            assert "/board/api/v1/health" not in segl.log()
        finally:
            process.send_signal(signal.SIGTERM)
            _out, errors = process.communicate(timeout=20)

    assert process.returncode == 0, errors.decode()
    assert "Traceback" not in errors.decode()
    assert not _listening(board_port)
    assert not _listening(root_port)
    # The shipped files were copied, not edited.
    assert (
        tmp_path / "proxy" / harness.BOARD_SITE / "snippets" / "segl-proxy.conf"
    ).read_bytes() == (harness.NGINX_FILES / "segl-proxy.conf").read_bytes()


def test_without_nginx_the_script_says_why_and_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "find_nginx_tools", lambda: "nginx is not installed")
    argv = ["--prefix", str(tmp_path), "--upstream-port", "1", "--board-port", "2"]

    assert e2e_nginx.main([*argv, "--root-port", "3"]) == 1
    assert "nginx is not installed" in capsys.readouterr().err
