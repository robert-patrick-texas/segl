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

"""A release's version: ``MAJOR.MINOR.PATCH``, as ``scripts/release.py cut`` writes it."""

import re
from dataclasses import dataclass
from typing import Self

# 0.1.0 in versions.toml and in the package's name, v0.1.0 as the tag.
_PATTERN = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
ARCH = "amd64"


@dataclass(frozen=True, order=True)
class Version:
    """One release. Versions order by their three numbers."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read ``0.1.0`` or ``v0.1.0``.

        Raises:
            ValueError: When the text is not three numbers. A pre-release or
                a build suffix is not a release an update installs.
        """
        found = _PATTERN.fullmatch(text.strip())
        if found is None:
            raise ValueError(f"{text!r} is not a version such as 0.1.0")
        return cls(*(int(part) for part in found.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def tag(self) -> str:
        """Return the release's tag, such as ``v0.1.0``."""
        return f"v{self}"

    @property
    def package(self) -> str:
        """Return the package's file name, such as ``segl_0.1.0_amd64.deb``."""
        return f"segl_{self}_{ARCH}.deb"


PACKAGE_NAME = re.compile(rf"segl_(\d+\.\d+\.\d+)_{ARCH}\.deb")
