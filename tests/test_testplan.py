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

"""`scripts/testplan.py`: the rows of docs/TEST-PLAN.md as one command (T-018).

The table, `tests/testplan.toml`, is held to the test plan and to the names
of the tests it cites. The judging is held to made-up reports: a row passes
only when every test it names ran and passed.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import testplan
from testplan import FAILED, PASSED, SKIPPED, Row, Table

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "web" / "e2e"


# The table against the repository.


def plan_rows() -> list[str]:
    text = (ROOT / "docs" / "TEST-PLAN.md").read_text(encoding="utf-8")
    return re.findall(r"^\| (T-\d{3}) \|", text, flags=re.MULTILINE)


def test_the_table_has_every_row_of_the_test_plan_but_the_two_it_cannot_run() -> None:
    table = testplan.load_table()
    elsewhere = {*testplan.NOT_HERE, testplan.CONTAINER_ROW}
    assert elsewhere == {"T-017", "T-018"}
    assert [row.name for row in table.rows] == [row for row in plan_rows() if row not in elsewhere]
    assert len(plan_rows()) == 20


def test_every_row_names_a_test() -> None:
    for row in testplan.load_table().rows:
        assert row.pytest or row.browser, row.name


def test_every_pytest_test_the_table_names_exists() -> None:
    for row in testplan.load_table().rows:
        for claim in row.pytest:
            file, _, name = claim.partition("::")
            path = ROOT / file
            assert path.is_file(), f"{row.name}: no file {file}"
            assert path.parent == ROOT / "tests", f"{row.name}: {file} is not in tests/"
            text = path.read_text(encoding="utf-8")
            wanted = rf"^(async )?def {re.escape(name)}\(" if name else r"^(async )?def test_"
            assert re.search(wanted, text, flags=re.MULTILINE), f"{row.name}: no test {claim}"


def test_every_browser_test_the_table_names_exists() -> None:
    for row in testplan.load_table().rows:
        for claim in row.browser:
            spec, *titles = claim.split(" > ")
            path = SPECS / spec
            assert path.is_file(), f"{row.name}: no spec {spec}"
            text = path.read_text(encoding="utf-8")
            for title in titles:
                quoted = [f"({quote}{title}{quote}," for quote in "'\"`"]
                assert any(each in text for each in quoted), f"{row.name}: {spec} has no {title!r}"


def test_the_projects_of_the_table_are_those_of_the_playwright_config() -> None:
    table = testplan.load_table()
    config = (ROOT / "web" / "playwright.config.ts").read_text(encoding="utf-8")
    named = {project for projects in table.projects.values() for project in projects}
    for project in named:
        assert f"'{project}'" in config, project
    assert table.projects_of("collab.spec.ts") == ("direct", "root", "board")
    assert table.projects_of("access.spec.ts") == ("access-direct", "access-root", "access-board")
    # The specs the config keeps apart are the ones the table gives projects of their own.
    apart = set(re.findall(r"'(\w+\.spec\.ts)'", config))
    assert apart == set(table.projects) - {"default"}


# The reports.


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="8">
<testcase classname="tests.test_room" name="test_one" time="0.1" />
<testcase classname="tests.test_room" name="test_cases[a-b]" time="0.1" />
<testcase classname="tests.test_room" name="test_cases[c]" time="0.1">
  <failure message="boom">trace</failure></testcase>
<testcase classname="tests.test_mount" name="test_through_nginx" time="0.0">
  <skipped type="pytest.skip" message="nginx is not installed">why</skipped></testcase>
<testcase classname="tests.test_mount" name="test_teardown" time="0.1" />
<testcase classname="tests.test_mount" name="test_teardown" time="0.0">
  <error message="failed on teardown">trace</error></testcase>
<testcase classname="tests.test_mount" name="test_setup" time="0.0">
  <error message="failed on setup">trace</error></testcase>
<testcase classname="tests.test_mount" name="test_setup" time="0.1" />
</testsuite></testsuites>
"""


def test_a_pytest_report_is_read_by_file_and_test(tmp_path: Path) -> None:
    path = tmp_path / "pytest.xml"
    path.write_text(JUNIT, encoding="utf-8")
    assert testplan.read_pytest_report(path) == {
        "tests/test_room.py::test_one": PASSED,
        "tests/test_room.py::test_cases[a-b]": PASSED,
        "tests/test_room.py::test_cases[c]": FAILED,
        "tests/test_mount.py::test_through_nginx": SKIPPED,
        # In the file twice, and failed once: failed, whichever comes first.
        "tests/test_mount.py::test_teardown": FAILED,
        "tests/test_mount.py::test_setup": FAILED,
    }


def browser_test(project: str, status: str) -> dict[str, Any]:
    return {"projectName": project, "status": status, "results": []}


def browser_report() -> dict[str, Any]:
    return {
        "suites": [
            {
                "title": "collab.spec.ts",
                "file": "collab.spec.ts",
                "specs": [
                    {
                        "title": "a rectangle appears",
                        "tests": [
                            browser_test("direct", "expected"),
                            browser_test("root", "expected"),
                            browser_test("board", "unexpected"),
                        ],
                    },
                    {"title": "a retried test", "tests": [browser_test("direct", "flaky")]},
                    {
                        "title": "a repeated test",
                        "tests": [
                            browser_test("direct", "unexpected"),
                            browser_test("direct", "expected"),
                            browser_test("root", "expected"),
                            browser_test("root", "unexpected"),
                        ],
                    },
                ],
                "suites": [
                    {
                        "title": "a new visitor",
                        "file": "collab.spec.ts",
                        "specs": [
                            {"title": "gets a label", "tests": [browser_test("direct", "skipped")]}
                        ],
                    }
                ],
            }
        ]
    }


def test_a_browser_report_is_read_by_spec_title_and_project(tmp_path: Path) -> None:
    path = tmp_path / "browser.json"
    path.write_text(json.dumps(browser_report()), encoding="utf-8")
    assert testplan.read_browser_report(path) == {
        "collab.spec.ts > a rectangle appears": {"direct": PASSED, "root": PASSED, "board": FAILED},
        "collab.spec.ts > a retried test": {"direct": FAILED},
        "collab.spec.ts > a repeated test": {"direct": FAILED, "root": FAILED},
        "collab.spec.ts > a new visitor > gets a label": {"direct": SKIPPED},
    }


# The judging.


PROJECTS = {"default": ("direct", "board"), "own.spec.ts": ("restart",)}
EVERYWHERE = {"direct": PASSED, "board": PASSED}


def judge_one(
    row: Row,
    pytest_outcomes: dict[str, str] | None,
    browser_outcomes: dict[str, dict[str, str]] | None,
) -> testplan.Verdict:
    (verdict,) = testplan.judge(Table((row,), PROJECTS), pytest_outcomes, browser_outcomes)
    return verdict


def test_a_row_passes_when_every_test_it_names_passed() -> None:
    row = Row(
        "T-001",
        pytest=("tests/test_a.py::test_one", "tests/test_b.py"),
        browser=("a.spec.ts > draws", "own.spec.ts"),
    )
    verdict = judge_one(
        row,
        {
            "tests/test_a.py::test_one": PASSED,
            "tests/test_a.py::test_one_more": FAILED,
            "tests/test_b.py::test_x": PASSED,
            "tests/test_b.py::test_y[1]": PASSED,
        },
        {
            "a.spec.ts > draws": dict(EVERYWHERE),
            "a.spec.ts > draws twice": {"direct": FAILED, "board": FAILED},
            "own.spec.ts > restarts": {"restart": PASSED},
            "own.spec.ts > group > restarts again": {"restart": PASSED},
        },
    )
    assert verdict.passed
    assert verdict.problems == []
    # Three pytest tests, and four runs of browser tests: two mounts, and two tests.
    assert (verdict.pytest, verdict.browser) == (3, 4)


@pytest.mark.parametrize("outcome", [FAILED, SKIPPED])
def test_a_pytest_test_that_failed_or_was_skipped_fails_its_row(outcome: str) -> None:
    row = Row("T-002", pytest=("tests/test_a.py::test_one",))
    verdict = judge_one(row, {"tests/test_a.py::test_one": outcome}, {})
    assert not verdict.passed
    assert verdict.problems == [f"{outcome}: tests/test_a.py::test_one"]


def test_one_failed_case_of_a_parametrized_test_fails_its_row() -> None:
    row = Row("T-002", pytest=("tests/test_a.py::test_cases",))
    verdict = judge_one(
        row,
        {
            "tests/test_a.py::test_cases[a]": PASSED,
            "tests/test_a.py::test_cases[b]": FAILED,
            # Another test, whose name only starts the same.
            "tests/test_a.py::test_cases_more": FAILED,
        },
        {},
    )
    assert verdict.problems == ["failed: tests/test_a.py::test_cases[b]"]
    assert verdict.pytest == 1


def test_a_named_test_that_did_not_run_fails_its_row() -> None:
    row = Row(
        "T-003",
        pytest=("tests/test_a.py::test_gone", "tests/test_none.py"),
        browser=("a.spec.ts > gone", "none.spec.ts"),
    )
    verdict = judge_one(row, {"tests/test_a.py::test_other": PASSED}, {"a.spec.ts > other": {}})
    assert verdict.problems == [
        "did not run: tests/test_a.py::test_gone",
        "did not run: tests/test_none.py",
        "did not run: a.spec.ts > gone",
        "did not run: none.spec.ts",
    ]


def test_a_file_is_not_taken_for_another_whose_name_starts_the_same() -> None:
    row = Row("T-003", pytest=("tests/test_a.py",), browser=("a.spec.ts",))
    verdict = judge_one(
        row, {"tests/test_a.py.py::test_x": PASSED}, {"a.spec.ts.ts > x": dict(EVERYWHERE)}
    )
    assert verdict.problems == ["did not run: tests/test_a.py", "did not run: a.spec.ts"]


@pytest.mark.parametrize("outcome", [FAILED, SKIPPED])
def test_a_browser_test_that_failed_or_was_skipped_in_one_project_fails_its_row(
    outcome: str,
) -> None:
    row = Row("T-013", browser=("a.spec.ts > draws",))
    verdict = judge_one(row, {}, {"a.spec.ts > draws": {"direct": PASSED, "board": outcome}})
    assert verdict.problems == [f"{outcome} in board: a.spec.ts > draws"]
    assert verdict.browser == 1


def test_a_browser_test_that_missed_one_of_its_projects_fails_its_row() -> None:
    row = Row("T-013", browser=("a.spec.ts > draws", "own.spec.ts > restarts"))
    verdict = judge_one(
        row,
        {},
        {"a.spec.ts > draws": {"direct": PASSED}, "own.spec.ts > restarts": {"direct": PASSED}},
    )
    assert verdict.problems == [
        "did not run in board: a.spec.ts > draws",
        "did not run in restart: own.spec.ts > restarts",
    ]


def test_a_suite_that_left_no_report_fails_the_rows_that_need_it() -> None:
    table = Table(
        (
            Row("T-001", pytest=("tests/test_a.py",), browser=("a.spec.ts",)),
            Row("T-020", pytest=("tests/test_a.py",)),
        ),
        PROJECTS,
    )
    both, server_only = testplan.judge(table, {"tests/test_a.py::test_x": PASSED}, None)
    assert both.problems == ["no browser report: a.spec.ts"]
    assert server_only.passed
    both, server_only = testplan.judge(table, None, {"a.spec.ts > x": dict(EVERYWHERE)})
    assert both.problems == ["no pytest report: tests/test_a.py"]
    assert server_only.problems == ["no pytest report: tests/test_a.py"]


def test_a_row_without_tests_does_not_pass() -> None:
    assert judge_one(Row("T-099"), {}, {}).problems == ["the table names no test for this row"]


# The command, with stand-ins for the two suites.


def passing_reports() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Reports in which every test the real table names ran and passed."""
    table = testplan.load_table()
    server: dict[str, str] = {}
    browser: dict[str, dict[str, str]] = {}
    for row in table.rows:
        for claim in row.pytest:
            server[claim if "::" in claim else f"{claim}::test_all"] = PASSED
        for claim in row.browser:
            spec = claim.split(" > ", 1)[0]
            test = claim if " > " in claim else f"{claim} > all"
            browser[test] = dict.fromkeys(table.projects_of(spec), PASSED)
    return server, browser


class Suites:
    """Stands in for `subprocess.run`: writes the reports the two suites would."""

    def __init__(
        self,
        server: dict[str, str] | None,
        browser: dict[str, dict[str, str]] | None,
        exits: tuple[int, int] = (0, 0),
    ) -> None:
        self.server, self.browser, self.exits = server, browser, exits
        self.commands: list[list[str]] = []
        self.environments: list[dict[str, str]] = []
        self.folders: list[Path] = []

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        self.environments.append(options["env"])
        self.folders.append(options["cwd"])
        if "pytest" in command:
            (path,) = (arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))
            if self.server is not None:
                Path(path).write_text(self.junit(), encoding="utf-8")
            return subprocess.CompletedProcess(command, self.exits[0])
        if self.browser is not None:
            report = Path(command[command.index("--report") + 1])
            report.write_text(json.dumps(self.report()), encoding="utf-8")
        return subprocess.CompletedProcess(command, self.exits[1])

    def junit(self) -> str:
        assert self.server is not None
        cases = []
        for test, outcome in self.server.items():
            file, name = test.split("::")
            classname = file.removesuffix(".py").replace("/", ".")
            inner = {PASSED: "", FAILED: "<failure/>", SKIPPED: "<skipped/>"}[outcome]
            cases.append(f'<testcase classname="{classname}" name="{name}">{inner}</testcase>')
        return f"<testsuites><testsuite>{''.join(cases)}</testsuite></testsuites>"

    def report(self) -> dict[str, Any]:
        assert self.browser is not None
        status = {PASSED: "expected", FAILED: "unexpected", SKIPPED: "skipped"}
        suites = []
        for test, by_project in self.browser.items():
            spec, *groups, title = test.split(" > ")
            tests = [browser_test(project, status[each]) for project, each in by_project.items()]
            node: dict[str, Any] = {"specs": [{"title": title, "tests": tests}]}
            for group in reversed(groups):
                node = {"suites": [{"title": group, **node}]}
            suites.append({"title": spec, "file": spec, **node})
        return {"suites": suites}


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A repository root that has a web build, and is not the dev container."""
    for name in ("tests", "versions.toml", ".python-version"):
        (tmp_path / name).symlink_to(ROOT / name)
    (tmp_path / "web" / "dist").mkdir(parents=True)
    (tmp_path / "web" / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(testplan, "ROOT", tmp_path)
    monkeypatch.setattr(testplan, "TABLE", tmp_path / "tests" / "testplan.toml")
    monkeypatch.delenv(testplan.CONTAINER_MARK, raising=False)
    # CI and the dev container set this. The command has to set it itself.
    monkeypatch.delenv("SEGL_REQUIRE_NGINX", raising=False)
    return tmp_path


def run_main(suites: Suites, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    status = testplan.main(run=suites)
    return status, capsys.readouterr().out


def test_the_command_passes_when_every_row_did(
    built: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    suites = Suites(*passing_reports())
    status, out = run_main(suites, capsys)
    assert status == 0, out
    assert "All 18 rows passed." in out
    for row in testplan.load_table().rows:
        assert re.search(rf"^  {row.name}  pass  \d+ pytest, \d+ browser$", out, flags=re.MULTILINE)
    assert "T-017  -     not run here: the .deb: deploy/debian/package-test.sh" in out
    assert "T-018  -     not judged: this is not the dev container" in out
    assert "FAIL" not in out

    # It ran pytest whole, and then the browser tests whole, each once, from the root.
    assert suites.folders == [built, built]
    server, browser = suites.commands
    assert server[1:3] == ["-m", "pytest"] and len(server) == 4
    assert browser[:3] == [sys.executable, "scripts/e2e.py", "--report"]
    assert len(browser) == 4
    # A test through nginx fails here where it would skip.
    assert suites.environments[0]["SEGL_REQUIRE_NGINX"] == "1"


def test_the_command_fails_and_names_the_row_when_one_test_failed(
    built: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server, browser = passing_reports()
    test = "collab.spec.ts > both browsers draw at the same time, and both elements remain"
    browser[test]["board"] = FAILED
    status, out = run_main(Suites(server, browser, exits=(0, 1)), capsys)
    assert status == 1
    assert "  T-002  FAIL  1 pytest, 2 browser\n" in out
    assert f"failed in board: {test}" in out
    assert out.rstrip().endswith("FAILED: T-002")
    assert "  T-001  pass" in out


def test_the_command_fails_when_a_named_test_was_skipped(
    built: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server, browser = passing_reports()
    server["tests/test_mount.py::test_all"] = SKIPPED
    # pytest calls a run with skips a pass.
    status, out = run_main(Suites(server, browser), capsys)
    assert status == 1
    assert "skipped: tests/test_mount.py::test_all" in out
    assert out.rstrip().endswith("FAILED: T-013")


@pytest.mark.parametrize("exits", [(1, 0), (0, 1)])
def test_the_command_fails_when_a_suite_failed_outside_the_rows(
    exits: tuple[int, int], built: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out = run_main(Suites(*passing_reports(), exits=exits), capsys)
    assert status == 1
    said = f"pytest exit {exits[0]}, browser tests exit {exits[1]}."
    assert f"Every row passed, but a suite did not: {said}" in out
    assert "All 18 rows passed." not in out


def test_the_command_fails_every_browser_row_when_the_browser_tests_left_no_report(
    built: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server, _ = passing_reports()
    status, out = run_main(Suites(server, None, exits=(0, 1)), capsys)
    assert status == 1
    assert "no browser report: origin.spec.ts" in out
    # T-020 is pytest alone, and stands.
    assert "  T-020  pass" in out
    assert "T-020" not in out.rstrip().splitlines()[-1]


def test_in_the_dev_container_the_command_judges_t018(
    built: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(testplan.CONTAINER_MARK, "1")
    monkeypatch.setattr(testplan, "python_is_uvs", lambda: True)
    status, out = run_main(Suites(*passing_reports()), capsys)
    assert status == 0, out
    assert "  T-018  pass  the dev container ran the rows above on uv's Python" in out

    # On the system's Python the rows may pass, and T-018 does not.
    monkeypatch.setattr(testplan, "python_is_uvs", lambda: False)
    status, out = run_main(Suites(*passing_reports()), capsys)
    assert status == 1
    assert "  T-018  FAIL" in out
    assert out.rstrip().endswith("FAILED: T-018")

    # A failed row fails T-018 with it.
    monkeypatch.setattr(testplan, "python_is_uvs", lambda: True)
    server, browser = passing_reports()
    server["tests/test_networks.py::test_all"] = FAILED
    status, out = run_main(Suites(server, browser, exits=(1, 0)), capsys)
    assert status == 1
    assert out.rstrip().endswith("FAILED: T-020, T-018")


def test_the_command_stops_without_a_web_build(
    built: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (built / "web" / "dist" / "index.html").unlink()
    suites = Suites(*passing_reports())
    status, out = run_main(suites, capsys)
    assert status == 2
    assert out == "testplan: no web build. Run: npm --prefix web run build\n"
    assert suites.commands == []


def test_this_python_is_the_pinned_one_from_uv() -> None:
    # The suite itself runs on uv's Python (docs/DEVELOPMENT.md), so this holds here.
    assert testplan.python_is_uvs()


def test_the_system_python_is_not_uvs(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(sys, "base_prefix", "/usr")
        assert not testplan.python_is_uvs()
    with monkeypatch.context() as patch:
        patch.setattr(sys, "version_info", (3, 14, 4, "final", 0))
        assert not testplan.python_is_uvs()
    assert testplan.python_is_uvs()


def test_the_environment_lines_name_what_an_evidence_block_needs() -> None:
    lines = "\n".join(testplan.environment())
    versions = (ROOT / "versions.toml").read_text(encoding="utf-8")
    pin = re.search(r'^python = "(.+)"$', versions, flags=re.MULTILINE)
    excalidraw = re.search(r'^"@excalidraw/excalidraw" = "(.+)"$', versions, flags=re.MULTILINE)
    assert pin and excalidraw
    assert f"Python {pin.group(1)} from " in lines
    assert f"Excalidraw {excalidraw.group(1)}" in lines
    assert "revision: " in lines
    assert "Node " in lines
