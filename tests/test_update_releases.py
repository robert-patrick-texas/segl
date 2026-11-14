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

"""Asking for a release and fetching its files, over HTTPS and through a proxy.

A small HTTPS server on this host plays GitHub, with the test certificate,
and a small CONNECT proxy stands in for a site's own.
"""

import http.server
import json
import select
import socket
import socketserver
import ssl
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from harness import NginxTools
from update_helpers import API, FakeGitHub

from segl.update import releases
from segl.update.releases import (
    DEFAULT_URL,
    Https,
    Release,
    ReleaseError,
    fetch_release,
    parse_release,
    proxy_problem,
    release_url,
    shown_proxy,
)
from segl.update.versions import PACKAGE_NAME, Version

V = Version.parse


class _GitHub(http.server.BaseHTTPRequestHandler):
    """Answers a few paths, and records what each request sent."""

    def do_GET(self) -> None:
        site = cast(_Site, self.server)
        site.requests.append((self.path, dict(self.headers)))
        status, headers, body = site.routes.get(self.path, (404, {}, b"not found"))
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class _Site(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, certificate: tuple[Path, Path]) -> None:
        super().__init__(("127.0.0.1", 0), _GitHub)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*certificate)
        self.socket = context.wrap_socket(self.socket, server_side=True)
        self.routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    @property
    def base(self) -> str:
        # The certificate below is for this name.
        return f"https://localhost:{self.server_address[1]}"


class _Tunnel(socketserver.StreamRequestHandler):
    """A CONNECT proxy: it opens the tunnel and passes bytes both ways."""

    def handle(self) -> None:
        request = self.rfile.readline().decode()
        headers = {}
        while (line := self.rfile.readline().decode().strip()) != "":
            name, _, value = line.partition(":")
            headers[name.lower()] = value.strip()
        cast(_Proxy, self.server).seen.append((request.strip(), headers))
        _, target, _ = request.split()
        host, _, port = target.rpartition(":")
        with socket.create_connection((host, int(port))) as upstream:
            self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            self.wfile.flush()
            pair = [self.connection, upstream]
            while True:
                ready, _, _ = select.select(pair, [], [], 10)
                if not ready:
                    return
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)


class _Proxy(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Tunnel)
        self.seen: list[tuple[str, dict[str, str]]] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


@pytest.fixture(scope="module")
def certificate(tools: NginxTools, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A self-signed certificate for ``localhost``, and its key."""
    folder = tmp_path_factory.mktemp("github")
    certificate, key = folder / "github.crt", folder / "github.key"
    command = [tools.openssl, "req", "-x509", "-newkey", "ec"]
    command += ["-pkeyopt", "ec_paramgen_curve:prime256v1", "-noenc", "-days", "2"]
    command += ["-keyout", str(key), "-out", str(certificate), "-subj", "/CN=localhost"]
    command += ["-addext", "subjectAltName=DNS:localhost"]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return certificate, key


@pytest.fixture
def site(certificate: tuple[Path, Path]) -> Iterator[_Site]:
    server = _Site(certificate)
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.fixture
def proxy() -> Iterator[_Proxy]:
    server = _Proxy()
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.fixture
def trusting(certificate: tuple[Path, Path]) -> ssl.SSLContext:
    """A context that trusts the test certificate, as a host trusts its CAs."""
    return ssl.create_default_context(cafile=str(certificate[0]))


@pytest.fixture(autouse=True)
def no_proxy_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)


def test_get_returns_the_body_and_names_a_generic_client(
    site: _Site, trusting: ssl.SSLContext
) -> None:
    site.routes["/hello"] = (200, {}, b"the body")

    assert Https(context=trusting).get(f"{site.base}/hello") == b"the body"

    ((_, headers),) = site.requests
    assert headers["User-Agent"] == "segl-update"


def test_download_writes_the_file_and_leaves_no_part_behind(
    site: _Site, trusting: ssl.SSLContext, tmp_path: Path
) -> None:
    body = bytes(range(256)) * 9000  # more than one read
    site.routes["/files/package.deb"] = (200, {}, body)
    dest = tmp_path / "package.deb"

    Https(context=trusting).download(f"{site.base}/files/package.deb", dest)

    assert dest.read_bytes() == body
    assert sorted(path.name for path in tmp_path.iterdir()) == ["package.deb"]


def test_a_failed_download_leaves_nothing_behind(
    site: _Site, trusting: ssl.SSLContext, tmp_path: Path
) -> None:
    with pytest.raises(ReleaseError, match="HTTP 404"):
        Https(context=trusting).download(f"{site.base}/files/gone.deb", tmp_path / "gone.deb")

    assert list(tmp_path.iterdir()) == []


def test_a_download_follows_a_redirect_as_githubs_do(
    site: _Site, trusting: ssl.SSLContext, tmp_path: Path
) -> None:
    site.routes["/download/package.deb"] = (302, {"Location": f"{site.base}/objects/1"}, b"")
    site.routes["/objects/1"] = (200, {}, b"the package")

    Https(context=trusting).download(f"{site.base}/download/package.deb", tmp_path / "p.deb")

    assert (tmp_path / "p.deb").read_bytes() == b"the package"


@pytest.mark.parametrize("given", ["{url}", "{url}/"])
def test_a_proxy_carries_the_request(
    site: _Site, proxy: _Proxy, trusting: ssl.SSLContext, given: str
) -> None:
    site.routes["/hello"] = (200, {}, b"through the proxy")

    body = Https(given.format(url=proxy.url), trusting).get(f"{site.base}/hello")

    assert body == b"through the proxy"
    ((request, _),) = proxy.seen
    assert request == f"CONNECT localhost:{site.server_address[1]} HTTP/1.1"


def test_without_a_proxy_nothing_goes_through_one(
    site: _Site, proxy: _Proxy, trusting: ssl.SSLContext
) -> None:
    site.routes["/hello"] = (200, {}, b"direct")

    assert Https(context=trusting).get(f"{site.base}/hello") == b"direct"
    assert proxy.seen == []


def test_without_a_proxy_setting_the_environments_proxy_is_used(
    site: _Site, proxy: _Proxy, trusting: ssl.SSLContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    site.routes["/hello"] = (200, {}, b"by the environment")
    monkeypatch.setenv("https_proxy", proxy.url)

    assert Https(context=trusting).get(f"{site.base}/hello") == b"by the environment"
    assert len(proxy.seen) == 1


def test_a_proxy_that_was_given_wins_over_the_environments(
    site: _Site, proxy: _Proxy, trusting: ssl.SSLContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    site.routes["/hello"] = (200, {}, b"by the option")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")

    assert Https(proxy.url, trusting).get(f"{site.base}/hello") == b"by the option"
    assert len(proxy.seen) == 1


def test_a_proxys_user_and_password_go_to_the_proxy_alone(
    site: _Site, proxy: _Proxy, trusting: ssl.SSLContext
) -> None:
    site.routes["/hello"] = (200, {}, b"ok")
    port = proxy.server_address[1]

    Https(f"http://pat:s3cret@127.0.0.1:{port}", trusting).get(f"{site.base}/hello")

    ((_, headers),) = proxy.seen
    assert headers["proxy-authorization"].startswith("Basic ")
    ((_, sent),) = site.requests
    assert "Proxy-Authorization" not in sent


def test_a_proxy_that_is_not_there_is_an_error_that_names_the_address(
    site: _Site, trusting: ssl.SSLContext
) -> None:
    with pytest.raises(ReleaseError, match="/hello"):
        Https("http://127.0.0.1:9", trusting).get(f"{site.base}/hello")


def test_a_certificate_the_host_does_not_trust_is_refused_and_says_what_to_do(
    site: _Site, tmp_path: Path
) -> None:
    site.routes["/hello"] = (200, {}, b"never read")
    # A host whose CA store does not have the test certificate.
    strangers = releases.tls_context(tmp_path / "no-bundle", tmp_path / "no-folder")

    with pytest.raises(ReleaseError) as refused:
        Https(context=strangers).get(f"{site.base}/hello")

    said = str(refused.value)
    assert "the certificate is not trusted" in said
    assert "/usr/local/share/ca-certificates/" in said and "update-ca-certificates" in said
    assert site.requests == []


def test_the_context_trusts_a_ca_in_the_hosts_bundle(
    site: _Site, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    site.routes["/hello"] = (200, {}, b"trusted")
    # As after `update-ca-certificates`: the site's CA is in the one file.
    context = releases.tls_context(certificate[0], tmp_path / "no-folder")

    assert Https(context=context).get(f"{site.base}/hello") == b"trusted"
    assert context.verify_mode is ssl.CERT_REQUIRED and context.check_hostname


def test_a_name_the_certificate_is_not_for_is_refused(
    site: _Site, trusting: ssl.SSLContext
) -> None:
    with pytest.raises(ReleaseError, match="the certificate is not trusted"):
        Https(context=trusting).get(f"https://127.0.0.1:{site.server_address[1]}/hello")


@pytest.mark.parametrize("url", ["http://localhost/x", "file:///etc/passwd", "ftp://localhost/x"])
def test_only_https_addresses_are_asked(url: str, tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="not an https:// URL"):
        Https().get(url)
    with pytest.raises(ReleaseError, match="not an https:// URL"):
        Https().download(url, tmp_path / "x")


def test_an_answer_that_is_too_long_is_refused(
    site: _Site, trusting: ssl.SSLContext, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    site.routes["/long"] = (200, {}, b"x" * 2000)
    monkeypatch.setattr(releases, "MAX_ANSWER_BYTES", 1000)
    monkeypatch.setattr(releases, "MAX_PACKAGE_BYTES", 1000)

    with pytest.raises(ReleaseError, match="longer than 1000 bytes"):
        Https(context=trusting).get(f"{site.base}/long")
    with pytest.raises(ReleaseError, match="longer than 1000 bytes"):
        Https(context=trusting).download(f"{site.base}/long", tmp_path / "long")
    assert list(tmp_path.iterdir()) == []


def test_a_used_up_rate_limit_says_when_it_starts_again(
    site: _Site, trusting: ssl.SSLContext
) -> None:
    limited = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1794603600"}
    site.routes["/limited"] = (403, limited, b"{}")
    site.routes["/forbidden"] = (403, {}, b"{}")

    with pytest.raises(ReleaseError, match=r"rate limit .* starts again at 21:00 UTC"):
        Https(context=trusting).get(f"{site.base}/limited")
    with pytest.raises(ReleaseError, match="HTTP 403"):
        Https(context=trusting).get(f"{site.base}/forbidden")


def test_the_newest_release_and_one_version_have_their_own_addresses() -> None:
    assert release_url(DEFAULT_URL, None) == (
        "https://api.github.com/repos/robert-patrick-texas/segl/releases/latest"
    )
    assert release_url(DEFAULT_URL + "/", V("0.2.0")) == (
        "https://api.github.com/repos/robert-patrick-texas/segl/releases/tags/v0.2.0"
    )


def test_fetch_release_reads_githubs_description(tmp_path: Path) -> None:
    home = tmp_path / "9.0.2"
    home.mkdir()
    for name in ("segl_9.0.2_amd64.deb", "SHA256SUMS", "SHA256SUMS.sig"):
        (home / name).write_bytes(b"x")
    github = FakeGitHub()
    github.add(home)

    release = fetch_release(github, API)

    assert release.version == V("9.0.2")
    assert release.date == "2026-11-13"
    assert release.page.endswith("/releases/tag/v9.0.2")
    assert release.url("SHA256SUMS") == "https://github.test/files/9.0.2/SHA256SUMS"
    assert fetch_release(github, API, V("9.0.2")) == release
    with pytest.raises(ReleaseError, match=r"release v9\.0\.2 has no segl_9\.0\.3_amd64\.deb"):
        release.url("segl_9.0.3_amd64.deb")


def test_a_repository_with_no_release_says_so() -> None:
    github = FakeGitHub()

    with pytest.raises(ReleaseError, match=f"no release yet at {API}"):
        fetch_release(github, API)
    with pytest.raises(ReleaseError, match=rf"no release v9\.9\.9 at {API}"):
        fetch_release(github, API, V("9.9.9"))


def test_fetch_release_over_https_from_a_stand_in(site: _Site, trusting: ssl.SSLContext) -> None:
    described = {
        "tag_name": "v0.2.0",
        "draft": False,
        "assets": [{"name": "SHA256SUMS", "browser_download_url": f"{site.base}/files/SHA256SUMS"}],
    }
    site.routes["/repos/example/segl/releases/latest"] = (200, {}, json.dumps(described).encode())

    release = fetch_release(Https(context=trusting), f"{site.base}/repos/example/segl/")

    assert release == Release(V("0.2.0"), {"SHA256SUMS": f"{site.base}/files/SHA256SUMS"})


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (b"<html>a login page</html>", "did not answer with JSON"),
        (b"[]", "did not describe a release"),
        (b'{"tag_name": "nightly"}', "the tag 'nightly' is not a version"),
        (b'{"tag_name": "v0.2.0-rc.1"}', "is not a version"),
        (b"{}", "the tag '' is not a version"),
    ],
)
def test_an_answer_that_is_not_a_release_is_an_error(body: bytes, said: str) -> None:
    class Answers(FakeGitHub):
        def get(self, url: str) -> bytes:
            return body

    with pytest.raises(ReleaseError, match=said):
        fetch_release(Answers(), API)


def test_assets_without_a_name_or_an_address_are_left_out() -> None:
    release = parse_release(
        {
            "tag_name": "v0.2.0",
            "assets": [
                {"name": "a", "browser_download_url": "https://x/a"},
                {"name": "b"},
                {"browser_download_url": "https://x/c"},
                "not an asset",
            ],
        },
        "the test",
    )

    assert release.assets == {"a": "https://x/a"}


@pytest.mark.parametrize(
    "url",
    [
        "http://proxy.example.com:2025/",
        "http://proxy.example.com:3128",
        "http://10.1.2.3:8080",
        "http://[2001:db8::1]:3128",
        "http://pat:s3cret@proxy.example.com:3128",
    ],
)
def test_a_proxy_address_that_can_be_used(url: str) -> None:
    assert proxy_problem(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "proxy.example.com:3128",
        "https://proxy.example.com:3128",
        "socks5://proxy.example.com:1080",
        "http://proxy.example.com",
        "http://proxy.example.com:port",
        "http://proxy.example.com:3128/path",
        "http://proxy.example.com:3128/?x=1",
        "http://:3128",
        "http://",
    ],
)
def test_a_proxy_address_that_cannot_be_used(url: str) -> None:
    assert proxy_problem(url) is not None


def test_a_proxy_is_shown_without_its_user_and_password() -> None:
    assert shown_proxy("http://pat:s3cret@proxy.example.com:3128/") == (
        "http://proxy.example.com:3128"
    )
    assert shown_proxy("http://[2001:db8::1]:3128") == "http://[2001:db8::1]:3128"


def test_versions_order_by_their_numbers_and_refuse_anything_else() -> None:
    assert V("v0.10.0") > V("0.9.9") > V("0.9.1") > V("0.0.0")
    assert str(V("v1.2.3")) == "1.2.3" and V("1.2.3").tag == "v1.2.3"
    assert V("1.2.3").package == "segl_1.2.3_amd64.deb"
    assert PACKAGE_NAME.fullmatch("segl_1.2.3_amd64.deb")
    for text in ("1.2", "1.2.3.4", "1.2.3-rc.1", "1.2.3+upgrade", "", "latest", "1.2.x"):
        with pytest.raises(ValueError, match="is not a version"):
            V(text)
    for name in ("segl_1.2.3_arm64.deb", "segl_1.2.3+upgrade_amd64.deb", "xsegl_1.2.3_amd64.deb"):
        assert not PACKAGE_NAME.fullmatch(name)
