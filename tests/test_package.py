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

"""The files the Debian package is built from agree with the rest of the tree.

These tests read ``deploy/debian/``, ``deploy/systemd/``, and
``deploy/OPERATOR.md``. They build no package and install none:
``deploy/debian/package-test.sh`` does that, in a container that booted with
systemd (docs/TEST-PLAN.md T-017).
"""

import configparser
import hashlib
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from segl.config import DEFAULTS, load_settings

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
DEBIAN = DEPLOY / "debian"
UNIT = DEPLOY / "systemd" / "segl.service"
VERSIONS = tomllib.loads((ROOT / "versions.toml").read_text(encoding="utf-8"))
OPT = Path("/opt/segl")
SHELL_SCRIPTS = {
    "build-deb.sh": "bash",
    "build.sh": "bash",
    "package-test.sh": "bash",
    "systemd-test.sh": "bash",
    "testlib.sh": "bash",
    "postinst": "sh",
    "prerm": "sh",
    "postrm": "sh",
}
UV_EXPORT = ("uv", "export", "--frozen", "--no-emit-project", "--format", "requirements.txt")
# The scripts a person or dpkg runs. testlib.sh is sourced.
RUN_DIRECTLY = sorted(set(SHELL_SCRIPTS) - {"testlib.sh"})


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # ty: ignore[invalid-assignment]
    parser.read_string(read(UNIT))
    return parser


def from_lines(text: str, stage: str) -> list[str]:
    """Return the ``FROM`` lines of a container file that name ``stage``."""
    return [line for line in text.splitlines() if re.fullmatch(rf"FROM \S+ AS {stage}", line)]


def runtime_packages() -> list[str]:
    """Return what the package's virtualenv installs: the build's own command."""
    exported = subprocess.run(
        [*UV_EXPORT, "--no-default-groups"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return re.findall(r"^([a-z0-9][a-z0-9._-]*)==", exported, flags=re.MULTILINE)


# The builder image


def test_the_builder_takes_uv_and_node_as_the_dev_container_does() -> None:
    builder = read(DEBIAN / "Containerfile")
    dev = read(DEPLOY / "Containerfile")

    for stage in ("uv", "node"):
        assert len(from_lines(dev, stage)) == 1
        assert from_lines(builder, stage) == from_lines(dev, stage), stage


def test_the_builders_node_is_the_pin() -> None:
    (line,) = from_lines(read(DEBIAN / "Containerfile"), "node")

    assert f"/node:{VERSIONS['runtime']['node']}-" in line


def test_every_image_the_builder_takes_is_pinned_by_digest() -> None:
    builder = read(DEBIAN / "Containerfile")
    stages = re.findall(r"^FROM (\S+) AS \w+$", builder, flags=re.MULTILINE)

    assert len(stages) == 3
    for image in stages:
        assert re.search(r":[\w.-]+@sha256:[0-9a-f]{64}$", image), image


def test_nfpm_is_built_at_an_exact_version() -> None:
    builder = read(DEBIAN / "Containerfile")

    assert re.search(
        r"go install github\.com/goreleaser/nfpm/v2/cmd/nfpm@v\d+\.\d+\.\d+$", builder, re.M
    )
    # On the command, not only in the comment above it: Go fetches no other Go.
    assert "\nRUN CGO_ENABLED=0 GOTOOLCHAIN=local GOBIN=/out \\\n    go install " in builder


# The build


def test_the_build_installs_what_the_lockfile_says_segl_needs() -> None:
    build = read(DEBIAN / "build.sh")
    packages = runtime_packages()

    assert "uv export --frozen --no-default-groups --no-emit-project" in build
    assert "--require-hashes --only-binary :all:" in build
    for name in VERSIONS["python"]["dependencies"]:
        assert name in packages
    for name in (*VERSIONS["python"]["dev"], *VERSIONS["python"]["docs"]):
        assert name not in packages, f"{name} is a development tool"


def test_the_lockfile_holds_the_build_backend_with_hashes() -> None:
    exported = subprocess.run(
        [*UV_EXPORT, "--only-group", "build"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pins = re.findall(r"^([a-z0-9][a-z0-9._-]*)==(\S+) \\$", exported, flags=re.MULTILINE)

    assert dict(pins)["hatchling"] == VERSIONS["python"]["build"]["hatchling"]
    assert len(pins) > 1, "hatchling has dependencies of its own"
    for name, _version in pins:
        assert re.search(rf"^{re.escape(name)}==\S+ \\\n    --hash=sha256:", exported, re.M), name
    build = read(DEBIAN / "build.sh")
    assert "uv export --frozen --only-group build --no-emit-project" in build
    assert "--build-constraints /build/build-constraints.txt --require-hashes" in build


def test_the_build_puts_the_web_application_where_the_settings_look() -> None:
    build = read(DEBIAN / "build.sh")

    assert "OPT=/opt/segl" in build
    assert 'cp -R web/dist "$OPT/app/web/dist"' in build
    assert DEFAULTS["web_dir"] == "/opt/segl/app/web/dist"
    # The command itself. The line that logs it says the same words.
    assert "\n        npm ci --ignore-scripts --no-audit --no-fund\n" in build


def test_the_build_ships_the_files_the_task_names() -> None:
    build = read(DEBIAN / "build.sh")

    assert 'install -D -m 0644 -t "$share/nginx" deploy/nginx/*.conf' in build
    assert 'install -D -m 0644 deploy/segl.toml.example "$share/segl.toml.example"' in build
    assert 'install -D -m 0644 deploy/display-names.txt "$share/display-names.txt"' in build
    assert 'install -D -m 0644 -t "$DOC" deploy/OPERATOR.md LICENSE NOTICE' in build
    for name in ("OPERATOR.md", "segl.toml.example", "display-names.txt"):
        assert (DEPLOY / name).is_file()


@pytest.mark.parametrize("name", sorted(SHELL_SCRIPTS))
def test_a_script_parses(name: str) -> None:
    shell = SHELL_SCRIPTS[name]
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is not installed")

    checked = subprocess.run([shell, "-n", str(DEBIAN / name)], capture_output=True, text=True)

    assert checked.returncode == 0, checked.stderr
    assert read(DEBIAN / name).startswith(f"#!/bin/{shell}\n") == (name != "testlib.sh")


@pytest.mark.parametrize("name", RUN_DIRECTLY)
def test_a_script_is_executable(name: str) -> None:
    assert os.access(DEBIAN / name, os.X_OK)


# nfpm.yaml


def test_every_file_nfpm_is_told_to_package_is_in_the_tree() -> None:
    spec = read(DEBIAN / "nfpm.yaml")
    sources = re.findall(r"^\s+- src: (\S+)$", spec, flags=re.MULTILINE)
    scripts = re.findall(r"^\s+(?:postinstall|preremove|postremove): (\S+)$", spec, re.M)

    assert len(scripts) == 3
    in_tree = [source for source in sources if not source.startswith("/")]
    # What build.sh makes inside the container: /opt/segl, the documents, and
    # the changelog.
    assert sorted(set(sources) - set(in_tree)) == ["/build/changelog.gz", "/build/doc", "/opt/segl"]
    for path in (*in_tree, *scripts):
        assert (ROOT / path).is_file(), path


def test_the_package_is_segl_under_apache_2() -> None:
    spec = read(DEBIAN / "nfpm.yaml")

    assert re.search(r"^name: segl$", spec, re.M)
    assert re.search(r"^arch: amd64$", spec, re.M)
    assert re.search(r"^version: \$\{SEGL_DEB_VERSION\}$", spec, re.M)
    assert re.search(rf"^license: {re.escape(VERSIONS['project']['license'])}$", spec, re.M)
    assert re.search(r"^\s+- systemd$", spec, re.M)
    assert re.search(r"^\s+- libc6 \(>= \d+\.\d+\)$", spec, re.M)
    assert "dst: /usr/lib/systemd/system/segl.service" in spec
    assert "dst: /usr/share/doc/segl/copyright" in spec


def test_the_package_ships_no_file_in_the_folders_it_must_not_own() -> None:
    """dpkg removes and overwrites what a package ships. The settings and the
    boards are the site's, so postinst makes them and nfpm.yaml names neither."""
    spec = read(DEBIAN / "nfpm.yaml")
    placed = re.findall(r"^\s+dst: (\S+)$", spec, flags=re.MULTILINE)

    assert "/opt/segl" in placed
    for path in placed:
        assert not path.startswith(("/opt/segl/etc", "/opt/segl/var", "/etc")), path
    assert not re.search(r"type: config", spec), "no dpkg conffile: an upgrade never stops to ask"


# The account and the folders


def test_the_account_is_segl_with_no_shell() -> None:
    lines = [line.split() for line in read(DEBIAN / "sysusers.conf").splitlines()]
    (account,) = [line for line in lines if line and not line[0].startswith("#")]

    assert account[:3] == ["u", "segl", "-"]
    assert account[-2:] == ["/opt/segl", "/usr/sbin/nologin"]


def test_the_folders_are_roots_settings_and_segls_data() -> None:
    lines = [line.split() for line in read(DEBIAN / "tmpfiles.conf").splitlines()]
    folders = [line for line in lines if line and not line[0].startswith("#")]

    assert folders == [
        ["d", "/opt/segl/etc", "0755", "root", "root", "-"],
        ["d", "/opt/segl/var", "0750", "segl", "segl", "-"],
    ]


def test_the_example_settings_keep_everything_in_those_two_folders() -> None:
    settings = load_settings(DEPLOY / "segl.toml.example")

    assert settings.database.parent == OPT / "var"
    assert settings.assets_dir.parent == OPT / "var"
    assert settings.display_names.parent == OPT / "etc"
    assert settings.web_dir == OPT / "app" / "web" / "dist"
    assert settings.host == "127.0.0.1"


def test_postinst_creates_the_settings_for_root_and_segls_group() -> None:
    postinst = read(DEBIAN / "postinst")

    assert "systemd-sysusers segl.conf" in postinst
    assert "systemd-tmpfiles --create segl.conf" in postinst
    assert 'install_file "$SHARE/segl.toml.example" "$ETC/segl.toml" segl 0640' in postinst
    assert 'install_file "$SHARE/display-names.txt" "$ETC/display-names.txt" root 0644' in postinst
    # Only when the file is missing, and the unit only if it was running.
    assert '[ -e "$2" ] && return 0' in postinst
    assert "systemctl try-restart segl.service" in postinst
    assert "systemctl enable" not in postinst
    assert "systemctl start" not in postinst


def test_purge_removes_the_settings_and_keeps_the_boards() -> None:
    postrm = read(DEBIAN / "postrm")
    purge = postrm.split("    purge)", 1)[1].split(";;", 1)[0]

    assert "rm -rf /opt/segl/etc" in purge
    assert "rmdir /opt/segl/var /opt/segl" in purge
    assert "rm -rf /opt/segl/var" not in postrm
    assert "rm -rf /opt/segl\n" not in postrm
    assert "userdel" not in postrm


# The unit


def test_the_unit_runs_the_packaged_command_as_segl() -> None:
    service = unit()["Service"]

    assert service["ExecStart"] == "/opt/segl/venv/bin/segl --config /opt/segl/etc/segl.toml"
    assert service["User"] == service["Group"] == "segl"
    assert service["Restart"] == "on-failure"
    # Exit status 2 is a setting segl cannot use (src/segl/cli.py).
    assert service["RestartPreventExitStatus"] == "2"
    assert unit()["Install"]["WantedBy"] == "multi-user.target"


def test_the_unit_gives_a_stop_time_to_write_the_slots() -> None:
    service = unit()["Service"]

    assert service["TimeoutStopSec"] == "20"
    # SIGTERM, on which segl flushes (docs/DEPLOY.md), is systemd's default.
    assert "KillSignal" not in service
    assert "KillMode" not in service


def test_the_unit_lets_segl_write_its_data_folder_and_nothing_else() -> None:
    service = unit()["Service"]

    assert service["ProtectSystem"] == "strict"
    assert service["ReadWritePaths"] == "/opt/segl/var"
    assert service["NoNewPrivileges"] == "yes"
    assert service["CapabilityBoundingSet"] == ""
    for key in ("database", "assets_dir"):
        assert str(DEFAULTS[key]).startswith(service["ReadWritePaths"] + "/"), key
    # nginx on the same host reaches segl over loopback.
    assert "AF_INET" in service["RestrictAddressFamilies"].split()


def test_the_manual_shows_the_unit_as_it_is() -> None:
    manual = read(ROOT / "docs" / "DEPLOY.md")
    shown = re.search(r"^```ini\n(.*?)^```$", manual, flags=re.MULTILINE | re.DOTALL)
    assert shown, "docs/DEPLOY.md shows the unit in an ```ini block"
    lines = [line for line in shown.group(1).splitlines() if line.strip()]
    real = read(UNIT).splitlines()

    assert "[Service]" in lines
    assert len(lines) > 5
    for line in lines:
        assert line in real, f"docs/DEPLOY.md shows {line!r}, which the unit does not have"


# The copyright file and the license texts


def test_the_copyright_file_names_apache_2_for_segl() -> None:
    copyright_file = read(DEBIAN / "copyright")
    first = copyright_file.split("\n\n")[1]

    assert first == "Files: *\nCopyright: 2026 segl contributors\nLicense: Apache-2.0"
    assert VERSIONS["project"]["license"] == "Apache-2.0"


def test_the_copyright_file_names_every_package_in_the_virtualenv() -> None:
    copyright_file = read(DEBIAN / "copyright")
    packages = runtime_packages()

    assert len(packages) >= len(VERSIONS["python"]["dependencies"])
    for name in packages:
        assert re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", copyright_file), (
            f"deploy/debian/copyright does not name {name}, which uv.lock installs"
        )


def test_every_license_the_copyright_file_uses_has_its_paragraph() -> None:
    copyright_file = read(DEBIAN / "copyright")
    paragraphs = copyright_file.split("\n\n")
    used: set[str] = set()
    explained: set[str] = set()
    for paragraph in paragraphs:
        field = re.search(r"^License: (.+)$", paragraph, flags=re.MULTILINE)
        if field is None:
            continue
        if paragraph.startswith("License: "):
            explained.add(field.group(1))
        else:
            used.update(field.group(1).split(" and "))

    assert used == explained


def test_the_build_checks_the_license_texts_the_copyright_file_points_at() -> None:
    build = read(DEBIAN / "build.sh")

    assert 'node scripts/collect-licenses.ts "$DOC/web-licenses" "$DOC/font-licenses"' in build
    # Called, and not only defined: the calls are the script's last lines.
    assert "\ncheck_python_licenses\n" in build.rsplit("\nunpack_source\n", 1)[1]
    assert '[ -s "$stdlib/LICENSE.txt" ]' in build


def test_everything_in_the_real_build_has_a_license_text(tmp_path: Path) -> None:
    """Run the collector against web/dist, when there is one."""
    if not (ROOT / "web" / ".bundled-packages.json").is_file():
        pytest.skip("web/dist is not built: `npm --prefix web run build`")
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    collected = subprocess.run(
        [node, "scripts/collect-licenses.ts", str(tmp_path / "web"), str(tmp_path / "fonts")],
        cwd=ROOT / "web",
        capture_output=True,
        text=True,
    )

    assert collected.returncode == 0, collected.stderr
    listed = read(tmp_path / "web" / "PACKAGES.txt")
    excalidraw = VERSIONS["web"]["dependencies"]["@excalidraw/excalidraw"]
    assert f"@excalidraw/excalidraw {excalidraw} MIT\n" in listed
    assert f"react {VERSIONS['web']['dependencies']['react']} MIT\n" in listed
    for folder in (tmp_path / "web").iterdir():
        if folder.is_dir():
            assert any(folder.iterdir()), f"{folder.name} has no license text"
    fonts = sorted(folder.name for folder in (tmp_path / "fonts").iterdir())
    assert fonts == sorted(
        folder.name for folder in (ROOT / "web" / "dist" / "fonts").iterdir() if folder.is_dir()
    )


# The font segl ships in place of the editor's (D2-026)

LIBERATION = Path("fonts") / "Liberation" / "LiberationSans-Regular.woff2"


def test_the_liberation_sans_segl_ships_is_the_file_its_record_names() -> None:
    shipped = (ROOT / "web" / LIBERATION).read_bytes()
    record = read(ROOT / "web" / "licenses" / "README.md")
    digest = hashlib.sha256(shipped).hexdigest()

    assert shipped[:4] == b"wOF2"
    assert f"`web/{LIBERATION}`, SHA-256 `{digest}`" in record, (
        "web/licenses/README.md names another file: a new font needs its source recorded there"
    )
    assert "Liberation Fonts 2.1.5" in record


def test_the_real_build_carries_that_liberation_sans() -> None:
    built = ROOT / "web" / "dist" / LIBERATION
    if not built.is_file():
        pytest.skip("web/dist is not built: `npm --prefix web run build`")

    assert built.read_bytes() == (ROOT / "web" / LIBERATION).read_bytes()


def test_no_font_license_segl_keeps_or_names_is_the_gpl() -> None:
    kept = [path for path in (ROOT / "web" / "licenses" / "fonts").rglob("*") if path.is_file()]
    fonts = read(DEBIAN / "copyright").split("Files: opt/segl/app/web/dist/fonts/*", 1)[1]
    licenses = re.search(r"^License: (.+)$", fonts, flags=re.MULTILINE)

    assert len(kept) >= 9
    for path in kept:
        assert "GNU GENERAL PUBLIC LICENSE" not in read(path), path
    assert licenses
    assert licenses.group(1) == "OFL-1.1 and MIT"
    assert "License: GPL" not in read(DEBIAN / "copyright")


def test_the_install_test_holds_the_packaged_font_to_the_checkouts() -> None:
    runner = read(DEBIAN / "package-test.sh")
    test = read(DEBIAN / "systemd-test.sh")

    assert f"sha256sum web/{LIBERATION}" in runner
    assert '--env SEGL_LIBERATION_SHA256="$liberation"' in runner
    assert f"sha256sum /opt/segl/app/web/dist/{LIBERATION}" in test
    assert 'equals "$SEGL_LIBERATION_SHA256"' in test


def test_every_lintian_override_is_for_segl_and_has_a_reason() -> None:
    lines = read(DEBIAN / "lintian-overrides").splitlines()
    overrides = [index for index, line in enumerate(lines) if line and not line.startswith("#")]

    assert overrides
    for index in overrides:
        assert lines[index].startswith("segl: "), lines[index]
        before = index - 1
        while lines[before].startswith("segl: "):
            before -= 1
        assert lines[before].startswith("# "), f"no reason above {lines[index]!r}"


# The operator notes and the install test


def test_the_install_test_runs_the_nginx_commands_of_the_operator_notes() -> None:
    notes = read(DEPLOY / "OPERATOR.md")
    test = read(DEBIAN / "systemd-test.sh")
    commands = re.findall(r"^sudo (install -m 644 \S+\s+\S+)$", notes, flags=re.MULTILINE)

    assert len(commands) == 4
    for command in commands:
        assert " ".join(command.split()) in test, command
        source = command.split()[3]
        assert (DEPLOY / "nginx" / Path(source).name).is_file(), source
    assert "sudo systemctl enable --now segl" in notes
    assert "systemctl enable --now segl.service" in test
    assert "include snippets/segl-board.conf;" in notes
    assert "include snippets/segl-board.conf;" in read(DEPLOY / "nginx" / "site-board.example.conf")


def test_the_install_test_waits_for_nginx_to_finish_its_reload() -> None:
    """A reload returns before the old workers are gone, and one of them can
    still answer on port 80 with the old configuration. The test asked port 80
    too soon once, on CI."""
    test = read(DEBIAN / "systemd-test.sh")
    reload = test.index('check "nginx reloads" systemctl reload-or-restart nginx')
    waited = test.index('check "the workers from before the reload are gone" gone $before_reload')
    asked = test.index('check "plain HTTP only sends the browser to HTTPS"')

    assert test.index("before_reload=$(nginx_workers)") < reload < waited < asked


def test_a_failed_check_of_the_install_test_says_what_the_command_printed() -> None:
    library = read(DEBIAN / "testlib.sh")

    assert 'if "$@" >/tmp/check.out 2>&1; then' in library
    assert "tail -n 5 /tmp/check.out" in library
    assert "printf 'got:    %s\\nwanted: %s\\n'" in library


def test_the_operator_notes_say_what_the_manual_asks_for() -> None:
    notes = read(DEPLOY / "OPERATOR.md")

    for needed in (
        "apt install ./segl_",
        "access_codes",
        "access_secret",
        "access_passes_after",
        "internal_networks",
        "display-names.txt",
        "systemctl restart segl",
        "not a login",
        "The slots are shared",
        "Protected inventory is not available",
    ):
        assert needed in notes, needed


def test_the_operator_notes_show_no_real_code_or_secret() -> None:
    notes = read(DEPLOY / "OPERATOR.md")
    shown = re.search(r'^access_secret = "(.*)"$', notes, flags=re.MULTILINE)

    assert shown
    assert shown.group(1).startswith("<"), "a placeholder, not a secret someone would copy"


def test_the_install_test_names_the_host_of_the_example_site() -> None:
    site = read(DEPLOY / "nginx" / "site-board.example.conf")
    runner = read(DEBIAN / "package-test.sh")

    assert "server_name dev.example.com;" in site
    assert "--hostname dev.example.com" in runner
    assert "include snippets/snakeoil.conf;" in site
    assert "ssl-cert" in read(DEBIAN / "Containerfile.systemd")
