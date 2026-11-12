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

"""Real processes for the tests: a segl server, and nginx in front of it.

``running_segl`` starts ``python -m segl --config`` on a free loopback port.
``install_nginx`` copies the files in deploy/nginx/ into a temporary prefix,
laid out as docs/DEPLOY.md installs them, and ``running_nginx`` serves from it.
The shipped files are never edited. The copies differ in three ways:

- the upstream names the test server's port
- the sites listen on free loopback ports, not 80 and 443
- ``snippets/snakeoil.conf`` names a certificate made for the test

T04's browser tests put the same nginx in front of the production build.
"""

import http.client
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from segl.config import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]
NGINX_FILES = ROOT / "deploy" / "nginx"

# Set in the dev container and in CI, where a missing nginx is a failure, not a skip.
REQUIRE_NGINX = "SEGL_REQUIRE_NGINX"
# `http2 on;` in the site examples needs this release.
MINIMUM_NGINX = (1, 25, 1)
# Ubuntu keeps nginx here, which is not on every account's PATH.
SBIN_NGINX = Path("/usr/sbin/nginx")

# The site examples, by the host name each one serves.
BOARD_SITE = "dev.example.com"
ROOT_SITE = "board.example.com"
SITE_FILES: Mapping[str, str] = {
    BOARD_SITE: "site-board.example.conf",
    ROOT_SITE: "site-root.example.conf",
}

NGINX_CONF = """\
# Written by tests/harness.py. It stands in for Ubuntu's /etc/nginx/nginx.conf,
# with every path inside this folder so that nginx runs without root.
daemon off;
worker_processes 1;
pid nginx.pid;
error_log error.log info;

events {
    worker_connections 64;
}

http {
    access_log access.log;
    client_body_temp_path tmp/body;
    proxy_temp_path tmp/proxy;
    fastcgi_temp_path tmp/fastcgi;
    uwsgi_temp_path tmp/uwsgi;
    scgi_temp_path tmp/scgi;

    include conf.d/*.conf;
    include sites-enabled/*;
}
"""


def make_settings(**changes: Any) -> Settings:
    """Return the settings deploy/segl.toml.example gives, with ``changes`` applied."""
    return replace(load_settings(ROOT / "deploy" / "segl.toml.example"), **changes)


def free_port() -> int:
    """Return a loopback TCP port that nothing is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass(frozen=True)
class Reply:
    """One HTTP response."""

    status: int
    headers: http.client.HTTPMessage
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


class _NamedLoopback(http.client.HTTPSConnection):
    """HTTPS to 127.0.0.1 that asks for, and verifies, a site's host name."""

    def __init__(self, name: str, port: int, context: ssl.SSLContext) -> None:
        super().__init__(name, port, timeout=10, context=context)
        self._tls = context

    def connect(self) -> None:
        plain = socket.create_connection(("127.0.0.1", self.port), self.timeout)
        self.sock = self._tls.wrap_socket(plain, server_hostname=self.host)


def fetch(
    port: int,
    path: str,
    *,
    site: str | None = None,
    tls: ssl.SSLContext | None = None,
    headers: Mapping[str, str] | None = None,
) -> Reply:
    """GET ``path`` from 127.0.0.1:``port``. Redirects are returned, not followed.

    With ``site`` and ``tls``, the request is HTTPS for that host name, as a
    browser would send it: the name is in the TLS handshake and, with the
    port, in ``Host``.
    """
    connection: http.client.HTTPConnection
    if site is not None and tls is not None:
        connection = _NamedLoopback(site, port, tls)
    else:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path, headers=dict(headers or {}))
        response = connection.getresponse()
        return Reply(response.status, response.headers, response.read())
    finally:
        connection.close()


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _wait_until(
    ready: Callable[[], object], process: subprocess.Popen[bytes], what: str, log: Path
) -> None:
    """Call ``ready`` until it stops raising OSError, or fail with the log."""
    deadline = time.monotonic() + 10
    while True:
        try:
            ready()
            return
        except OSError as exc:
            if process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
                continue
            text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
            raise AssertionError(f"{what} did not start ({exc}):\n{text}") from exc


@dataclass(frozen=True)
class SeglServer:
    """A running segl process."""

    port: int
    config: Path
    log_file: Path

    def get(self, path: str, headers: Mapping[str, str] | None = None) -> Reply:
        return fetch(self.port, path, headers=headers)

    def log(self) -> str:
        return self.log_file.read_text(encoding="utf-8")

    def logged_line(self, text: str) -> str:
        """Return the first log line containing ``text``, waiting up to five seconds."""
        deadline = time.monotonic() + 5
        while True:
            for line in self.log().splitlines():
                if text in line:
                    return line
            if time.monotonic() > deadline:
                raise AssertionError(f"segl did not log {text!r}:\n{self.log()}")
            time.sleep(0.02)


@contextmanager
def running_segl(folder: Path, config: str = "") -> Generator[SeglServer]:
    """Run ``python -m segl --config`` on a free loopback port until the block ends.

    The data paths point inside ``folder``. ``config`` is further TOML, and
    may replace them.
    """
    folder.mkdir(parents=True, exist_ok=True)
    port = free_port()
    config_file = folder / "segl.toml"
    config_file.write_text(
        f'bind = "127.0.0.1:{port}"\n'
        f'database = "{folder / "segl.sqlite"}"\n'
        f'assets_dir = "{folder / "assets"}"\n'
        f'display_names = "{folder / "display-names.txt"}"\n' + config,
        encoding="utf-8",
    )
    server = SeglServer(port=port, config=config_file, log_file=folder / "segl.log")
    with server.log_file.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "segl", "--config", str(config_file)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_until(lambda: server.get("/api/v1/health"), process, "segl", server.log_file)
        yield server
    finally:
        _stop(process)


@dataclass(frozen=True)
class NginxTools:
    """The programs the nginx harness runs."""

    nginx: str
    openssl: str


def find_nginx_tools() -> NginxTools | str:
    """Return the programs, or the reason the nginx tests cannot run here."""
    nginx = shutil.which("nginx") or (str(SBIN_NGINX) if SBIN_NGINX.is_file() else None)
    if nginx is None:
        return "nginx is not installed"
    banner = subprocess.run([nginx, "-v"], capture_output=True, text=True, check=False)
    found = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", banner.stderr + banner.stdout)
    if found is None:
        return f"{nginx} -v did not print a version"
    version = tuple(int(part) for part in found.groups())
    if version < MINIMUM_NGINX:
        need = ".".join(str(part) for part in MINIMUM_NGINX)
        have = ".".join(str(part) for part in version)
        return f"nginx {have} is older than {need}, which the files in deploy/nginx/ need"
    openssl = shutil.which("openssl")
    if openssl is None:
        return "openssl is not installed, so there is no test certificate"
    return NginxTools(nginx=nginx, openssl=openssl)


def nginx_tools_or_skip() -> NginxTools:
    """Return the programs, or skip the test. Where nginx is required, fail it."""
    found = find_nginx_tools()
    if isinstance(found, NginxTools):
        return found
    if os.environ.get(REQUIRE_NGINX):
        pytest.fail(f"{found}, and {REQUIRE_NGINX} is set")
    pytest.skip(f"{found}: the tests through nginx (docs/TEST-PLAN.md T-013) did not run")


def make_certificate(tools: NginxTools, folder: Path) -> tuple[Path, Path]:
    """Write a two-day self-signed certificate for both site names, and its key."""
    folder.mkdir(parents=True, exist_ok=True)
    certificate, key = folder / "test.crt", folder / "test.key"
    names = ",".join(f"DNS:{name}" for name in SITE_FILES)
    command = [tools.openssl, "req", "-x509", "-newkey", "ec"]
    command += ["-pkeyopt", "ec_paramgen_curve:prime256v1", "-noenc", "-days", "2"]
    command += ["-keyout", str(key), "-out", str(certificate)]
    command += ["-subj", "/CN=segl test", "-addext", f"subjectAltName={names}"]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return certificate, key


def _swap(name: str, replacements: Mapping[str, str]) -> str:
    """Return a shipped file's text with each fragment replaced exactly once."""
    text = (NGINX_FILES / name).read_text(encoding="utf-8")
    for old, new in replacements.items():
        count = text.count(old)
        assert count == 1, (
            f"deploy/nginx/{name} has {old!r} {count} times; tests/harness.py expects 1"
        )
        text = text.replace(old, new)
    return text


def install_nginx(
    prefix: Path,
    *,
    sites: Sequence[str],
    upstream_port: int,
    http_port: int,
    https_port: int,
    certificate: Path,
    key: Path,
) -> Path:
    """Lay the deploy/nginx/ files out under ``prefix`` and return it.

    ``sites`` are host names from ``SITE_FILES``. The layout is the one in
    docs/DEPLOY.md, with ``prefix`` in place of /etc/nginx.
    """
    for name in ("conf.d", "snippets", "sites-enabled", "tmp"):
        (prefix / name).mkdir(parents=True, exist_ok=True)
    upstream = {"server 127.0.0.1:8000;": f"server 127.0.0.1:{upstream_port};"}
    (prefix / "conf.d" / "segl.conf").write_text(_swap("segl-http.conf", upstream), "utf-8")
    for name in ("segl-proxy.conf", "segl-board.conf"):
        shutil.copyfile(NGINX_FILES / name, prefix / "snippets" / name)
    (prefix / "snippets" / "snakeoil.conf").write_text(
        f"ssl_certificate {certificate};\nssl_certificate_key {key};\n", "utf-8"
    )
    # Loopback only, and no IPv6 listener: a container build may have no ::1.
    listeners = {
        "    listen 80;\n": f"    listen 127.0.0.1:{http_port};\n",
        "    listen [::]:80;\n": "",
        "    listen 443 ssl;\n": f"    listen 127.0.0.1:{https_port} ssl;\n",
        "    listen [::]:443 ssl;\n": "",
    }
    for site in sites:
        text = _swap(SITE_FILES[site], listeners)
        (prefix / "sites-enabled" / site).write_text(text, "utf-8")
    (prefix / "nginx.conf").write_text(NGINX_CONF, "utf-8")
    return prefix


def nginx_command(tools: NginxTools, prefix: Path) -> list[str]:
    """Return the nginx command line for a prefix. Append ``-t`` to test it."""
    # -e keeps nginx from opening /var/log/nginx/error.log before it reads the file.
    log = str(prefix / "error.log")
    return [tools.nginx, "-p", f"{prefix}/", "-c", str(prefix / "nginx.conf"), "-e", log]


def check_nginx(tools: NginxTools, prefix: Path) -> subprocess.CompletedProcess[str]:
    """Run ``nginx -t`` on a prefix."""
    command = [*nginx_command(tools, prefix), "-t"]
    return subprocess.run(command, capture_output=True, text=True, check=False)


@contextmanager
def running_nginx(tools: NginxTools, prefix: Path, https_port: int) -> Generator[None]:
    """Run nginx from a prefix until the block ends."""
    process = subprocess.Popen(nginx_command(tools, prefix))

    def connect() -> None:
        socket.create_connection(("127.0.0.1", https_port), timeout=2).close()

    try:
        _wait_until(connect, process, "nginx", prefix / "error.log")
        yield
    finally:
        _stop(process)
