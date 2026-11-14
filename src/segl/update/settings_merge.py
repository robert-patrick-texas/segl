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

"""Add this version's new settings to a site's settings file, and nothing else.

Each release ships ``segl.toml.example``: every key at its default, with a
note above it. A site's ``segl.toml`` started as a copy of some release's
example and was edited since. After an upgrade the site's file lacks the keys
the new release added. This puts each of them in, with its note, where the
example has it: after the key that comes before it there.

Every line the site's file already has stays as it is, byte for byte: the
values, the order, and the site's own comments. A key the site commented out
counts as there. The merged text must parse, hold every value the file held,
and give each added key the example's value, or nothing is written.

The example keeps one setting on a line. The site's file need not.
"""

import re
import tomllib
from dataclasses import dataclass, field

_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)[ \t]*=")
_COMMENTED_KEY = re.compile(r"#[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=")


class SettingsMergeError(Exception):
    """The settings file cannot be merged. Nothing was changed."""


@dataclass(frozen=True)
class _Unit:
    """One key of the example: its line, and the comment lines right above it."""

    key: str
    comment: tuple[str, ...]
    line: str
    # Whether a blank line, or the start of the file, comes before it.
    starts_paragraph: bool


@dataclass
class Merged:
    """A merged settings file, and the keys that were added to it."""

    text: str
    added: list[str] = field(default_factory=list)
    # The lines that were put in, for a preview. They come from the example,
    # so they hold nothing of the site's.
    lines: list[str] = field(default_factory=list)


def _units(example: str) -> list[_Unit]:
    units: list[_Unit] = []
    comment: list[str] = []
    after_blank = True
    for line in example.splitlines():
        found = _KEY.match(line)
        if found:
            units.append(_Unit(found[1], tuple(comment), line, after_blank))
            comment, after_blank = [], False
        elif line.startswith("#"):
            comment.append(line)
        else:
            # A blank line ends a paragraph. A note with no key under it, such
            # as the file's first lines, belongs to no key.
            comment, after_blank = [], not line.strip()
    return units


def _parse(text: str, what: str) -> dict[str, object]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsMergeError(f"{what} is not valid TOML: {exc}") from exc


def _statement_end(lines: list[str], start: int) -> int:
    """Return the index of the last line of the statement that starts at ``start``.

    A value may run over several lines: a list, or a string in triple quotes.
    The statement ends at the first line where it parses on its own.
    """
    for end in range(start, len(lines)):
        try:
            tomllib.loads("".join(lines[start : end + 1]))
        except tomllib.TOMLDecodeError:
            continue
        return end
    return start


def _key_at(line: str) -> str | None:
    found = _KEY.match(line) or _COMMENTED_KEY.match(line)
    return found[1] if found else None


def _find(lines: list[str], key: str) -> int | None:
    """Return the index of the line that sets ``key``, or has it commented out."""
    index = 0
    while index < len(lines):
        if _key_at(lines[index]) == key:
            return index
        # Skip the rest of a value that runs over several lines, so that text
        # inside it is not read as a key.
        index = _statement_end(lines, index) + 1 if _KEY.match(lines[index]) else index + 1
    return None


def _paragraph_end(lines: list[str], index: int) -> int:
    """Return the index of the last line of the paragraph that holds line ``index``."""
    end = _statement_end(lines, index) if _KEY.match(lines[index]) else index
    while end + 1 < len(lines) and lines[end + 1].strip():
        nxt = end + 1
        end = _statement_end(lines, nxt) if _KEY.match(lines[nxt]) else nxt
    return end


def merge_settings(current: str, example: str) -> Merged:
    """Return ``current`` with the keys of ``example`` that it lacks.

    Raises:
        SettingsMergeError: When either text is not valid TOML, or the merged
            text does not hold what it must. The second means a fault in this
            code, and the message says so.
    """
    old = _parse(current, "the settings file")
    defaults = _parse(example, "this version's example settings")
    units = _units(example)
    newline = "\r\n" if "\r\n" in current else "\n"
    lines = current.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    merged = Merged(text=current)
    order = [unit.key for unit in units]
    for place, unit in enumerate(units):
        if unit.key in old or _find(lines, unit.key) is not None:
            continue
        block = [text + newline for text in (*unit.comment, unit.line)]
        before = next(
            (at for key in reversed(order[:place]) if (at := _find(lines, key)) is not None),
            None,
        )
        if before is None:
            # Nothing that comes before it in the example is in the file.
            at = len(lines)
            block = ([newline] if lines and lines[-1].strip() else []) + block
        elif unit.starts_paragraph:
            at = _paragraph_end(lines, before) + 1
            block = [newline, *block]
        else:
            at = _statement_end(lines, before) + 1 if _KEY.match(lines[before]) else before + 1
        lines[at:at] = block
        merged.added.append(unit.key)
        merged.lines += [text.rstrip("\r\n") for text in block if text.strip()]
    merged.text = "".join(lines)
    _check(merged, old, defaults)
    return merged


def _check(merged: Merged, old: dict[str, object], defaults: dict[str, object]) -> None:
    """Hold the merged text to what it must be, before anyone writes it."""
    fault = "nothing was written (this is a fault in segl: please report it)"
    try:
        new = tomllib.loads(merged.text)
    except tomllib.TOMLDecodeError as exc:
        said = f"the merged settings are not valid TOML ({exc}); {fault}"
        raise SettingsMergeError(said) from exc
    changed = sorted(key for key, value in old.items() if key not in new or new[key] != value)
    if changed:
        raise SettingsMergeError(f"the merge changed {', '.join(changed)}; {fault}")
    if set(new) - set(old) != set(merged.added):
        raise SettingsMergeError(f"the merge added keys it did not mean to; {fault}")
    wrong = sorted(key for key in merged.added if new[key] != defaults[key])
    if wrong:
        raise SettingsMergeError(f"the merge gave {', '.join(wrong)} another value; {fault}")
