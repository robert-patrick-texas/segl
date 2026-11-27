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

"""`upgrade`: one move at a time, kept when the suite passes, held when it fails."""

import datetime as dt
import json
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from release_components import LookupFailed
from release_proc import Result
from release_upgrade import NARROW_PYTHON, NARROW_WEB, suite_commands, upgrade
from suite import recorded_pass, step_of, work_tree

TODAY = dt.date(2026, 11, 12)


def pytest_failure(test: str) -> Result:
    """Return what a failing ``uv run pytest`` prints for one failed test."""
    summary = f"=========== short test summary info ===========\nFAILED {test} - assert 1 == 2\n"
    return Result(1, summary + "=========== 1 failed, 57 passed in 2.10s ===========\n")


def suite_that_fails_on(root: Path, text: str) -> Callable[[Sequence[str]], Result]:
    """Return a fake ``uv`` whose pytest fails while versions.toml contains ``text``."""

    def reply(argv: Sequence[str]) -> Result:
        failing = text in (root / "versions.toml").read_text()
        if failing and list(argv) == ["uv", "run", "pytest"]:
            return pytest_failure("tests/test_scene.py::test_reconcile")
        return Result(0)

    return reply


def versions(root: Path) -> dict:
    return tomllib.loads((root / "versions.toml").read_text())


def add_tool(root: Path, name: str, version: str) -> None:
    """Pin a development tool in the tree, as versions.toml and pyproject.toml do."""
    path = root / "versions.toml"
    path.write_text(
        path.read_text().replace("[python.dev]\n", f'[python.dev]\n{name} = "{version}"\n')
    )
    path = root / "pyproject.toml"
    path.write_text(
        path.read_text().replace(
            "[dependency-groups]\n", f'[dependency-groups]\ndev = ["{name}=={version}"]\n'
        )
    )


def commands(runner) -> list[str]:
    """Return every command the runner was given, each as one line.

    The commands of one stage run side by side (scripts/suite.py), so the
    order they were called in is not fixed. Each run of one stage is sorted.
    """
    staged: list[str] = []
    run: list[str] = []
    last = None
    for argv in runner.calls:
        stage = step_of(argv).stage
        if stage != last:
            staged += sorted(run)
            run, last = [], stage
        run.append(" ".join(argv))
    return staged + sorted(run)


def in_stages(lines: Sequence[str]) -> list[str]:
    """Return expected commands with each run of one stage sorted, as `commands` does."""
    staged: list[str] = []
    run: list[str] = []
    last = None
    for line in lines:
        stage = step_of(line.split(" ")).stage
        if stage != last:
            staged += sorted(run)
            run, last = [], stage
        run.append(line)
    return staged + sorted(run)


def test_upgrade_holds_the_component_that_fails_and_keeps_the_others(
    tree: Path, fake_runner, fake_sources
) -> None:
    runner = fake_runner(tree, {("uv",): suite_that_fails_on(tree, 'bad = "2.0.0"')})
    sources = fake_sources(runner, {"good": "1.1.0", "bad": "2.0.0", "markdown-it-py": "4.4.0"})
    before = (tree / "pyproject.toml").read_text()

    assert upgrade(tree, runner, sources, TODAY) == 0

    doc = versions(tree)
    assert doc["python"]["dependencies"] == {"good": "1.1.0", "bad": "1.0.0"}
    assert doc["python"]["docs"] == {"markdown-it-py": "4.4.0"}
    assert doc["held"] == {
        "bad": {
            "version": "1.0.0",
            "skipped": "2.0.0",
            "reason": "tests/test_scene.py::test_reconcile",
            "since": "2026-11-12",
        }
    }
    pyproject = (tree / "pyproject.toml").read_text()
    assert pyproject == before.replace("good==1.0.0", "good==1.1.0").replace(
        "markdown-it-py==4.3.0", "markdown-it-py==4.4.0"
    )
    # A [python.docs] move also updates md2html's inline metadata.
    assert '#     "markdown-it-py==4.4.0",' in (tree / "tools/md2html/md2html.py").read_text()
    # pytest ran five times: for md2html's package, whose move only pytest
    # covers, then for the two dependencies together, which failed, for the
    # tree as it was, and for each of the two alone. `uv sync` ran last, to
    # put the environment back on the kept pin.
    assert len(runner.called("uv", "run", "pytest")) == 5
    assert runner.calls[-1] == ["uv", "sync"]


def test_moves_that_all_pass_cost_one_run_of_the_suite(
    tree: Path, fake_runner, fake_sources, capsys
) -> None:
    runner = fake_runner(tree)
    sources = fake_sources(runner, {"good": "1.1.0", "bad": "2.0.0", "python": "3.15.3"})

    assert upgrade(tree, runner, sources, TODAY) == 0

    doc = versions(tree)
    assert doc["python"]["dependencies"] == {"good": "1.1.0", "bad": "2.0.0"}
    assert doc["runtime"]["python"] == "3.15.3"
    assert doc["held"] == {}
    assert len(runner.called("uv", "run", "pytest")) == 1
    assert commands(runner) == in_stages([" ".join(argv) for argv in suite_commands(tree)])
    assert "trying together: " in capsys.readouterr().out


def test_one_component_that_fails_is_held_after_two_runs_and_not_three(
    tree: Path, fake_runner, fake_sources
) -> None:
    runner = fake_runner(tree, {("uv",): suite_that_fails_on(tree, 'bad = "2.0.0"')})

    assert upgrade(tree, runner, fake_sources(runner, {"bad": "2.0.0"}), TODAY) == 0

    assert versions(tree)["held"]["bad"]["reason"] == "tests/test_scene.py::test_reconcile"
    assert versions(tree)["python"]["dependencies"]["bad"] == "1.0.0"
    # With the move, and as the tree was. It had already run alone.
    assert len(runner.called("uv", "run", "pytest")) == 2


def test_a_tool_gets_the_checks_that_use_it_and_no_others(
    tree: Path, fake_runner, fake_sources
) -> None:
    add_tool(tree, "ruff", "0.1.0")
    runner = fake_runner(tree)

    assert upgrade(tree, runner, fake_sources(runner, {"ruff": "0.2.0"}), TODAY) == 0

    assert versions(tree)["python"]["dev"] == {"ruff": "0.2.0"}
    assert 'dev = ["ruff==0.2.0"]' in (tree / "pyproject.toml").read_text()
    checks = ["uv sync", "uv run ruff check .", "uv run ruff format --check ."]
    # Once, with the move. The tree as it was is checked only when that fails.
    assert commands(runner) == in_stages(checks)
    assert not runner.called("uv", "run", "pytest")


def test_a_tool_whose_check_fails_after_the_move_is_held(
    tree: Path, fake_runner, fake_sources
) -> None:
    add_tool(tree, "ty", "0.0.1")

    def reply(argv: Sequence[str]) -> Result:
        moved = 'ty = "0.0.2"' in (tree / "versions.toml").read_text()
        return Result(1 if moved and "ty" in argv else 0, "error[invalid-argument-type]\n")

    runner = fake_runner(tree, {("uv",): reply})

    assert upgrade(tree, runner, fake_sources(runner, {"ty": "0.0.2"}), TODAY) == 0

    doc = versions(tree)
    assert doc["python"]["dev"] == {"ty": "0.0.1"}
    assert doc["held"]["ty"]["reason"] == "`uv run ty check` failed"
    assert doc["held"]["ty"]["skipped"] == "0.0.2"
    assert 'dev = ["ty==0.0.1"]' in (tree / "pyproject.toml").read_text()
    assert not runner.called("uv", "run", "pytest")
    assert runner.calls[-1] == ["uv", "sync"]


def test_a_tool_whose_check_fails_without_the_move_too_is_not_held(
    tree: Path, fake_runner, fake_sources, capsys
) -> None:
    add_tool(tree, "ruff", "0.1.0")
    runner = fake_runner(tree, {("uv", "run", "ruff"): Result(1, "E501 line too long\n")})
    before = (tree / "versions.toml").read_text()

    assert upgrade(tree, runner, fake_sources(runner, {"ruff": "0.2.0"}), TODAY) == 1

    assert (tree / "versions.toml").read_text() == before
    assert "ruff==0.1.0" in (tree / "pyproject.toml").read_text()
    assert "its check fails without the move too (`uv run ruff check .` failed); not held" in (
        capsys.readouterr().out
    )


def test_a_tool_moves_before_the_suite_so_that_its_one_run_covers_both(
    tree: Path, fake_runner, fake_sources
) -> None:
    add_tool(tree, "ruff", "0.1.0")
    runner = fake_runner(tree)

    assert (
        upgrade(tree, runner, fake_sources(runner, {"ruff": "0.2.0", "good": "1.1.0"}), TODAY) == 0
    )

    doc = versions(tree)
    assert doc["python"]["dev"] == {"ruff": "0.2.0"}
    assert doc["python"]["dependencies"]["good"] == "1.1.0"
    suite = [" ".join(argv) for argv in suite_commands(tree)]
    # ruff's own checks once, with its move, and then the suite for the
    # dependency, on the tree with both moves: the pass it records is of the
    # tree `upgrade` leaves, so `cut` has nothing to run again.
    assert commands(runner) == in_stages(
        ["uv sync", "uv run ruff check .", "uv run ruff format --check .", *suite]
    )


def test_the_narrow_checks_are_commands_of_the_suite() -> None:
    """A tool's checks are a part of the suite, never something else."""
    suite = {
        ("uv", "run", "ruff", "check", "."),
        ("uv", "run", "ruff", "format", "--check", "."),
        ("uv", "run", "ty", "check"),
        ("uv", "run", "pytest"),
        ("npm", "--prefix", "web", "run", "check"),
        ("npm", "--prefix", "web", "run", "format:check"),
    }
    for name, checks in {**NARROW_PYTHON, **NARROW_WEB}.items():
        assert checks, name
        assert set(checks) <= suite, name
    # What can reach the running application, or the build, is not narrow.
    for name in ("fastapi", "uvicorn", "websockets", "hatchling", "vite", "vitest", "react"):
        assert name not in NARROW_PYTHON
        assert name not in NARROW_WEB


def test_a_held_component_is_left_alone_until_a_newer_release_appears(
    tree: Path, fake_runner, fake_sources
) -> None:
    runner = fake_runner(tree, {("uv",): suite_that_fails_on(tree, 'bad = "2.0.0"')})
    upgrade(tree, runner, fake_sources(runner, {"bad": "2.0.0"}), TODAY)
    runner.calls.clear()

    assert upgrade(tree, runner, fake_sources(runner, {"bad": "2.0.0"}), TODAY) == 0
    assert runner.calls == []

    assert upgrade(tree, runner, fake_sources(runner, {"bad": "2.0.1"}), TODAY) == 0
    doc = versions(tree)
    assert doc["python"]["dependencies"]["bad"] == "2.0.1"
    assert doc["held"] == {}


def test_a_hold_goes_when_the_pin_is_current_again(tree: Path, fake_runner, fake_sources) -> None:
    runner = fake_runner(tree, {("uv",): suite_that_fails_on(tree, 'bad = "2.0.0"')})
    upgrade(tree, runner, fake_sources(runner, {"bad": "2.0.0"}), TODAY)
    path = tree / "versions.toml"
    path.write_text(path.read_text().replace('bad = "1.0.0"', 'bad = "2.0.0"'))

    upgrade(tree, runner, fake_sources(runner, {"bad": "2.0.0"}), TODAY)

    assert versions(tree)["held"] == {}


def test_nothing_changes_when_the_suite_fails_before_any_move(
    tree: Path, fake_runner, fake_sources
) -> None:
    runner = fake_runner(tree, {("uv",): suite_that_fails_on(tree, "[project]")})
    before = (tree / "versions.toml").read_text()

    assert upgrade(tree, runner, fake_sources(runner, {"good": "1.1.0"}), TODAY) == 1
    assert (tree / "versions.toml").read_text() == before


def test_a_python_minor_move_takes_the_mirrors_with_it(
    tree: Path, fake_runner, fake_sources
) -> None:
    runner = fake_runner(tree)

    assert upgrade(tree, runner, fake_sources(runner, {"python": "3.16.0"}), TODAY) == 0

    pyproject = tomllib.loads((tree / "pyproject.toml").read_text())
    assert versions(tree)["runtime"]["python"] == "3.16.0"
    assert (tree / ".python-version").read_text() == "3.16.0\n"
    assert pyproject["project"]["requires-python"] == ">=3.16,<3.17"
    assert pyproject["tool"]["ruff"]["target-version"] == "py316"
    assert pyproject["tool"]["ty"]["environment"]["python-version"] == "3.16"


def test_a_python_patch_move_leaves_the_minor_settings(
    tree: Path, fake_runner, fake_sources
) -> None:
    runner = fake_runner(tree)
    before = (tree / "pyproject.toml").read_text()

    assert upgrade(tree, runner, fake_sources(runner, {"python": "3.15.3"}), TODAY) == 0

    assert (tree / ".python-version").read_text() == "3.15.3\n"
    assert (tree / "pyproject.toml").read_text() == before


def test_action_pins_move_by_tag_and_by_commit(
    tree: Path, fake_runner, fake_sources, capsys
) -> None:
    runner = fake_runner(tree)
    latest = {"actions/checkout": "v8.1.0", "astral-sh/setup-uv": "v10.4.0"}

    assert upgrade(tree, runner, fake_sources(runner, latest), TODAY) == 0

    workflow = (tree / ".github/workflows/ci.yml").read_text()
    assert "      - uses: actions/checkout@v8\n" in workflow
    assert f"      - uses: astral-sh/setup-uv@{'b' * 40} # v10.4.0\n" in workflow
    # Nothing on this machine runs an action, so nothing was run for it.
    assert runner.calls == []
    assert "nothing here runs it; CI on the push is its test" in capsys.readouterr().out


def test_web_moves_edit_package_json_and_node_version(
    tree: Path, fake_runner, fake_sources, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PW_WS_ENDPOINT", raising=False)
    web = tree / "web"
    web.mkdir()
    (web / "package.json").write_text('{\n  "dependencies": {\n    "@scope/pkg": "1.0.0"\n  }\n}\n')
    (web / ".node-version").write_text("24.22.1\n")
    path = tree / "versions.toml"
    text = path.read_text().replace('node = ""', 'node = "24.22.1"')
    path.write_text(
        text.replace("[web.dependencies]\n", '[web.dependencies]\n"@scope/pkg" = "1.0.0"\n')
    )
    runner = fake_runner(tree, {("npm",): "", (sys.executable,): ""})
    sources = fake_sources(runner, {"node": "24.23.0", "@scope/pkg": "1.2.0"})

    suite = [" ".join(argv) for argv in suite_commands(tree)]
    # Both lockfiles are resolved before anything reads them, the build is
    # made before pytest and the browser tests, and those come last.
    assert suite[:2] == ["uv sync", "npm --prefix web install --no-audit --no-fund"]
    assert suite.index("npm --prefix web run build") < suite.index("uv run pytest")
    # The browser tests last, through the script that runs them in groups,
    # with the browser of the moved Playwright fetched just before.
    assert suite[-3:] == [
        "uv run pytest",
        "npm --prefix web exec -- playwright install chromium",
        f"{sys.executable} scripts/e2e.py",
    ]
    assert len(suite) == 12
    assert upgrade(tree, runner, sources, TODAY) == 0

    doc = versions(tree)
    assert doc["runtime"]["node"] == "24.23.0"
    assert doc["web"]["dependencies"] == {"@scope/pkg": "1.2.0"}
    assert (web / ".node-version").read_text() == "24.23.0\n"
    assert '"@scope/pkg": "1.2.0"' in (web / "package.json").read_text()
    assert runner.called("npm", "--prefix", "web", "test")
    assert runner.called(sys.executable, "scripts/e2e.py")
    # Node and the package moved together: the suite ran once.
    assert len(runner.called(sys.executable, "scripts/e2e.py")) == 1


def test_a_failed_lookup_is_reported_and_the_others_still_move(
    tree: Path, fake_runner, fake_sources
) -> None:
    runner = fake_runner(tree)
    sources = fake_sources(runner, {"good": "1.1.0", "bad": None})

    assert upgrade(tree, runner, sources, TODAY) == 1
    assert versions(tree)["python"]["dependencies"] == {"good": "1.1.0", "bad": "1.0.0"}


def test_a_failing_check_other_than_pytest_is_the_reason(
    tree: Path, fake_runner, fake_sources
) -> None:
    def reply(argv: Sequence[str]) -> Result:
        moved = 'good = "1.1.0"' in (tree / "versions.toml").read_text()
        return Result(1 if moved and "ruff" in argv else 0, "E501 line too long\n")

    runner = fake_runner(tree, {("uv",): reply})

    upgrade(tree, runner, fake_sources(runner, {"good": "1.1.0"}), TODAY)

    assert versions(tree)["held"]["good"]["reason"] == "`uv run ruff check .` failed"


def test_a_tree_known_to_be_good_is_not_run_again_after_a_failed_try(
    repo: Path, fake_runner, fake_sources, capsys
) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    runner = fake_runner(
        repo,
        {
            ("uv",): suite_that_fails_on(repo, 'bad = "2.0.0"'),
            ("gh", "run", "list"): Result(0, json.dumps([{"headSha": head}])),
        },
    )

    assert upgrade(repo, runner, fake_sources(runner, {"bad": "2.0.0"}), TODAY) == 0

    assert versions(repo)["held"]["bad"]["reason"] == "tests/test_scene.py::test_reconcile"
    # One run, with the move. CI had passed on the tree as it was.
    assert len(runner.called("uv", "run", "pytest")) == 1
    out = capsys.readouterr().out
    assert f"  CI passed on {head[:7]}: not run again" in out


# The images and the Go tool the container files pin (CONTAINERS in conftest.py)

INSTALL = ("deploy/debian/package-test.sh",)
UV = "ghcr.io/astral-sh/uv"
CONTAINER_FILES = ("deploy/Containerfile", "deploy/debian/Containerfile")


def read_all(root: Path) -> dict[str, str]:
    return {name: (root / name).read_text() for name in CONTAINER_FILES}


def test_an_image_moves_in_every_container_file_with_its_new_digest(
    containers: Path, fake_runner, fake_sources
) -> None:
    before = read_all(containers)
    runner = fake_runner(containers, {INSTALL: ""})
    sources = fake_sources(runner, {UV: "0.13.10"})

    assert upgrade(containers, runner, sources, TODAY) == 0

    for name, text in read_all(containers).items():
        old = before[name].split("\n")
        changed = [line for i, line in enumerate(text.split("\n")) if line != old[i]]
        assert changed == [f"FROM {UV}:0.13.10@{sources.digest} AS uv"], name
    # One lookup serves both files.
    assert sources.digests_asked == [f"{UV}:0.13.10"]
    # The suite builds no image, so the install test runs with it, once.
    suite = [" ".join(argv) for argv in suite_commands(containers)]
    assert commands(runner) == in_stages([*suite, " ".join(INSTALL)])


def test_a_node_move_takes_the_node_image_lines_with_it(
    containers: Path, fake_runner, fake_sources
) -> None:
    path = containers / "versions.toml"
    path.write_text(path.read_text().replace('node = ""', 'node = "24.22.1"'))
    (containers / "web").mkdir()
    (containers / "web" / ".node-version").write_text("24.22.1\n")
    runner = fake_runner(containers, {INSTALL: ""})
    sources = fake_sources(runner, {"node": "24.23.0"})

    assert upgrade(containers, runner, sources, TODAY) == 0

    assert (containers / "web" / ".node-version").read_text() == "24.23.0\n"
    for name, text in read_all(containers).items():
        line = f"FROM docker.io/library/node:24.23.0-trixie-slim@{sources.digest} AS node\n"
        assert line in text, name
        assert f"FROM {UV}:0.13.7@sha256:" in text, name
    assert sources.digests_asked == ["docker.io/library/node:24.23.0-trixie-slim"]
    # The move changed the container files, so the install test ran with the suite.
    assert len(runner.called(*INSTALL)) == 1


def test_a_go_tool_moves_by_its_install_line(containers: Path, fake_runner, fake_sources) -> None:
    before = read_all(containers)
    runner = fake_runner(containers, {INSTALL: ""})
    sources = fake_sources(runner, {"goreleaser/nfpm": "v2.50.0"})

    assert upgrade(containers, runner, sources, TODAY) == 0

    after = read_all(containers)
    assert after["deploy/Containerfile"] == before["deploy/Containerfile"]
    assert after["deploy/debian/Containerfile"] == before["deploy/debian/Containerfile"].replace(
        "nfpm@v2.49.0\n", "nfpm@v2.50.0\n"
    )
    assert len(runner.called(*INSTALL)) == 1


def test_an_image_whose_new_tag_has_no_digest_is_reported_and_left(
    containers: Path, fake_runner, fake_sources, capsys
) -> None:
    before = read_all(containers)
    runner = fake_runner(containers, {INSTALL: ""})
    sources = fake_sources(runner, {UV: "0.13.10"})
    sources.digest_errors[f"{UV}:0.13.10"] = LookupFailed("not published yet")

    assert upgrade(containers, runner, sources, TODAY) == 1

    assert read_all(containers) == before
    assert UV not in versions(containers)["held"]
    assert f"image {UV} 0.13.7: could not be moved (not published yet)" in capsys.readouterr().out


def test_an_image_whose_install_test_fails_is_held_and_put_back(
    containers: Path, fake_runner, fake_sources
) -> None:
    before = read_all(containers)

    def install(argv: Sequence[str]) -> Result:
        moved = "uv:0.13.10@" in (containers / "deploy/debian/Containerfile").read_text()
        return Result(1 if moved else 0, "FAIL segl answers on its port\n")

    runner = fake_runner(containers, {INSTALL: install})

    assert upgrade(containers, runner, fake_sources(runner, {UV: "0.13.10"}), TODAY) == 0

    assert read_all(containers) == before
    held = versions(containers)["held"][UV]
    assert (held["version"], held["skipped"]) == ("0.13.7", "0.13.10")
    assert held["reason"] == "`deploy/debian/package-test.sh` failed"


def test_a_failed_install_test_is_laid_on_the_move_that_caused_it(
    containers: Path, fake_runner, fake_sources
) -> None:
    """Node's move changes image lines too: the install test runs for it, not only for uv's."""
    path = containers / "versions.toml"
    path.write_text(path.read_text().replace('node = ""', 'node = "24.22.1"'))
    (containers / "web").mkdir()
    (containers / "web" / ".node-version").write_text("24.22.1\n")

    def install(argv: Sequence[str]) -> Result:
        moved = "node:24.23.0-" in (containers / "deploy/debian/Containerfile").read_text()
        return Result(1 if moved else 0, "FAIL node does not start\n")

    runner = fake_runner(containers, {INSTALL: install})
    sources = fake_sources(runner, {"node": "24.23.0", UV: "0.13.10"})

    assert upgrade(containers, runner, sources, TODAY) == 0

    doc = versions(containers)
    assert doc["runtime"]["node"] == "24.22.1"
    assert doc["held"]["node"]["reason"] == "`deploy/debian/package-test.sh` failed"
    assert UV not in doc["held"]
    builder = (containers / "deploy/debian/Containerfile").read_text()
    assert f"FROM {UV}:0.13.10@{sources.digest} AS uv\n" in builder
    assert "node:24.22.1-trixie-slim@" in builder


def test_an_install_test_that_fails_before_any_move_holds_nothing(
    containers: Path, fake_runner, fake_sources, capsys
) -> None:
    before = read_all(containers)
    runner = fake_runner(containers, {INSTALL: Result(1, "docker: cannot connect\n")})

    assert upgrade(containers, runner, fake_sources(runner, {UV: "0.13.10"}), TODAY) == 1

    assert read_all(containers) == before
    assert versions(containers)["held"] == {}
    assert "the suite fails before any move" in capsys.readouterr().out


def test_a_good_tree_still_gets_the_install_test_before_any_move(
    containers: Path, repo: Path, fake_runner, fake_sources, capsys
) -> None:
    """A good tree passed the suite, which builds no image: the install test runs alone."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    def install(argv: Sequence[str]) -> Result:
        moved = "uv:0.13.10@" in (repo / "deploy/debian/Containerfile").read_text()
        return Result(1 if moved else 0, "FAIL segl answers on its port\n")

    runner = fake_runner(
        repo, {INSTALL: install, ("gh", "run", "list"): json.dumps([{"headSha": head}])}
    )

    assert upgrade(repo, runner, fake_sources(runner, {UV: "0.13.10"}), TODAY) == 0

    assert versions(repo)["held"][UV]["reason"] == "`deploy/debian/package-test.sh` failed"
    # The suite once, with the move, and the install test with it and then
    # alone. ruff runs in a stage of its own before the install test.
    assert len(runner.called("uv", "run", "ruff", "check", ".")) == 1
    assert len(runner.called(*INSTALL)) == 2
    assert "the install test, which that does not cover, runs before any move" in (
        capsys.readouterr().out
    )


def test_a_go_tool_at_a_new_major_version_is_left_for_a_person(
    containers: Path, fake_runner, fake_sources, capsys
) -> None:
    before = read_all(containers)
    runner = fake_runner(containers, {INSTALL: ""})

    assert (
        upgrade(containers, runner, fake_sources(runner, {"goreleaser/nfpm": "v3.0.0"}), TODAY) == 1
    )

    assert read_all(containers) == before
    assert "goreleaser/nfpm" not in versions(containers)["held"]
    assert "v3.0.0 is a new major version, and its module path changes" in capsys.readouterr().out
    assert not runner.called(*INSTALL)


def test_the_pass_upgrade_records_is_of_the_tree_it_leaves(
    repo: Path, fake_runner, fake_sources
) -> None:
    """A tool moved after the suite left a pass of another tree, and `cut` ran it all again."""
    add_tool(repo, "ruff", "0.1.0")
    runner = fake_runner(repo)
    sources = fake_sources(
        runner, {"ruff": "0.2.0", "good": "1.1.0", "astral-sh/setup-uv": "v10.4.0"}
    )

    assert upgrade(repo, runner, sources, TODAY) == 0

    kept = recorded_pass(repo)
    assert kept is not None
    assert kept[0] == work_tree(repo)
