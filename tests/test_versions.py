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

"""Both lookups of versions.toml: a checkout's root file, and the packaged copy."""

import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from segl import cli, versions

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILE = ROOT / "versions.toml"
ROOT_VERSION = tomllib.loads(ROOT_FILE.read_text(encoding="utf-8"))["project"]["version"]


def test_a_checkout_reads_the_file_at_the_repository_root() -> None:
    assert versions.PACKAGE_DIR == ROOT / "src" / "segl"
    assert versions.find_versions_file() == ROOT_FILE
    assert versions.app_version() == ROOT_VERSION


def test_an_installed_package_reads_its_own_copy(tmp_path: Path) -> None:
    package_dir = tmp_path / "site-packages" / "segl"
    package_dir.mkdir(parents=True)
    (package_dir / "versions.toml").write_text('[project]\nversion = "9.8.7"\n', encoding="utf-8")

    assert versions.find_versions_file(package_dir) == package_dir / "versions.toml"
    assert versions.app_version(package_dir) == "9.8.7"


def test_the_packaged_copy_wins_over_a_checkout_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "versions.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    package_dir = tmp_path / "src" / "segl"
    package_dir.mkdir(parents=True)

    assert versions.app_version(package_dir) == "1.0.0"

    (package_dir / "versions.toml").write_text('[project]\nversion = "2.0.0"\n', encoding="utf-8")

    assert versions.app_version(package_dir) == "2.0.0"


def test_no_file_is_an_error_that_names_the_file(tmp_path: Path) -> None:
    package_dir = tmp_path / "site-packages" / "segl"
    package_dir.mkdir(parents=True)
    # A versions.toml two folders up does not count without pyproject.toml beside it.
    (tmp_path / "versions.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")

    with pytest.raises(FileNotFoundError, match=r"versions\.toml"):
        versions.find_versions_file(package_dir)


def test_version_flag_prints_the_application_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"segl {ROOT_VERSION}\n"


def test_console_module_prints_the_application_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "segl", "--version"], check=True, capture_output=True, text=True
    )

    assert completed.stdout == f"segl {ROOT_VERSION}\n"


def test_the_built_wheel_carries_versions_toml_the_migrations_and_the_empty_scene(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH, so the wheel cannot be built")
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
        check=True,
        capture_output=True,
        text=True,
    )
    (wheel,) = tmp_path.glob("segl-*.whl")

    with zipfile.ZipFile(wheel) as archive:
        assert archive.read("segl/versions.toml") == ROOT_FILE.read_bytes()
        assert "segl/versions.py" in archive.namelist()
        # The SQL files the repository applies at startup (docs/DATA-MODEL.md).
        for migration in sorted((ROOT / "src" / "segl" / "migrations").glob("*.sql")):
            assert archive.read(f"segl/migrations/{migration.name}") == migration.read_bytes()
        assert "segl/migrations/0001_slots.sql" in archive.namelist()
        # The scene a new slot starts with.
        empty_scene = ROOT / "src" / "segl" / "empty_scene.json"
        assert archive.read("segl/empty_scene.json") == empty_scene.read_bytes()
