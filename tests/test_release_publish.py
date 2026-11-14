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

"""`notes`, `cut`, and `publish`: what is written, and every reason to stop."""

import datetime as dt
import hashlib
import json
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
import release
import release_notes
from release_proc import CommandError, Result
from release_publish import PACKAGE_TEST, bump_version, check_runs_pass, cut, publish
from release_sign import (
    KEY_VARIABLE,
    SIG_NAME,
    SIGNER,
    SIGNERS,
    SUMS_NAME,
    key_path,
    signer_entries,
)

from segl.update import verify

ROOT = Path(__file__).resolve().parents[1]

TODAY = dt.date(2026, 11, 12)
GREEN = {"check_runs": [{"name": "checks", "status": "completed", "conclusion": "success"}]}


def failing_pytest(argv: Sequence[str]) -> Result:
    if list(argv) == ["uv", "run", "pytest"]:
        return Result(1, "FAILED tests/test_health.py::test_health_answers_ok - boom\n")
    return Result(0)


def unchanged(root: Path) -> Callable[[], bool]:
    """Return a check that versions.toml and CHANGELOG.md are as they are now."""
    names = ("versions.toml", "CHANGELOG.md", "pyproject.toml")
    before = {name: (root / name).read_text() for name in names}
    return lambda: all((root / name).read_text() == text for name, text in before.items())


def cut_and_commit(root: Path, runner, sources, run_git) -> None:
    assert cut(root, runner, sources, TODAY) == 0
    run_git(root, "commit", "-q", "-am", "release 0.1.0")
    run_git(root, "push", "-q", "origin", "main")
    runner.calls.clear()


def test_version_steps() -> None:
    def topics(**bullets: list[str]) -> dict[str, list[str]]:
        return {name: [] for name in release_notes.TOPICS} | bullets

    assert bump_version("0.0.0", topics(Fixed=["x"])) == "0.1.0"
    assert bump_version("0.1.0", topics(New=["x"])) == "0.2.0"
    assert bump_version("0.1.0", topics(Changed=["x"])) == "0.2.0"
    assert bump_version("0.1.4", topics(Fixed=["x"])) == "0.1.5"
    with pytest.raises(SystemExit):
        bump_version("1.0", topics())


def test_cut_changes_nothing_when_the_gate_fails(
    tree: Path, fake_runner, fake_sources, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = fake_runner(tree)
    same = unchanged(tree)

    assert cut(tree, runner, fake_sources(runner, {"bad": "2.0.0"}), TODAY) == 1
    assert same()
    assert not runner.called("uv"), "the suite does not run once the gate has failed"
    assert "python bad 1.0.0: newer 2.0.0" in capsys.readouterr().out


def test_cut_changes_nothing_when_the_suite_fails(
    tree: Path, fake_runner, fake_sources, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = fake_runner(tree, {("uv",): failing_pytest})
    same = unchanged(tree)

    assert cut(tree, runner, fake_sources(runner), TODAY) == 1
    assert same()
    assert "tests/test_health.py::test_health_answers_ok" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("The first release. It serves a health route.", ""),
        ("The first release. It serves a health route.", "One. Two. Three. Four."),
        ("- A health route.\n", ""),
    ],
)
def test_cut_needs_a_summary_and_bullets(
    tree: Path, fake_runner, fake_sources, old: str, new: str
) -> None:
    changelog = tree / "CHANGELOG.md"
    text = changelog.read_text().replace(old, new)
    changelog.write_text(
        text.replace("- A typo.\n", "") if not new and old.startswith("-") else text
    )
    runner = fake_runner(tree)
    same = unchanged(tree)

    assert cut(tree, runner, fake_sources(runner), TODAY) == 1
    assert same()


def test_a_successful_cut_writes_the_version_and_the_changelog_section(
    tree: Path, fake_runner, fake_sources
) -> None:
    runner = fake_runner(tree)

    assert cut(tree, runner, fake_sources(runner), TODAY) == 0

    assert tomllib.loads((tree / "versions.toml").read_text())["project"]["version"] == "0.1.0"
    assert tomllib.loads((tree / "pyproject.toml").read_text())["project"]["version"] == "0.1.0"
    changelog = (tree / "CHANGELOG.md").read_text()
    assert "## Unreleased\n\n## 0.1.0 — 2026-11-12\n\nThe first release." in changelog
    summary, topics = release_notes.parse_section(changelog)
    assert not summary
    assert not any(topics.values()), "a fresh, empty Unreleased"
    _, topics = release_notes.parse_section(changelog, release_notes.version_heading("0.1.0"))
    assert topics["New"] == ["A health route."]
    assert runner.calls[-1] == ["uv", "lock"]
    # The next cut has nothing to release.
    assert cut(tree, runner, fake_sources(runner), TODAY) == 1


def test_notes_have_the_shape_in_the_manual(tree: Path, fake_runner) -> None:
    path = tree / "versions.toml"
    path.write_text(
        path.read_text().replace(
            "[held]\n",
            '[held]\n\n[held.bad]\nversion = "1.0.0"\nskipped = "2.0.0"\n'
            'reason = "tests/test_scene.py::test_reconcile"\nsince = "2026-11-12"\n',
        )
    )
    (tree / "uv.lock").write_text(
        '[[package]]\nname = "segl"\nversion = "0.0.0"\n\n[[package]]\nname = "good"\n'
        'version = "1.0.0"\n\n[[package]]\nname = "starlette"\nversion = "1.10.0"\n'
    )
    doc = tomllib.loads(path.read_text())

    body = release_notes.preview(tree, fake_runner(tree), doc)

    lines = body.splitlines()
    assert lines[0].startswith("## 0.0.0 — ")
    assert lines[2] == "The first release. It serves a health route."
    headings = [line for line in lines if line.startswith("### ")]
    assert headings == ["### New", "### Fixed", "### Additional Notes"], "Changed has no bullets"
    assert (
        "- Kept bad at 1.0.0. Version 2.0.0 failed tests/test_scene.py::test_reconcile. "
        "It is tried again when bad publishes a newer release." in lines
    )
    table = lines.index("| Item | Value |")
    assert lines[table + 2 : table + 6] == [
        "| Project lines of code | 1234 |",
        "| Python | 3.15.2 |",
        "| segl | 0.0.0 |",
        "| good | 1.0.0 |",
    ]
    assert "<summary>Python sub-dependencies (1)</summary>" in lines
    assert "| starlette | 1.10.0 |" in lines


def test_notes_command_prints_the_preview(
    tree: Path, monkeypatch: pytest.MonkeyPatch, fake_runner, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(release, "Runner", fake_runner)

    assert release.main(["notes"], root=tree) == 0

    captured = capsys.readouterr()
    assert "| Project lines of code | 1234 |" in captured.out
    assert "0.0.0, which is not a publishable release" in captured.err


def test_check_runs() -> None:
    assert check_runs_pass(GREEN) == (True, "1 check run(s) passed")
    assert check_runs_pass({"check_runs": []})[0] is False
    pending = {"check_runs": [{"name": "checks", "status": "in_progress", "conclusion": None}]}
    assert check_runs_pass(pending) == (False, "pending: checks")
    failed = {"check_runs": [{"name": "checks", "status": "completed", "conclusion": "failure"}]}
    assert check_runs_pass(failed) == (False, "failed: checks")


def test_publish_never_publishes_0_0_0(repo: Path, fake_runner, fake_sources, run_git) -> None:
    # Even with a section for it in the changelog and green checks.
    changelog = repo / "CHANGELOG.md"
    changelog.write_text(changelog.read_text() + "\n## 0.0.0 — 2026-11-12\n\n- Nothing.\n")
    run_git(repo, "commit", "-q", "-am", "section")
    runner = fake_runner(repo, {("gh", "api"): json.dumps(GREEN)})

    assert publish(repo, runner, fake_sources(runner)) == 1
    assert not runner.called("git", "tag")
    assert not runner.called("git", "push")
    assert not runner.called("gh")
    assert run_git(repo, "tag", "--list") == ""


def break_dirty(repo: Path, run_git) -> None:
    (repo / "stray.txt").write_text("x")


def break_branch(repo: Path, run_git) -> None:
    run_git(repo, "switch", "-q", "-c", "topic")


def break_section(repo: Path, run_git) -> None:
    changelog = repo / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text().replace("## 0.1.0 — 2026-11-12", "## 0.9.0 — 2026-11-12")
    )
    run_git(repo, "commit", "-q", "-am", "wrong section")


def break_local_tag(repo: Path, run_git) -> None:
    run_git(repo, "tag", "v0.1.0")


def break_remote_tag(repo: Path, run_git) -> None:
    run_git(repo, "tag", "v0.1.0")
    run_git(repo, "push", "-q", "origin", "v0.1.0")
    run_git(repo, "tag", "-d", "v0.1.0")


@pytest.fixture
def release_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway release key with no passphrase, where ``publish`` looks for one."""
    key = tmp_path / "keys" / "release_ed25519"
    key.parent.mkdir()
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(key)], check=True
    )
    monkeypatch.setenv(KEY_VARIABLE, str(key))
    return key


def signers_line(key: Path) -> str:
    public = key.with_name(key.name + ".pub").read_text(encoding="utf-8").strip()
    return f'{SIGNER} namespaces="{SIGNER}" {public}\n'


def add_package_test(repo: Path, run_git, signers: str | None = None) -> None:
    """Give the tree the install test, as a file the fake runner answers for,
    and a signers file that lists the test's release key."""
    script = repo / PACKAGE_TEST
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\n")
    if signers is None:
        signers = "# The test's key.\n" + signers_line(key_path())
    (repo / SIGNERS).write_text(signers, encoding="utf-8")
    (repo / ".git" / "info" / "exclude").write_text("dist/\n")
    run_git(repo, "add", PACKAGE_TEST, SIGNERS)
    run_git(repo, "commit", "-q", "-m", "the install test")
    run_git(repo, "push", "-q", "origin", "main")


def add_package_test_without_a_key(repo: Path, run_git) -> None:
    add_package_test(repo, run_git, signers="# No key is listed yet.\n\n")


def add_package_test_and_lose_the_key(repo: Path, run_git) -> None:
    add_package_test(repo, run_git)
    key_path().unlink()


@pytest.mark.parametrize(
    ("spoil", "replies", "latest", "failed"),
    [
        (break_dirty, {}, {}, "the working tree is clean"),
        (break_branch, {}, {}, "HEAD is on main"),
        (break_section, {}, {}, "CHANGELOG.md has a 0.1.0 section"),
        (break_local_tag, {}, {}, "tag v0.1.0 is new: the tag already exists locally"),
        (break_remote_tag, {}, {}, "tag v0.1.0 is new: the tag already exists on origin"),
        (
            None,
            {("gh", "api"): json.dumps({"check_runs": []})},
            {},
            "GitHub checks passed for HEAD",
        ),
        (
            None,
            {("gh", "api"): CommandError("gh: not logged in")},
            {},
            "GitHub checks passed for HEAD",
        ),
        (None, {}, {"good": "1.1.0"}, "every component is current or held"),
        (
            add_package_test_without_a_key,
            {(PACKAGE_TEST,): Result(0, "all checks passed\n")},
            {},
            "deploy/release-signers lists a key: add the release key's public half",
        ),
        (
            add_package_test_and_lose_the_key,
            {(PACKAGE_TEST,): Result(0, "all checks passed\n")},
            {},
            "the release key is there: no key at ",
        ),
        (
            add_package_test,
            {(PACKAGE_TEST,): Result(1, "the unit is not active\n")},
            {},
            "the package builds and installs: `deploy/debian/package-test.sh` failed",
        ),
        (
            add_package_test,
            {(PACKAGE_TEST,): Result(0, "all checks passed\n")},
            {},
            "the package builds and installs: dist/segl_0.1.0_amd64.deb was not built",
        ),
    ],
)
def test_publish_stops_at_each_preflight_failure(
    repo: Path,
    fake_runner,
    fake_sources,
    run_git,
    release_key: Path,
    capsys: pytest.CaptureFixture[str],
    spoil: Callable[..., None] | None,
    replies: dict,
    latest: dict,
    failed: str,
) -> None:
    runner = fake_runner(repo, {("gh", "api"): json.dumps(GREEN)})
    cut_and_commit(repo, runner, fake_sources(runner), run_git)
    if spoil:
        spoil(repo, run_git)
    runner.replies.update(replies)
    tags_before = run_git(repo, "tag", "--list")

    assert publish(repo, runner, fake_sources(runner, latest)) == 1

    out = capsys.readouterr().out
    assert f"FAIL {failed}" in out
    assert out.count("FAIL") == 1, "it stops at the first failure"
    assert out.rstrip().endswith("not published")
    assert not runner.called("git", "tag")
    assert not runner.called("git", "push")
    assert not runner.called("gh", "release")
    assert run_git(repo, "tag", "--list") == tags_before


def test_a_successful_publish_tags_and_creates_the_release_with_the_notes(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path
) -> None:
    seen: dict[str, str] = {}

    def gh_release(argv: Sequence[str]) -> Result:
        seen["notes"] = Path(argv[argv.index("--notes-file") + 1]).read_text()
        return Result(0)

    def package_test(argv: Sequence[str]) -> Result:
        # What the real script does: build this version's package into dist/.
        (repo / "dist" / "segl_0.1.0_amd64.deb").write_bytes(b"deb")
        return Result(0, "systemd-test: all checks passed\n")

    runner = fake_runner(
        repo,
        {
            ("gh", "api"): json.dumps(GREEN),
            ("gh", "release"): gh_release,
            (PACKAGE_TEST,): package_test,
        },
    )
    cut_and_commit(repo, runner, fake_sources(runner), run_git)
    add_package_test(repo, run_git)
    # A package of an older version, left in dist/ by an earlier build.
    (repo / "dist").mkdir()
    (repo / "dist" / "segl_0.0.9_amd64.deb").write_bytes(b"old")

    assert publish(repo, runner, fake_sources(runner)) == 0

    head = run_git(repo, "rev-parse", "HEAD").strip()
    assert run_git(repo, "rev-parse", "v0.1.0^{commit}").strip() == head
    assert run_git(repo, "cat-file", "-t", "v0.1.0").strip() == "tag", "an annotated tag"
    assert runner.called("git", "push") == [["git", "push", "origin", "v0.1.0"]]
    (create,) = runner.called("gh", "release")
    assert create[:8] == [
        "gh",
        "release",
        "create",
        "v0.1.0",
        "--verify-tag",
        "--repo",
        "example/segl",
        "--title",
    ]
    assert create[8] == "segl 0.1.0"
    dist = repo / "dist"
    assert create[-3:] == [
        str(dist / "segl_0.1.0_amd64.deb"),
        str(dist / "SHA256SUMS"),
        str(dist / "SHA256SUMS.sig"),
    ]
    assert [arg for arg in create if arg.endswith(".deb")] == [create[-3]], "that package alone"
    # The checksums list that package alone, and the signature over them
    # verifies as it will on a server: against the signers file of the tree.
    digest = hashlib.sha256(b"deb").hexdigest()
    assert (dist / "SHA256SUMS").read_text() == f"{digest}  segl_0.1.0_amd64.deb\n"
    check = ["ssh-keygen", "-Y", "verify", "-f", str(repo / SIGNERS), "-I", SIGNER, "-n", SIGNER]
    verified = subprocess.run(
        [*check, "-s", str(dist / "SHA256SUMS.sig")],
        input=(dist / "SHA256SUMS").read_bytes(),
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert seen["notes"].startswith(
        "The first release. It serves a health route.\n\n### New\n\n- A health route."
    )
    assert (
        "| Project lines of code | 1234 |\n| Python | 3.15.2 |\n| segl | 0.1.0 |" in seen["notes"]
    )
    steps = ([PACKAGE_TEST], ["ssh-keygen", "-Y"], ["git", "tag"], ["git", "push"])
    order = [call[:2] for call in runner.calls if call[:2] in (*steps, ["gh", "release"])]
    # Signed and checked before the tag, so a failure leaves nothing published.
    assert order == [
        [PACKAGE_TEST],
        ["ssh-keygen", "-Y"],
        ["ssh-keygen", "-Y"],
        ["git", "tag"],
        ["git", "push"],
        ["gh", "release"],
    ]
    assert [call[2] for call in runner.called("ssh-keygen", "-Y")] == ["sign", "verify"]
    assert not runner.called("uv", "publish"), "PyPI is off"


def test_a_signature_the_signers_file_does_not_vouch_for_is_not_published(
    repo: Path,
    fake_runner,
    fake_sources,
    run_git,
    release_key: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def package_test(argv: Sequence[str]) -> Result:
        (repo / "dist").mkdir(exist_ok=True)
        (repo / "dist" / "segl_0.1.0_amd64.deb").write_bytes(b"deb")
        return Result(0, "systemd-test: all checks passed\n")

    runner = fake_runner(repo, {("gh", "api"): json.dumps(GREEN), (PACKAGE_TEST,): package_test})
    cut_and_commit(repo, runner, fake_sources(runner), run_git)
    # The tree lists another key than the one that signs.
    other = tmp_path / "other"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "other", "-f", str(other)], check=True
    )
    add_package_test(repo, run_git, signers=signers_line(other))

    assert publish(repo, runner, fake_sources(runner)) == 1

    out = capsys.readouterr().out
    assert "not published: deploy/release-signers does not vouch for the signature" in out
    assert not runner.called("git", "tag")
    assert not runner.called("git", "push")
    assert not runner.called("gh", "release")
    assert run_git(repo, "tag", "--list") == ""


def test_the_release_key_is_looked_for_beside_the_sibling_projects_keys() -> None:
    assert key_path({}) == Path.home() / ".config/segl-release/release_ed25519"
    assert key_path({KEY_VARIABLE: "/media/key/release"}) == Path("/media/key/release")
    assert key_path({KEY_VARIABLE: ""}) == Path.home() / ".config/segl-release/release_ed25519"


def test_the_release_script_and_the_server_agree_on_the_signature(tmp_path: Path) -> None:
    # One signs and the other checks, in two programs that share no code.
    assert (SIGNER, SUMS_NAME, SIG_NAME) == (verify.SIGNER, verify.SUMS, verify.SIG)
    assert SIGNERS == "deploy/release-signers"
    empty = tmp_path / "signers"
    empty.write_text("# a comment\n\n   # another\n")
    assert signer_entries(empty) == 0
    assert signer_entries(tmp_path / "absent") == 0
    assert signer_entries(ROOT / SIGNERS) == len(verify.signer_keys(ROOT / SIGNERS))


def test_pypi_is_used_only_when_enabled(repo: Path, fake_runner, fake_sources, run_git) -> None:
    path = repo / "versions.toml"
    path.write_text(path.read_text().replace("pypi = false", "pypi = true"))
    run_git(repo, "commit", "-q", "-am", "enable pypi")
    runner = fake_runner(repo, {("gh", "api"): json.dumps(GREEN)})
    cut_and_commit(repo, runner, fake_sources(runner), run_git)

    assert publish(repo, runner, fake_sources(runner)) == 0
    assert runner.called("uv", "build")
    assert runner.called("uv", "publish")


def test_the_command_line_reaches_each_command(
    tree: Path, monkeypatch: pytest.MonkeyPatch, fake_runner, fake_sources
) -> None:
    monkeypatch.setattr(release, "Runner", fake_runner)
    monkeypatch.setattr(release, "Sources", fake_sources)

    assert release.main(["check", "--gate"], root=tree) == 0
    assert release.main(["upgrade"], root=tree) == 0
    assert release.main(["publish"], root=tree) == 1  # 0.0.0, and not a git repository
    assert release.main(["cut"], root=tree) == 0
    with pytest.raises(SystemExit):
        release.main(["cut", "--publish"], root=tree)
