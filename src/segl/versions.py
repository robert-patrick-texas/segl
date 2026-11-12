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

"""Read versions.toml, the only version list (D2-020).

An installed package carries a copy of the file beside this module, which the
build puts there. A checkout has no such copy and reads the file at the
repository root.
"""

import tomllib
from pathlib import Path
from typing import Any

FILE_NAME = "versions.toml"
PACKAGE_DIR = Path(__file__).resolve().parent


def find_versions_file(package_dir: Path = PACKAGE_DIR) -> Path:
    """Return the packaged copy of versions.toml, or the checkout's file.

    Raises:
        FileNotFoundError: When neither file exists.
    """
    packaged = package_dir / FILE_NAME
    if packaged.is_file():
        return packaged
    # A checkout: <root>/src/segl/versions.py, with pyproject.toml at <root>.
    if len(package_dir.parents) >= 2:
        root = package_dir.parents[1]
        checkout = root / FILE_NAME
        if checkout.is_file() and (root / "pyproject.toml").is_file():
            return checkout
    raise FileNotFoundError(f"{FILE_NAME} is not in {package_dir} or at a checkout root above it")


def load_versions(package_dir: Path = PACKAGE_DIR) -> dict[str, Any]:
    """Return the parsed contents of versions.toml."""
    return tomllib.loads(find_versions_file(package_dir).read_text(encoding="utf-8"))


def app_version(package_dir: Path = PACKAGE_DIR) -> str:
    """Return the application version, ``project.version`` in versions.toml."""
    return str(load_versions(package_dir)["project"]["version"])
