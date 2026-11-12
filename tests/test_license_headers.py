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

"""Every first-party source file starts with the license header in CONTRIBUTING.md."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# web/src joins the list of folders once T04 creates it.
SOURCE_DIRS = ("src", "tests", "scripts", "web/src")
# Suffix → the line-comment marker that carries the header.
LINE_COMMENT = {
    ".py": "#",
    ".ts": "//",
    ".tsx": "//",
    ".js": "//",
    ".jsx": "//",
    ".mjs": "//",
    ".cjs": "//",
}
SKIP_DIRS = {"__pycache__", "node_modules"}


def header_lines() -> list[str]:
    """Return the header from the first ``text`` block under "License header"."""
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    section = text.split("## License header", 1)[1]
    block = re.search(r"^```text\n(.*?)^```$", section, flags=re.MULTILINE | re.DOTALL)
    assert block, "CONTRIBUTING.md has no ```text block under 'License header'"
    return block.group(1).rstrip("\n").split("\n")


def expected_header(suffix: str) -> list[str]:
    marker = LINE_COMMENT[suffix]
    return [f"{marker} {line}" if line else marker for line in header_lines()]


def source_files() -> list[Path]:
    found: list[Path] = []
    for name in SOURCE_DIRS:
        folder = ROOT / name
        if not folder.is_dir():
            continue
        found.extend(
            path
            for path in folder.rglob("*")
            if path.is_file()
            and path.suffix in LINE_COMMENT
            and SKIP_DIRS.isdisjoint(path.relative_to(ROOT).parts)
        )
    return sorted(found)


def missing_header(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    expected = expected_header(path.suffix)
    return lines[: len(expected)] != expected


def test_the_header_is_the_apache_notice() -> None:
    lines = header_lines()

    assert lines[0] == "Copyright 2026 segl contributors"
    assert "    http://www.apache.org/licenses/LICENSE-2.0" in lines


def test_the_checked_folders_hold_source_files() -> None:
    folders = {path.relative_to(ROOT).parts[0] for path in source_files()}

    assert {"src", "tests", "scripts"} <= folders


def test_every_source_file_starts_with_the_header() -> None:
    missing = [str(path.relative_to(ROOT)) for path in source_files() if missing_header(path)]

    assert not missing, "no license header (CONTRIBUTING.md): " + ", ".join(missing)


@pytest.mark.parametrize("suffix", [".py", ".ts"])
def test_a_file_without_the_header_is_caught(tmp_path: Path, suffix: str) -> None:
    header = "\n".join(expected_header(suffix))
    good = tmp_path / f"good{suffix}"
    good.write_text(f"{header}\n\ncode\n", encoding="utf-8")
    script = tmp_path / f"script{suffix}"
    script.write_text(f"#!/usr/bin/env run\n{header}\n", encoding="utf-8")
    bare = tmp_path / f"bare{suffix}"
    bare.write_text("code\n", encoding="utf-8")
    altered = tmp_path / f"altered{suffix}"
    altered.write_text(header.replace("2026", "2025") + "\n", encoding="utf-8")

    assert not missing_header(good)
    assert not missing_header(script)
    assert missing_header(bare)
    assert missing_header(altered)
