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

"""Settings: every key in docs/DEPLOY.md, the two sets of defaults, and refusals."""

import json
import re
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import ClassVar, Self

import pytest
from harness import DISPLAY_NAMES_FILE

from segl import app, cli
from segl.assets import AssetStore
from segl.config import (
    DEFAULT_BIND,
    DEFAULTS,
    ConfigError,
    Settings,
    is_edit_token,
    load_settings,
    parse_bind,
    parse_trusted_proxies,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "deploy" / "segl.toml.example"

PRODUCTION = Settings(
    host="127.0.0.1",
    port=8888,
    trusted_proxies=("127.0.0.1", "::1"),
    edit_token="",
    database=Path("/opt/segl/var/segl.sqlite"),
    assets_dir=Path("/opt/segl/var/assets"),
    display_names=Path("/opt/segl/etc/display-names.txt"),
    web_dir=Path("/opt/segl/app/web/dist"),
    max_asset_bytes=10 * 1024 * 1024,
    max_scene_bytes=50 * 1024 * 1024,
    history_limit=50,
    history_interval_seconds=1.0,
    head_flush_seconds=0.2,
)


@pytest.fixture
def empty_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the test in a working directory that has no ``segl.toml``."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(folder: Path, text: str) -> Path:
    config = folder / "segl.toml"
    config.write_text(text, encoding="utf-8")
    return config


def test_a_missing_config_file_gives_the_production_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "absent.toml")

    assert settings == PRODUCTION
    assert settings.bind == DEFAULT_BIND
    assert not settings.edit_required


def test_an_empty_config_file_gives_the_production_defaults(tmp_path: Path) -> None:
    assert load_settings(write(tmp_path, "")) == PRODUCTION


def test_the_example_file_lists_every_key_at_its_default() -> None:
    example = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))

    assert example == dict(DEFAULTS)
    assert list(example) == list(DEFAULTS)
    assert load_settings(EXAMPLE) == PRODUCTION


def test_the_deployment_page_shows_the_example_files_values() -> None:
    page = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    block = re.search(r"^```toml\n(.*?)^```$", page, flags=re.MULTILINE | re.DOTALL)
    assert block

    assert tomllib.loads(block.group(1)) == tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_no_config_flag_gives_the_development_defaults(empty_directory: Path) -> None:
    settings = load_settings()

    assert settings.database == Path("var/segl.sqlite")
    assert settings.assets_dir == Path("var/assets")
    assert settings.display_names == Path("deploy/display-names.txt")
    assert settings.web_dir == Path("web/dist")
    assert settings.bind == DEFAULT_BIND
    assert settings.trusted_proxies == PRODUCTION.trusted_proxies
    assert settings.head_flush_seconds == PRODUCTION.head_flush_seconds


def test_a_local_segl_toml_overrides_the_development_defaults(empty_directory: Path) -> None:
    write(empty_directory, 'bind = "127.0.0.1:9001"\nedit_token = "local"\n')

    settings = load_settings()

    assert (settings.host, settings.port) == ("127.0.0.1", 9001)
    assert settings.edit_required
    assert settings.database == Path("var/segl.sqlite")


def test_a_local_segl_toml_is_not_read_with_a_config_flag(empty_directory: Path) -> None:
    write(empty_directory, 'bind = "127.0.0.1:9001"\n')

    assert load_settings(empty_directory / "absent.toml") == PRODUCTION


def test_every_key_comes_from_the_file(tmp_path: Path) -> None:
    config = write(
        tmp_path,
        """
        bind = "[::1]:9001"
        trusted_proxies = ["10.0.0.5", "192.168.0.0/24", "2001:DB8::1"]
        edit_token = "s3cret"
        database = "data/segl.sqlite"
        assets_dir = "/srv/segl/assets"
        display_names = "names.txt"
        web_dir = "/srv/segl/web"
        max_asset_bytes = 1
        max_scene_bytes = 2
        history_limit = 3
        history_interval_seconds = 0.5
        head_flush_seconds = 4
        """,
    )

    assert load_settings(config) == Settings(
        host="::1",
        port=9001,
        trusted_proxies=("10.0.0.5", "192.168.0.0/24", "2001:db8::1"),
        edit_token="s3cret",
        database=Path("data/segl.sqlite"),
        assets_dir=Path("/srv/segl/assets"),
        display_names=Path("names.txt"),
        web_dir=Path("/srv/segl/web"),
        max_asset_bytes=1,
        max_scene_bytes=2,
        history_limit=3,
        history_interval_seconds=0.5,
        head_flush_seconds=4.0,
    )


def test_the_edit_token_is_not_in_the_settings_repr(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, 'edit_token = "s3cret"\n'))

    assert settings.edit_required
    assert "s3cret" not in repr(settings)


def test_an_ipv6_bind_uses_brackets() -> None:
    assert parse_bind("[::1]:8888") == ("::1", 8888)
    assert replace(PRODUCTION, host="::1").bind == "[::1]:8888"


@pytest.mark.parametrize(
    "value", ["127.0.0.1", ":8888", "host:port", "h:0", "h:65536", "::1:80", 8888]
)
def test_an_unusable_bind_is_refused(value: object) -> None:
    with pytest.raises(ConfigError):
        parse_bind(value)


def test_an_empty_proxy_list_believes_nobody() -> None:
    assert parse_trusted_proxies([]) == ()


@pytest.mark.parametrize(
    "value",
    ["127.0.0.1", ["*"], ["proxy.example"], ["10.0.0.1/8"], [""], [7], ["127.0.0.1", "nope"]],
)
def test_an_unusable_proxy_list_is_refused(value: object) -> None:
    with pytest.raises(ConfigError, match="trusted_proxies"):
        parse_trusted_proxies(value)


@pytest.mark.parametrize(
    "line",
    [
        "edit_token = 5",
        'database = ""',
        "assets_dir = 3",
        "display_names = []",
        "web_dir = false",
        'web_dir = ""',
        "max_asset_bytes = 0",
        "max_scene_bytes = 1.5",
        'history_limit = "50"',
        "history_limit = true",
        "history_interval_seconds = 0",
        "head_flush_seconds = -1",
        "head_flush_seconds = true",
        "head_flush_seconds = nan",
        "history_interval_seconds = inf",
    ],
)
def test_an_unusable_value_is_refused_by_key(tmp_path: Path, line: str) -> None:
    key = line.split(" = ")[0]

    with pytest.raises(ConfigError, match=key):
        load_settings(write(tmp_path, line + "\n"))


def test_an_unknown_key_is_refused_by_name(tmp_path: Path) -> None:
    # base_path was removed (D2-007). A misspelled edit_token must not pass quietly.
    config = write(tmp_path, 'base_path = "/board"\nedit_tokn = "s3cret"\n')

    with pytest.raises(ConfigError, match=r"unknown key base_path, edit_tokn") as refused:
        load_settings(config)

    assert "s3cret" not in str(refused.value)


def test_a_bad_edit_token_is_not_echoed(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as refused:
        load_settings(write(tmp_path, "edit_token = 12345678\n"))

    assert "12345678" not in str(refused.value)


# What is, and is not, an edit token. web/src/editToken.test.ts reads the same file.
TOKEN_CASES: list[tuple[str, bool]] = [
    (text, usable)
    for text, usable in json.loads(
        (ROOT / "tests" / "edit_token_cases.json").read_text(encoding="utf-8")
    )["cases"]
]


def toml_string(text: str) -> str:
    """Return ``text`` as a TOML basic string, with every awkward character escaped."""
    plain = set(range(0x20, 0x7F)) - {ord('"'), ord("\\")}
    return '"' + "".join(c if ord(c) in plain else f"\\U{ord(c):08x}" for c in text) + '"'


# The whole message. Nothing of the value is in it: it may be most of a real token.
NOT_A_TOKEN = (
    "edit_token must be 1 to 256 printable ASCII characters, with no space at either end, "
    'or "" for none: a browser sends it in a request header'
)


def test_the_token_table_has_both_kinds() -> None:
    assert sum(usable for _, usable in TOKEN_CASES) >= 5
    assert sum(not usable for _, usable in TOKEN_CASES) >= 5


@pytest.mark.parametrize(("text", "usable"), TOKEN_CASES)
def test_an_edit_token_is_what_a_request_header_carries_whole(text: str, usable: bool) -> None:
    assert is_edit_token(text) is usable


@pytest.mark.parametrize("text", [text for text, usable in TOKEN_CASES if usable])
def test_a_usable_edit_token_is_kept_as_written(tmp_path: Path, text: str) -> None:
    settings = load_settings(write(tmp_path, f"edit_token = {toml_string(text)}\n"))

    assert settings.edit_token == text
    assert settings.edit_required


@pytest.mark.parametrize("text", [text for text, usable in TOKEN_CASES if not usable and text])
def test_a_token_no_browser_could_send_stops_segl_and_is_not_echoed(
    tmp_path: Path, text: str
) -> None:
    # Such a token would let a browser draw, over the socket, and fail at every
    # title, restore, import, and upload, which carry it in a header.
    with pytest.raises(ConfigError) as refused:
        load_settings(write(tmp_path, f"edit_token = {toml_string(text)}\n"))

    assert str(refused.value) == NOT_A_TOKEN


def test_an_empty_edit_token_is_none(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, 'edit_token = ""\n'))

    assert settings.edit_token == ""
    assert not settings.edit_required


def test_the_command_refuses_a_token_no_browser_could_send(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write(tmp_path, 'edit_token = "lykilor\u00f0 "\n')

    assert cli.main(["--config", str(config)]) == 2

    printed = capsys.readouterr().err
    assert NOT_A_TOKEN in printed
    assert "lykilor" not in printed


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"segl\.toml"):
        load_settings(write(tmp_path, "bind = \n"))


class OpenedDatabase:
    """Stands in for the repository, and records what the command opened."""

    opened: ClassVar[list[tuple[Path, int]]] = []

    def __init__(self, path: Path, *, history_limit: int) -> None:
        self.opened.append((path, history_limit))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def bootstrap(self) -> None:
        pass


def test_the_command_serves_with_a_missing_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served: dict[str, object] = {}
    read: list[Path] = []

    def fake_run(app: object, **options: object) -> None:
        served.update(options)

    def fake_words(path: Path) -> tuple[str, ...]:
        read.append(path)
        return ("Guest",)

    def fake_prepare(store: AssetStore) -> None:
        prepared.append(store.folder)

    prepared: list[Path] = []
    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    # The production database path is not this test's to create, and neither
    # are the production display-name file and the folder for uploaded files.
    monkeypatch.setattr(OpenedDatabase, "opened", [])
    monkeypatch.setattr(cli, "Repository", OpenedDatabase)
    monkeypatch.setattr(app, "load_display_names", fake_words)
    monkeypatch.setattr(AssetStore, "prepare", fake_prepare)

    assert cli.main(["--config", str(tmp_path / "absent.toml")]) == 0
    assert prepared == [Path("/opt/segl/var/assets")]
    assert served == {
        "host": "127.0.0.1",
        "port": 8888,
        "proxy_headers": True,
        "forwarded_allow_ips": ["127.0.0.1", "::1"],
        # The WebSocket: a message may be a whole scene, max_scene_bytes.
        "ws": "websockets-sansio",
        "ws_max_size": 52428800,
    }
    assert OpenedDatabase.opened == [(Path("/opt/segl/var/segl.sqlite"), 50)]
    assert read == [Path("/opt/segl/etc/display-names.txt")]


def test_the_command_passes_the_trusted_proxies_to_uvicorn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served: dict[str, object] = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **options: served.update(options))
    monkeypatch.setattr(cli, "Repository", OpenedDatabase)
    config = write(
        tmp_path,
        f'trusted_proxies = []\ndisplay_names = "{DISPLAY_NAMES_FILE}"\n'
        f'assets_dir = "{tmp_path / "assets"}"\n',
    )

    assert cli.main(["--config", str(config)]) == 0
    # An empty list, not None: None would make uvicorn fall back to its own default.
    assert served["forwarded_allow_ips"] == []


def test_the_command_reports_a_bad_config_and_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--config", str(write(tmp_path, 'bind = "nowhere"\n'))]) == 2
    assert "is not host:port" in capsys.readouterr().err
