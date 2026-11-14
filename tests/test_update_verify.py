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

"""A release is installed only when its signature and its checksum check out.

``ssh-keygen`` runs for real, with keys made for the test.
"""

import shutil
from pathlib import Path

import pytest
from update_helpers import ROOT, Keys, make_keys, make_release, sign

from segl.update.process import run_command
from segl.update.verify import (
    SIG,
    SIGNER,
    SUMS,
    Artifacts,
    VerificationError,
    signer_keys,
    verify,
)
from segl.update.versions import Version

PACKAGE = Version.parse("9.0.2").package


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> Keys:
    return make_keys(tmp_path_factory.mktemp("keys"))


@pytest.fixture
def release(keys: Keys, tmp_path: Path) -> Artifacts:
    home = make_release(tmp_path, "9.0.2", keys.release)
    return Artifacts.in_folder(home, PACKAGE)


def test_a_release_signed_with_the_release_key_verifies(release: Artifacts, keys: Keys) -> None:
    assert release.complete()

    verify(release, keys.signers, run_command)


def test_a_package_changed_after_signing_is_refused(release: Artifacts, keys: Keys) -> None:
    with release.package.open("ab") as handle:
        handle.write(b"x")

    with pytest.raises(VerificationError, match=f"{PACKAGE} does not match its line in SHA256SUMS"):
        verify(release, keys.signers, run_command)


def test_checksums_changed_after_signing_are_refused(release: Artifacts, keys: Keys) -> None:
    # Someone who swaps the package must change its line too. The signature
    # is over that file, so it no longer verifies.
    with release.package.open("ab") as handle:
        handle.write(b"x")
    signature = release.sig.read_bytes()
    sign(release.package.parent, keys.stranger)
    release.sig.write_bytes(signature)

    with pytest.raises(VerificationError, match="the signature on SHA256SUMS did not verify"):
        verify(release, keys.signers, run_command)


def test_a_release_signed_by_another_key_is_refused(release: Artifacts, keys: Keys) -> None:
    sign(release.package.parent, keys.stranger)

    with pytest.raises(VerificationError, match="the signature on SHA256SUMS did not verify"):
        verify(release, keys.signers, run_command)


def test_a_signature_made_for_another_project_is_refused(release: Artifacts, keys: Keys) -> None:
    # The right key, and the namespace of another project's releases.
    sign(release.package.parent, keys.release, namespace="sunstone-release")

    with pytest.raises(VerificationError, match="did not verify"):
        verify(release, keys.signers, run_command)


def test_a_package_that_the_checksums_do_not_list_is_refused(
    release: Artifacts, keys: Keys
) -> None:
    other = release.package.with_name(Version.parse("9.0.3").package)
    shutil.copy(release.package, other)

    with pytest.raises(VerificationError, match=r"segl_9\.0\.3_amd64\.deb is not in SHA256SUMS"):
        verify(Artifacts(other, release.sums, release.sig), keys.signers, run_command)


@pytest.mark.parametrize("missing", ["package", "sums", "sig"])
def test_a_release_with_a_file_missing_is_refused(
    release: Artifacts, keys: Keys, missing: str
) -> None:
    getattr(release, missing).unlink()

    assert not release.complete()
    with pytest.raises(VerificationError, match="cannot read a file of the release"):
        verify(release, keys.signers, run_command)


def test_a_signers_file_with_no_key_refuses_everything(release: Artifacts, tmp_path: Path) -> None:
    empty = tmp_path / "release-signers"
    empty.write_text("# No key is listed yet.\n\n", encoding="utf-8")

    with pytest.raises(VerificationError, match="lists no key"):
        verify(release, empty, run_command)


def test_a_missing_signers_file_refuses_everything(release: Artifacts, tmp_path: Path) -> None:
    with pytest.raises(VerificationError, match="cannot read the release signers"):
        verify(release, tmp_path / "nowhere", run_command)


def test_a_host_without_ssh_keygen_refuses_everything(release: Artifacts, keys: Keys) -> None:
    def no_program(args, stdin=None, env=None):
        return run_command(["/nonexistent/ssh-keygen", *args[1:]], stdin, env)

    with pytest.raises(VerificationError, match="did not verify"):
        verify(release, keys.signers, no_program)


def test_the_signature_is_checked_against_the_bytes_of_the_checksums(
    release: Artifacts, keys: Keys
) -> None:
    calls = []

    def recording(args, stdin=None, env=None):
        calls.append((list(args), stdin))
        return run_command(args, stdin, env)

    verify(release, keys.signers, recording)

    ((args, stdin),) = calls
    assert args == [
        "ssh-keygen",
        "-Y",
        "verify",
        "-f",
        str(keys.signers),
        "-I",
        SIGNER,
        "-n",
        SIGNER,
        "-s",
        str(release.sig),
    ]
    assert stdin == release.sums.read_bytes()


def test_the_shipped_signers_file_is_in_ssh_keygens_form() -> None:
    # Every line that is not a comment names segl's principal and namespace.
    shipped = ROOT / "deploy" / "release-signers"

    for line in signer_keys(shipped):
        assert line.startswith(f'{SIGNER} namespaces="{SIGNER}" ssh-ed25519 '), line
    assert SUMS == "SHA256SUMS" and SIG == "SHA256SUMS.sig"
