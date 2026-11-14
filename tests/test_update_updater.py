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

"""The update's order: verify, stop, save, install, merge, check, start, or go back.

apt, systemctl, nginx, and the installed ``segl`` are played by a runner.
The releases are real files signed with a throwaway key, and ``ssh-keygen``
checks them for real. The install test runs the same update with real
packages on a machine that booted systemd (``deploy/debian/systemd-test.sh``).
"""

import fcntl
import http.server
import json
import os
import shutil
import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from update_helpers import (
    API,
    FakeGitHub,
    Keys,
    ScriptedRunner,
    install_nginx_files,
    make_keys,
    make_paths,
    make_release,
    sign,
)

from segl.update import backup, updater
from segl.update.paths import SERVICE
from segl.update.process import NOT_FOUND, RunResult
from segl.update.updater import AVAILABLE, UpdateError, Updater, local_get
from segl.update.versions import Version

V = Version.parse
OLD, NEW = "9.0.1", "9.0.2"
SECRET = 'access_secret = "a-secret-that-is-long-enough-0123456789"\n'
STEPS = ("apt", "merge", "check", "nginx", "start", "answer")


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> Keys:
    return make_keys(tmp_path_factory.mktemp("keys"))


class Machine:
    """A host with segl ``OLD`` installed and running, and a GitHub it can reach."""

    def __init__(self, folder: Path, keys: Keys) -> None:
        self.keys = keys
        self.paths = make_paths(folder)
        shutil.copy(keys.signers, self.paths.signers)
        install_nginx_files(self.paths)
        self.database = folder / "opt/segl/var/segl.sqlite"
        self.database.parent.mkdir(parents=True)
        self.database.write_bytes(b"the boards, as 9.0.1 wrote them")
        # The record an installed package keeps of its nginx files, as merged.
        self.paths.merged.mkdir(parents=True)
        for name, shipped, _ in self.paths.nginx_pairs():
            shutil.copy(shipped, self.paths.merged / name)
        self.releases = folder / "releases"
        self.github = FakeGitHub()
        self.github.add(make_release(self.releases, OLD, keys.release))
        # What is installed and whether it runs. An update changes both.
        self.package = OLD
        self.running = True
        self.nginx = True
        self.nginx_active = True
        # The step at which a version fails, such as {"9.0.2": "start"}.
        self.fails: dict[str, str] = {}
        # Versions whose package apt says it cannot install.
        self.unmet: set[str] = set()
        self.restarts = 0
        self.nginx_broken_before = False
        self.said: list[str] = []
        self.clock = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)
        self.probed = 0
        binary = str(self.paths.binary)
        self.runner = ScriptedRunner(
            {
                ("systemctl", "is-active", "--quiet", SERVICE): self._is_active,
                ("systemctl", "stop", SERVICE): self._stop,
                # Not in systemd's failed state, unless a test says so.
                ("systemctl", "is-failed", "--quiet", SERVICE): 1,
                # How often systemd has started the unit again since its start.
                ("systemctl", "show", "-p", "NRestarts"): lambda args: RunResult(
                    0, f"{self.restarts}\n"
                ),
                ("systemctl", "start", SERVICE): self._start,
                ("systemctl", "is-active", "--quiet", "nginx.service"): self._nginx_is_active,
                ("apt-get", "install"): self._apt,
                ("apt-get", "install", "--simulate"): self._simulate,
                (binary, "config", "merge"): lambda args: self._step("merge", "a conflict"),
                (binary, "check"): lambda args: self._step("check", "unknown key retired"),
                ("nginx", "-v"): lambda args: RunResult(0 if self.nginx else NOT_FOUND, ""),
                ("nginx", "-t"): self._nginx_test,
            }
        )

    def release(self, version: str, latest: bool = True) -> Path:
        home = make_release(self.releases, version, self.keys.release)
        self.github.add(home, latest)
        return home

    def updater(self, installed: str = OLD) -> Updater:
        return Updater(
            paths=self.paths,
            installed=V(installed),
            update_url=API,
            version_url="http://127.0.0.1:8888/api/v1/version",
            database=self.database,
            http=self.github,
            run=self.runner,
            probe=self._probe,
            say=self.said.append,
            now=self._now,
            sleep=lambda seconds: None,
            settle=6,
        )

    def text(self) -> str:
        return "\n".join(self.said)

    def record(self) -> dict[str, str]:
        return json.loads(self.paths.record.read_text(encoding="utf-8"))

    def installs(self) -> list[str]:
        """Return the package files apt was asked to install, in order."""
        return [
            Path(call[-1]).name
            for call in self.runner.called("apt-get", "install")
            if "--simulate" not in call
        ]

    def merged_record(self) -> dict[str, bytes]:
        return {path.name: path.read_bytes() for path in sorted(self.paths.merged.iterdir())}

    def _now(self) -> datetime:
        self.clock += timedelta(seconds=1)
        return self.clock

    def _fails(self, step: str) -> bool:
        return self.fails.get(self.package) == step

    def _step(self, step: str, said: str) -> RunResult:
        return RunResult(1, f"segl: {said}\n") if self._fails(step) else RunResult(0, "")

    def _is_active(self, args: Sequence[str]) -> RunResult:
        return RunResult(0 if self.running else 3, "")

    def _stop(self, args: Sequence[str]) -> RunResult:
        self.running = False
        return RunResult(0, "")

    def _start(self, args: Sequence[str]) -> RunResult:
        if self._fails("start"):
            return RunResult(1, "Job for segl.service failed.\n")
        self.running = True
        if self.package != OLD:
            # A newer version migrates the database when it starts.
            self.database.write_bytes(f"migrated by {self.package}".encode())
        return RunResult(0, "")

    def _nginx_is_active(self, args: Sequence[str]) -> RunResult:
        return RunResult(0 if self.nginx_active else 3, "")

    def _nginx_test(self, args: Sequence[str]) -> RunResult:
        broken = self.nginx_broken_before or self._fails("nginx")
        return RunResult(1, "nginx: [emerg] unknown directive\n") if broken else RunResult(0, "")

    def _simulate(self, args: Sequence[str]) -> RunResult:
        if Path(args[-1]).name.split("_")[1] in self.unmet:
            return RunResult(100, "E: Unable to satisfy dependencies. segl Depends on newthing\n")
        return RunResult(0, "Inst segl\n")

    def _apt(self, args: Sequence[str]) -> RunResult:
        version = Path(args[-1]).name.split("_")[1]
        if self.fails.get(version) == "apt":
            return RunResult(100, "E: Sub-process /usr/bin/dpkg returned an error code (1)\n")
        self.package = version
        if version != OLD:
            # What a newer package's postinst does: new statements go in.
            with self.paths.config_file.open("a", encoding="utf-8") as handle:
                handle.write(f'added_by = "{version}"\n')
            proxy = self.paths.nginx_dir / "snippets/segl-proxy.conf"
            proxy.write_text(proxy.read_text(encoding="utf-8") + f"# {version}\n", encoding="utf-8")
            # And the record moves on: a file of the release, and a new one.
            (self.paths.merged / "segl-proxy.conf").write_text(version, encoding="utf-8")
            (self.paths.merged / "segl-new.conf").write_text(version, encoding="utf-8")
        said = f"Setting up segl ({version}) ...\nsegl config merge: added added_by to segl.toml\n"
        return RunResult(0, said)

    def _probe(self, url: str) -> bytes:
        self.probed += 1
        if not self.running or self._fails("answer"):
            raise ConnectionRefusedError("connection refused")
        return json.dumps({"version": self.package}).encode()


@pytest.fixture
def machine(tmp_path: Path, keys: Keys) -> Machine:
    return Machine(tmp_path, keys)


def yes(question: str) -> bool:
    return True


def no(question: str) -> bool:
    return False


def test_check_says_a_newer_release_is_out_and_changes_nothing(machine: Machine) -> None:
    machine.release(NEW)

    assert machine.updater().check() == AVAILABLE == 100

    assert machine.said == [
        "segl 9.0.1 is installed; 9.0.2 is available (2026-11-13).",
        "  Release notes: https://github.test/example/segl/releases/tag/v9.0.2",
        "To install it: sudo segl update",
    ]
    assert machine.runner.calls == []
    assert [path.name for path in machine.paths.update_dir.iterdir()] == ["merged"]


def test_check_says_up_to_date(machine: Machine) -> None:
    assert machine.updater().check() == 0
    assert machine.said == ["segl 9.0.1 is installed: up to date."]

    machine.said.clear()
    assert machine.updater("9.1.0").check() == 0
    assert machine.said == [
        "segl 9.1.0 is installed, newer than the latest release (9.0.1): up to date."
    ]


def test_check_fails_when_github_cannot_be_reached(machine: Machine) -> None:
    machine.github.broken[f"{API}/releases/latest"] = "[Errno 110] Connection timed out"

    assert machine.updater().check() == 1
    assert machine.said == [f"segl update: {API}/releases/latest: [Errno 110] Connection timed out"]


def test_an_update_goes_through_its_steps_in_order(machine: Machine) -> None:
    machine.release(NEW)
    binary, config = str(machine.paths.binary), str(machine.paths.config_file)

    assert machine.updater().update(None, yes) == 0

    package = str(machine.paths.cache / NEW / "segl_9.0.2_amd64.deb")
    calls = [call for call in machine.runner.calls if call[0] != "ssh-keygen"]
    assert calls == [
        ["nginx", "-v"],
        ["nginx", "-t"],
        ["apt-get", "install", "--simulate", package],
        ["systemctl", "is-active", "--quiet", SERVICE],
        ["systemctl", "stop", SERVICE],
        [
            "apt-get",
            "install",
            "-y",
            "--allow-downgrades",
            "-o",
            "DPkg::Lock::Timeout=300",
            package,
        ],
        [binary, "config", "merge", "--write", "--config", config],
        [binary, "check", "--config", config],
        ["nginx", "-v"],
        ["nginx", "-t"],
        ["systemctl", "reset-failed", SERVICE],
        ["systemctl", "start", SERVICE],
    ]
    # Both releases were checked before anything else ran: the new one, and
    # the installed one, to go back to.
    assert [call[0] for call in machine.runner.calls[:2]] == ["ssh-keygen", "nginx"]
    assert len(machine.runner.called("ssh-keygen")) == 2
    apt = machine.runner.calls.index(calls[5])
    assert calls[5][:3] == ["apt-get", "install", "-y"]
    assert machine.runner.environments[apt] == {"DEBIAN_FRONTEND": "noninteractive"}
    assert machine.package == NEW and machine.running
    assert machine.said[-1] == "segl update: updated 9.0.1 -> 9.0.2"
    assert "  segl config merge: added added_by to segl.toml" in machine.said
    record = machine.record()
    assert (record["result"], record["from"], record["to"]) == ("updated", OLD, NEW)


def test_what_an_update_keeps(machine: Machine) -> None:
    machine.release(NEW)
    settings = machine.paths.config_file.read_bytes()
    wal = machine.database.with_name("segl.sqlite-wal")
    wal.write_bytes(b"pages not folded in yet")

    assert machine.updater().update(None, yes) == 0

    (saved,) = backup.list_backups(machine.paths.backups, backup.PRE_UPDATE)
    assert saved.stat().st_mode & 0o7777 == 0o700
    assert (saved / "etc/segl.toml").read_bytes() == settings
    assert (saved / "etc/segl.toml").stat().st_mode & 0o7777 == 0o640
    assert (saved / "database/segl.sqlite").read_bytes() == b"the boards, as 9.0.1 wrote them"
    assert (saved / "database/segl.sqlite-wal").read_bytes() == b"pages not folded in yet"
    for _, shipped, site in machine.paths.nginx_pairs():
        kept = saved / "nginx" / site.relative_to(machine.paths.nginx_dir)
        assert kept.read_bytes() == shipped.read_bytes()
    # The new version's package, and the one to go back to. Nothing else.
    assert sorted(path.name for path in machine.paths.cache.iterdir()) == [OLD, NEW]
    assert sorted(path.name for path in (machine.paths.cache / NEW).iterdir()) == [
        "SHA256SUMS",
        "SHA256SUMS.sig",
        "segl_9.0.2_amd64.deb",
    ]


def test_nothing_newer_means_nothing_happens(machine: Machine) -> None:
    assert machine.updater().update(None, yes) == 0

    assert machine.said == ["segl 9.0.1 is installed: up to date."]
    assert machine.runner.calls == []
    assert not machine.paths.cache.exists()


def test_an_answer_of_no_installs_nothing(machine: Machine) -> None:
    machine.release(NEW)
    asked = []

    def decline(question: str) -> bool:
        asked.append(question)
        return False

    assert machine.updater().update(None, decline) == 1

    assert asked == ["Install segl 9.0.2 now?"]
    assert machine.said[-1] == "Nothing was installed."
    assert machine.runner.calls == []
    assert not machine.paths.cache.exists()


def test_a_package_changed_after_signing_is_refused_before_anything_changes(
    machine: Machine,
) -> None:
    home = machine.release(NEW)
    with (home / "segl_9.0.2_amd64.deb").open("ab") as handle:
        handle.write(b"x")

    assert machine.updater().update(None, yes) == 1

    assert "segl_9.0.2_amd64.deb does not match its line in SHA256SUMS" in machine.said[-1]
    assert machine.said[-1].endswith("Nothing was changed.")
    assert {call[0] for call in machine.runner.calls} == {"ssh-keygen"}
    assert machine.package == OLD and machine.running
    assert machine.record()["result"] == "refused"
    # The files that did not verify are not kept.
    assert not (machine.paths.cache / NEW).exists()
    assert not machine.paths.backups.exists() or list(machine.paths.backups.iterdir()) == []


def test_a_release_signed_by_another_key_is_refused(machine: Machine) -> None:
    home = machine.release(NEW)
    sign(home, machine.keys.stranger)

    assert machine.updater().update(None, yes) == 1

    assert "the signature on SHA256SUMS did not verify" in machine.said[-1]
    assert machine.installs() == []


def test_a_release_without_its_signature_is_not_installed(machine: Machine) -> None:
    home = machine.release(NEW)
    (home / "SHA256SUMS.sig").unlink()

    assert machine.updater().update(None, yes) == 1

    assert machine.said[-1] == "segl update: release v9.0.2 has no SHA256SUMS.sig"
    assert machine.runner.calls == []


def test_nginx_that_fails_its_test_as_things_are_stops_the_update(machine: Machine) -> None:
    machine.release(NEW)
    machine.nginx_broken_before = True

    assert machine.updater().update(None, yes) == 1

    assert "nginx -t fails as things are, so nothing was changed" in machine.said[-1]
    assert machine.runner.called("systemctl") == []
    assert machine.installs() == []
    assert machine.running


def test_a_package_apt_cannot_install_stops_the_update_before_segl_is_stopped(
    machine: Machine,
) -> None:
    machine.release(NEW)
    machine.unmet.add(NEW)

    assert machine.updater().update(None, yes) == 1

    assert machine.said[-1] == (
        "segl update: apt cannot install segl_9.0.2_amd64.deb, so nothing was changed: "
        "E: Unable to satisfy dependencies. segl Depends on newthing"
    )
    assert machine.runner.called("systemctl") == []
    assert machine.installs() == []
    assert machine.running
    # Not the release's fault for good: the timer tries it again tomorrow.
    assert not machine.paths.record.exists()


def test_a_host_without_nginx_skips_its_tests(machine: Machine) -> None:
    machine.release(NEW)
    machine.nginx = False

    assert machine.updater().update(None, yes) == 0

    assert machine.runner.called("nginx", "-t") == []


@pytest.mark.parametrize("step", STEPS)
def test_a_step_that_fails_goes_back_to_the_previous_version(machine: Machine, step: str) -> None:
    machine.release(NEW)
    machine.fails[NEW] = step
    before = {
        "settings": machine.paths.config_file.read_bytes(),
        "proxy": (machine.paths.nginx_dir / "snippets/segl-proxy.conf").read_bytes(),
        "merged": machine.merged_record(),
    }
    assert len(before["merged"]) == 3

    assert machine.updater().update(None, yes) == 1

    # The previous package is back, unless apt never put the new one in.
    assert machine.installs() == ["segl_9.0.2_amd64.deb", "segl_9.0.1_amd64.deb"]
    assert machine.package == OLD
    assert machine.running
    assert machine.paths.config_file.read_bytes() == before["settings"]
    proxy = machine.paths.nginx_dir / "snippets/segl-proxy.conf"
    assert proxy.read_bytes() == before["proxy"]
    # The record of merged nginx files too: its contents, and no file more.
    assert machine.merged_record() == before["merged"]
    said = machine.text()
    assert "segl update: 9.0.2 failed: " in said
    assert "segl update: going back to 9.0.1" in said
    assert machine.said[-1] == "segl update: 9.0.1 answers again"
    record = machine.record()
    assert (record["result"], record["from"], record["to"]) == ("failed", OLD, NEW)
    assert record["message"]
    # The database goes back only when the new version was started.
    started = step in ("start", "answer")
    assert ("the database is as it was before the update" in said) == started
    assert machine.database.read_bytes() == b"the boards, as 9.0.1 wrote them"
    assert bool(machine.runner.called("systemctl", "reset-failed")) is True
    starts = machine.runner.called("systemctl", "start", SERVICE)
    assert len(starts) == (2 if started else 1)
    # Stopped once to save, and again before the files of a started version go back.
    assert len(machine.runner.called("systemctl", "stop", SERVICE)) == (2 if started else 1)


def test_going_back_reloads_nginx_when_its_files_went_back(machine: Machine) -> None:
    machine.release(NEW)
    machine.fails[NEW] = "check"

    assert machine.updater().update(None, yes) == 1

    assert machine.runner.called("systemctl", "reload", "nginx.service") == [
        ["systemctl", "reload", "nginx.service"]
    ]
    # Tested before the update, and after the files went back. The update
    # stopped at `segl check`, before its own test of nginx.
    assert len(machine.runner.called("nginx", "-t")) == 2


@pytest.mark.parametrize(
    ("step", "said"),
    [
        ("apt", "apt-get install failed: E: Sub-process /usr/bin/dpkg returned an error code (1)"),
        ("merge", "segl config merge failed: segl: a conflict"),
        ("check", "segl check failed: segl: unknown key retired"),
        ("nginx", "nginx -t failed: nginx: [emerg] unknown directive"),
        ("start", "segl.service did not start; see `journalctl -u segl`"),
        ("answer", "segl.service did not answer as 9.0.2 within 6 s (connection refused)"),
    ],
)
def test_a_failure_says_which_step_and_what_it_said(machine: Machine, step: str, said: str) -> None:
    machine.release(NEW)
    machine.fails[NEW] = step

    assert machine.updater().update(None, yes) == 1

    assert f"segl update: 9.0.2 failed: {said}" in machine.said
    assert machine.record()["message"] == said


def test_a_version_that_answers_as_another_is_a_failure(machine: Machine) -> None:
    machine.release(NEW)
    updater_ = machine.updater()
    updater_.probe = lambda url: json.dumps({"version": OLD}).encode()

    assert updater_.update(None, yes) == 1

    assert "segl.service did not answer as 9.0.2 within 6 s (it answers as 9.0.1)" in machine.text()


def test_a_unit_that_systemd_gave_up_on_is_not_waited_for(machine: Machine) -> None:
    machine.release(NEW)
    machine.fails[NEW] = "answer"
    machine.runner.replies[("systemctl", "is-failed", "--quiet", SERVICE)] = lambda args: RunResult(
        0 if machine.package == NEW else 1, ""
    )

    assert machine.updater().update(None, yes) == 1

    assert "segl.service failed to start; see `journalctl -u segl`" in machine.text()
    # Asked once before the install, and once after the start. Not for a minute.
    assert machine.probed == 3
    assert machine.said[-1] == "segl update: 9.0.1 answers again"


@pytest.mark.parametrize(("restarts", "probes"), [(0, 5), (1, 5), (2, 2), (5, 2)])
def test_a_unit_that_keeps_stopping_is_not_waited_for(
    machine: Machine, restarts: int, probes: int
) -> None:
    machine.release(NEW)
    machine.fails[NEW] = "answer"
    updater_ = machine.updater()
    # The new version dies each time systemd starts it. The old one runs.
    seen: list[str] = []

    def probe(url: str) -> bytes:
        seen.append(machine.package)
        machine.restarts = restarts if machine.package == NEW else 0
        return machine._probe(url)

    updater_.probe = probe

    assert updater_.update(None, yes) == 1

    # Asked once before the install. Then to the end of the wait, unless
    # the unit was started again twice: then once, and it goes back.
    assert seen.count(NEW) == probes - 1
    said = machine.text()
    assert ("segl.service keeps stopping; see `journalctl -u segl`" in said) == (restarts >= 2)
    assert ("segl.service did not answer as 9.0.2 within 6 s" in said) == (restarts < 2)
    assert machine.said[-1] == "segl update: 9.0.1 answers again"


def test_a_unit_that_answers_is_not_asked_how_often_it_restarted(machine: Machine) -> None:
    machine.release(NEW)
    machine.restarts = 4

    # It crashed on the way and came up: it answers as the new version.
    assert machine.updater().update(None, yes) == 0


def test_a_service_that_was_stopped_is_left_stopped(machine: Machine) -> None:
    machine.release(NEW)
    machine.running = False

    assert machine.updater().update(None, yes) == 0

    assert machine.runner.called("systemctl", "stop") == []
    assert machine.runner.called("systemctl", "start") == []
    assert not machine.running
    assert "segl update: segl.service was not running, and is left stopped" in machine.said
    # Called once, before the install, and never to wait for an answer.
    assert machine.probed == 1


def test_a_stopped_service_stays_stopped_when_the_update_goes_back(machine: Machine) -> None:
    machine.release(NEW)
    machine.running = False
    machine.fails[NEW] = "check"

    assert machine.updater().update(None, yes) == 1

    assert machine.package == OLD and not machine.running
    assert machine.runner.called("systemctl", "start") == []


def test_the_timer_does_not_try_again_a_release_that_failed(machine: Machine) -> None:
    machine.release(NEW)
    machine.fails[NEW] = "start"
    assert machine.updater().update(None, yes, auto=True) == 1
    machine.runner.calls.clear()
    machine.said.clear()

    assert machine.updater().update(None, yes, auto=True) == 0

    assert machine.runner.calls == []
    assert "9.0.2 did not install last time" in machine.said[-1]
    assert "sudo segl update --version 9.0.2" in machine.said[-1]
    # A person at the console still can, and a newer release is tried.
    machine.fails.clear()
    machine.release("9.0.3")
    assert machine.updater().update(None, yes, auto=True) == 0
    assert machine.package == "9.0.3"


def test_a_person_may_try_again_a_release_that_failed(machine: Machine) -> None:
    machine.release(NEW)
    machine.fails[NEW] = "start"
    assert machine.updater().update(None, yes) == 1
    machine.fails.clear()

    assert machine.updater().update(None, yes) == 0
    assert machine.package == NEW


def test_the_package_to_go_back_to_is_fetched_when_it_is_not_at_hand(machine: Machine) -> None:
    machine.release(NEW)

    assert machine.updater().update(None, yes) == 0

    assert f"{API}/releases/tags/v9.0.1" in machine.github.asked
    assert (machine.paths.cache / OLD / "segl_9.0.1_amd64.deb").is_file()


def test_the_package_to_go_back_to_is_not_fetched_twice(machine: Machine) -> None:
    machine.release(NEW)
    assert machine.updater().update(None, yes) == 0
    machine.release("9.0.3")
    machine.github.asked.clear()

    assert machine.updater(NEW).update(None, yes) == 0

    # 9.0.2 is in the cache from the update that installed it.
    assert f"{API}/releases/tags/v9.0.2" not in machine.github.asked
    assert sorted(path.name for path in machine.paths.cache.iterdir()) == [NEW, "9.0.3"]


def test_without_a_package_to_go_back_to_a_person_is_told_and_the_timer_refuses(
    machine: Machine,
) -> None:
    machine.release(NEW)
    del machine.github.releases[OLD]

    assert machine.updater().update(None, yes, auto=True) == 1

    assert "does not start without a package to go back to" in machine.said[-1]
    assert machine.installs() == []
    assert machine.running

    machine.said.clear()
    machine.fails[NEW] = "check"
    assert machine.updater().update(None, yes) == 1

    said = machine.text()
    assert "no verified package of 9.0.1 is at hand" in said
    assert "so the new one stays installed" in said
    assert machine.installs() == ["segl_9.0.2_amd64.deb"]
    assert "added_by" not in machine.paths.config_file.read_text(encoding="utf-8")


def test_a_named_version_is_installed_even_if_it_is_older(machine: Machine) -> None:
    machine.release("9.0.0", latest=False)

    assert machine.updater().update(V("9.0.0"), yes) == 0

    assert machine.said[0] == "segl 9.0.1 is installed; 9.0.0 was asked for."
    assert machine.installs() == ["segl_9.0.0_amd64.deb"]


def test_a_named_version_that_does_not_exist_is_an_error(machine: Machine) -> None:
    assert machine.updater().update(V("9.9.9"), yes) == 1

    assert machine.said == [f"segl update: no release v9.9.9 at {API}"]


def test_a_release_from_a_folder_installs_without_github(machine: Machine, tmp_path: Path) -> None:
    home = make_release(tmp_path / "usb", NEW, machine.keys.release)

    assert machine.updater().install_from(home, yes) == 0

    assert machine.github.asked == []
    assert machine.package == NEW
    assert machine.said[0] == f"segl 9.0.1 is installed; 9.0.2 is in {home}."
    # Installed from root's own copy, not from the folder it was brought in.
    assert machine.runner.called("apt-get")[0][-1] == str(
        machine.paths.cache / NEW / "segl_9.0.2_amd64.deb"
    )
    assert "no verified package of 9.0.1 is at hand" in machine.text()


def test_a_folder_that_does_not_hold_one_release_is_refused(
    machine: Machine, tmp_path: Path
) -> None:
    home = make_release(tmp_path / "usb", NEW, machine.keys.release)
    (home / "SHA256SUMS.sig").unlink()

    assert machine.updater().install_from(home, yes) == 2
    assert "must also hold SHA256SUMS and SHA256SUMS.sig" in machine.said[-1]

    shutil.copy(home / "segl_9.0.2_amd64.deb", home / "segl_9.0.3_amd64.deb")
    assert machine.updater().install_from(home, yes) == 2
    assert "must hold one segl_<version>_amd64.deb" in machine.said[-1]

    assert machine.updater().install_from(tmp_path / "empty", yes) == 2
    assert machine.said[-1].endswith("(found: none)")
    assert machine.runner.calls == []


def test_a_tampered_release_from_a_folder_is_refused(machine: Machine, tmp_path: Path) -> None:
    home = make_release(tmp_path / "usb", NEW, machine.keys.release)
    with (home / "segl_9.0.2_amd64.deb").open("ab") as handle:
        handle.write(b"x")

    assert machine.updater().install_from(home, yes) == 1

    assert "does not match its line in SHA256SUMS" in machine.said[-1]
    assert machine.installs() == []


def test_only_one_update_runs_at_a_time(machine: Machine) -> None:
    machine.release(NEW)
    descriptor = os.open(machine.paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(UpdateError, match="another segl update is running"):
            machine.updater().update(None, yes)
    finally:
        os.close(descriptor)

    assert machine.runner.calls == []
    assert machine.updater().update(None, yes) == 0


def test_an_update_folder_that_is_missing_stops_the_update(machine: Machine) -> None:
    machine.release(NEW)
    shutil.rmtree(machine.paths.update_dir)

    with pytest.raises(UpdateError, match="is missing; install the package again"):
        machine.updater().update(None, yes)


def test_too_little_room_for_the_database_stops_the_update(
    machine: Machine, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine.release(NEW)
    usage = shutil.disk_usage(machine.paths.update_dir)
    monkeypatch.setattr(
        updater.shutil, "disk_usage", lambda path: usage._replace(free=updater.ROOM_TO_SPARE)
    )

    assert machine.updater().update(None, yes) == 1

    assert "MiB free, and the copy of the database needs" in machine.said[-1]
    assert machine.said[-1].endswith("Nothing was changed.")
    assert machine.runner.called("systemctl") == []
    assert machine.running


def test_a_service_that_does_not_stop_stops_the_update(machine: Machine) -> None:
    machine.release(NEW)
    machine.runner.replies[("systemctl", "stop", SERVICE)] = 1

    assert machine.updater().update(None, yes) == 1

    assert machine.said[-1] == "segl update: segl.service did not stop. Nothing was changed."
    assert machine.installs() == []
    assert machine.record()["result"] == "failed"


def test_only_the_newest_backups_are_kept_and_one_copy_of_the_database(machine: Machine) -> None:
    installed = OLD
    for patch in range(2, 7):
        version = f"9.0.{patch}"
        machine.release(version)
        assert machine.updater(installed).update(None, yes) == 0
        installed = version

    kept = backup.list_backups(machine.paths.backups, backup.PRE_UPDATE)
    assert len(kept) == 3
    assert [(saved / "database").is_dir() for saved in kept] == [True, False, False]
    assert all((saved / "etc/segl.toml").is_file() for saved in kept)
    assert sorted(path.name for path in machine.paths.cache.iterdir()) == ["9.0.5", "9.0.6"]


def test_the_settings_backup_is_read_by_nobody_else(machine: Machine) -> None:
    machine.paths.config_file.write_text(SECRET, encoding="utf-8")
    machine.release(NEW)

    assert machine.updater().update(None, yes) == 0

    for folder in (machine.paths.backups, machine.paths.cache):
        assert folder.stat().st_mode & 0o077 == 0
    assert "a-secret" not in machine.text()


def test_the_version_is_asked_on_this_host_and_never_through_a_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Version_(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b'{"version": "9.0.2"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Version_)
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    # A proxy from the environment that nothing listens on.
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/v1/version"
        assert json.loads(local_get(url)) == {"version": "9.0.2"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_an_update_folder_with_a_file_in_the_way_stops_the_update(machine: Machine) -> None:
    machine.release(NEW)
    # A file where the folder of backups should be.
    machine.paths.backups.write_text("in the way", encoding="utf-8")

    with pytest.raises(UpdateError, match="is not as the package made it"):
        machine.updater().update(None, yes)

    assert machine.runner.calls == []
    assert machine.running


def test_a_backup_that_fails_midway_changes_nothing_and_starts_segl_again(
    machine: Machine, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine.release(NEW)

    def no_room(folder: Path, database: Path) -> None:
        raise backup.BackupError(f"cannot save {database}: No space left on device")

    monkeypatch.setattr(updater.backup, "save_database", no_room)

    assert machine.updater().update(None, yes) == 1

    assert machine.said[-1].startswith("segl update: cannot save ")
    assert machine.said[-1].endswith("No space left on device. Nothing was changed.")
    assert machine.installs() == []
    # It had stopped segl to copy the database, and it started segl again.
    assert machine.runner.called("systemctl", "stop", SERVICE)
    assert machine.running
    assert machine.record()["result"] == "failed"


def test_going_back_goes_on_when_the_previous_package_does_not_install(machine: Machine) -> None:
    machine.release(NEW)
    machine.fails[NEW] = "check"
    machine.fails[OLD] = "apt"
    settings = machine.paths.config_file.read_bytes()

    assert machine.updater().update(None, yes) == 1

    said = machine.text()
    assert "segl update: reinstalling 9.0.1: apt-get install failed: E: Sub-process" in said
    # The files still go back, and it says what answers now.
    assert machine.paths.config_file.read_bytes() == settings
    assert "segl update: after going back, segl.service did not answer as 9.0.1" in said
    assert machine.record()["result"] == "failed"


def test_an_update_folder_that_another_user_owns_or_may_write_is_refused(
    machine: Machine, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine.release(NEW)
    # As root sees it: the folder belongs to the user who runs this test.
    monkeypatch.setattr(updater.os, "geteuid", lambda: 0)

    with pytest.raises(UpdateError, match="must be root's, and only root may write in it"):
        machine.updater().update(None, yes)

    assert machine.runner.calls == []
    assert not machine.paths.cache.exists()
