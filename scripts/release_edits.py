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

"""Text edits to versions.toml and the files that mirror it.

The standard library reads TOML and does not write it, and versions.toml
carries comments worth keeping, so each edit changes one line or one block.
Every function takes text and returns text.
"""

from __future__ import annotations

import json
import re


class EditError(ValueError):
    """The text did not hold the line an edit expected."""


def toml_key(name: str) -> str:
    """Return ``name`` as a TOML key, quoted when it must be."""
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else json.dumps(name)


def toml_string(value: str) -> str:
    """Return ``value`` as a one-line TOML basic string."""
    return json.dumps(" ".join(value.split()), ensure_ascii=False)


def set_entry(text: str, table: str, key: str, value: str) -> str:
    """Set ``key`` in ``[table]`` to the string ``value``, keeping any comment.

    Raises:
        EditError: When the table has no such key.
    """
    lines = text.split("\n")
    pattern = re.compile(
        rf'^(\s*(?:{re.escape(key)}|{re.escape(json.dumps(key))})\s*=\s*)"[^"]*"(.*)$'
    )
    inside = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            inside = stripped == f"[{table}]"
            continue
        match = pattern.match(line) if inside else None
        if match:
            lines[index] = f"{match[1]}{toml_string(value)}{match[2]}"
            return "\n".join(lines)
    raise EditError(f"[{table}] has no {key!r} entry")


def clear_hold(text: str, name: str) -> str:
    """Remove the ``[held.<name>]`` table, if there is one."""
    lines = text.split("\n")
    header = f"[held.{toml_key(name)}]"
    for start, line in enumerate(lines):
        if line.strip() != header:
            continue
        end = start + 1
        while end < len(lines) and lines[end].strip() and not lines[end].lstrip().startswith("["):
            end += 1
        if start > 0 and not lines[start - 1].strip():
            start -= 1
        return "\n".join(lines[:start] + lines[end:])
    return text


def set_hold(text: str, name: str, version: str, skipped: str, reason: str, since: str) -> str:
    """Write the ``[held.<name>]`` table, replacing an earlier one."""
    lines = clear_hold(text, name).split("\n")
    block = [
        "",
        f"[held.{toml_key(name)}]",
        f"version = {toml_string(version)}",
        f"skipped = {toml_string(skipped)}",
        f"reason = {toml_string(reason)}",
        f"since = {toml_string(since)}",
    ]
    for index, line in enumerate(lines):
        if line.strip() == "[held]":
            return "\n".join(lines[: index + 1] + block + lines[index + 1 :])
    return "\n".join(lines).rstrip("\n") + "\n" + "\n".join(block) + "\n"


def replace_once(text: str, pattern: str, replacement: str, what: str) -> str:
    """Replace every match of ``pattern``, and fail when there is none.

    Raises:
        EditError: When ``pattern`` does not match.
    """
    changed, count = re.subn(pattern, lambda _match: replacement, text, flags=re.MULTILINE)
    if count == 0:
        raise EditError(f"{what} not found")
    return changed


def set_requirement(text: str, name: str, old: str, new: str) -> str:
    """Move an exact ``name==old`` requirement to ``new``.

    This serves pyproject.toml and md2html's inline script metadata.
    """
    pattern = rf"(?<![\w.-]){re.escape(name)}=={re.escape(old)}(?![\w.])"
    return replace_once(text, pattern, f"{name}=={new}", f"{name}=={old}")


def set_package_json(text: str, name: str, old: str, new: str) -> str:
    """Move an exact ``"name": "old"`` entry of web/package.json to ``new``."""
    pattern = rf"{re.escape(json.dumps(name))}(\s*:\s*){re.escape(json.dumps(old))}"
    changed, count = re.subn(pattern, lambda m: f"{json.dumps(name)}{m[1]}{json.dumps(new)}", text)
    if count == 0:
        raise EditError(f'"{name}": "{old}" not found')
    return changed


def minor_of(version: str) -> tuple[str, str]:
    """Return the major and minor parts of ``X.Y.Z`` as text."""
    major, minor, *_rest = version.split(".")
    return major, minor


def set_python_minor(text: str, old: str, new: str) -> str:
    """Move pyproject.toml's ``requires-python`` and the ruff and ty targets."""
    (old_major, old_minor), (major, minor) = minor_of(old), minor_of(new)
    following = f"{major}.{int(minor) + 1}"
    text = replace_once(
        text,
        r'^requires-python = "[^"]*"',
        f'requires-python = ">={major}.{minor},<{following}"',
        "requires-python",
    )
    text = replace_once(
        text,
        rf'^target-version = "py{old_major}{old_minor}"',
        f'target-version = "py{major}{minor}"',
        "ruff target-version",
    )
    return replace_once(
        text,
        rf'^python-version = "{old_major}\.{old_minor}"',
        f'python-version = "{major}.{minor}"',
        "ty python-version",
    )


def set_action(text: str, repo: str, old_ref: str, new_ref: str, new_note: str = "") -> str:
    """Move every ``uses: repo[/path]@old_ref`` line to ``new_ref``.

    ``new_note`` replaces the version in the comment after a commit pin.
    """
    pattern = re.compile(
        rf"^(\s*(?:-\s*)?uses:\s*[\"']?{re.escape(repo)}(?:/[^@\s]+)?@){re.escape(old_ref)}"
        rf"(?![\w.])([\"']?)(\s*#.*)?$",
        flags=re.MULTILINE,
    )

    def moved(match: re.Match[str]) -> str:
        comment = f" # {new_note}" if new_note else (match[3] or "")
        return f"{match[1]}{new_ref}{match[2]}{comment}"

    changed, count = pattern.subn(moved, text)
    if count == 0:
        raise EditError(f"{repo}@{old_ref} not found")
    return changed
