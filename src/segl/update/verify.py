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

"""Check a release before anything is installed, as Sunstone's updater does.

``SHA256SUMS`` carries an SSH signature made with the release key.
``ssh-keygen -Y verify`` checks it against the signers file the installed
package ships. Then the package must match its line in ``SHA256SUMS``. If
either check fails, the update stops and nothing has changed.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from segl.update.process import Runner

# The signature's namespace, and the principal in the signers file. A
# signature made for another project's releases never passes for segl's.
SIGNER = "segl-release"
SUMS = "SHA256SUMS"
SIG = "SHA256SUMS.sig"


class VerificationError(Exception):
    """A release's signature or checksum does not check out."""


@dataclass(frozen=True)
class Artifacts:
    """A release's three files, side by side."""

    package: Path
    sums: Path
    sig: Path

    @classmethod
    def in_folder(cls, folder: Path, package: str) -> Self:
        """Return the three files of the release whose package is ``package``."""
        return cls(folder / package, folder / SUMS, folder / SIG)

    def complete(self) -> bool:
        """Return whether all three files are there."""
        return all(path.is_file() for path in (self.package, self.sums, self.sig))


def signer_keys(signers: Path) -> list[str]:
    """Return the key lines of a signers file, without comments and blank lines.

    Raises:
        VerificationError: When the file cannot be read.
    """
    try:
        text = signers.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise VerificationError(f"cannot read the release signers {signers}: {exc}") from exc
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def sha256(path: Path) -> str:
    """Return a file's SHA-256, read a megabyte at a time."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(artifacts: Artifacts, signers: Path, run: Runner) -> None:
    """Check a release's signature, then its package's checksum.

    Raises:
        VerificationError: When a file cannot be read, the signers file has
            no key, the signature does not verify against it, or the package
            is missing from ``SHA256SUMS`` or does not match its line.
    """
    if not signer_keys(signers):
        raise VerificationError(f"the release signers file {signers} lists no key")
    try:
        sums = artifacts.sums.read_bytes()
        digest = sha256(artifacts.package)
        artifacts.sig.stat()
    except OSError as exc:
        raise VerificationError(f"cannot read a file of the release: {exc}") from exc
    checked = run(
        [
            "ssh-keygen",
            "-Y",
            "verify",
            "-f",
            str(signers),
            "-I",
            SIGNER,
            "-n",
            SIGNER,
            "-s",
            str(artifacts.sig),
        ],
        sums,
        None,
    )
    if checked.code != 0:
        said = " ".join(checked.output.split()) or "no output"
        raise VerificationError(f"the signature on {SUMS} did not verify: {said}")
    name = artifacts.package.name
    for line in sums.decode(errors="replace").splitlines():
        expected, _, listed = line.partition("  ")
        if listed.lstrip("*") == name:
            if expected.lower() != digest:
                raise VerificationError(f"{name} does not match its line in {SUMS}")
            return
    raise VerificationError(f"{name} is not in {SUMS}")
