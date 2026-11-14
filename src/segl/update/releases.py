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

"""segl's releases on GitHub, and fetching their files.

``update_url`` is the releases API of segl's repository. The newest release
is ``<update_url>/releases/latest``, which leaves out drafts and
pre-releases, and one version is ``<update_url>/releases/tags/v<version>``.
A GitHub Enterprise server, or a mirror that answers the same two paths in
GitHub's shape, works the same way.

Requests go over HTTPS and check certificates against the system's own
store, so a CA that the site installed with ``update-ca-certificates`` is
trusted. They go through ``--proxy`` or ``update_proxy`` when one is set,
and through ``https_proxy`` from the environment otherwise.
"""

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from segl.update.versions import Version

DEFAULT_URL = "https://api.github.com/repos/robert-patrick-texas/segl"
# Debian and Ubuntu keep the trusted CAs here: one file with all of them, and
# a folder of links by hash. segl's own interpreter may look elsewhere.
CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")
CA_DIR = Path("/etc/ssl/certs")
# More than a release's description, or its package, will ever be. A longer
# answer is refused, not read.
MAX_ANSWER_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_BYTES = 500 * 1024 * 1024
TIMEOUT_SECONDS = 60
AGENT = "segl-update"
UNTRUSTED_HINT = (
    "if a firewall inspects TLS with a CA of its own, install that CA: copy it as a "
    ".crt file to /usr/local/share/ca-certificates/ and run `sudo update-ca-certificates`"
)


class ReleaseError(Exception):
    """A release cannot be found or fetched, or lacks a file."""


@dataclass(frozen=True)
class Release:
    """One release, and where its files are."""

    version: Version
    # File name to download URL.
    assets: dict[str, str]
    # The release notes' page, and the day it was published. Either may be empty.
    page: str = ""
    date: str = ""

    def url(self, name: str) -> str:
        """Return where to download one of the release's files.

        Raises:
            ReleaseError: When the release has no such file.
        """
        if name not in self.assets:
            raise ReleaseError(f"release {self.version.tag} has no {name}")
        return self.assets[name]


class Http(Protocol):
    """What the updater needs of HTTP. Tests give it a stand-in."""

    def get(self, url: str) -> bytes: ...

    def download(self, url: str, dest: Path) -> None: ...


def proxy_problem(url: str) -> str | None:
    """Return what is wrong with a proxy's URL, or None when it can be used."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return "expected http://HOST:PORT"
    if parts.scheme != "http":
        return "expected http://HOST:PORT (an http:// proxy that takes CONNECT)"
    if not parts.hostname or parts.path not in ("", "/") or parts.query or parts.fragment:
        return "expected http://HOST:PORT"
    if port is None:
        return "expected a port, as in http://HOST:PORT"
    return None


def shown_proxy(url: str) -> str:
    """Return a proxy's URL without the user name and password it may carry."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    host = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{host}" + (f":{parts.port}" if parts.port else "")


def tls_context(bundle: Path = CA_BUNDLE, folder: Path = CA_DIR) -> ssl.SSLContext:
    """Return a context that checks certificates and names against the system's CAs."""
    context = ssl.create_default_context()
    if bundle.is_file():
        context.load_verify_locations(cafile=str(bundle))
    if folder.is_dir():
        context.load_verify_locations(capath=str(folder))
    return context


class Https:
    """Fetches URLs over HTTPS, through a proxy when one is given."""

    def __init__(self, proxy: str = "", context: ssl.SSLContext | None = None) -> None:
        handlers: list[urllib.request.BaseHandler] = [
            urllib.request.HTTPSHandler(context=context or tls_context())
        ]
        if proxy:
            # Without this handler, urllib takes https_proxy from the environment.
            handlers.append(urllib.request.ProxyHandler({"https": proxy}))
        self._opener = urllib.request.build_opener(*handlers)

    def get(self, url: str) -> bytes:
        """Return a small answer's body.

        Raises:
            ReleaseError: When the host cannot be reached, its certificate is
                not trusted, the answer is an error or too long, or GitHub's
                rate limit is used up.
        """
        try:
            with self._open(url) as answer:
                body = answer.read(MAX_ANSWER_BYTES + 1)
        except OSError as exc:
            raise ReleaseError(f"{url}: {exc}") from exc
        if len(body) > MAX_ANSWER_BYTES:
            raise ReleaseError(f"{url}: the answer is longer than {MAX_ANSWER_BYTES} bytes")
        return body

    def download(self, url: str, dest: Path) -> None:
        """Write a file's bytes to ``dest``, which only then exists.

        Raises:
            ReleaseError: As ``get``, and when the file cannot be written.
        """
        part = dest.with_name(dest.name + ".part")
        written = 0
        try:
            with self._open(url) as answer, part.open("wb") as handle:
                while block := answer.read(1 << 20):
                    written += len(block)
                    if written > MAX_PACKAGE_BYTES:
                        raise ReleaseError(f"{url}: longer than {MAX_PACKAGE_BYTES} bytes")
                    handle.write(block)
            os.replace(part, dest)
        except OSError as exc:
            raise ReleaseError(f"{url}: {exc}") from exc
        finally:
            part.unlink(missing_ok=True)

    def _open(self, url: str) -> Any:
        if not url.startswith("https://"):
            raise ReleaseError(f"{url}: not an https:// URL")
        request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "*/*"})
        try:
            return self._opener.open(request, timeout=TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
                raise ReleaseError(_rate_limit(exc.headers.get("X-RateLimit-Reset"))) from exc
            raise ReleaseError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
        except (urllib.error.URLError, OSError) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise ReleaseError(
                    f"{url}: the certificate is not trusted ({reason.verify_message}); "
                    f"{UNTRUSTED_HINT}"
                ) from exc
            raise ReleaseError(f"{url}: {reason}") from exc


def _rate_limit(reset: str | None) -> str:
    said = "GitHub's rate limit for this address is used up"
    try:
        when = datetime.fromtimestamp(int(reset or ""), UTC)
    except ValueError, OverflowError, OSError:
        return said
    return f"{said}; it starts again at {when:%H:%M} UTC"


def release_url(base: str, version: Version | None) -> str:
    """Return the API address of the newest release, or of one version."""
    base = base.rstrip("/")
    return f"{base}/releases/latest" if version is None else f"{base}/releases/tags/{version.tag}"


def parse_release(data: object, source: str) -> Release:
    """Read a release as GitHub's API describes it.

    Raises:
        ReleaseError: When the description is not a release, or its tag is
            not a version.
    """
    if not isinstance(data, dict):
        raise ReleaseError(f"{source} did not describe a release")
    tag = str(data.get("tag_name") or "")
    try:
        version = Version.parse(tag)
    except ValueError:
        raise ReleaseError(f"{source}: the tag {tag!r} is not a version") from None
    assets = {
        str(asset["name"]): str(asset["browser_download_url"])
        for asset in data.get("assets") or []
        if isinstance(asset, dict) and asset.get("name") and asset.get("browser_download_url")
    }
    return Release(
        version=version,
        assets=assets,
        page=str(data.get("html_url") or ""),
        date=str(data.get("published_at") or "")[:10],
    )


def fetch_release(http: Http, base: str, version: Version | None = None) -> Release:
    """Ask for the newest release, or for one version.

    Raises:
        ReleaseError: When the API cannot be reached or does not describe a
            release. For a version it has none of, the message says so.
    """
    url = release_url(base, version)
    try:
        body = http.get(url)
    except ReleaseError as exc:
        if "HTTP 404" in str(exc):
            what = f"no release {version.tag}" if version else "no release yet"
            raise ReleaseError(f"{what} at {base}") from exc
        raise
    try:
        data = json.loads(body)
    except ValueError:
        raise ReleaseError(f"{url} did not answer with JSON") from None
    return parse_release(data, url)
