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

"""Settings from ``--config``: the bind address, and a missing file."""

from pathlib import Path

import pytest

from segl import cli
from segl.config import DEFAULT_BIND, ConfigError, Settings, load_settings, parse_bind


def test_defaults_without_a_config_path() -> None:
    settings = load_settings()

    assert settings == Settings(host="127.0.0.1", port=8000)
    assert settings.bind == DEFAULT_BIND


def test_a_missing_file_gives_the_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "absent.toml") == load_settings()


def test_bind_comes_from_the_file(tmp_path: Path) -> None:
    config = tmp_path / "segl.toml"
    config.write_text('bind = "0.0.0.0:9001"\n', encoding="utf-8")

    assert load_settings(config) == Settings(host="0.0.0.0", port=9001)


def test_an_ipv6_bind_uses_brackets() -> None:
    assert parse_bind("[::1]:8000") == ("::1", 8000)
    assert Settings(host="::1", port=8000).bind == "[::1]:8000"


@pytest.mark.parametrize(
    "value", ["127.0.0.1", ":8000", "host:port", "h:0", "h:65536", "::1:80", 8000]
)
def test_an_unusable_bind_is_refused(value: object) -> None:
    with pytest.raises(ConfigError):
        parse_bind(value)


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    config = tmp_path / "segl.toml"
    config.write_text("bind = \n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"segl\.toml"):
        load_settings(config)


def test_the_command_serves_with_a_missing_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int) -> None:
        served.update(host=host, port=port)

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    assert cli.main(["--config", str(tmp_path / "absent.toml")]) == 0
    assert served == {"host": "127.0.0.1", "port": 8000}


def test_the_command_reports_a_bad_config_and_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "segl.toml"
    config.write_text('bind = "nowhere"\n', encoding="utf-8")

    assert cli.main(["--config", str(config)]) == 2
    assert "is not host:port" in capsys.readouterr().err
