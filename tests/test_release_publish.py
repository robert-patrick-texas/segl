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
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
import release
import release_notes
from release_proc import CommandError, Result
from release_publish import (
    BUILD,
    PACKAGE_TEST,
    REAL_UPDATE,
    Preflight,
    bump_version,
    check_runs_pass,
    cut,
    previous_release,
    publish,
)
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


def digest_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class FakeGitHub:
    """GitHub's side of a release: what `gh release create` made, as the API serves it.

    It answers for origin's copy of the tag too, since the fake runner does
    not push: origin has the tag `publish` made here. ``latest`` and ``by_tag``
    change the release as each endpoint gives it, to spoil one of them.
    """

    TAG = "v0.1.0"

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.made: dict = {}
        self.latest: Callable[[dict], dict] = lambda release: release
        self.by_tag: Callable[[dict], dict] = lambda release: release

    def create(self, argv: Sequence[str]) -> Result:
        at = list(argv).index("--notes-file")
        files = [Path(arg) for arg in argv[at + 2 :]]
        self.made = {
            "tag_name": argv[3],
            "draft": False,
            "prerelease": False,
            "published_at": "2026-11-12T15:00:00Z",
            "body": Path(argv[at + 1]).read_text(),
            "assets": [{"name": path.name, "digest": digest_of(path)} for path in files],
        }
        return Result(0)

    def peeled(self, argv: Sequence[str]) -> Result:
        sha = git(self.repo, "rev-parse", f"{self.TAG}^{{commit}}").strip()
        return Result(0, f"{sha}\t{argv[-1]}\n")

    def replies(self) -> dict:
        api = "repos/example/segl/releases"
        return {
            ("gh", "release", "create"): self.create,
            ("gh", "api", f"{api}/latest"): lambda _: Result(
                0, json.dumps(self.latest(dict(self.made)))
            ),
            ("gh", "api", f"{api}/tags/{self.TAG}"): lambda _: Result(
                0, json.dumps(self.by_tag(dict(self.made)))
            ),
            ("git", "ls-remote", "--tags", "origin", f"refs/tags/{self.TAG}^{{}}"): self.peeled,
        }


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout


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
    tree: Path, fake_runner, fake_sources, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = fake_runner(tree)

    assert cut(tree, runner, fake_sources(runner), TODAY) == 0

    # It says what it is doing: the gate, then each command of the suite.
    # Outside a git checkout no tree is known to be good, so it is all of it.
    said = capsys.readouterr().out.splitlines()
    assert said[:5] == [
        "checking that every component is current",
        "running the suite",
        "no tree is known to be good here: running the whole suite",
        "  uv sync",
        "    0:00  uv sync: done",
    ]
    assert "  uv run pytest" in said
    assert said[-2] == "not a git checkout: the version change itself is not checked"
    assert said[-1].startswith("cut 0.1.0.")
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
    assert headings[-2:] == ["### Lines of code", "### Versions"]
    headings = headings[:-2]
    assert headings == ["### New", "### Fixed", "### Additional Notes"], "Changed has no bullets"
    assert (
        "- Kept bad at 1.0.0. Version 2.0.0 failed tests/test_scene.py::test_reconcile. "
        "It is tried again when bad publishes a newer release." in lines
    )
    # Two tables, each under a heading of its own: the lines of code, which
    # are this project's, and then the versions, which are mostly not.
    counted = lines.index("### Lines of code")
    assert lines[counted + 2 : counted + 7] == [
        "| Language | Files | Code | Comments | Product | Tests | Tooling |",
        "|---|--:|--:|--:|--:|--:|--:|",
        "| Python | 2 | 1,200 | 54 | 1,000 | 200 | - |",
        "| TypeScript | 1 | 34 | 2 | 34 | - | - |",
        "| **All** | **3** | **1,234** | **56** | **1,034** | **200** | **-** |",
    ]
    assert lines[counted + 8].startswith(
        "These lines of code are segl's own. They do not count the dependencies listed below."
    )
    assert lines[counted + 8].endswith("another 40 lines of Markdown in 1 files.")
    versions = lines.index("### Versions")
    assert versions == counted + 10
    assert lines[versions + 2 : versions + 7] == [
        "| Item | Version |",
        "|---|---|",
        "| Python | 3.15.2 |",
        "| segl | 0.0.0 |",
        "| good | 1.0.0 |",
    ]
    assert not any("lines of code |" in line for line in lines[versions:]), "not in this table"
    assert "<summary>Python sub-dependencies (1)</summary>" in lines
    assert "| starlette | 1.10.0 |" in lines


def test_notes_command_prints_the_preview(
    tree: Path, monkeypatch: pytest.MonkeyPatch, fake_runner, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(release, "Runner", fake_runner)

    assert release.main(["notes"], root=tree) == 0

    captured = capsys.readouterr()
    assert "| **All** | **3** | **1,234** | **56** | **1,034** | **200** | **-** |" in captured.out
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


def builds(repo: Path, version: str = "0.1.0") -> Callable[[Sequence[str]], Result]:
    """A package build that writes this version's package into dist/, as build-deb.sh does."""

    def build(argv: Sequence[str]) -> Result:
        assert list(argv[1:]) == ["dist"], argv
        (repo / "dist").mkdir(exist_ok=True)
        (repo / "dist" / f"segl_{version}_amd64.deb").write_bytes(b"deb")
        return Result(0, "==> lintian\n")

    return build


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
            {(BUILD,): Result(0, "==> lintian\n")},
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
    runner.replies[(BUILD,)] = builds(repo)
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
    repo: Path,
    fake_runner,
    fake_sources,
    run_git,
    release_key: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    github = FakeGitHub(repo)

    def package_test(argv: Sequence[str]) -> Result:
        # Given the package in dist/, which the build wrote.
        assert list(argv[1:]) == ["dist/segl_0.1.0_amd64.deb"]
        said = "== install\nPASS  the package installs with apt\n"
        return Result(0, said + "systemd-test: all checks passed\n")

    runner = fake_runner(
        repo,
        {
            ("gh", "api"): json.dumps(GREEN),
            (BUILD,): builds(repo),
            (PACKAGE_TEST,): package_test,
            **github.replies(),
        },
    )
    cut_and_commit(repo, runner, fake_sources(runner), run_git)
    add_package_test(repo, run_git)
    # A package of an older version, left in dist/ by an earlier build.
    (repo / "dist").mkdir()
    (repo / "dist" / "segl_0.0.9_amd64.deb").write_bytes(b"old")

    assert publish(repo, runner, fake_sources(runner)) == 0

    # The install test takes minutes: its steps are said as they come, between
    # the line that it started and the line that it passed.
    said = capsys.readouterr().out.splitlines()
    # No CI run is known here, so the install test runs here.
    start = said.index(
        "     the package builds and installs: no passed CI run for HEAD was found; "
        f"building it, then running `{PACKAGE_TEST}` on it"
    )
    assert said[start - 1].startswith("ok   the release key is there: ")
    assert said[start + 1 : start + 5] == [
        "    0:00  ==> lintian",
        "    0:00  == install",
        "    0:00  systemd-test: all checks passed",
        "ok   the package builds and installs: dist/segl_0.1.0_amd64.deb passed the install test",
    ]
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
    assert github.made["body"].startswith(
        "The first release. It serves a health route.\n\n### New\n\n- A health route."
    )
    assert (
        "| **All** | **3** | **1,234** | **56** | **1,034** | **200** | **-** |"
        in github.made["body"]
    )
    assert (
        "### Versions\n\n| Item | Version |\n|---|---|\n| Python | 3.15.2 |\n| segl | 0.1.0 |"
        in github.made["body"]
    )
    tested = [PACKAGE_TEST, "dist/segl_0.1.0_amd64.deb"]
    steps = ([BUILD, "dist"], tested, ["ssh-keygen", "-Y"], ["git", "tag"], ["git", "push"])
    order = [call[:2] for call in runner.calls if call[:2] in (*steps, ["gh", "release"])]
    # Built into dist/, tested, signed, and checked before the tag, so a
    # failure leaves nothing published.
    assert order == [
        [BUILD, "dist"],
        tested,
        ["ssh-keygen", "-Y"],
        ["ssh-keygen", "-Y"],
        ["git", "tag"],
        ["git", "push"],
        ["gh", "release"],
    ]
    assert [call[2] for call in runner.called("ssh-keygen", "-Y")] == ["sign", "verify"]
    assert not runner.called("uv", "publish"), "PyPI is off"
    # Then the release as GitHub serves it, and one line that says how it all went.
    sent = github.made["body"].rstrip()
    assert said[said.index("published v0.1.0 to example/segl") + 1 :] == [
        f"ok   tag v0.1.0 on origin is HEAD: {head[:7]}",
        "ok   releases/latest is v0.1.0: published 2026-11-12T15:00:00Z",
        "ok   the release has the files from dist/: "
        "segl_0.1.0_amd64.deb, SHA256SUMS, SHA256SUMS.sig",
        f"ok   the notes on GitHub are the notes sent: {len(sent):,} characters",
        "done: v0.1.0 is published, and every check passed",
    ]


def test_a_signature_the_signers_file_does_not_vouch_for_is_not_published(
    repo: Path,
    fake_runner,
    fake_sources,
    run_git,
    release_key: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = fake_runner(
        repo,
        {
            ("gh", "api"): json.dumps(GREEN),
            (BUILD,): builds(repo),
            (PACKAGE_TEST,): Result(0, "systemd-test: all checks passed\n"),
        },
    )
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
    github = FakeGitHub(repo)
    runner = fake_runner(repo, {("gh", "api"): json.dumps(GREEN), **github.replies()})
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


def head_of(repo: Path) -> str:
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def ci_passed_on(sha: str) -> Result:
    return Result(0, json.dumps([{"headSha": sha}]))


def test_a_cut_after_ci_passed_runs_no_suite_and_checks_the_version_change(
    repo: Path, fake_runner, fake_sources, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = fake_runner(repo, {("gh", "run", "list"): ci_passed_on(head_of(repo))})

    assert cut(repo, runner, fake_sources(runner), TODAY) == 0

    said = capsys.readouterr().out.splitlines()
    assert said[1:4] == [
        "running the suite",
        f"known good: CI passed on {head_of(repo)[:7]}. Changed since: 0 files",
        "nothing to run",
    ]
    assert "checking the version change to 0.1.0" in said
    # versions.toml, pyproject.toml, and CHANGELOG.md: the fake `uv lock` leaves uv.lock.
    assert "known good: the tree before the change. Changed since: 3 files" in said
    # The suite did not run before the change; the change's own checks did.
    assert runner.called("uv", "run", "pytest") == [["uv", "run", "pytest"]]
    assert runner.called("uv", "lock")
    assert said[-1].startswith("cut 0.1.0.")


def test_a_version_change_that_fails_its_checks_is_put_back(
    repo: Path, fake_runner, fake_sources, capsys: pytest.CaptureFixture[str]
) -> None:
    names = ("versions.toml", "pyproject.toml", "CHANGELOG.md", "uv.lock")
    before = {name: (repo / name).read_bytes() for name in names}

    def pytest_after_the_change(_argv: Sequence[str]) -> Result:
        moved = 'version = "0.1.0"' in (repo / "versions.toml").read_text()
        return Result(1, "FAILED tests/test_versions.py::test_version\n") if moved else Result(0)

    runner = fake_runner(
        repo,
        {
            ("gh", "run", "list"): ci_passed_on(head_of(repo)),
            ("uv", "lock"): lambda _argv: (repo / "uv.lock").write_text("moved\n") or Result(0),
            ("uv", "run", "pytest"): pytest_after_the_change,
        },
    )

    assert cut(repo, runner, fake_sources(runner), TODAY) == 1

    assert {name: (repo / name).read_bytes() for name in names} == before
    assert capsys.readouterr().out.splitlines()[-1] == (
        "not cut: the version change fails the suite "
        "(tests/test_versions.py::test_version); files put back"
    )


def ci_runs(*ids: int) -> Result:
    return Result(0, json.dumps([{"databaseId": run} for run in ids]))


@pytest.mark.parametrize(
    ("runs", "ci_bytes", "install_test", "detail"),
    [
        (ci_runs(77), b"deb", None, "is the package CI installed and tested (run 77)"),
        (ci_runs(77), b"other", ["dist/{name}"], "passed the install test"),
        (ci_runs(77), None, ["dist/{name}"], "passed the install test"),
        (ci_runs(), None, ["dist/{name}"], "passed the install test"),
        (Result(1, "", "gh: not logged in"), None, ["dist/{name}"], "passed the install test"),
    ],
    ids=["same-bytes", "other-bytes", "no-download", "no-run", "gh-fails"],
)
def test_the_install_test_runs_here_unless_ci_tested_the_same_bytes(
    repo: Path,
    fake_runner,
    fake_sources,
    run_git,
    release_key: Path,
    runs: Result,
    ci_bytes: bytes | None,
    install_test: list[str] | None,
    detail: str,
) -> None:
    add_package_test(repo, run_git)
    name = f"segl_{release.load_versions(repo)['project']['version']}_amd64.deb"

    def download(argv: Sequence[str]) -> Result:
        if ci_bytes is None:
            return Result(1, "", "no valid artifacts found to download")
        (Path(argv[argv.index("--dir") + 1]) / name).write_bytes(ci_bytes)
        return Result(0)

    def build(_argv: Sequence[str]) -> Result:
        (repo / "dist").mkdir(exist_ok=True)
        (repo / "dist" / name).write_bytes(b"deb")
        return Result(0, "==> lintian\n")

    def package_test(argv: Sequence[str]) -> Result:
        return Result(0, "== install\nsystemd-test: all checks passed\n")

    runner = fake_runner(
        repo,
        {
            ("gh", "run", "list"): runs,
            ("gh", "run", "download"): download,
            (BUILD,): build,
            (PACKAGE_TEST,): package_test,
        },
    )

    ok, said = Preflight(repo, runner, fake_sources(runner)).package()

    assert ok, said
    assert said == f"dist/{name} {detail}"
    tests = [call[1:] for call in runner.called(PACKAGE_TEST)]
    if install_test is None:
        assert tests == [], "CI's test of the same bytes stands"
    else:
        assert tests == [[arg.format(name=name) for arg in install_test]]
    if runs.returncode == 0 and json.loads(runs.stdout):
        (listed,) = runner.called("gh", "run", "list")
        assert listed[listed.index("--commit") + 1] == run_git(repo, "rev-parse", "HEAD").strip()
        assert "--status" in listed and "success" in listed
    # Built into dist/ each time, on purpose: the install test, given no
    # package, would build one elsewhere.
    assert runner.called(BUILD) == [[BUILD, "dist"]]


def test_a_package_that_does_not_build_stops_the_preflight(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path
) -> None:
    add_package_test(repo, run_git)
    name = f"segl_{release.load_versions(repo)['project']['version']}_amd64.deb"

    def download(argv: Sequence[str]) -> Result:
        (Path(argv[argv.index("--dir") + 1]) / name).write_bytes(b"deb")
        return Result(0)

    runner = fake_runner(
        repo,
        {
            ("gh", "run", "list"): ci_runs(77),
            ("gh", "run", "download"): download,
            (BUILD,): Result(1, "lintian: E: bad\n"),
        },
    )

    assert Preflight(repo, runner, fake_sources(runner)).package() == (False, f"`{BUILD}` failed")
    assert not runner.called(PACKAGE_TEST)


def add_real_update(repo: Path, run_git) -> None:
    """Give the tree the check of the update from an earlier release."""
    (repo / REAL_UPDATE).write_text("#!/bin/bash\n")
    run_git(repo, "add", REAL_UPDATE)
    run_git(repo, "commit", "-q", "-m", "the update check")
    run_git(repo, "push", "-q", "origin", "main")


def releases(*tags: str) -> Result:
    """What `gh release list` answers: the newest first."""
    rows = [
        {"tagName": tag, "publishedAt": f"2026-11-0{9 - n}T00:00:00Z"} for n, tag in enumerate(tags)
    ]
    return Result(0, json.dumps(rows))


def publishable(
    repo: Path, fake_runner, fake_sources, run_git, replies: dict, github: FakeGitHub | None = None
):
    """Cut 0.1.0 in ``repo``, with the install test and the update check, ready to publish."""

    github = github or FakeGitHub(repo)
    runner = fake_runner(
        repo,
        {
            ("gh", "api"): json.dumps(GREEN),
            (BUILD,): builds(repo),
            (PACKAGE_TEST,): Result(0, "systemd-test: all checks passed\n"),
            **github.replies(),
            **replies,
        },
    )
    cut_and_commit(repo, runner, fake_sources(runner), run_git)
    add_package_test(repo, run_git)
    add_real_update(repo, run_git)
    return runner


PASSED = Result(0, "== the site\nPASS  it works\n== summary\nreal-update: all 39 checks passed\n")


def test_publish_checks_the_update_from_the_last_release_before_the_tag_and_from_github_after(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path, capsys
) -> None:
    runner = publishable(
        repo,
        fake_runner,
        fake_sources,
        run_git,
        {("gh", "release", "list"): releases("v0.0.9", "v0.0.8"), (REAL_UPDATE,): PASSED},
    )

    assert publish(repo, runner, fake_sources(runner)) == 0

    assert [call[1:] for call in runner.called(REAL_UPDATE)] == [["v0.0.9", "dist"], ["v0.0.9"]]

    # Signed, then checked with the signed files, then tagged and released,
    # then checked from GitHub.
    def at(*prefix: str) -> int:
        return next(n for n, call in enumerate(runner.calls) if call[: len(prefix)] == [*prefix])

    first, last = [n for n, call in enumerate(runner.calls) if call[0] == REAL_UPDATE]
    verify = at("ssh-keygen", "-Y", "verify")
    assert verify < first < at("git", "tag") < at("gh", "release", "create") < last
    out = capsys.readouterr().out.splitlines()
    assert f"     v0.0.9 updates to 0.1.0: running `{REAL_UPDATE} v0.0.9 dist`" in out
    assert "    0:00  real-update: all 39 checks passed" in out
    assert "ok   v0.0.9 updates to 0.1.0, from the signed files: all 39 checks passed" in out
    assert out[-2:] == [
        "ok   a server on v0.0.9 takes 0.1.0 from GitHub: all 39 checks passed",
        "done: v0.1.0 is published, and every check passed",
    ]


def test_a_release_the_last_one_does_not_update_to_is_not_published(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path, capsys
) -> None:
    failed = Result(1, "FAIL  it says what it did\nreal-update: 1 of 39 checks FAILED\n")
    runner = publishable(
        repo,
        fake_runner,
        fake_sources,
        run_git,
        {("gh", "release", "list"): releases("v0.0.9"), (REAL_UPDATE,): failed},
    )

    assert publish(repo, runner, fake_sources(runner)) == 1

    assert not runner.called("git", "tag")
    assert not runner.called("gh", "release", "create")
    assert capsys.readouterr().out.splitlines()[-1] == (
        "not published: v0.0.9 does not update to 0.1.0 (real-update: 1 of 39 checks FAILED)"
    )


def test_the_first_release_has_no_update_to_check(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path, capsys
) -> None:
    runner = publishable(
        repo, fake_runner, fake_sources, run_git, {("gh", "release", "list"): releases()}
    )

    assert publish(repo, runner, fake_sources(runner)) == 0

    assert not runner.called(REAL_UPDATE)
    assert "ok   no earlier release is on GitHub: no update from one to check" in (
        capsys.readouterr().out.splitlines()
    )


def test_a_release_a_server_cannot_take_from_github_is_said_and_fails(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path, capsys
) -> None:
    def from_github_fails(argv: Sequence[str]) -> Result:
        return PASSED if "dist" in argv else Result(1, "real-update: 2 of 45 checks FAILED\n")

    runner = publishable(
        repo,
        fake_runner,
        fake_sources,
        run_git,
        {("gh", "release", "list"): releases("v0.0.9"), (REAL_UPDATE,): from_github_fails},
    )

    assert publish(repo, runner, fake_sources(runner)) == 1

    assert runner.called("gh", "release", "create"), "it was published"
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "FAIL a server on v0.0.9 takes 0.1.0 from GitHub: real-update: 2 of 45 checks FAILED",
        "done: v0.1.0 is published, but 1 of 5 checks after it failed",
    ]


def test_releases_that_cannot_be_listed_stop_publish_before_the_tag(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path, capsys
) -> None:
    runner = publishable(
        repo, fake_runner, fake_sources, run_git, {("gh", "release", "list"): "not json"}
    )

    assert publish(repo, runner, fake_sources(runner)) == 1

    assert not runner.called("git", "tag")
    assert (
        capsys.readouterr()
        .out.splitlines()[-1]
        .startswith("not published: the releases on GitHub cannot be listed")
    )


def test_the_last_release_is_the_newest_other_than_this_one(repo: Path, fake_runner) -> None:
    newest_first = releases("v0.1.0", "v0.0.9", "v0.0.8")
    runner = fake_runner(repo, {("gh", "release", "list"): newest_first})

    assert previous_release(runner, "example/segl", "v0.1.0") == "v0.0.9"
    assert previous_release(runner, "example/segl", "v0.2.0") == "v0.1.0"
    (listed, _) = runner.called("gh", "release", "list")
    assert "--exclude-drafts" in listed and "--exclude-pre-releases" in listed


PEELED = ("git", "ls-remote", "--tags", "origin", "refs/tags/v0.1.0^{}")
LATEST = ("gh", "api", "repos/example/segl/releases/latest")


def without_sig(release: dict) -> dict:
    return {**release, "assets": [a for a in release["assets"] if a["name"] != SIG_NAME]}


def other_deb(release: dict) -> dict:
    def spoil(asset: dict) -> dict:
        return (
            {**asset, "digest": "sha256:" + "0" * 64} if asset["name"].endswith(".deb") else asset
        )

    return {**release, "assets": [spoil(a) for a in release["assets"]]}


@pytest.mark.parametrize(
    ("spoil", "failed"),
    [
        (
            lambda r, g: r.replies.update({PEELED: ""}),
            "tag v0.1.0 on origin is HEAD: origin has no",
        ),
        (
            lambda r, g: r.replies.update({PEELED: f"{'c' * 40}\trefs/tags/v0.1.0^{{}}\n"}),
            "tag v0.1.0 on origin is HEAD: it is on ccccccc, and HEAD is ",
        ),
        (
            lambda r, g: setattr(g, "latest", lambda rel: {**rel, "tag_name": "v0.0.9"}),
            "releases/latest is v0.1.0: it is v0.0.9",
        ),
        (
            lambda r, g: r.replies.update({LATEST: CommandError("gh api exited: HTTP 502")}),
            "releases/latest is v0.1.0: gh api exited: HTTP 502",
        ),
        (
            lambda r, g: r.replies.update({LATEST: "<html>"}),
            "releases/latest is v0.1.0: releases/latest gave no JSON",
        ),
        (
            lambda r, g: setattr(g, "by_tag", without_sig),
            "the release has the files from dist/: missing SHA256SUMS.sig",
        ),
        (
            lambda r, g: setattr(g, "by_tag", other_deb),
            "the release has the files from dist/: not the bytes in dist/: segl_0.1.0_amd64.deb",
        ),
        (
            lambda r, g: setattr(
                g, "by_tag", lambda rel: {**rel, "assets": [*rel["assets"], {"name": "x.txt"}]}
            ),
            "the release has the files from dist/: not sent: x.txt",
        ),
        (
            lambda r, g: setattr(
                g, "by_tag", lambda rel: {**rel, "body": "Other.\n" + rel["body"]}
            ),
            "the notes on GitHub are the notes sent: line 1 differs",
        ),
        (
            lambda r, g: setattr(
                g, "by_tag", lambda rel: {**rel, "body": "\n".join(rel["body"].splitlines()[:3])}
            ),
            "the notes on GitHub are the notes sent: GitHub's notes are longer or shorter",
        ),
    ],
    ids=[
        "no-tag",
        "tag-elsewhere",
        "latest-older",
        "latest-unasked",
        "latest-not-json",
        "file-missing",
        "file-other-bytes",
        "file-extra",
        "notes-differ",
        "notes-cut",
    ],
)
def test_a_check_after_the_release_that_fails_is_said_and_the_others_still_run(
    repo: Path,
    fake_runner,
    fake_sources,
    run_git,
    release_key: Path,
    capsys,
    spoil: Callable[..., None],
    failed: str,
) -> None:
    github = FakeGitHub(repo)
    runner = publishable(
        repo,
        fake_runner,
        fake_sources,
        run_git,
        {("gh", "release", "list"): releases("v0.0.9"), (REAL_UPDATE,): PASSED},
        github,
    )
    spoil(runner, github)

    assert publish(repo, runner, fake_sources(runner)) == 1

    out = capsys.readouterr().out.splitlines()
    (line,) = [said for said in out if said.startswith("FAIL")]
    assert line.startswith(f"FAIL {failed}")
    # The release is out: the checks after the failed one still ran.
    after = out[out.index("published v0.1.0 to example/segl") + 1 :]
    assert len([said for said in after if said.startswith(("ok   ", "FAIL "))]) == 5
    assert len(runner.called(REAL_UPDATE)) == 2
    assert out[-2] == "ok   a server on v0.0.9 takes 0.1.0 from GitHub: all 39 checks passed"
    assert out[-1] == "done: v0.1.0 is published, but 1 of 5 checks after it failed"


def test_notes_that_github_ends_its_own_way_are_the_notes_sent(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path, capsys
) -> None:
    github = FakeGitHub(repo)
    github.by_tag = lambda rel: {**rel, "body": rel["body"].replace("\n", "\r\n") + "\r\n\r\n"}
    runner = publishable(
        repo, fake_runner, fake_sources, run_git, {("gh", "release", "list"): releases()}, github
    )

    assert publish(repo, runner, fake_sources(runner)) == 0

    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("ok   the notes on GitHub are the notes sent: ") for line in out)


def test_publish_keeps_all_it_prints_in_a_log_and_adds_each_run(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path, capsys
) -> None:
    runner = publishable(
        repo,
        fake_runner,
        fake_sources,
        run_git,
        {("gh", "release", "list"): releases("v0.0.9"), (REAL_UPDATE,): PASSED},
    )
    capsys.readouterr()  # what `cut` said
    zone = dt.timezone(dt.timedelta(hours=-5))
    terminal = sys.stdout
    head = run_git(repo, "rev-parse", "--short", "HEAD").strip()
    log = repo / "dist" / "publish-0.1.0.log"

    assert (
        publish(repo, runner, fake_sources(runner), dt.datetime(2026, 11, 12, 10, tzinfo=zone)) == 0
    )

    assert sys.stdout is terminal
    first = capsys.readouterr().out
    assert first.splitlines()[0] == "     log: dist/publish-0.1.0.log"
    assert first.rstrip().endswith("done: v0.1.0 is published, and every check passed")
    header = f"== publish 0.1.0 at 2026-11-12T10:00:00-05:00, HEAD {head}\n"
    assert log.read_text() == header + first

    # Run again: the log in dist/ leaves the tree clean, and the tag stops it.
    assert (
        publish(repo, runner, fake_sources(runner), dt.datetime(2026, 11, 12, 11, tzinfo=zone)) == 1
    )

    second = capsys.readouterr().out
    assert "ok   the working tree is clean: 0 changed or untracked path(s)" in second
    assert second.rstrip().endswith("not published")
    again = f"== publish 0.1.0 at 2026-11-12T11:00:00-05:00, HEAD {head}\n"
    assert log.read_text() == header + first + again + second


def test_an_error_that_ends_publish_is_in_its_log(
    repo: Path, fake_runner, fake_sources, run_git, release_key: Path, capsys
) -> None:
    refused = CommandError("gh release create exited with status 1: HTTP 422")
    runner = publishable(
        repo,
        fake_runner,
        fake_sources,
        run_git,
        {("gh", "release", "list"): releases(), ("gh", "release", "create"): refused},
    )
    capsys.readouterr()  # what `cut` said
    terminal = sys.stdout

    with pytest.raises(CommandError):
        publish(repo, runner, fake_sources(runner))

    assert sys.stdout is terminal
    written = (repo / "dist" / "publish-0.1.0.log").read_text()
    assert capsys.readouterr().out in written
    assert written.rstrip().endswith(
        "CommandError: gh release create exited with status 1: HTTP 422"
    )
