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

"""The lines-of-code table of the release notes: what is counted, and where."""

import json
from pathlib import Path

import pytest
import release_lines
from release_lines import Lines, Row, area, count_lines, left_out, lines_of_code, render_lines
from release_proc import CommandError

ROOT = Path(__file__).resolve().parents[1]


def counted(language: str, code: int, comment: int = 0) -> dict:
    return {"language": language, "code": code, "comment": comment, "blank": 1}


# What cloc prints for a small tree, with the lines it prints beside the files.
BY_FILE = {
    "header": {"cloc_version": "2.06", "n_files": 9},
    "./src/segl/app.py": counted("Python", 1000, 50),
    "./tests/test_app.py": counted("Python", 200, 4),
    "./scripts/release.py": counted("Python", 30, 6),
    "./web/src/main.ts": counted("TypeScript", 300, 20),
    "./web/src/main.test.ts": counted("TypeScript", 150),
    "./deploy/debian/postinst": counted("Bourne Shell", 40, 9),
    "./deploy/debian/build-deb.sh": counted("Bourne Again Shell", 60, 1),
    "./web/src/bar.css": counted("CSS", 500, 2),
    "./docs/DEPLOY.md": counted("Markdown", 320),
    "./README.md": counted("Markdown", 12),
    "./web/package-lock.json": counted("JSON", 4587),
    "./deploy/display-names.txt": counted("Text", 201),
    "./web/licenses/packages/react.txt": counted("Text", 21),
    "SUM": {"code": 7421, "comment": 92, "blank": 13, "nFiles": 13},
}


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("uv.lock", "TOML"),
        ("web/package-lock.json", "JSON"),
        ("deploy/display-names.txt", "Text"),
        ("draft2/display-names.txt", "Text"),
        ("web/licenses/packages/excalidraw.txt", "Text"),
        ("web/licenses/fonts/Cascadia/LICENSE", "Markdown"),
        ("web/licenses/fonts/Cascadia/LICENSE.md", "Markdown"),
    ],
)
def test_lock_files_word_lists_and_license_texts_are_left_out(path: str, language: str) -> None:
    assert left_out(path, language)


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("web/licenses/README.md", "Markdown"),
        ("web/package.json", "JSON"),
        ("tests/reconcile_cases.json", "JSON"),
        ("src/segl/empty_scene.json", "JSON"),
        ("pyproject.toml", "TOML"),
        ("docs/RELEASING.md", "Markdown"),
        ("src/segl/licenses.py", "Python"),
    ],
)
def test_the_project_s_own_files_are_counted(path: str, language: str) -> None:
    assert not left_out(path, language)


@pytest.mark.parametrize(
    ("path", "column"),
    [
        ("src/segl/app.py", "product"),
        ("src/segl/update/updater.py", "product"),
        ("src/segl/migrations/0001_slots.sql", "product"),
        ("src/segl/empty_scene.json", "product"),
        ("web/src/collab/session.ts", "product"),
        ("web/src/bar/bar.css", "product"),
        ("web/index.html", "product"),
        ("web/public/favicon.svg", "product"),
        ("deploy/debian/postinst", "product"),
        ("deploy/debian/prerm", "product"),
        ("deploy/nginx/segl-http.conf", "product"),
        ("tests/test_collab.py", "tests"),
        ("tests/harness.py", "tests"),
        ("tests/testplan.toml", "tests"),
        ("tests/header_value_cases.json", "tests"),
        ("conftest.py", "tests"),
        ("web/e2e/collab.spec.ts", "tests"),
        ("web/stretch/sizes.stretch.ts", "tests"),
        ("web/src/collab/session.test.ts", "tests"),
        ("web/scripts/collect-licenses.test.ts", "tests"),
        ("tools/md2html/test_md2html.py", "tests"),
        ("deploy/debian/package-test.sh", "tests"),
        ("deploy/debian/systemd-test.sh", "tests"),
        ("deploy/debian/fake_github.py", "tests"),
        ("deploy/debian/Containerfile.systemd", "tests"),
        ("scripts/release.py", "tooling"),
        ("tools/md2html/md2html.py", "tooling"),
        ("tools/md2html/template.html", "tooling"),
        (".github/workflows/ci.yml", "tooling"),
        ("pyproject.toml", "tooling"),
        ("versions.toml", "tooling"),
        ("deploy/Containerfile", "tooling"),
        ("deploy/debian/Containerfile", "tooling"),
        ("deploy/debian/build-deb.sh", "tooling"),
        ("deploy/debian/nfpm.yaml", "tooling"),
        ("web/package.json", "tooling"),
        ("web/tsconfig.json", "tooling"),
        ("web/vite.config.ts", "tooling"),
        ("web/playwright.stretch.config.ts", "tooling"),
        ("web/scripts/collect-licenses.ts", "tooling"),
        # Only the web package's own settings: not a file of the application.
        ("web/src/app.config.ts", "product"),
        ("web/src/tsconfig-reader.ts", "product"),
    ],
)
def test_each_file_s_lines_go_to_one_column(path: str, column: str) -> None:
    assert area(path) == column


def test_every_file_of_the_package_folder_has_a_column_by_name() -> None:
    # deploy/debian/ holds three kinds of file side by side: what the package
    # installs, what builds it, and what tests it. A new file must be put in
    # one of them here, and not fall to "product" by default.
    installed = {"copyright", "lintian-overrides", "postinst", "postrm", "prerm"}
    installed |= {"sysusers.conf", "tmpfiles.conf"}
    folder = "deploy/debian/"
    named = {
        name.removeprefix(folder)
        for name in (*release_lines.TEST_FILES, *release_lines.TOOLING_FILES)
        if name.startswith(folder)
    }

    found = {path.name for path in (ROOT / "deploy" / "debian").iterdir() if path.is_file()}

    assert found - named - installed == set()
    assert named - found == set(), "a named file that is gone"
    assert all(area(folder + name) == "product" for name in installed)


def test_the_files_are_gathered_into_a_row_for_each_language() -> None:
    lines = lines_of_code(BY_FILE)

    assert list(lines.rows) == ["Python", "TypeScript", "CSS", "Shell"]
    assert lines.rows["Python"] == Row(3, 1230, 60, {"product": 1000, "tests": 200, "tooling": 30})
    assert lines.rows["TypeScript"] == Row(2, 450, 20, {"product": 300, "tests": 150, "tooling": 0})
    # Two of cloc's names for a shell are one row.
    assert lines.rows["Shell"] == Row(2, 100, 10, {"product": 40, "tests": 0, "tooling": 60})
    assert (lines.docs_files, lines.docs_lines) == (2, 332)
    assert lines.cloc == "2.06"
    assert lines.code == 1230 + 450 + 500 + 100, "no lock file, no word list, no Markdown"


def test_python_and_typescript_come_first_and_the_rest_by_size_then_name() -> None:
    by_file = {
        "./a.sql": counted("SQL", 7),
        "./a.css": counted("CSS", 7),
        "./a.yml": counted("YAML", 900),
        "./web/src/a.ts": counted("TypeScript", 2),
        "./a.py": counted("Python", 1),
    }

    assert list(lines_of_code(by_file).rows) == ["Python", "TypeScript", "YAML", "CSS", "SQL"]


def test_the_table_and_the_sentences_under_it() -> None:
    assert render_lines(lines_of_code(BY_FILE)) == [
        "### Lines of code",
        "",
        "| Language | Files | Code | Comments | Product | Tests | Tooling |",
        "|---|--:|--:|--:|--:|--:|--:|",
        "| Python | 3 | 1,230 | 60 | 1,000 | 200 | 30 |",
        "| TypeScript | 2 | 450 | 20 | 300 | 150 | - |",
        "| CSS | 1 | 500 | 2 | 500 | - | - |",
        "| Shell | 2 | 100 | 10 | 40 | - | 60 |",
        "| **All** | **8** | **2,280** | **92** | **1,840** | **350** | **90** |",
        "",
        "These lines of code are segl's own. They do not count the dependencies listed below. "
        "Counted by cloc 2.06 in the files git tracks. Product is what the package installs "
        "and runs. Tests check it. Tooling builds and releases it. Lock files, word lists, "
        "and the license texts of other projects are left out. The documentation is another "
        "332 lines of Markdown in 2 files.",
    ]


def test_the_statement_says_whose_lines_these_are_and_whose_they_are_not() -> None:
    statement = render_lines(lines_of_code(BY_FILE))[-1]

    assert statement.startswith(
        "These lines of code are segl's own. They do not count the dependencies listed below."
    )


def test_large_numbers_have_separators_and_a_missing_version_is_left_out() -> None:
    lines = Lines({"Python": Row(1200, 20488, 5026, {"product": 0, "tests": 20488, "tooling": 0})})
    lines.docs_lines, lines.docs_files = 4041, 48

    table = render_lines(lines)

    assert table[4] == "| Python | 1,200 | 20,488 | 5,026 | - | 20,488 | - |"
    assert (
        table[5] == "| **All** | **1,200** | **20,488** | **5,026** | **-** | **20,488** | **-** |"
    )
    assert "Counted by cloc in the files git tracks." in table[-1]
    assert table[-1].endswith("another 4,041 lines of Markdown in 48 files.")


def test_cloc_is_asked_for_the_files_git_tracks_one_by_one(tmp_path: Path, fake_runner) -> None:
    runner = fake_runner(tmp_path, {("cloc",): json.dumps(BY_FILE)})

    lines = count_lines(runner)

    assert runner.calls == [["cloc", "--vcs=git", "--by-file", "--json", "--quiet", "."]]
    assert lines.code == 2280


@pytest.mark.parametrize(
    ("reply", "said"),
    [
        (CommandError("command not found: cloc"), "cloc failed: command not found: cloc"),
        ("", "cloc failed: "),
        ("not json", "cloc failed: "),
        ("[]", "cloc counted no file"),
        (json.dumps({"header": {"cloc_version": "2.06"}}), "cloc counted no file"),
        (json.dumps({"./README.md": counted("Markdown", 5)}), "cloc counted no file"),
    ],
)
def test_a_count_that_cannot_be_made_stops_the_notes(
    tmp_path: Path, fake_runner, reply: object, said: str
) -> None:
    runner = fake_runner(tmp_path, {("cloc",): reply})

    with pytest.raises(SystemExit) as stopped:
        count_lines(runner)

    assert str(stopped.value).startswith(said)


def test_the_fake_count_of_the_other_release_tests_is_a_real_shape(
    tmp_path: Path, fake_runner
) -> None:
    lines = count_lines(fake_runner(tmp_path))

    assert lines.code == 1234
