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

"""versions.toml is the only version list, and its mirrors agree with it (D2-020)."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = tomllib.loads((ROOT / "versions.toml").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
PYTHON_PIN: str = VERSIONS["runtime"]["python"]
EXACT = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.]*)")


def exact_pins(requirements: list[str]) -> dict[str, str]:
    """Return name → version, and fail on a requirement that is not ``name==version``."""
    pins: dict[str, str] = {}
    for requirement in requirements:
        match = EXACT.fullmatch(requirement)
        assert match, f"{requirement!r} is not an exact name==version pin"
        pins[match.group(1)] = match.group(2)
    return pins


def python_minor() -> tuple[int, int]:
    major, minor, _patch = (int(part) for part in PYTHON_PIN.split("."))
    return major, minor


def test_the_python_pin_is_an_exact_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", PYTHON_PIN)


def test_python_version_file_matches_the_pin() -> None:
    assert (ROOT / ".python-version").read_text(encoding="utf-8") == f"{PYTHON_PIN}\n"


def test_requires_python_is_the_pins_minor() -> None:
    major, minor = python_minor()

    assert PYPROJECT["project"]["requires-python"] == f">={major}.{minor},<{major}.{minor + 1}"


def test_ruff_and_ty_target_the_pins_minor() -> None:
    major, minor = python_minor()

    assert PYPROJECT["tool"]["ruff"]["target-version"] == f"py{major}{minor}"
    assert PYPROJECT["tool"]["ty"]["environment"]["python-version"] == f"{major}.{minor}"


def test_project_version_and_license_match() -> None:
    assert PYPROJECT["project"]["version"] == VERSIONS["project"]["version"]
    assert PYPROJECT["project"]["license"] == VERSIONS["project"]["license"] == "Apache-2.0"


def test_every_direct_dependency_is_listed_at_the_same_version() -> None:
    groups = PYPROJECT["dependency-groups"]
    mirrors = {
        "dependencies": PYPROJECT["project"]["dependencies"],
        "dev": groups["dev"],
        "docs": groups["docs"],
        "build": PYPROJECT["build-system"]["requires"],
    }

    assert set(groups) == {"dev", "docs"}, "a new dependency group needs a versions.toml table"
    assert "optional-dependencies" not in PYPROJECT["project"]
    for table, requirements in mirrors.items():
        assert exact_pins(requirements) == VERSIONS["python"][table], f"[python.{table}]"
    assert set(VERSIONS["python"]) == set(mirrors)


def test_md2html_inline_metadata_matches_the_docs_pins() -> None:
    script = (ROOT / "tools" / "md2html" / "md2html.py").read_text(encoding="utf-8")
    block = re.search(r"^# /// script\n(.*?)^# ///$", script, flags=re.MULTILINE | re.DOTALL)
    assert block
    metadata = tomllib.loads(re.sub(r"^# ?", "", block.group(1), flags=re.MULTILINE))

    assert exact_pins(metadata["dependencies"]) == VERSIONS["python"]["docs"]
