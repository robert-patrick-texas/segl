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

"""Fixtures: a bootstrapped database, nginx for the tests that go through it,
and what the release-script tests need.

``repository`` is a SQLite file in the test's temporary folder, with the nine
slots. For the release script there are fakes and a throwaway git repository.

The fake runner stands in for ``uv``, ``gh``, ``cloc``, and ``git push``, and
runs other git commands for real against a work repository with a local bare
``origin``, as Sunstone's tools/release tests do. The fake sources stand in
for PyPI, npm, nodejs.org, and GitHub. No test uses the network.
"""

import json
import subprocess
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import harness
import pytest
from harness import NginxTools
from release_components import Component, LookupFailed, Sources
from release_proc import Result, Runner
from release_progress import Progress

from segl.repository import Repository

SHA_OLD = "a" * 40
SHA_NEW = "b" * 40

VERSIONS = """\
# Test manifest.
[project]
name = "segl"
version = "0.0.0"
license = "Apache-2.0"

[runtime]
python = "3.15.2"  # exact
node = ""

[python.dependencies]
good = "1.0.0"
bad = "1.0.0"

[python.dev]

[python.build]

[python.docs]
markdown-it-py = "4.3.0"

[web.dependencies]

[web.dev]

# [held.example]
[held]

[publish]
github = true
github_repo = "example/segl"
pypi = false
"""

PYPROJECT = """\
[project]
name = "segl"
version = "0.0.0"
requires-python = ">=3.15,<3.16"
dependencies = [
    "good==1.0.0",
    "bad==1.0.0",
]

[dependency-groups]
docs = ["markdown-it-py==4.3.0"]

[tool.ruff]
target-version = "py315"

[tool.ty.environment]
python-version = "3.15"
"""

MD2HTML = """\
# /// script
# dependencies = [
#     "markdown-it-py==4.3.0",
# ]
# ///
"""

WORKFLOW = f"""\
jobs:
  checks:
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@{SHA_OLD} # v10.3.3
"""

CHANGELOG = """\
# Changelog

## Unreleased

The first release. It serves a health route.

### New

- A health route.

### Fixed

- A typo.
"""

LATEST = {
    "python": "3.15.2",
    "good": "1.0.0",
    "bad": "1.0.0",
    "markdown-it-py": "4.3.0",
    "actions/checkout": "v7.0.1",
    "astral-sh/setup-uv": "v10.3.3",
}

Reply = str | Exception | Result | Callable[[Sequence[str]], Result]


@pytest.fixture(scope="session")
def tools() -> NginxTools:
    """nginx and openssl. Without them the test skips, or fails where nginx is required."""
    return harness.nginx_tools_or_skip()


@pytest.fixture(scope="session")
def certificate(tools: NginxTools, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """The test certificate for both site examples, and its key."""
    return harness.make_certificate(tools, tmp_path_factory.mktemp("certificate"))


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[Repository]:
    """A database in the test's folder, bootstrapped as segl does at startup."""
    with Repository(tmp_path / "segl.sqlite") as repository:
        repository.bootstrap()
        yield repository


class FakeRunner(Runner):
    """A runner that fakes chosen commands and runs the others for real.

    ``replies`` maps an argv prefix to canned output, an exception to raise,
    a result, or a function of the argv. ``calls`` records every argv.
    """

    def __init__(self, cwd: Path, replies: dict[tuple[str, ...], Reply] | None = None) -> None:
        super().__init__(cwd)
        self.replies: dict[tuple[str, ...], Reply] = {
            ("uv",): "",
            ("cloc",): json.dumps({"SUM": {"code": 1234}}),
            ("git", "push"): "",
            ("gh", "release"): "",
        }
        self.replies.update(replies or {})
        self.calls: list[list[str]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = True,
        capture: bool = True,
        stdin: str | None = None,
        progress: Progress | None = None,
    ) -> Result:
        self.calls.append(list(argv))
        # The longest matching prefix wins.
        for prefix in sorted(self.replies, key=len, reverse=True):
            if tuple(argv[: len(prefix)]) != prefix:
                continue
            reply = self.replies[prefix]
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, Result):
                result = reply
            elif isinstance(reply, str):
                result = Result(0, reply)
            else:
                result = reply(argv)
            # A canned command says its lines as a real one would.
            if progress is not None:
                for line in result.output.splitlines():
                    progress.line(line)
            return result
        # Always captured: a test has no terminal for a program to ask at.
        return super().run(argv, check=check, stdin=stdin, progress=progress)

    def called(self, *prefix: str) -> list[list[str]]:
        """Return the recorded calls that start with ``prefix``."""
        return [call for call in self.calls if tuple(call[: len(prefix)]) == prefix]


class FakeSources(Sources):
    """Sources that answer from a dictionary of name → newest release."""

    def __init__(self, runner: Runner, latest: dict[str, Any] | None = None) -> None:
        super().__init__(runner)
        self.newest: dict[str, Any] = {**LATEST, **(latest or {})}

    def latest(self, component: Component) -> str:
        found = self.newest.get(component.name)
        if found is None or isinstance(found, Exception):
            raise LookupFailed(str(found or "no answer"))
        return found

    def action_commit(self, repo: str, tag: str) -> str:
        return SHA_NEW


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` and return its standard output."""
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout


@pytest.fixture
def run_git() -> Callable[..., str]:
    """Provide ``git(repo, *args)``."""
    return git


@pytest.fixture
def git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep git away from the developer's configuration, and give it an identity."""
    settings = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Release Test",
        "GIT_AUTHOR_EMAIL": "release-test@example.invalid",
        "GIT_COMMITTER_NAME": "Release Test",
        "GIT_COMMITTER_EMAIL": "release-test@example.invalid",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Create a small project tree with versions.toml and its mirrors. No git."""
    root = tmp_path / "work"
    files = {
        "versions.toml": VERSIONS,
        "pyproject.toml": PYPROJECT,
        ".python-version": "3.15.2\n",
        "uv.lock": "version = 1\n",
        "CHANGELOG.md": CHANGELOG,
        "tools/md2html/md2html.py": MD2HTML,
        ".github/workflows/ci.yml": WORKFLOW,
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


@pytest.fixture
def repo(tree: Path, tmp_path: Path, git_env: None) -> Path:
    """Commit ``tree`` on ``main`` and push it to a local bare ``origin``."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(tree)], check=True)
    git(tree, "add", ".")
    git(tree, "commit", "-q", "-m", "initial")
    git(tree, "remote", "add", "origin", str(origin))
    git(tree, "push", "-q", "origin", "main")
    return tree


@pytest.fixture
def fake_runner() -> type[FakeRunner]:
    """Provide the ``FakeRunner`` class."""
    return FakeRunner


@pytest.fixture
def fake_sources() -> type[FakeSources]:
    """Provide the ``FakeSources`` class."""
    return FakeSources
