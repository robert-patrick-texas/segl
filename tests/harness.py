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
import itertools
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import tomllib
import warnings
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin

from segl.access import Access, normalize
from segl.config import DEFAULT_BIND, Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]
NGINX_FILES = ROOT / "deploy" / "nginx"

# The scene a new slot starts with: the editor's own empty scene, captured in
# T04 (docs/DATA-MODEL.md). web/e2e/fixture.spec.ts holds it to the editor.
EMPTY_SCENE_FILE = ROOT / "src" / "segl" / "empty_scene.json"
EMPTY_SCENE: Any = json.loads(EMPTY_SCENE_FILE.read_text(encoding="utf-8"))

# The packaged display-name list, and the two-word file docs/TEST-PLAN.md
# T-014 names, which every test server gets unless the test wrote its own.
DISPLAY_NAMES_FILE = ROOT / "deploy" / "display-names.txt"
TEST_DISPLAY_NAMES = "Guest\nStaff\n"

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


# A segl that asks for an access code (S-008): one code, as a person might
# write it down, and the secret that signs its passes.
ACCESS_CODE = "Maple River 42"
ACCESS_SECRET = "segl-tests-secret-3f1c9a7e5b2d4f60-not-a-real-one"
# The settings of such a segl, for ``make_settings(**GATED)``.
GATED: Mapping[str, Any] = {
    "access_codes": (normalize(ACCESS_CODE),),
    "access_secret": ACCESS_SECRET,
}
# The same two keys, as lines of a TOML file.
GATED_TOML = f'access_codes = ["{ACCESS_CODE}"]\naccess_secret = "{ACCESS_SECRET}"\n'
# What must be in no answer, no page, and no log: the code as written and as
# compared, and the secret.
SECRETS = (ACCESS_CODE, normalize(ACCESS_CODE), ACCESS_SECRET)

# The header a pass travels in. Its name is from when it carried a token.
PASS_HEADER = "X-Segl-Edit-Token"


def issue_pass(
    code: str = ACCESS_CODE, *, secret: str = ACCESS_SECRET, at: float | None = None
) -> str:
    """Return a pass as a segl with ``GATED`` issues one for ``code``, now or at ``at``.

    Two calls in one second give the same pass: it is the second of its
    issue and a signature over that second and the code.
    """
    clock = time.time if at is None else (lambda: at)
    return Access((normalize(code),), secret, clock=clock).issue(normalize(code))[0]


def assert_no_secrets(text: str | bytes, what: str = "") -> None:
    """Fail when ``text`` holds an access code, the secret, or a pass issued today."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    for secret in SECRETS:
        assert secret not in text, what
    # A pass ends in its signature, which the secret makes.
    assert issue_pass().partition(".")[2] not in text, what


def make_settings(**changes: Any) -> Settings:
    """Return the settings deploy/segl.toml.example gives, with ``changes`` applied.

    One value differs: ``display_names`` is the packaged list in the checkout,
    because the application reads the file and the example's path exists only
    on an installed host.
    """
    changes.setdefault("display_names", DISPLAY_NAMES_FILE)
    return replace(load_settings(ROOT / "deploy" / "segl.toml.example"), **changes)


# With the tests in several processes (conftest.py at the root), each worker
# takes its ports from a range of its own. Two workers that asked the system
# for a free port could be handed the same one, each before the other's
# server had it. The ranges are below the ports the system hands out and
# above the browser tests' fixed ones.
WORKER_PORTS_FROM = 20000
WORKER_PORTS_EACH = 1000
_port_turn = itertools.count()


def worker_ports(worker: str) -> range | None:
    """Return the ports of a pytest-xdist worker such as ``gw2``, or None for none."""
    if not (worker.startswith("gw") and worker[2:].isdecimal()):
        return None
    first = WORKER_PORTS_FROM + int(worker[2:]) * WORKER_PORTS_EACH
    return range(first, first + WORKER_PORTS_EACH)


def free_port() -> int:
    """Return a loopback TCP port that nothing is listening on."""
    ports = worker_ports(os.environ.get("PYTEST_XDIST_WORKER", ""))
    if ports is None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]
    # In turn, so that a port a test has just let go is not the next one out.
    for _ in ports:
        port = ports[next(_port_turn) % len(ports)]
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no free port from {ports.start} to {ports.stop - 1}")


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
    method: str = "GET",
    site: str | None = None,
    tls: ssl.SSLContext | None = None,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
) -> Reply:
    """Ask 127.0.0.1:``port`` for ``path``. Redirects are returned, not followed.

    With ``site`` and ``tls``, the request is HTTPS for that host name, as a
    browser would send it: the name is in the TLS handshake and, with the
    port, in ``Host``. ``body`` is sent as it is.
    """
    connection: http.client.HTTPConnection
    if site is not None and tls is not None:
        connection = _NamedLoopback(site, port, tls)
    else:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=dict(headers or {}))
        response = connection.getresponse()
        return Reply(response.status, response.headers, response.read())
    finally:
        connection.close()


# How long a WebSocket handshake may take: the client's own default.
HANDSHAKE_SECONDS = 10.0

# How much of a log a failure quotes.
LOG_TAIL_LINES = 40


def log_tails(logs: Mapping[str, Path]) -> str:
    """Return the end of each log, under its name, for a failure's message.

    A test that waited for a server and gave up says what the server had
    written. A log that is not there, or is empty, is said to be so.
    """
    parts = []
    for name, file in logs.items():
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            parts.append(f"--- {name} ({file}): cannot be read: {exc}")
            continue
        if not lines:
            parts.append(f"--- {name} ({file}): empty")
            continue
        shown = lines[-LOG_TAIL_LINES:]
        parts.append(f"--- {name} ({file}), the last {len(shown)} of {len(lines)} lines:")
        parts.extend(shown)
    return "\n".join(parts)


def open_socket(
    port: int,
    path: str,
    *,
    site: str | None = None,
    tls: ssl.SSLContext | None = None,
    origin: str | None = None,
    headers: Mapping[str, str] | None = None,
    logs: Mapping[str, Path] | None = None,
) -> ClientConnection:
    """Open a WebSocket to 127.0.0.1:``port`` at ``path``, as ``fetch`` asks for a page.

    ``origin`` is the ``Origin`` header a browser would send, and ``headers``
    are any others, such as the ``X-Forwarded-For`` of a proxy. A handshake that
    is refused raises ``websockets.exceptions.InvalidStatus``, which carries
    the HTTP response. One that is not answered in time fails the test with
    the end of each of ``logs``: what the servers on the way had written.
    """
    plain = socket.create_connection(("127.0.0.1", port), timeout=10)
    sent_from = None if origin is None else Origin(origin)
    try:
        # proxy=None: never through a proxy the environment names.
        if site is not None and tls is not None:
            uri = f"wss://{site}:{port}{path}"
            return connect(
                uri,
                sock=plain,
                ssl=tls,
                server_hostname=site,
                origin=sent_from,
                additional_headers=headers,
                proxy=None,
                open_timeout=HANDSHAKE_SECONDS,
            )
        return connect(
            f"ws://127.0.0.1:{port}{path}",
            sock=plain,
            origin=sent_from,
            additional_headers=headers,
            proxy=None,
            open_timeout=HANDSHAKE_SECONDS,
        )
    except TimeoutError as exc:
        message = (
            f"the WebSocket handshake for {path} on port {port} was not answered in "
            f"{HANDSHAKE_SECONDS:g} seconds ({exc})"
        )
        raise AssertionError(f"{message}\n{log_tails(logs or {})}") from exc


def say_hello(
    connection: ClientConnection,
    name: str | None = "Guest1",
    *,
    edit_pass: str = "",
    client_id: str = "client-1",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Send ``hello`` on a new socket, and return the ``welcome`` and the ``scene``.

    ``edit_pass`` goes in the field the protocol still calls ``editToken``.
    """
    hello = {"type": "hello", "clientId": client_id, "displayName": name, "editToken": edit_pass}
    connection.send(json.dumps(hello))
    return next_message(connection), next_message(connection)


def next_message(connection: ClientConnection, seconds: float = 5.0) -> dict[str, Any]:
    """Return the next message on a socket. A socket with none fails the test."""
    try:
        return json.loads(connection.recv(timeout=seconds))
    except TimeoutError:
        raise AssertionError(f"no message arrived in {seconds} seconds") from None


# How long a server has to stop after SIGTERM before it is killed.
STOP_SECONDS = 10.0


def _stop(process: subprocess.Popen[bytes], what: str, log: Path) -> None:
    """End a server with SIGTERM, and with SIGKILL when that does not end it.

    A server that had to be killed is said so, with the end of its log, as a
    warning in pytest's summary. The test it served has already had its
    verdict, and a stop that hangs should not pass unseen.
    """
    process.terminate()
    try:
        process.wait(timeout=STOP_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        warnings.warn(
            f"{what} had not stopped {STOP_SECONDS:g} seconds after SIGTERM and was killed\n"
            f"{log_tails({what: log})}",
            stacklevel=2,
        )


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
    process: subprocess.Popen[bytes]

    def get(self, path: str, headers: Mapping[str, str] | None = None) -> Reply:
        return fetch(self.port, path, headers=headers)

    def post(
        self, path: str, headers: Mapping[str, str] | None = None, body: bytes | None = None
    ) -> Reply:
        return fetch(self.port, path, method="POST", headers=headers, body=body)

    def kill(self) -> None:
        """End the process with SIGKILL: no flush, no close, as a crash or a lost host."""
        self.process.kill()
        self.process.wait()

    def patch(self, path: str, body: object, headers: Mapping[str, str] | None = None) -> Reply:
        """Send ``body`` as JSON."""
        sent = json.dumps(body).encode()
        return fetch(self.port, path, method="PATCH", headers=headers, body=sent)

    def socket(
        self, path: str, origin: str | None = None, headers: Mapping[str, str] | None = None
    ) -> ClientConnection:
        return open_socket(
            self.port, path, origin=origin, headers=headers, logs={"segl": self.log_file}
        )

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
    may replace them. The display-name file is ``Guest`` and ``Staff``, unless
    the folder already has a ``display-names.txt``. A second run in the same
    folder is a restart: it has the database and the uploaded files of the first.
    """
    folder.mkdir(parents=True, exist_ok=True)
    names = folder / "display-names.txt"
    if not names.exists():
        names.write_text(TEST_DISPLAY_NAMES, encoding="utf-8")
    port = free_port()
    config_file = folder / "segl.toml"
    defaults = {
        "bind": f"127.0.0.1:{port}",
        "database": folder / "segl.sqlite",
        "assets_dir": folder / "assets",
        "display_names": names,
    }
    # TOML takes a key once, so a key the test sets is left out here.
    given = tomllib.loads(config)
    lines = [f'{key} = "{value}"\n' for key, value in defaults.items() if key not in given]
    config_file.write_text("".join(lines) + config, encoding="utf-8")
    log_file = folder / "segl.log"
    with log_file.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "segl", "--config", str(config_file)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    server = SeglServer(port=port, config=config_file, log_file=log_file, process=process)
    try:
        _wait_until(lambda: server.get("/api/v1/health"), process, "segl", server.log_file)
        yield server
    finally:
        _stop(process, "segl", log_file)


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
    # The shipped upstream is segl's default bind. A default that moves without
    # the nginx file fails here.
    upstream = {f"server {DEFAULT_BIND};": f"server 127.0.0.1:{upstream_port};"}
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


@dataclass(frozen=True)
class Mount:
    """nginx serving both site examples in front of one segl process."""

    segl: SeglServer
    https_port: int
    tls: ssl.SSLContext
    # The folder nginx runs from, which holds its two logs.
    prefix: Path

    def get(self, site: str, path: str, headers: Mapping[str, str] | None = None) -> Reply:
        return fetch(self.https_port, path, site=site, tls=self.tls, headers=headers)

    def post(
        self,
        site: str,
        path: str,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> Reply:
        return fetch(
            self.https_port,
            path,
            method="POST",
            site=site,
            tls=self.tls,
            headers=headers,
            body=body,
        )

    def patch(
        self, site: str, path: str, body: object, headers: Mapping[str, str] | None = None
    ) -> Reply:
        """Send ``body`` as JSON."""
        sent = json.dumps(body).encode()
        return fetch(
            self.https_port,
            path,
            method="PATCH",
            site=site,
            tls=self.tls,
            headers=headers,
            body=sent,
        )

    def origin(self, site: str) -> str:
        """Return the ``Origin`` of a page this mount served for ``site``."""
        return f"https://{site}:{self.https_port}"

    def socket(self, site: str, path: str, origin: str | None = None) -> ClientConnection:
        # A socket through nginx that is not answered: what nginx saw of it,
        # what it said went wrong, and what segl had logged.
        logs = {
            "nginx error.log": self.prefix / "error.log",
            "nginx access.log": self.prefix / "access.log",
            "segl": self.segl.log_file,
        }
        return open_socket(self.https_port, path, site=site, tls=self.tls, origin=origin, logs=logs)


@contextmanager
def running_mount(
    tools: NginxTools, certificate: tuple[Path, Path], folder: Path, config: str = ""
) -> Generator[Mount]:
    """Run a segl process, and nginx in front of it with both site examples.

    ``certificate`` is the pair ``make_certificate`` returned. ``config`` is
    further TOML for segl.
    """
    https_port = free_port()
    with running_segl(folder / "segl", config) as segl:
        prefix = install_nginx(
            folder / "nginx",
            sites=(BOARD_SITE, ROOT_SITE),
            upstream_port=segl.port,
            http_port=free_port(),
            https_port=https_port,
            certificate=certificate[0],
            key=certificate[1],
        )
        with running_nginx(tools, prefix, https_port):
            # The client checks the test certificate and the site's name, as a browser would.
            tls = ssl.create_default_context(cafile=str(certificate[0]))
            # Held at TLS 1.2 until the `websockets` client is sound under 1.3
            # (docs/ROADMAP.md). Its sync client reads the socket from a second
            # thread before it has written its request, and under TLS 1.3 on a
            # busy machine that request was sometimes lost: nginx waited a
            # minute for it, and the test failed with a handshake that was not
            # answered. `tests/handshake_loop.py` measures it. nginx is not
            # held: it runs the shipped files, and the browser tests use 1.3.
            tls.maximum_version = ssl.TLSVersion.TLSv1_2
            yield Mount(segl=segl, https_port=https_port, tls=tls, prefix=prefix)


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
        _stop(process, "nginx", prefix / "error.log")
