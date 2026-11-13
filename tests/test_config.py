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

import re
import time
import tomllib
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
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
    load_settings,
    parse_access_codes,
    parse_bind,
    parse_internal_networks,
    parse_trusted_proxies,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "deploy" / "segl.toml.example"

PRODUCTION = Settings(
    host="127.0.0.1",
    port=8888,
    trusted_proxies=("127.0.0.1", "::1"),
    internal_networks=(),
    access_codes=(),
    access_secret="",
    access_pass_hours=12.0,
    access_passes_after=None,
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
    assert settings.access_pass_seconds == 12 * 3600
    assert settings.access_passes_after_seconds is None


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
    write(empty_directory, f'bind = "127.0.0.1:9001"\naccess_codes = ["local code"]\n{SECRET_LINE}')

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
        internal_networks = ["10.0.0.0/8", "2001:DB8::/32", "192.0.2.7"]
        access_codes = ["Maple River 42", "night-shift-1836"]
        access_secret = "0123456789abcdef0123456789abcdef"
        access_pass_hours = 0.5
        access_passes_after = 2026-11-12T15:00:00+01:00
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
        internal_networks=("10.0.0.0/8", "2001:db8::/32", "192.0.2.7/32"),
        access_codes=("maple.river.42", "night.shift.1836"),
        access_secret="0123456789abcdef0123456789abcdef",
        access_pass_hours=0.5,
        access_passes_after=datetime(2026, 11, 12, 14, 0, tzinfo=UTC),
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


def test_the_codes_and_the_secret_are_not_in_the_settings_repr(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, f'access_codes = ["Maple River 42"]\n{SECRET_LINE}'))

    assert settings.edit_required
    assert settings.access_codes == ("maple.river.42",)
    assert settings.access_secret == SECRET
    for hidden in ("maple", "Maple", SECRET):
        assert hidden not in repr(settings)


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
        "access_codes = 5",
        'access_codes = "maple river 42"',
        "access_codes = [12345678]",
        "access_secret = 5",
        "access_pass_hours = -1",
        "access_pass_hours = true",
        'access_pass_hours = "12"',
        "access_pass_hours = nan",
        "access_pass_hours = inf",
        'access_passes_after = "yesterday"',
        'access_passes_after = "2026-11-12T15:00:00Z"',
        # Without an offset, and a day without a time.
        "access_passes_after = 2026-11-12T15:00:00",
        "access_passes_after = 2026-11-12",
        "access_passes_after = 15:00:00",
        "access_passes_after = 0",
        'internal_networks = "10.0.0.0/8"',
        'internal_networks = ["inside"]',
        "internal_networks = [10]",
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
    # base_path was removed (D2-007). A misspelled access_codes must not pass quietly.
    config = write(tmp_path, 'base_path = "/board"\naccess_code = ["s3cret phrase"]\n')

    with pytest.raises(ConfigError, match=r"unknown key access_code, base_path") as refused:
        load_settings(config)

    assert "s3cret" not in str(refused.value)
    assert "edit_token" not in str(refused.value)


def test_the_token_of_an_earlier_build_stops_segl_and_points_at_the_codes(tmp_path: Path) -> None:
    # D2-033: edit_token is gone, and no release shipped with it.
    with pytest.raises(ConfigError, match="unknown key edit_token") as refused:
        load_settings(write(tmp_path, 'edit_token = "s3cret-token"\n'))

    message = str(refused.value)
    assert message.endswith(
        "edit_token is gone: list access codes in access_codes, with access_secret (docs/DEPLOY.md)"
    )
    assert "s3cret" not in message


# Access codes (D2-033, S-008).


def codes_from(tmp_path: Path, toml_list: str) -> tuple[str, ...]:
    return load_settings(write(tmp_path, f"access_codes = {toml_list}\n{SECRET_LINE}")).access_codes


@pytest.mark.parametrize(
    ("written", "kept"),
    [
        ("Maple River 42", "maple.river.42"),
        ("maple.river.42", "maple.river.42"),
        ("  MAPLE--river__42!  ", "maple.river.42"),
        ("mapleriver42", "mapleriver42"),
        ("12345678", "12345678"),
        ("a b c d e f g h", "a.b.c.d.e.f.g.h"),
        ("x" * 256, "x" * 256),
    ],
)
def test_a_code_is_kept_in_its_normal_form(tmp_path: Path, written: str, kept: str) -> None:
    assert codes_from(tmp_path, f'["{written}"]') == (kept,)


def test_the_codes_keep_the_lists_order(tmp_path: Path) -> None:
    codes = codes_from(tmp_path, '["zebra crossing", "apple orchard", "Maple River 42"]')

    assert codes == ("zebra.crossing", "apple.orchard", "maple.river.42")


@pytest.mark.parametrize(
    ("toml_list", "reason"),
    [
        # Fewer than 8 letters and digits, however long it is written.
        ('["maple river 42", "short 1"]', "entry 2 has fewer than 8 letters and digits"),
        ('["a.b.c.d.e.f.g"]', "entry 1 has fewer than 8 letters and digits"),
        ('["- - - - - - - - - -"]', "entry 1 has fewer than 8 letters and digits"),
        ('[""]', "entry 1 has fewer than 8 letters and digits"),
        # The same code twice, as it is compared.
        ('["maple river 42", "other code 77", "Maple-River-42"]', "entry 3 is the same code as"),
        ('["maple river 42", "maple river 42"]', "entry 2 is the same code as entry 1"),
        # A letter a person could not be sure to type the same way.
        ('["lykilor\\u00f0 1234"]', "entry 1 has a character outside ASCII"),
        ('["maple river 42", 7]', "entry 2 must be text"),
        ('["maple river 42", ["nested code"]]', "entry 2 must be text"),
        (f'["{"x" * 257}"]', "entry 1 is longer than 256 characters"),
    ],
)
def test_a_code_segl_cannot_use_stops_it_by_its_place_and_is_not_echoed(
    tmp_path: Path, toml_list: str, reason: str
) -> None:
    with pytest.raises(ConfigError, match=f"access_codes {reason}") as refused:
        codes_from(tmp_path, toml_list)

    message = str(refused.value).lower()
    for part in ("maple", "short", "lykilor", "other", "nested", "a.b.c", "xxxx"):
        assert part not in message


def test_no_codes_is_an_open_segl(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, "access_codes = []\n"))

    assert settings.access_codes == ()
    assert not settings.edit_required


def test_codes_are_parsed_without_a_file() -> None:
    assert parse_access_codes(["Maple River 42"]) == ("maple.river.42",)
    assert parse_access_codes([]) == ()


SECRET = "0123456789abcdef0123456789abcdef"
SECRET_LINE = f'access_secret = "{SECRET}"\n'


def test_codes_without_a_secret_stop_segl(tmp_path: Path) -> None:
    for more in ("", 'access_secret = ""\n'):
        with pytest.raises(ConfigError) as refused:
            load_settings(write(tmp_path, f'access_codes = ["maple river 42"]\n{more}'))

        assert str(refused.value) == (
            "access_codes needs access_secret, which signs the passes: "
            "`openssl rand -base64 32` writes one"
        )


@pytest.mark.parametrize("secret", ["x", "short-secret-1234", "0123456789abcdef0123456789abcde"])
def test_a_short_secret_stops_segl_and_is_not_echoed(tmp_path: Path, secret: str) -> None:
    # With codes and without them: a mistake is found when it is made.
    for codes in ("", 'access_codes = ["maple river 42"]\n'):
        with pytest.raises(ConfigError) as refused:
            load_settings(write(tmp_path, f'{codes}access_secret = "{secret}"\n'))

        assert str(refused.value) == (
            "access_secret must be at least 32 characters: `openssl rand -base64 32` writes one"
        )


def test_a_secret_without_codes_changes_nothing(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, SECRET_LINE))

    assert settings.access_secret == SECRET
    assert not settings.edit_required


@pytest.mark.parametrize(
    ("hours", "seconds"),
    [("12", 43200.0), ("0.5", 1800.0), ("1", 3600.0), ("0.001", 3.6), ("0", None), ("0.0", None)],
)
def test_the_pass_hours_are_a_length_or_no_limit(
    tmp_path: Path, hours: str, seconds: float | None
) -> None:
    settings = load_settings(write(tmp_path, f"access_pass_hours = {hours}\n"))

    assert settings.access_pass_seconds == pytest.approx(seconds)


@pytest.mark.parametrize(
    ("written", "moment"),
    [
        ("2026-11-12T15:00:00Z", datetime(2026, 11, 12, 15, tzinfo=UTC)),
        ("2026-11-12 15:00:00Z", datetime(2026, 11, 12, 15, tzinfo=UTC)),
        ("2026-11-12T15:00:00-06:00", datetime(2026, 11, 12, 21, tzinfo=UTC)),
        ("2026-11-12T15:00:00.250+00:00", datetime(2026, 11, 12, 15, 0, 0, 250000, tzinfo=UTC)),
    ],
)
def test_the_time_passes_ended_at_is_a_moment(
    tmp_path: Path, written: str, moment: datetime
) -> None:
    settings = load_settings(write(tmp_path, f"access_passes_after = {written}\n"))

    assert settings.access_passes_after == moment
    assert settings.access_passes_after_seconds == moment.timestamp()


def test_no_time_is_no_end_of_passes(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, 'access_passes_after = ""\n'))

    assert settings.access_passes_after is None
    assert settings.access_passes_after_seconds is None


def test_internal_networks_are_networks_of_either_family() -> None:
    assert parse_internal_networks([]) == ()
    assert parse_internal_networks(
        ["10.0.0.0/8", " 192.168.4.0/24 ", "2001:DB8::/32", "203.0.113.9", "::1"]
    ) == ("10.0.0.0/8", "192.168.4.0/24", "2001:db8::/32", "203.0.113.9/32", "::1/128")


@pytest.mark.parametrize(
    "value",
    [
        "10.0.0.0/8",
        ["*"],
        ["inside.example"],
        # A host with a mask is not a network: the site meant something else.
        ["10.0.0.1/8"],
        ["2001:db8::1/32"],
        ["10.0.0.0/33"],
        [""],
        [7],
        ["10.0.0.0/8", "nope"],
        [["10.0.0.0/8"]],
    ],
)
def test_an_entry_that_is_not_a_network_is_refused(value: object) -> None:
    with pytest.raises(ConfigError, match="internal_networks"):
        parse_internal_networks(value)


def test_the_command_refuses_codes_without_a_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write(tmp_path, 'access_codes = ["Maple River 42"]\n')

    assert cli.main(["--config", str(config)]) == 2

    printed = capsys.readouterr().err
    assert "segl: access_codes needs access_secret" in printed
    assert "maple" not in printed.lower()


def test_the_command_refuses_a_short_code_by_its_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write(tmp_path, f'access_codes = ["Maple River 42", "pass 1"]\n{SECRET_LINE}')

    assert cli.main(["--config", str(config)]) == 2

    printed = capsys.readouterr().err
    assert "segl: access_codes entry 2 has fewer than 8 letters and digits" in printed
    assert "pass 1" not in printed
    assert "maple" not in printed.lower()


def test_the_command_refuses_an_entry_that_is_not_a_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write(tmp_path, 'internal_networks = ["10.0.0.0/8", "the office"]\n')

    assert cli.main(["--config", str(config)]) == 2
    assert "internal_networks entry 'the office' is not a network" in capsys.readouterr().err


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


AHEAD_WARNING = (
    "segl: access_passes_after is ahead of this server's clock: "
    "no pass lets a browser edit until then"
)


def toml_time(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


@pytest.mark.parametrize(
    ("ahead", "warned"),
    [
        # Five minutes is what a pass may be ahead of the clock (segl.access).
        (timedelta(hours=6), True),
        (timedelta(minutes=10), True),
        (timedelta(minutes=2), False),
        (timedelta(0), False),
        (timedelta(days=-1), False),
    ],
)
def test_the_command_says_when_passes_are_ended_from_a_time_still_to_come(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ahead: timedelta,
    warned: bool,
) -> None:
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **options: None)
    monkeypatch.setattr(cli, "Repository", OpenedDatabase)
    # A time written in another zone is the same moment.
    moment = (datetime.fromtimestamp(time.time(), UTC) + ahead).astimezone(
        timezone(timedelta(hours=1))
    )
    config = write(
        tmp_path,
        f"access_passes_after = {toml_time(moment)}\n"
        f'display_names = "{DISPLAY_NAMES_FILE}"\nassets_dir = "{tmp_path / "assets"}"\n',
    )

    # It starts either way: the setting is usable, and may be meant.
    assert cli.main(["--config", str(config)]) == 0
    assert (AHEAD_WARNING in capsys.readouterr().err) is warned
