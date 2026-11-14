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

"""Write ``SHA256SUMS`` for a release, sign it, and check the signature.

A server installs a release only when ``SHA256SUMS`` carries an SSH signature
from a key in the ``release-signers`` file of the package it runs, and the
package matches its line (``src/segl/update/verify.py``). ``publish`` makes
those two files here, and checks the signature against
``deploy/release-signers`` the way a server will, before it tags anything.
So a release that servers would refuse is never published.

The private key is named to ``ssh-keygen`` by its path and is never read
here. The pattern follows Sunstone's ``tools/release/release_artifacts.py``.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path

from release_proc import Runner

SUMS_NAME = "SHA256SUMS"
SIG_NAME = "SHA256SUMS.sig"
# The signature's namespace, and the principal in the signers file. The same
# two words are in src/segl/update/verify.py, and a test holds them together.
SIGNER = "segl-release"
SIGNERS = "deploy/release-signers"
# Beside the release keys of the sibling projects. Never in the repository.
DEFAULT_KEY = "~/.config/segl-release/release_ed25519"
KEY_VARIABLE = "SEGL_RELEASE_KEY"


def key_path(environment: Mapping[str, str] | None = None) -> Path:
    """Return where the private release key is: ``SEGL_RELEASE_KEY``, or the default."""
    environment = os.environ if environment is None else environment
    return Path(environment.get(KEY_VARIABLE) or DEFAULT_KEY).expanduser()


def signer_entries(signers: Path) -> int:
    """Count the keys in a signers file. Comments and blank lines are not keys."""
    if not signers.is_file():
        return 0
    lines = signers.read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#"))


def sha256_of(path: Path) -> str:
    """Return a file's SHA-256 as 64 hexadecimal characters."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_sums(files: list[Path], folder: Path) -> Path:
    """Write ``SHA256SUMS`` for ``files`` in ``sha256sum``'s format, by file name."""
    lines = [f"{sha256_of(path)}  {path.name}\n" for path in sorted(files, key=lambda p: p.name)]
    sums = folder / SUMS_NAME
    sums.write_text("".join(lines), encoding="utf-8")
    return sums


def sign(runner: Runner, key: Path, sums: Path) -> Path:
    """Sign ``SHA256SUMS`` with the release key, and return ``SHA256SUMS.sig``.

    ``ssh-keygen`` asks for the key's passphrase, so its output is not
    captured and the question reaches the terminal.

    Raises:
        release_proc.CommandError: When the signing fails.
    """
    signature = sums.with_name(SIG_NAME)
    # ssh-keygen asks before it writes over a signature that is there.
    signature.unlink(missing_ok=True)
    runner.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", SIGNER, str(sums)], capture=False)
    return signature


def verify(runner: Runner, signers: Path, sums: Path) -> tuple[bool, str]:
    """Check ``SHA256SUMS.sig`` as ``segl update`` does on a server.

    Returns:
        Whether the signature is good, and ssh-keygen's own line about it.
    """
    argv = ["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", SIGNER, "-n", SIGNER]
    argv += ["-s", str(sums.with_name(SIG_NAME))]
    result = runner.run(argv, check=False, stdin=sums.read_text(encoding="utf-8"))
    lines = result.output.strip().splitlines()
    return result.returncode == 0, lines[0] if lines else "ssh-keygen said nothing"
