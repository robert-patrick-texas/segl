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

"""What the tests of ``segl update`` share: an installation in a folder, a
runner that plays apt, systemctl, and nginx, a stand-in for GitHub, and
releases signed with a throwaway key."""

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from segl.update.paths import Paths
from segl.update.process import RunResult, run_command
from segl.update.releases import ReleaseError
from segl.update.verify import SIG, SIGNER, SUMS
from segl.update.versions import Version

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
EXAMPLE = DEPLOY / "segl.toml.example"
API = "https://github.test/repos/example/segl"

Reply = int | RunResult | Callable[[Sequence[str]], RunResult]


def make_paths(folder: Path) -> Paths:
    """Lay an installation out under ``folder``, as the package does under /."""
    paths = Paths(
        config_file=folder / "opt/segl/etc/segl.toml",
        share=folder / "opt/segl/share",
        update_dir=folder / "opt/segl/update",
        binary=folder / "opt/segl/venv/bin/segl",
        nginx_dir=folder / "etc/nginx",
    )
    for made in (paths.etc, paths.share / "nginx", paths.nginx_dir, paths.binary.parent):
        made.mkdir(parents=True)
    paths.update_dir.mkdir(mode=0o700)
    (paths.nginx_dir / "conf.d").mkdir()
    (paths.nginx_dir / "snippets").mkdir()
    shutil.copy(EXAMPLE, paths.example)
    shutil.copy(EXAMPLE, paths.config_file)
    paths.config_file.chmod(0o640)
    for name, shipped, _ in paths.nginx_pairs():
        shutil.copy(DEPLOY / "nginx" / name, shipped)
    return paths


def install_nginx_files(paths: Paths) -> None:
    """Copy the package's nginx files to the site's places, as docs/DEPLOY.md says."""
    for _, shipped, site in paths.nginx_pairs():
        shutil.copy(shipped, site)


class ScriptedRunner:
    """Plays the programs an update runs, and records each call.

    ``replies`` maps the start of an argument list to an exit status, a
    result, or a function of the arguments. The longest match wins. ``diff3``
    and ``ssh-keygen`` run for real unless a reply names them. Anything else
    ends with status 0 and says nothing.
    """

    REAL = ("diff3", "ssh-keygen")

    def __init__(self, replies: Mapping[tuple[str, ...], Reply] | None = None) -> None:
        self.replies: dict[tuple[str, ...], Reply] = dict(replies or {})
        self.calls: list[list[str]] = []
        self.environments: list[Mapping[str, str] | None] = []

    def __call__(
        self,
        args: Sequence[str],
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
    ) -> RunResult:
        self.calls.append(list(args))
        self.environments.append(env)
        for prefix in sorted(self.replies, key=len, reverse=True):
            if tuple(args[: len(prefix)]) == prefix:
                reply = self.replies[prefix]
                if isinstance(reply, RunResult):
                    return reply
                if isinstance(reply, int):
                    return RunResult(reply, "")
                return reply(args)
        if args[0] in self.REAL:
            return run_command(args, stdin, env)
        return RunResult(0, "")

    def called(self, *prefix: str) -> list[list[str]]:
        """Return the recorded calls that start with ``prefix``."""
        return [call for call in self.calls if tuple(call[: len(prefix)]) == prefix]

    def order(self, *programs: str) -> list[str]:
        """Return the first words of the recorded calls, those in ``programs``."""
        return [call[0] for call in self.calls if call[0] in programs]


@dataclass
class Keys:
    """A throwaway release key, a signers file that trusts it, and a stranger's key."""

    release: Path
    signers: Path
    stranger: Path


def make_keys(folder: Path) -> Keys:
    """Make two keys with ssh-keygen, and a signers file for the first."""
    for name in ("release", "stranger"):
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(folder / name)],
            check=True,
        )
    public = (folder / "release.pub").read_text(encoding="utf-8").strip()
    signers = folder / "release-signers"
    signers.write_text(
        f'# A comment, as the shipped file has.\n{SIGNER} namespaces="{SIGNER}" {public}\n',
        encoding="utf-8",
    )
    return Keys(folder / "release", signers, folder / "stranger")


def sign(folder: Path, key: Path, namespace: str = SIGNER) -> None:
    """Write SHA256SUMS for the packages in ``folder``, and sign it with ``key``."""
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(folder.glob("*.deb"))
    ]
    (folder / SUMS).write_text("".join(lines), encoding="utf-8")
    (folder / SIG).unlink(missing_ok=True)
    subprocess.run(
        ["ssh-keygen", "-q", "-Y", "sign", "-f", str(key), "-n", namespace, str(folder / SUMS)],
        check=True,
        capture_output=True,
    )


def make_release(folder: Path, version: str, key: Path, body: bytes = b"") -> Path:
    """Make a signed release in ``folder/<version>``. The package is a few bytes."""
    home = folder / version
    home.mkdir(parents=True)
    package = home / Version.parse(version).package
    package.write_bytes(body or f"the package of segl {version}\n".encode())
    sign(home, key)
    return home


@dataclass
class FakeGitHub:
    """Answers the two release paths and the downloads, from folders of releases."""

    releases: dict[str, Path] = field(default_factory=dict)
    latest: str | None = None
    # A URL to an error to raise for it, for a host that cannot be reached.
    broken: dict[str, str] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)
    # The releases API it answers at, and the proxies it was reached through.
    api: str = API
    proxies: list[str] = field(default_factory=list)

    def add(self, home: Path, latest: bool = True) -> None:
        """Offer the release in ``home``, whose name is its version."""
        self.releases[home.name] = home
        if latest:
            self.latest = home.name

    def describe(self, version: str) -> dict[str, object]:
        """Return a release as GitHub's API describes it."""
        home = self.releases[version]
        return {
            "tag_name": f"v{version}",
            "html_url": f"https://github.test/example/segl/releases/tag/v{version}",
            "published_at": "2026-11-13T21:00:00Z",
            "assets": [
                {
                    "name": path.name,
                    "browser_download_url": f"https://github.test/files/{version}/{path.name}",
                }
                for path in sorted(home.iterdir())
            ],
        }

    def _body(self, url: str) -> bytes:
        self.asked.append(url)
        if url in self.broken:
            raise ReleaseError(f"{url}: {self.broken[url]}")
        if url == f"{self.api}/releases/latest" and self.latest is not None:
            return json.dumps(self.describe(self.latest)).encode()
        if url.startswith(f"{self.api}/releases/tags/v"):
            version = url.rsplit("/v", 1)[1]
            if version in self.releases:
                return json.dumps(self.describe(version)).encode()
        if url.startswith("https://github.test/files/"):
            version, name = url.removeprefix("https://github.test/files/").split("/")
            return (self.releases[version] / name).read_bytes()
        raise ReleaseError(f"{url}: HTTP 404 Not Found")

    def get(self, url: str) -> bytes:
        return self._body(url)

    def download(self, url: str, dest: Path) -> None:
        dest.write_bytes(self._body(url))
