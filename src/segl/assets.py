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

"""Uploaded files: the bytes of the images on the canvases (D2-028).

A file is stored once, under ``assets_dir``, in a file named by the SHA-256
of its bytes. The name is the only way to ask for it, so no path a browser
sends is ever joined to the folder (docs/SECURITY.md). Which file an image
element means is the slot's file list, in SQLite.
"""

import contextlib
import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

# The image types the pinned editor takes (its IMAGE_MIME_TYPES). An upload
# says which it is, and the browsers are told the same when they fetch it.
MEDIA_TYPES = frozenset(
    {
        "image/svg+xml",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/x-icon",
        "image/avif",
        "image/jfif",
    }
)

_HASH = re.compile(r"[0-9a-f]{64}")


class AssetsError(Exception):
    """The folder for uploaded files cannot be used."""


def is_hash(value: object) -> bool:
    """Return whether ``value`` is a SHA-256 as segl writes it: 64 lowercase hex digits."""
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


class AssetStore:
    """The files under ``assets_dir``. Every method blocks, as the repository's do."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def prepare(self) -> None:
        """Make the folder, and check that segl can write in it.

        Raises:
            AssetsError: When it cannot.
        """
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=self.folder):
                pass
        except OSError as exc:
            raise AssetsError(f"cannot store uploaded files in {self.folder}: {exc}") from exc

    def path(self, name: str) -> Path | None:
        """Return where the file with this hash is kept, or None for any other name."""
        return self.folder / name if is_hash(name) else None

    def has(self, name: str) -> bool:
        path = self.path(name)
        return path is not None and path.is_file()

    def present(self, names: Iterable[str]) -> frozenset[str]:
        """Return the names, of those given, that are stored files."""
        return frozenset(name for name in names if self.has(name))

    def save(self, data: bytes) -> str:
        """Store the bytes and return their hash. Bytes already stored are left alone.

        The file is written beside its place and then moved there, so a
        reader never finds half of one, and it has reached the disk before
        this returns: a head that names it may be called saved.

        Raises:
            OSError: When the folder cannot be written.
        """
        name = hashlib.sha256(data).hexdigest()
        target = self.folder / name
        if target.is_file():
            return name
        self.folder.mkdir(parents=True, exist_ok=True)
        descriptor, partial = tempfile.mkstemp(dir=self.folder, prefix=".upload-")
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(partial, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(partial)
            raise
        _sync_folder(self.folder)
        return name


def _sync_folder(folder: Path) -> None:
    """Put a folder's new entry on the disk, where the system can."""
    try:
        descriptor = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
