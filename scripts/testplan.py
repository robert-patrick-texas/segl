#!/usr/bin/env python3
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

"""Run the rows of docs/TEST-PLAN.md and print one line for each.

    uv run python scripts/testplan.py

It runs pytest and the browser tests once, whole, then reads each row's
result from their reports. tests/testplan.toml says which tests run which
row. A row passes when every test it names ran and passed: a skipped test, or
one that is missing from the report, fails its row.

The exit status is 0 when every row passed and both suites did. The browser
tests need the build (`npm --prefix web run build`) and a browser, as
docs/DEVELOPMENT.md says. The dev container has both, and runs this as its
command.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "tests" / "testplan.toml"

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"

# The dev container sets this (deploy/Containerfile). T-018 is judged there.
CONTAINER_MARK = "SEGL_DEV_CONTAINER"
# Rows of the test plan that no test here runs, and why.
NOT_HERE = {"T-017": "the .deb: deploy/debian/package-test.sh builds and installs it"}
CONTAINER_ROW = "T-018"

Run = Callable[..., Any]
"""`subprocess.run`, or a test's stand-in for it."""


@dataclass(frozen=True)
class Row:
    """One row of the test plan, and the tests that run it."""

    name: str
    pytest: tuple[str, ...] = ()
    browser: tuple[str, ...] = ()


@dataclass(frozen=True)
class Table:
    rows: tuple[Row, ...]
    # Spec file → the Playwright projects its tests must pass in.
    projects: Mapping[str, tuple[str, ...]]

    def projects_of(self, spec: str) -> tuple[str, ...]:
        return self.projects.get(spec, self.projects["default"])


@dataclass
class Verdict:
    """What the reports say about one row."""

    row: str
    pytest: int = 0
    browser: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems


def load_table(path: Path = TABLE) -> Table:
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    rows = tuple(
        Row(name, tuple(claims.get("pytest", ())), tuple(claims.get("browser", ())))
        for name, claims in doc["rows"].items()
    )
    projects = {spec: tuple(names) for spec, names in doc["projects"].items()}
    return Table(rows, projects)


def read_pytest_report(path: Path) -> dict[str, str]:
    """Read pytest's JUnit file: test id, as `tests/file.py::name[case]`, to outcome."""
    outcomes: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        file = case.get("classname", "").replace(".", "/") + ".py"
        test = f"{file}::{case.get('name', '')}"
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = FAILED
        elif case.find("skipped") is not None:
            outcome = SKIPPED
        else:
            outcome = PASSED
        # A test whose teardown failed is in the file twice. The failure counts.
        if outcomes.get(test) != FAILED:
            outcomes[test] = outcome
    return outcomes


def read_browser_report(path: Path) -> dict[str, dict[str, str]]:
    """Read Playwright's JSON report: `spec > title` to each project's outcome."""
    outcomes: dict[str, dict[str, str]] = {}

    def walk(suite: dict[str, Any], names: list[str]) -> None:
        for spec in suite.get("specs", []):
            by_project = outcomes.setdefault(" > ".join([*names, spec["title"]]), {})
            for test in spec.get("tests", []):
                status = test.get("status")
                # `flaky` passed on a second try. Here that is a failure.
                outcome = {"expected": PASSED, "skipped": SKIPPED}.get(status, FAILED)
                if by_project.get(test["projectName"]) != FAILED:
                    by_project[test["projectName"]] = outcome
        for group in suite.get("suites", []):
            walk(group, [*names, group["title"]])

    for top in json.loads(path.read_text(encoding="utf-8")).get("suites", []):
        walk(top, [Path(top["file"]).name])
    return outcomes


def _pytest_matches(claim: str, outcomes: Mapping[str, str]) -> dict[str, str]:
    if "::" in claim:
        return {
            test: outcome
            for test, outcome in outcomes.items()
            if test == claim or test.startswith(claim + "[")
        }
    return {test: outcome for test, outcome in outcomes.items() if test.startswith(claim + "::")}


def _browser_matches(
    claim: str, outcomes: Mapping[str, Mapping[str, str]]
) -> dict[str, Mapping[str, str]]:
    if " > " in claim:
        return {claim: outcomes[claim]} if claim in outcomes else {}
    return {test: found for test, found in outcomes.items() if test.startswith(claim + " > ")}


def judge(
    table: Table,
    pytest_outcomes: Mapping[str, str] | None,
    browser_outcomes: Mapping[str, Mapping[str, str]] | None,
) -> list[Verdict]:
    """Judge every row. `None` for a suite means it left no report."""
    verdicts = []
    for row in table.rows:
        verdict = Verdict(row.name)
        if not row.pytest and not row.browser:
            verdict.problems.append("the table names no test for this row")
        for claim in row.pytest:
            if pytest_outcomes is None:
                verdict.problems.append(f"no pytest report: {claim}")
                continue
            matches = _pytest_matches(claim, pytest_outcomes)
            if not matches:
                verdict.problems.append(f"did not run: {claim}")
            for test, outcome in matches.items():
                if outcome == PASSED:
                    verdict.pytest += 1
                else:
                    verdict.problems.append(f"{outcome}: {test}")
        for claim in row.browser:
            if browser_outcomes is None:
                verdict.problems.append(f"no browser report: {claim}")
                continue
            matches = _browser_matches(claim, browser_outcomes)
            if not matches:
                verdict.problems.append(f"did not run: {claim}")
            needed = table.projects_of(claim.split(" > ", 1)[0])
            for test, by_project in matches.items():
                for project in needed:
                    if project not in by_project:
                        verdict.problems.append(f"did not run in {project}: {test}")
                for project, outcome in by_project.items():
                    if outcome == PASSED:
                        verdict.browser += 1
                    else:
                        verdict.problems.append(f"{outcome} in {project}: {test}")
        verdicts.append(verdict)
    return verdicts


def python_is_uvs() -> bool:
    """Say whether this Python is the pinned one, and not the system's."""
    pin = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    running = ".".join(str(part) for part in sys.version_info[:3])
    return running == pin and Path(sys.base_prefix) not in (Path("/usr"), Path("/usr/local"))


def _first_line(command: list[str]) -> str:
    """Return the first line a tool prints, or `not found`."""
    try:
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    except OSError:
        return "not found"
    lines = (done.stdout + done.stderr).strip().splitlines()
    return lines[0].strip() if done.returncode == 0 and lines else "not found"


def environment() -> list[str]:
    """The lines an evidence block needs (docs/TEST-PLAN.md, "Evidence")."""
    versions = tomllib.loads((ROOT / "versions.toml").read_text(encoding="utf-8"))
    web = {**versions["web"]["dependencies"], **versions["web"]["dev"]}
    revision = _first_line(["git", "rev-parse", "--short", "HEAD"])
    if revision == "not found":
        revision = "no git checkout here"
    chromium = "not found"
    browsers = ROOT / "web" / "node_modules" / "playwright-core" / "browsers.json"
    if browsers.is_file():
        for browser in json.loads(browsers.read_text(encoding="utf-8"))["browsers"]:
            if browser["name"] == "chromium":
                chromium = browser["browserVersion"]
    where = "through PW_WS_ENDPOINT" if os.environ.get("PW_WS_ENDPOINT") else "run here"
    place = "in" if os.environ.get(CONTAINER_MARK) else "not in"
    return [
        f"segl {versions['project']['version']}, revision: {revision}, {place} the dev container",
        f"Python {sys.version.split()[0]} from {sys.base_prefix}"
        f" (pin {versions['runtime']['python']})",
        f"Node {_first_line(['node', '--version'])},"
        f" {_first_line(['nginx', '-v']).removeprefix('nginx version: ')}",
        f"Excalidraw {web['@excalidraw/excalidraw']}, Playwright {web['@playwright/test']},"
        f" Chromium {chromium}, {where}",
    ]


def _tally(outcomes: list[str]) -> str:
    return ", ".join(f"{outcomes.count(each)} {each}" for each in (PASSED, FAILED, SKIPPED))


def main(run: Run = subprocess.run) -> int:
    if importlib.util.find_spec("pytest") is None:
        print("testplan: this Python has no pytest. Run: uv run python scripts/testplan.py")
        return 2
    if not (ROOT / "web" / "dist" / "index.html").is_file():
        print("testplan: no web build. Run: npm --prefix web run build")
        return 2
    table = load_table()

    with tempfile.TemporaryDirectory(prefix="segl-testplan-") as work:
        junit = Path(work) / "pytest.xml"
        report = Path(work) / "browser.json"
        # Here a test through nginx fails where it would skip.
        pytest_exit = run(
            [sys.executable, "-m", "pytest", f"--junitxml={junit}"],
            cwd=ROOT,
            env={**os.environ, "SEGL_REQUIRE_NGINX": "1"},
            check=False,
        ).returncode
        # In as many groups at once as the machine has room for, with one
        # report for all of them (scripts/e2e.py).
        browser_exit = run(
            [sys.executable, "scripts/e2e.py", "--report", str(report)],
            cwd=ROOT,
            env=dict(os.environ),
            check=False,
        ).returncode
        pytest_outcomes = read_pytest_report(junit) if junit.is_file() else None
        browser_outcomes = read_browser_report(report) if report.is_file() else None

    verdicts = judge(table, pytest_outcomes, browser_outcomes)
    failed = [verdict.row for verdict in verdicts if not verdict.passed]

    print()
    print("Test plan rows (docs/TEST-PLAN.md)")
    for line in environment():
        print(f"  {line}")
    if pytest_outcomes is not None:
        print(f"  pytest: {_tally(list(pytest_outcomes.values()))} (exit {pytest_exit})")
    if browser_outcomes is not None:
        every = [each for found in browser_outcomes.values() for each in found.values()]
        print(f"  browser tests: {_tally(every)} (exit {browser_exit})")
    print()
    for verdict in verdicts:
        word = "pass" if verdict.passed else "FAIL"
        print(f"  {verdict.row}  {word}  {verdict.pytest} pytest, {verdict.browser} browser")
        for problem in verdict.problems:
            print(f"           {problem}")
    for row, why in NOT_HERE.items():
        print(f"  {row}  -     not run here: {why}")

    suites_passed = pytest_exit == 0 and browser_exit == 0
    if os.environ.get(CONTAINER_MARK):
        if not failed and suites_passed and python_is_uvs():
            print(f"  {CONTAINER_ROW}  pass  the dev container ran the rows above on uv's Python")
        else:
            print(f"  {CONTAINER_ROW}  FAIL  the dev container did not pass the rows above")
            failed.append(CONTAINER_ROW)
    else:
        print(f"  {CONTAINER_ROW}  -     not judged: this is not the dev container")

    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    if not suites_passed:
        print(
            f"Every row passed, but a suite did not: "
            f"pytest exit {pytest_exit}, browser tests exit {browser_exit}."
        )
        return 1
    print(f"All {len(verdicts)} rows passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
