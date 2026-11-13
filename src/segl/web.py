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

"""The built web application, and the pages segl makes from it.

``web_dir`` holds what ``npm --prefix web run build`` writes: ``index.html``,
Vite's ``assets/``, the editor's ``fonts/``, and the favicon. Vite builds with
``base: './'``, so ``index.html`` names its files ``./assets/...``. That is
right for a page at segl's root. A slot page, ``/s/N``, is one level down, so
for it every ``./`` becomes ``../`` (docs/ARCHITECTURE.md, "Mount and
navigation"). No URL in a page starts with ``/``, so the same build works
under any path a proxy strips (D2-007).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

INDEX = "index.html"

# The path from a page to segl's root.
ROOT_PAGE = "./"
SLOT_PAGE = "../"

# A URL that Vite wrote relative to index.html.
_RELATIVE_URL = re.compile(r'\b(src|href)="\./')
_HEAD_END = "</head>"


class WebBuildError(Exception):
    """``web_dir`` has an ``index.html`` that segl cannot make a page from."""


@dataclass(frozen=True)
class WebBuild:
    """One build of the web application.

    ``folders`` and ``files`` are the names at the top of the build, other
    than ``index.html``. They are the only static paths segl registers.
    """

    folder: Path
    index: str
    folders: tuple[str, ...]
    files: tuple[str, ...]


def load_web_build(folder: Path) -> WebBuild | None:
    """Read the build in ``folder``. Return None when it has no ``index.html``.

    Raises:
        WebBuildError: When ``index.html`` cannot be read, or has no ``</head>``
            for the page config to go in front of.
    """
    index_file = folder / INDEX
    if not index_file.is_file():
        return None
    try:
        index = index_file.read_text(encoding="utf-8")
        entries = sorted(folder.iterdir())
    except (OSError, UnicodeDecodeError) as exc:
        raise WebBuildError(f"cannot read the web application in {folder}: {exc}") from exc
    if _HEAD_END not in index:
        raise WebBuildError(f"{index_file} has no {_HEAD_END}, so it is not a build of web/")
    # Hidden entries are not part of a build. Symbolic links are not followed.
    visible = [e for e in entries if not e.name.startswith(".") and not e.is_symlink()]
    return WebBuild(
        folder=folder,
        index=index,
        folders=tuple(e.name for e in visible if e.is_dir()),
        files=tuple(e.name for e in visible if e.is_file() and e.name != INDEX),
    )


def page_config(root: str, edit_required: bool) -> str:
    """Return the script element that sets ``window.SEGL_CONFIG``.

    It holds the path to segl's root and whether editing needs an access
    code. No code, no pass, and no secret is ever written into a page.
    """
    config = json.dumps({"root": root, "editRequired": edit_required})
    # No "</script>" can come out of these two values. Escaped anyway, so that
    # a later key cannot end the element early.
    config = config.replace("<", "\\u003c")
    return f"<script>window.SEGL_CONFIG = {config};</script>"


def render_page(index: str, *, root: str, edit_required: bool) -> str:
    """Return ``index.html`` for a page whose path to segl's root is ``root``.

    ``root`` is ``./`` for a page at the root, and ``../`` for a slot page.
    The config script goes at the end of ``<head>``. It is a classic script,
    so it has run before the module script that reads it.
    """
    page = index if root == ROOT_PAGE else _RELATIVE_URL.sub(rf'\1="{root}', index)
    return page.replace(_HEAD_END, f"{page_config(root, edit_required)}\n{_HEAD_END}", 1)
