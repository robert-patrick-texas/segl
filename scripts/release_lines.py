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

"""The lines-of-code table of the release notes.

cloc counts the files git tracks, one row for each language. Each language's
code lines are split by path into what the package installs and runs
(Product), what checks it (Tests), and what builds and releases it (Tooling).
Markdown is the documentation, and is said in the sentence under the table.

The count is of segl's own files alone. Lock files, word lists, and the
license texts of other projects are left out, and no dependency is counted:
those are in the notes' second table, Versions.

The shape follows hirdir's scripts/release_facts.py, read at 724fd1f.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from release_proc import CommandError, Runner

CLOC = ("cloc", "--vcs=git", "--by-file", "--json", "--quiet", ".")

# Lock files, which a tool writes.
LEFT_OUT_NAMES = frozenset({"uv.lock", "package-lock.json"})
# The license texts of the bundled packages and fonts. The page beside them,
# which says where each came from, is segl's own.
LICENSE_TEXTS = "web/licenses/"
# Plain text here is word lists and license texts, and neither is code.
LEFT_OUT_LANGUAGES = frozenset({"Text"})
# Markdown is the documentation.
DOCUMENTATION = "Markdown"
# cloc's names for languages, where the notes use a shorter one.
LANGUAGE_NAMES = {"Bourne Shell": "Shell", "Bourne Again Shell": "Shell", "make": "Make"}
# These rows come first. The others follow by code lines, largest first.
FIRST_LANGUAGES = ("Python", "TypeScript")
AREAS = ("product", "tests", "tooling")

TEST_DIRS = ("tests/", "web/e2e/", "web/stretch/")
# The install test (docs/TEST-PLAN.md T-017 and T-021), and pytest's own setup.
TEST_FILES = frozenset(
    {
        "conftest.py",
        "deploy/debian/Containerfile.systemd",
        "deploy/debian/connect_proxy.py",
        "deploy/debian/fake_github.py",
        "deploy/debian/package-test.sh",
        "deploy/debian/socket_check.py",
        "deploy/debian/systemd-test.sh",
        "deploy/debian/test-releases.sh",
        "deploy/debian/testlib.sh",
    }
)
TOOLING_DIRS = ("scripts/", "tools/", ".github/", "web/scripts/")
# What builds the package and the dev container, and the project's settings.
TOOLING_FILES = frozenset(
    {
        "pyproject.toml",
        "versions.toml",
        "deploy/Containerfile",
        "deploy/debian/Containerfile",
        "deploy/debian/build-deb.sh",
        "deploy/debian/build.sh",
        "deploy/debian/nfpm.yaml",
        "web/package.json",
    }
)


def left_out(path: str, language: str) -> bool:
    """Return whether a tracked file is no work of this project's own hand."""
    name = path.rsplit("/", 1)[-1]
    if path.startswith(LICENSE_TEXTS) and name != "README.md":
        return True
    return name in LEFT_OUT_NAMES or language in LEFT_OUT_LANGUAGES


def area(path: str) -> str:
    """Return the column a file's code lines belong to: product, tests, or tooling.

    Tests are tests/, the browser tests, any `test_*` or `*.test.*` file, and
    the install test's files in deploy/debian/. Tooling is scripts/, tools/,
    the CI files, the web package's settings and build scripts, and what
    builds the package and the dev container. Everything else is the product:
    src/, web/src/, and the deploy files a server gets.
    """
    name = path.rsplit("/", 1)[-1]
    if path.startswith(TEST_DIRS) or path in TEST_FILES:
        return "tests"
    if name.startswith("test_") or ".test." in name:
        return "tests"
    if path in TOOLING_FILES or path.startswith(TOOLING_DIRS):
        return "tooling"
    # The web package's own settings: files right in web/, and no deeper.
    in_web = path.startswith("web/") and "/" not in path.removeprefix("web/")
    if in_web and (name.startswith("tsconfig") or ".config." in name):
        return "tooling"
    return "product"


@dataclass
class Row:
    """One language's counts."""

    files: int = 0
    code: int = 0
    comments: int = 0
    by_area: dict[str, int] = field(default_factory=lambda: dict.fromkeys(AREAS, 0))


@dataclass
class Lines:
    """The table's rows in their order, and the documentation beside them."""

    rows: dict[str, Row]
    docs_files: int = 0
    docs_lines: int = 0
    cloc: str = ""

    @property
    def code(self) -> int:
        """Return the code lines of every row together."""
        return sum(row.code for row in self.rows.values())


def lines_of_code(by_file: dict[str, Any]) -> Lines:
    """Gather the output of ``cloc --by-file --json`` into a row for each language."""
    rows: dict[str, Row] = defaultdict(Row)
    lines = Lines({}, cloc=str(by_file.get("header", {}).get("cloc_version", "")))
    for key, counts in by_file.items():
        if key in ("header", "SUM"):
            continue
        path = key.removeprefix("./")
        language = str(counts["language"])
        if left_out(path, language):
            continue
        if language == DOCUMENTATION:
            lines.docs_files += 1
            lines.docs_lines += counts["code"]
            continue
        row = rows[LANGUAGE_NAMES.get(language, language)]
        row.files += 1
        row.code += counts["code"]
        row.comments += counts["comment"]
        row.by_area[area(path)] += counts["code"]
    rest = sorted(
        (name for name in rows if name not in FIRST_LANGUAGES),
        key=lambda name: (-rows[name].code, name),
    )
    order = [name for name in FIRST_LANGUAGES if name in rows] + rest
    lines.rows = {name: rows[name] for name in order}
    return lines


def count_lines(runner: Runner) -> Lines:
    """Run cloc over the files git tracks in the runner's repository."""
    try:
        by_file = json.loads(runner.run(list(CLOC)).stdout)
    except (CommandError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cloc failed: {exc}") from exc
    lines = lines_of_code(by_file) if isinstance(by_file, dict) else Lines({})
    if not lines.rows:
        raise SystemExit("cloc counted no file: is this a git checkout with tracked files?")
    return lines


def _n(value: int) -> str:
    return f"{value:,}"


def _dash(value: int) -> str:
    return f"{value:,}" if value else "-"


def render_lines(lines: Lines) -> list[str]:
    """Return the heading, the table, and the sentences under it."""
    out = [
        "### Lines of code",
        "",
        "| Language | Files | Code | Comments | Product | Tests | Tooling |",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    total = Row()
    for name, row in lines.rows.items():
        areas = " | ".join(_dash(row.by_area[each]) for each in AREAS)
        out.append(f"| {name} | {_n(row.files)} | {_n(row.code)} | {_n(row.comments)} | {areas} |")
        total.files += row.files
        total.code += row.code
        total.comments += row.comments
        for each in AREAS:
            total.by_area[each] += row.by_area[each]
    areas = " | ".join(f"**{_dash(total.by_area[each])}**" for each in AREAS)
    counted = f"cloc {lines.cloc}" if lines.cloc else "cloc"
    out += [
        f"| **All** | **{_n(total.files)}** | **{_n(total.code)}** | **{_n(total.comments)}** "
        f"| {areas} |",
        "",
        "These lines of code are segl's own. They do not count the dependencies listed "
        f"below. Counted by {counted} in the files git tracks. Product is what the package "
        "installs and runs. Tests check it. Tooling builds and releases it. Lock files, "
        "word lists, and the license texts of other projects are left out. The "
        f"documentation is another {_n(lines.docs_lines)} lines of Markdown in "
        f"{_n(lines.docs_files)} files.",
    ]
    return out
