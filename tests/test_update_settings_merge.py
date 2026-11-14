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

"""New settings go into a site's file, and every line the site wrote stays."""

import re
import tomllib
from pathlib import Path

import pytest

from segl.config import DEFAULTS, load_settings
from segl.update import settings_merge
from segl.update.settings_merge import Merged, SettingsMergeError, merge_settings

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = (ROOT / "deploy" / "segl.toml.example").read_text(encoding="utf-8")

# A small example, in the shape of the shipped one: a note with no key, then
# paragraphs of keys, some with a note of their own inside a paragraph.
EXAMPLE = """\
# segl configuration. Every key is listed.

# Where segl listens.
bind = "127.0.0.1:8888"

# Who may edit.
access_codes = []
access_secret = ""

# Where the data is.
database = "/opt/segl/var/segl.sqlite"
assets_dir = "/opt/segl/var/assets"
# The words for names.
display_names = "/opt/segl/etc/display-names.txt"

# How many revisions.
history_limit = 50

# Where updates come from.
update_url = "https://example.com/segl"

# The proxy for updates.
update_proxy = ""
"""


def without(text: str, *keys: str) -> str:
    """Return ``text`` without the lines that set ``keys``."""
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not any(re.match(rf"{key}\s*=", line) for key in keys)
    )


def test_a_file_that_has_every_key_is_not_changed() -> None:
    merged = merge_settings(EXAMPLE, EXAMPLE)

    assert merged.text == EXAMPLE
    assert merged.added == []
    assert merged.lines == []


def test_the_shipped_example_merged_into_itself_is_not_changed() -> None:
    merged = merge_settings(SHIPPED, SHIPPED)

    assert merged.text == SHIPPED
    assert merged.added == []


def test_a_new_key_at_the_end_goes_in_with_its_note() -> None:
    site = EXAMPLE.split("# Where updates come from.")[0].rstrip("\n") + "\n"

    merged = merge_settings(site, EXAMPLE)

    assert merged.added == ["update_url", "update_proxy"]
    assert merged.text == EXAMPLE
    assert merged.lines == [
        "# Where updates come from.",
        'update_url = "https://example.com/segl"',
        "# The proxy for updates.",
        'update_proxy = ""',
    ]


def test_every_line_the_site_wrote_stays_as_it_is() -> None:
    site = (
        "# Our own first line.\n"
        'bind = "10.1.2.3:9000"   # behind the load balancer\n'
        "\n"
        "# Night shift and day shift.\n"
        'access_codes = ["maple river 42"]\n'
        "access_secret = 'a-secret-that-is-long-enough-0123456789'\n"
        "\n"
        "history_limit   =   7\n"
        'database = "/srv/segl/segl.sqlite"\n'
    )

    merged = merge_settings(site, EXAMPLE)

    kept = merged.text.splitlines(keepends=True)
    position = 0
    for line in site.splitlines(keepends=True):
        # Each of the site's lines is there, whole, and in the site's order.
        position = kept.index(line, position) + 1
    assert merged.added == ["assets_dir", "display_names", "update_url", "update_proxy"]
    values = tomllib.loads(merged.text)
    assert values["bind"] == "10.1.2.3:9000"
    assert values["history_limit"] == 7
    assert values["access_codes"] == ["maple river 42"]
    assert values["update_proxy"] == ""


def test_a_key_in_the_middle_goes_after_the_key_before_it_in_the_example() -> None:
    site = without(EXAMPLE, "assets_dir")

    merged = merge_settings(site, EXAMPLE)

    assert merged.added == ["assets_dir"]
    # In the same paragraph as the key before it: no blank line between them.
    assert merged.text == EXAMPLE


def test_a_key_with_a_note_inside_a_paragraph_brings_the_note() -> None:
    site = without(EXAMPLE, "display_names").replace("# The words for names.\n", "")

    merged = merge_settings(site, EXAMPLE)

    assert merged.added == ["display_names"]
    assert merged.text == EXAMPLE


def test_a_key_that_starts_a_paragraph_goes_after_the_paragraph_before_it() -> None:
    site = EXAMPLE.replace("\n# How many revisions.\nhistory_limit = 50\n", "")

    merged = merge_settings(site, EXAMPLE)

    assert merged.added == ["history_limit"]
    assert merged.text == EXAMPLE


def test_a_new_paragraph_goes_after_all_of_the_paragraph_before_it() -> None:
    # The key before it in the example is not the last line of its paragraph
    # in the site's file: the site wrote a note and a key of its own under it.
    site = (
        "# How many revisions.\n"
        "history_limit = 50\n"
        "# Seven was too few for the night shift.\n"
        'access_secret = ""\n'
        "\n"
        "# Ours, at the end.\n"
        'bind = "127.0.0.1:8888"\n'
    )

    merged = merge_settings(site, EXAMPLE)

    lines = merged.text.splitlines()
    at = lines.index("# Where updates come from.")
    assert lines[at - 2 : at] == ['access_secret = ""', ""]
    assert lines[at + 1] == 'update_url = "https://example.com/segl"'


def test_a_key_the_site_commented_out_counts_as_there() -> None:
    site = EXAMPLE.replace('update_proxy = ""', '#update_proxy = "http://old.example.com:3128"')
    other = EXAMPLE.replace("history_limit = 50", "# history_limit = 50")

    assert merge_settings(site, EXAMPLE).added == []
    assert merge_settings(other, EXAMPLE).text == other


def test_a_value_over_several_lines_is_not_cut_in_two() -> None:
    site = (
        'bind = "127.0.0.1:8888"\n'
        "access_codes = [\n"
        '    "maple river 42",\n'
        "\n"
        '    "night shift 1836",\n'
        "]\n"
        'database = "/opt/segl/var/segl.sqlite"\n'
    )

    merged = merge_settings(site, EXAMPLE)

    values = tomllib.loads(merged.text)
    assert values["access_codes"] == ["maple river 42", "night shift 1836"]
    # access_secret follows access_codes in the example, so it goes after the
    # whole list, not after the list's first line.
    lines = merged.text.splitlines()
    assert lines[lines.index("]") + 1] == 'access_secret = ""'


def test_text_inside_a_string_is_not_read_as_a_key() -> None:
    site = (
        'bind = "127.0.0.1:8888"\n'
        'access_secret = """\n'
        "update_proxy = not a key, only text in a string that is long enough\n"
        '"""\n'
    )

    merged = merge_settings(site, EXAMPLE)

    assert "update_proxy" in merged.added
    assert tomllib.loads(merged.text)["update_proxy"] == ""


def test_an_empty_file_gets_every_key() -> None:
    merged = merge_settings("", EXAMPLE)

    assert merged.added == list(tomllib.loads(EXAMPLE))
    assert tomllib.loads(merged.text) == tomllib.loads(EXAMPLE)


def test_a_file_with_none_of_the_earlier_keys_gets_them_at_its_end() -> None:
    site = "# Only this.\nhistory_limit = 9\n"

    merged = merge_settings(site, EXAMPLE)

    assert merged.text.startswith(site)
    assert tomllib.loads(merged.text)["history_limit"] == 9
    assert tomllib.loads(merged.text)["bind"] == "127.0.0.1:8888"


def test_a_file_without_a_last_newline_gets_one_before_what_is_added() -> None:
    site = EXAMPLE.split("\n# The proxy for updates.")[0].rstrip("\n")
    assert not site.endswith("\n")

    merged = merge_settings(site, EXAMPLE)

    assert merged.text == EXAMPLE


def test_windows_line_endings_are_kept_and_used() -> None:
    site = EXAMPLE.split("\n# The proxy for updates.")[0].replace("\n", "\r\n")

    merged = merge_settings(site, EXAMPLE)

    assert merged.added == ["update_proxy"]
    assert "\n" not in merged.text.replace("\r\n", "")
    assert merged.text.endswith('update_proxy = ""\r\n')


def test_a_file_that_is_not_toml_is_refused() -> None:
    with pytest.raises(SettingsMergeError, match="the settings file is not valid TOML"):
        merge_settings('bind = "unclosed\n', EXAMPLE)


def test_an_example_that_is_not_toml_is_refused() -> None:
    with pytest.raises(SettingsMergeError, match="this version's example settings"):
        merge_settings(EXAMPLE, "bind = \n")


def test_a_key_segl_does_not_know_is_left_for_segl_to_refuse() -> None:
    # A misspelled access_codes must stop segl (docs/SECURITY.md). The merge
    # does not take it out, comment it out, or hide it.
    site = 'acess_codes = ["maple river 42"]\n' + EXAMPLE

    merged = merge_settings(site, EXAMPLE)

    assert merged.text == site


@pytest.mark.parametrize("missing", sorted(DEFAULTS))
def test_each_key_of_the_shipped_example_can_be_put_back(missing: str, tmp_path: Path) -> None:
    site = without(SHIPPED, missing)
    assert missing not in tomllib.loads(site)

    merged = merge_settings(site, SHIPPED)

    assert merged.added == [missing]
    assert tomllib.loads(merged.text) == tomllib.loads(SHIPPED)
    # The site's lines are all still there, in order.
    kept = iter(merged.text.splitlines())
    assert all(line in kept for line in site.splitlines())
    # And segl takes the merged file.
    path = tmp_path / "segl.toml"
    path.write_text(merged.text, encoding="utf-8")
    load_settings(path)


def test_the_shipped_example_keeps_one_setting_on_a_line() -> None:
    # The merge reads the example a line at a time.
    keys = re.findall(r"^([a-z_]+) = \S.*$", SHIPPED, flags=re.MULTILINE)

    assert keys == list(DEFAULTS)
    for key in keys:
        line = next(line for line in SHIPPED.splitlines() if line.startswith(f"{key} = "))
        assert tomllib.loads(line) == {key: DEFAULTS[key]}


def test_the_last_check_refuses_a_merge_that_changed_a_value() -> None:
    # The merge never does this. The check is there in case a fault makes it.
    old: dict[str, object] = {"bind": "10.1.2.3:9000", "history_limit": 7}
    defaults = tomllib.loads(EXAMPLE)

    def check(text: str, added: list[str]) -> None:
        settings_merge._check(Merged(text=text, added=added), old, defaults)

    good = 'bind = "10.1.2.3:9000"\nhistory_limit = 7\nupdate_proxy = ""\n'
    check(good, ["update_proxy"])
    with pytest.raises(SettingsMergeError, match="the merge changed bind"):
        check(good.replace("10.1.2.3", "10.1.2.4"), ["update_proxy"])
    with pytest.raises(SettingsMergeError, match="the merge changed history_limit"):
        check('bind = "10.1.2.3:9000"\nupdate_proxy = ""\n', ["update_proxy"])
    with pytest.raises(SettingsMergeError, match="added keys it did not mean to"):
        check(good + 'access_secret = ""\n', ["update_proxy"])
    with pytest.raises(SettingsMergeError, match="gave update_proxy another value"):
        check(good.replace('update_proxy = ""', 'update_proxy = "http://x:1"'), ["update_proxy"])
    with pytest.raises(SettingsMergeError, match="are not valid TOML"):
        check(good + "= =\n", ["update_proxy"])
