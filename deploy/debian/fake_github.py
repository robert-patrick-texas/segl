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

"""A stand-in for GitHub's releases API, for deploy/debian/systemd-test.sh.

It serves, over HTTPS on localhost:8443, the two paths ``segl update`` asks
and the files of each release, in GitHub's shape. Its certificate comes from
the test's own CA, which the machine does not trust until the test installs
it: as with a firewall that inspects TLS.

/releases holds one folder to a release, with the package, SHA256SUMS, and
SHA256SUMS.sig. The newest release is the folder that /tmp/latest names, so
the test changes what is on offer by writing that file. A release is asked
for by version under the folder of that name. The install test runs this
with the package's own Python: the machine has no other.
"""

import http.server
import json
import re
import ssl
from pathlib import Path

ROOT = Path("/releases")
LATEST = Path("/tmp/latest")
ORIGIN = "https://localhost:8443"
REPOSITORY = "/repos/example/segl"
PACKAGE = re.compile(r"segl_(\d+\.\d+\.\d+)_amd64\.deb")


def describe(folder: str) -> dict[str, object] | None:
    """Return the release in a folder as GitHub's API describes one."""
    home = ROOT / folder
    names = sorted(path.name for path in home.iterdir()) if home.is_dir() else []
    versions = [found[1] for name in names if (found := PACKAGE.fullmatch(name))]
    if not versions:
        return None
    return {
        "tag_name": f"v{versions[0]}",
        "html_url": f"{ORIGIN}/example/segl/releases/tag/v{versions[0]}",
        "published_at": "2026-11-13T21:00:00Z",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": name, "browser_download_url": f"{ORIGIN}/files/{folder}/{name}"}
            for name in names
        ],
    }


class GitHub(http.server.BaseHTTPRequestHandler):
    """The newest release, one release by its tag, and each release's files."""

    def do_GET(self) -> None:
        release = None
        if self.path == f"{REPOSITORY}/releases/latest":
            release = describe(LATEST.read_text(encoding="utf-8").strip())
        elif self.path.startswith(f"{REPOSITORY}/releases/tags/v"):
            release = describe(self.path.rsplit("/v", 1)[1])
        elif self.path.startswith("/files/") and ".." not in self.path:
            path = ROOT / self.path.removeprefix("/files/")
            if path.is_file():
                self.answer(path.read_bytes())
                return
        if release is None:
            self.send_error(404)
            return
        self.answer(json.dumps(release).encode())

    def answer(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ROOT / "pki/server.pem", ROOT / "pki/server.key")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8443), GitHub)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
