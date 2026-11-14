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

"""Where an installed segl keeps what an update reads and writes."""

from dataclasses import dataclass
from pathlib import Path

SERVICE = "segl.service"
NGINX_SERVICE = "nginx.service"

# The package's nginx files, and where docs/DEPLOY.md has a site install each.
# The two site examples are the site's own from the start, and are not here.
NGINX_FILES: tuple[tuple[str, str], ...] = (
    ("segl-http.conf", "conf.d/segl.conf"),
    ("segl-proxy.conf", "snippets/segl-proxy.conf"),
    ("segl-board.conf", "snippets/segl-board.conf"),
)


@dataclass(frozen=True)
class Paths:
    """The files and folders of one installation. Tests point them elsewhere."""

    config_file: Path
    # The package's own copies: the example settings, the nginx files, the signers.
    share: Path
    # Root's alone: downloaded packages, what was saved, the record, the lock.
    update_dir: Path
    # The installed `segl`, run after an install to merge and to check.
    binary: Path
    nginx_dir: Path

    @property
    def etc(self) -> Path:
        """Return the folder of the settings and the display names."""
        return self.config_file.parent

    @property
    def example(self) -> Path:
        """Return this version's settings file, with every key and its note."""
        return self.share / "segl.toml.example"

    @property
    def signers(self) -> Path:
        """Return the keys a release may be signed with."""
        return self.share / "release-signers"

    @property
    def cache(self) -> Path:
        """Return the folder of downloaded and verified releases, one a version."""
        return self.update_dir / "cache"

    @property
    def backups(self) -> Path:
        """Return the folder of what was saved before each change."""
        return self.update_dir / "backups"

    @property
    def merged(self) -> Path:
        """Return the package's nginx files as they were last merged into the site's."""
        return self.update_dir / "merged" / "nginx"

    @property
    def record(self) -> Path:
        """Return the record of the last update."""
        return self.update_dir / "last-update.json"

    @property
    def lock(self) -> Path:
        """Return the file whose lock lets one update run at a time."""
        return self.update_dir / "update.lock"

    def nginx_pairs(self) -> list[tuple[str, Path, Path]]:
        """Return each nginx file's name, the package's copy, and the site's."""
        return [
            (name, self.share / "nginx" / name, self.nginx_dir / place)
            for name, place in NGINX_FILES
        ]


INSTALLED = Paths(
    config_file=Path("/opt/segl/etc/segl.toml"),
    share=Path("/opt/segl/share"),
    update_dir=Path("/opt/segl/update"),
    binary=Path("/opt/segl/venv/bin/segl"),
    nginx_dir=Path("/etc/nginx"),
)
