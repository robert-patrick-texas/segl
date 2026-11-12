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

"""segl behind nginx, with the files in deploy/nginx/ (docs/TEST-PLAN.md T-013).

This is the HTTP half: the ``/board`` redirect, and the health and config
routes under ``/board/`` and at a host root. T04 adds the page and T06 the
WebSocket. The responses also start T-012: none sets a cookie.

The tests need nginx and openssl. Without them they skip and say why. With
``SEGL_REQUIRE_NGINX`` set, as in the dev container and CI, they fail instead.
"""

import socket
import ssl
from collections.abc import Iterator
from pathlib import Path

import harness
import pytest
from harness import BOARD_SITE, ROOT_SITE, Mount, NginxTools


@pytest.fixture(scope="module")
def mount(
    tools: NginxTools,
    certificate: tuple[Path, Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Mount]:
    with harness.running_mount(tools, certificate, tmp_path_factory.mktemp("mount")) as mount:
        yield mount


@pytest.mark.parametrize("site", [BOARD_SITE, ROOT_SITE])
def test_nginx_accepts_each_site_example(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path, site: str
) -> None:
    prefix = harness.install_nginx(
        tmp_path,
        sites=(site,),
        upstream_port=harness.free_port(),
        http_port=harness.free_port(),
        https_port=harness.free_port(),
        certificate=certificate[0],
        key=certificate[1],
    )

    checked = harness.check_nginx(tools, prefix)

    assert checked.returncode == 0, checked.stderr
    assert "syntax is ok" in checked.stderr
    assert "test is successful" in checked.stderr


def test_the_installed_copies_leave_the_shipped_files_alone(
    certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    before = {path.name: path.read_bytes() for path in harness.NGINX_FILES.iterdir()}

    prefix = harness.install_nginx(
        tmp_path,
        sites=(BOARD_SITE, ROOT_SITE),
        upstream_port=18000,
        http_port=18080,
        https_port=18443,
        certificate=certificate[0],
        key=certificate[1],
    )

    assert {path.name: path.read_bytes() for path in harness.NGINX_FILES.iterdir()} == before
    # The snippets are byte-for-byte the shipped ones. Only the port lines differ elsewhere.
    for name in ("segl-proxy.conf", "segl-board.conf"):
        assert (prefix / "snippets" / name).read_bytes() == before[name]
    assert "server 127.0.0.1:18000;" in (prefix / "conf.d" / "segl.conf").read_text("utf-8")
    site = (prefix / "sites-enabled" / BOARD_SITE).read_text("utf-8")
    assert "listen 127.0.0.1:18443 ssl;" in site
    assert "include snippets/segl-board.conf;" in site


def test_board_redirects_to_board_slash(mount: Mount) -> None:
    reply = mount.get(BOARD_SITE, "/board")

    assert reply.status == 301
    # Relative, so it holds on any host name, scheme, and port.
    assert reply.headers["Location"] == "/board/"
    assert reply.headers["Set-Cookie"] is None


@pytest.mark.parametrize(
    ("site", "prefix"), [(BOARD_SITE, "/board"), (ROOT_SITE, "")], ids=["board", "host-root"]
)
def test_health_and_config_reach_segl(mount: Mount, site: str, prefix: str) -> None:
    health = mount.get(site, f"{prefix}/api/v1/health")
    config = mount.get(site, f"{prefix}/api/v1/config")

    assert (health.status, health.json()) == (200, {"status": "ok"})
    assert (config.status, config.json()) == (200, {"editRequired": False})
    for reply in (health, config):
        assert reply.headers["Set-Cookie"] is None
        assert reply.headers["Content-Type"] == "application/json"


@pytest.mark.parametrize(
    ("site", "prefix"), [(BOARD_SITE, "/board"), (ROOT_SITE, "")], ids=["board", "host-root"]
)
def test_the_slot_routes_reach_segl(mount: Mount, site: str, prefix: str) -> None:
    slots = mount.get(site, f"{prefix}/api/v1/slots")
    scene = mount.get(site, f"{prefix}/api/v1/slots/9/scene")
    invalid = mount.get(site, f"{prefix}/api/v1/slots/10")

    assert slots.status == 200
    assert [slot["title"] for slot in slots.json()["slots"]] == [
        f"Workspace {n}" for n in range(1, 10)
    ]
    assert (scene.status, scene.json()["scene"]) == (200, harness.EMPTY_SCENE)
    # segl's own 404, passed through, not an nginx error page.
    assert (invalid.status, invalid.json()["error"]) == (404, "invalid_slot")
    for reply in (slots, scene, invalid):
        assert reply.headers["Set-Cookie"] is None
        assert reply.headers["Content-Type"] == "application/json"


@pytest.mark.parametrize(
    ("site", "prefix"), [(BOARD_SITE, "/board"), (ROOT_SITE, "")], ids=["board", "host-root"]
)
def test_segl_sees_its_own_path_and_nginx_as_the_client(
    mount: Mount, site: str, prefix: str
) -> None:
    probe = f"probe={site}"

    # A client cannot choose the address segl records: nginx replaces the header.
    reply = mount.get(site, f"{prefix}/api/v1/health?{probe}", {"X-Forwarded-For": "203.0.113.9"})
    line = mount.segl.logged_line(probe)

    assert reply.status == 200
    assert f'"GET /api/v1/health?{probe} HTTP/1.1" 200' in line
    assert line.split(" - ")[0].endswith("127.0.0.1:0")
    assert "203.0.113.9" not in mount.segl.log()


def test_a_path_outside_board_does_not_reach_segl(mount: Mount) -> None:
    reply = mount.get(BOARD_SITE, "/api/v1/health?probe=outside")
    after = mount.get(BOARD_SITE, "/board/api/v1/health?probe=after-outside")

    assert reply.status == 404
    assert after.status == 200
    mount.segl.logged_line("probe=after-outside")
    assert "probe=outside" not in mount.segl.log()


@pytest.mark.parametrize(
    ("site", "prefix"), [(BOARD_SITE, "/board"), (ROOT_SITE, "")], ids=["board", "host-root"]
)
def test_segl_sends_no_redirect_of_its_own(mount: Mount, site: str, prefix: str) -> None:
    """A slash redirect from segl would be absolute and would drop ``/board``."""
    reply = mount.get(site, f"{prefix}/api/v1/health/")

    assert reply.status == 404
    assert reply.headers["Location"] is None
    # segl's own answer, not an nginx error page.
    assert reply.headers["Content-Type"] == "application/json"


def test_the_sites_own_header_survives_the_proxy(mount: Mount) -> None:
    reply = mount.get(BOARD_SITE, "/board/api/v1/health")

    assert reply.headers["Strict-Transport-Security"] == "max-age=31536000"


# The hardening the packaged site examples carry (docs/SECURITY.md). It is the
# site's to keep or to change: segl does not depend on any of it.

SITE_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "SAMEORIGIN",
}


@pytest.mark.parametrize(
    ("site", "path", "status"),
    [
        # What segl answers, a refusal of its own among it.
        (BOARD_SITE, "/board/api/v1/health", 200),
        (BOARD_SITE, "/board/api/v1/slots/10", 404),
        (ROOT_SITE, "/api/v1/health", 200),
        (ROOT_SITE, "/api/v1/nope", 404),
        # What nginx answers itself: its redirect, and a path it has nothing for.
        (BOARD_SITE, "/board", 301),
        (BOARD_SITE, "/api/v1/health", 404),
    ],
)
def test_every_answer_through_a_site_example_has_the_sites_headers(
    mount: Mount, site: str, path: str, status: int
) -> None:
    reply = mount.get(site, path)

    assert reply.status == status
    for name, value in SITE_HEADERS.items():
        assert reply.headers.get_all(name) == [value], name
    # nginx, and not which one.
    assert reply.headers["Server"] == "nginx"


@pytest.fixture(params=[BOARD_SITE, ROOT_SITE])
def alone(
    request: pytest.FixtureRequest,
    tools: NginxTools,
    certificate: tuple[Path, Path],
    tmp_path: Path,
) -> Iterator[tuple[str, int]]:
    """One site example in an nginx of its own: the site's name and its HTTPS port.

    Two sites on one listener share the TLS settings of the one nginx reads
    first, its protocols and its session tickets among them. So what each
    example sets for TLS can only be seen with that example alone. Nothing
    answers behind it: these tests stop at the handshake.
    """
    site: str = request.param
    port = harness.free_port()
    prefix = harness.install_nginx(
        tmp_path / "alone",
        sites=(site,),
        upstream_port=harness.free_port(),
        http_port=harness.free_port(),
        https_port=port,
        certificate=certificate[0],
        key=certificate[1],
    )
    with harness.running_nginx(tools, prefix, port):
        yield site, port


def handshake(
    port: int, certificate: Path, site: str, *, newest: bool = False, ciphers: str | None = None
) -> ssl.SSLSocket:
    """Open a TLS connection: TLS 1.2 unless ``newest``, offering only ``ciphers`` if given."""
    context = ssl.create_default_context(cafile=str(certificate))
    if not newest:
        context.maximum_version = ssl.TLSVersion.TLSv1_2
    if ciphers is not None:
        context.set_ciphers(ciphers)
    plain = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        return context.wrap_socket(plain, server_hostname=site)
    except BaseException:
        plain.close()
        raise


def test_a_site_example_takes_only_forward_secret_aead_ciphers_under_tls_1_2(
    alone: tuple[str, int], certificate: tuple[Path, Path]
) -> None:
    site, port = alone

    with handshake(port, certificate[0], site, ciphers="ECDHE-ECDSA-AES256-GCM-SHA384") as taken:
        assert taken.version() == "TLSv1.2"
        cipher = taken.cipher()
        assert cipher is not None
        assert cipher[0] == "ECDHE-ECDSA-AES256-GCM-SHA384"

    # A CBC cipher, which nginx's own default list would take.
    with pytest.raises(ssl.SSLError):
        handshake(port, certificate[0], site, ciphers="ECDHE-ECDSA-AES128-SHA256")


def test_a_site_example_gives_no_session_ticket(
    alone: tuple[str, int], certificate: tuple[Path, Path]
) -> None:
    # nginx would hold a ticket's key until it restarts.
    site, port = alone

    with handshake(port, certificate[0], site) as taken:
        assert taken.session is not None
        assert not taken.session.has_ticket


def test_a_site_example_offers_tls_1_3_and_1_2(
    alone: tuple[str, int], certificate: tuple[Path, Path]
) -> None:
    site, port = alone

    with handshake(port, certificate[0], site, newest=True) as newest:
        assert newest.version() == "TLSv1.3"
    with handshake(port, certificate[0], site) as older:
        assert older.version() == "TLSv1.2"


def test_a_missing_nginx_is_a_skip_that_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)
    monkeypatch.setattr(harness, "SBIN_NGINX", Path("/nonexistent/nginx"))
    monkeypatch.delenv(harness.REQUIRE_NGINX, raising=False)

    assert harness.find_nginx_tools() == "nginx is not installed"
    with pytest.raises(pytest.skip.Exception, match="nginx is not installed: the tests through"):
        harness.nginx_tools_or_skip()


def test_a_missing_nginx_is_a_failure_where_it_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)
    monkeypatch.setattr(harness, "SBIN_NGINX", Path("/nonexistent/nginx"))
    monkeypatch.setenv(harness.REQUIRE_NGINX, "1")

    with pytest.raises(pytest.fail.Exception, match="nginx is not installed"):
        harness.nginx_tools_or_skip()


def test_an_nginx_too_old_for_the_shipped_files_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old = tmp_path / "nginx"
    old.write_text("#!/bin/sh\necho 'nginx version: nginx/1.24.0 (Ubuntu)' >&2\n", "utf-8")
    old.chmod(0o755)
    monkeypatch.setattr(harness.shutil, "which", lambda name: str(old))

    assert harness.find_nginx_tools() == (
        "nginx 1.24.0 is older than 1.25.1, which the files in deploy/nginx/ need"
    )
