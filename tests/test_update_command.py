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

"""The command line of ``segl check``, ``segl config merge``, and ``segl update``."""

import shutil
from pathlib import Path
from typing import ClassVar

import pytest
from harness import make_settings
from update_helpers import DEPLOY, EXAMPLE, FakeGitHub, make_paths

from segl import cli
from segl.update import command
from segl.update.paths import INSTALLED, Paths
from segl.update.releases import DEFAULT_URL
from segl.update.updater import UpdateError
from segl.update.versions import Version
from segl.versions import app_version

API = DEFAULT_URL


def settings_file(folder: Path, text: str = "") -> Path:
    """Write a settings file whose word file is the packaged one."""
    config = folder / "segl.toml"
    names = DEPLOY / "display-names.txt"
    web = folder / "no-web-build"
    config.write_text(f'display_names = "{names}"\nweb_dir = "{web}"\n{text}', encoding="utf-8")
    return config


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    """An installation in the test's folder, where the commands look for one."""
    paths = make_paths(tmp_path)
    (paths.share / "release-signers").write_text("# no key\n", encoding="utf-8")
    monkeypatch.setattr(command, "INSTALLED", paths)
    return paths


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeGitHub:
    """GitHub, with one release newer than this checkout's version."""
    stand_in = FakeGitHub(api=API)
    home = tmp_path / "releases" / "99.0.0"
    home.mkdir(parents=True)
    (home / "segl_99.0.0_amd64.deb").write_bytes(b"x")
    stand_in.add(home)

    def https(proxy: str = "") -> FakeGitHub:
        stand_in.proxies.append(proxy)
        return stand_in

    monkeypatch.setattr(command, "Https", https)
    return stand_in


def test_without_a_command_segl_serves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    served = []
    monkeypatch.setattr(cli, "serve", lambda config: served.append(config) or 0)

    assert cli.main(["--config", str(tmp_path / "segl.toml")]) == 0
    assert cli.main([]) == 0

    assert served == [tmp_path / "segl.toml", None]


@pytest.mark.parametrize(
    "argv",
    [
        ["--config", "/x/segl.toml", "check"],
        ["check", "--config", "/x/segl.toml"],
        ["--config", "/ignored.toml", "check", "--config", "/x/segl.toml"],
    ],
)
def test_the_settings_file_may_be_named_before_or_after_the_command(argv: list[str]) -> None:
    args = cli.build_parser().parse_args(argv)

    assert (args.command, args.config) == ("check", Path("/x/segl.toml"))


def test_a_command_without_config_uses_the_installed_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []
    monkeypatch.setattr(command, "check", lambda config: seen.append(config) or 0)

    assert cli.main(["check"]) == 0

    assert seen == [INSTALLED.config_file] == [Path("/opt/segl/etc/segl.toml")]


def test_check_passes_for_settings_segl_would_start_with(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["check", "--config", str(settings_file(tmp_path))]) == 0

    said = capsys.readouterr().out
    assert said == (
        "segl check: ok: the settings, 190 display names, and no web application (the API only)\n"
    )


def test_check_makes_no_file_and_opens_no_database(tmp_path: Path) -> None:
    config = settings_file(
        tmp_path, f'database = "{tmp_path}/var/segl.sqlite"\nassets_dir = "{tmp_path}/var/assets"\n'
    )

    assert cli.main(["check", "--config", str(config)]) == 0

    assert sorted(path.name for path in tmp_path.iterdir()) == ["segl.toml"]


def test_check_names_a_setting_segl_cannot_use(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = settings_file(tmp_path, 'base_path = "/board"\n')

    assert cli.main(["check", "--config", str(config)]) == 2

    assert "unknown key base_path" in capsys.readouterr().err


def test_check_fails_for_a_word_file_segl_cannot_start_with(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "segl.toml"
    config.write_text(f'display_names = "{tmp_path}/absent.txt"\n', encoding="utf-8")

    assert cli.main(["check", "--config", str(config)]) == 1

    assert "cannot read the display-name file" in capsys.readouterr().err


def test_check_says_when_the_settings_file_is_not_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command, "load_settings", lambda path: make_settings())

    assert cli.main(["check", "--config", str(tmp_path / "absent.toml")]) == 0

    assert "absent.toml does not exist, so every setting has its default" in (
        capsys.readouterr().out
    )


def test_a_file_only_root_reads_asks_for_sudo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(path: Path) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(command, "load_settings", refuse)
    config = tmp_path / "segl.toml"

    for argv in (["check"], ["update", "--check"], ["config", "merge"]):
        assert cli.main([*argv, "--config", str(config)]) == 2 or argv[0] == "config"

    assert f"segl: {config}: permission denied. Run it with sudo." in capsys.readouterr().err


def test_config_needs_an_action(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["config"])

    assert stopped.value.code == 2


def test_config_merge_previews_and_then_writes(
    installed: Paths, capsys: pytest.CaptureFixture[str]
) -> None:
    site = 'bind = "127.0.0.1:8888"\n'
    installed.config_file.write_text(site, encoding="utf-8")
    argv = ["config", "merge", "--config", str(installed.config_file)]

    assert cli.main(argv) == 0

    assert installed.config_file.read_text(encoding="utf-8") == site
    assert "would add trusted_proxies" in capsys.readouterr().out

    assert cli.main([*argv, "--write"]) == 0

    assert "segl config merge: added trusted_proxies" in capsys.readouterr().out
    merged = installed.config_file.read_text(encoding="utf-8")
    assert merged.startswith(site) and 'update_proxy = ""' in merged
    # A second run has nothing left to do, and says nothing.
    assert cli.main([*argv, "--write"]) == 0
    assert capsys.readouterr().out == ""


def test_update_check_asks_the_address_in_the_settings(
    tmp_path: Path, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    config = settings_file(tmp_path)

    assert cli.main(["update", "--check", "--config", str(config)]) == 100

    said = capsys.readouterr().out
    assert f"segl {app_version()} is installed; 99.0.0 is available" in said
    assert github.asked == [f"{API}/releases/latest"]
    assert github.proxies == [""]


def test_update_check_for_one_version(
    tmp_path: Path, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    config = settings_file(tmp_path)

    assert cli.main(["update", "--check", "--version", "v99.0.0", "--config", str(config)]) == 100

    assert github.asked == [f"{API}/releases/tags/v99.0.0"]


def test_the_proxy_option_is_used_and_shown_without_its_password(
    tmp_path: Path, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    config = settings_file(tmp_path, 'update_proxy = "http://settings.example.com:3128"\n')
    given = "--proxy=http://pat:s3cret@proxy.example.com:2025/"

    assert cli.main(["update", "--check", given, "--config", str(config)]) == 100

    assert github.proxies == ["http://pat:s3cret@proxy.example.com:2025/"]
    said = capsys.readouterr().out
    assert said.startswith("Through the proxy http://proxy.example.com:2025.\n")
    assert "s3cret" not in said


def test_the_proxy_in_the_settings_is_used_without_the_option(
    tmp_path: Path, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    config = settings_file(tmp_path, 'update_proxy = "http://settings.example.com:3128"\n')

    assert cli.main(["update", "--check", "--config", str(config)]) == 100

    assert github.proxies == ["http://settings.example.com:3128"]
    assert "Through the proxy http://settings.example.com:3128." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "said"),
    [
        (["--auto", "--check"], "--auto goes with none of"),
        (["--auto", "--version", "1.0.0"], "--auto goes with none of"),
        (["--auto", "--from", "/x"], "--auto goes with none of"),
        (["--from", "/x", "--check"], "--from goes with neither"),
        (["--from", "/x", "--version", "1.0.0"], "--from goes with neither"),
        (["--proxy", "proxy.example.com:3128"], "--proxy: expected http://HOST:PORT"),
        (["--proxy", "https://proxy.example.com:3128"], "--proxy: expected http://HOST:PORT"),
        (["--version", "latest"], "--version: 'latest' is not a version such as 0.1.0"),
        (["--version", "1.0.0-rc.1"], "is not a version"),
    ],
)
def test_options_that_do_not_go_together_are_refused(
    argv: list[str], said: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["update", *argv])

    assert stopped.value.code == 2
    assert said in capsys.readouterr().err


def test_installing_needs_an_installed_package(
    tmp_path: Path, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    # A checkout has no /opt/segl/share/release-signers.
    assert cli.main(["update", "--yes", "--config", str(settings_file(tmp_path))]) == 2

    assert "segl is not installed from its package here" in capsys.readouterr().err
    assert github.asked == []


def test_installing_needs_root(
    installed: Paths,
    github: FakeGitHub,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command.os, "geteuid", lambda: 1000)
    config = settings_file(installed.etc)

    assert cli.main(["update", "--yes", "--config", str(config)]) == 2

    assert "segl update: installing needs root: sudo segl update" in capsys.readouterr().err
    assert github.asked == []


class _Recorder:
    """Stands in for the updater, and records how the command called it."""

    calls: ClassVar[list[tuple[object, ...]]] = []
    made: ClassVar[list[dict[str, object]]] = []

    def __init__(self, **given: object) -> None:
        self.made.append(given)

    def update(self, target: object, confirm: command.Confirm, auto: bool = False) -> int:
        self.calls.append(("update", target, confirm("Install?"), auto))
        return 0

    def install_from(self, folder: Path, confirm: command.Confirm) -> int:
        self.calls.append(("install_from", folder, confirm("Install?")))
        return 0


@pytest.fixture
def recorder(installed: Paths, monkeypatch: pytest.MonkeyPatch) -> type[_Recorder]:
    _Recorder.calls, _Recorder.made = [], []
    monkeypatch.setattr(command, "Updater", _Recorder)
    monkeypatch.setattr(command.os, "geteuid", lambda: 0)
    monkeypatch.setattr(command, "Https", lambda proxy="": FakeGitHub())
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: False)
    return _Recorder


def test_the_timer_and_yes_install_without_asking(
    installed: Paths, recorder: type[_Recorder], capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(settings_file(installed.etc, 'bind = "[::1]:9000"\n'))

    assert cli.main(["update", "--auto", "--config", config]) == 0
    assert cli.main(["update", "--yes", "--config", config]) == 0
    assert cli.main(["update", "--yes", "--version", "0.2.0", "--config", config]) == 0
    assert cli.main(["update", "--yes", "--from", "/media/usb", "--config", config]) == 0

    assert recorder.calls == [
        ("update", None, True, True),
        ("update", None, True, False),
        ("update", Version.parse("0.2.0"), True, False),
        ("install_from", Path("/media/usb"), True),
    ]
    made = recorder.made[0]
    assert made["installed"] == Version.parse(app_version())
    assert made["update_url"] == API
    assert made["version_url"] == "http://[::1]:9000/api/v1/version"
    assert made["paths"] == installed.__class__(
        config_file=Path(config),
        share=installed.share,
        update_dir=installed.update_dir,
        binary=installed.binary,
        nginx_dir=installed.nginx_dir,
    )
    assert capsys.readouterr().out == ""


def test_without_a_terminal_and_without_yes_nothing_is_installed(
    installed: Paths, recorder: type[_Recorder], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["update", "--config", str(settings_file(installed.etc))]) == 0

    assert recorder.calls == [("update", None, False, False)]
    assert "There is no terminal to ask at: add --yes to go ahead." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("typed", "taken"), [("y", True), ("YES", True), ("", False), ("n", False), ("maybe", False)]
)
def test_at_a_terminal_only_yes_goes_ahead(
    typed: str,
    taken: bool,
    installed: Paths,
    recorder: type[_Recorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: typed)

    assert cli.main(["update", "--config", str(settings_file(installed.etc))]) == 0

    assert recorder.calls == [("update", None, taken, False)]


def test_an_update_that_cannot_start_ends_with_status_1(
    installed: Paths,
    recorder: type[_Recorder],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def busy(self: object, *args: object, **named: object) -> int:
        raise UpdateError("another segl update is running")

    monkeypatch.setattr(recorder, "update", busy)

    assert cli.main(["update", "--yes", "--config", str(settings_file(installed.etc))]) == 1

    assert "segl update: another segl update is running" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("bind", "address"),
    [
        ("127.0.0.1:8888", "http://127.0.0.1:8888"),
        ("0.0.0.0:8888", "http://127.0.0.1:8888"),
        ("[::]:8888", "http://[::1]:8888"),
        ("[::1]:9000", "http://[::1]:9000"),
        ("10.1.2.3:8001", "http://10.1.2.3:8001"),
    ],
)
def test_the_version_is_asked_where_segl_listens(bind: str, address: str, tmp_path: Path) -> None:
    config = tmp_path / "segl.toml"
    config.write_text(f'bind = "{bind}"\n', encoding="utf-8")

    assert command.version_url(command.load_settings(config)) == f"{address}/api/v1/version"


def test_the_example_settings_pass_the_check(tmp_path: Path) -> None:
    # The file as the package installs it, but for the three paths under /opt.
    text = EXAMPLE.read_text(encoding="utf-8")
    for key, value in (
        ("display_names", DEPLOY / "display-names.txt"),
        ("web_dir", tmp_path / "none"),
    ):
        line = next(line for line in text.splitlines() if line.startswith(f"{key} = "))
        text = text.replace(line, f'{key} = "{value}"')
    config = tmp_path / "segl.toml"
    config.write_text(text, encoding="utf-8")
    shutil.copy(config, tmp_path / "copy.toml")

    assert cli.main(["check", "--config", str(config)]) == 0
