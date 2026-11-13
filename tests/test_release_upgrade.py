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
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

from release_proc import Result
from release_upgrade import NARROW_PYTHON, NARROW_WEB, suite_commands, upgrade

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
    """Return every command the runner was given, each as one line."""
    return [" ".join(argv) for argv in runner.calls]


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
    # pytest ran five times: for the two dependencies together, which failed,
    # for the tree as it was, for each of the two alone, and for md2html's
    # package, whose move only pytest covers. `uv sync` ran last, to put the
    # environment back on the kept pin.
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
    assert commands(runner) == [" ".join(argv) for argv in suite_commands(tree)]
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
    # As the tree stands, since no run of the suite has shown it to be good,
    # and then with the move.
    assert commands(runner) == checks + checks
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


def test_a_tool_whose_check_fails_before_the_move_is_not_tried(
    tree: Path, fake_runner, fake_sources, capsys
) -> None:
    add_tool(tree, "ruff", "0.1.0")
    runner = fake_runner(tree, {("uv", "run", "ruff"): Result(1, "E501 line too long\n")})
    before = (tree / "versions.toml").read_text()

    assert upgrade(tree, runner, fake_sources(runner, {"ruff": "0.2.0"}), TODAY) == 1

    assert (tree / "versions.toml").read_text() == before
    assert "ruff==0.1.0" in (tree / "pyproject.toml").read_text()
    assert (
        "its check fails before the move (`uv run ruff check .` failed)" in capsys.readouterr().out
    )


def test_after_a_suite_run_passed_a_tool_is_not_checked_twice(
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
    # The suite for the dependency, which showed the tree to be good, and
    # then ruff's own checks once, with its move.
    assert commands(runner) == [
        *suite,
        "uv sync",
        "uv run ruff check .",
        "uv run ruff format --check .",
    ]


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
    tree: Path, fake_runner, fake_sources
) -> None:
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
    # The browser tests last, through the script that runs them in groups.
    assert suite[-2:] == ["uv run pytest", f"{sys.executable} scripts/e2e.py"]
    assert len(suite) == 11
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
