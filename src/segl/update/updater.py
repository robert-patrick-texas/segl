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

"""The update: find, download, verify, save, install, merge, check, and go back.

Nothing changes before a release verifies, ``nginx -t`` passes as things
are, and apt says it can install the package. Then, in this order:

1. segl is stopped, which writes every unsaved edit.
2. The settings, the nginx files, and the database are copied.
3. apt installs the package. Its ``postinst`` merges the new version's
   statements into the settings and the nginx files.
4. The new ``segl config merge`` must report that nothing is left unmerged,
   the new ``segl check`` must pass, and ``nginx -t`` must pass.
5. segl is started, and must answer as the new version.

If a step from 3 on fails, the previous package goes back in, with the
settings and the nginx files as they were. The database goes back only if
the new version was started: it may have migrated it, and the older version
does not open a database a newer one wrote.

The timer's update (``--auto``) is stricter. It installs only a newer
release. It leaves out one whose install failed last time, so a broken
release is not installed and taken out again every night. And it does not
start without a verified package of the installed version to go back to.

Everything is in ``/opt/segl/update``, which only root opens: ``cache/``
(the installed version's package and the one before), ``backups/``, the
record of the last update, and the lock. The order follows Sunstone's
updater.

This process runs the old version's code while apt replaces the files it
was loaded from. So it imports everything at the start, and after the
install it leaves the work to other programs: apt, systemctl, nginx, and
the new ``segl``.
"""

import contextlib
import fcntl
import json
import os
import shutil
import stat
import time
import urllib.request
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from segl.update import backup
from segl.update.paths import NGINX_SERVICE, SERVICE, Paths
from segl.update.process import Runner, run_command, tail
from segl.update.releases import Http, Release, ReleaseError, fetch_release
from segl.update.verify import SIG, SUMS, Artifacts, VerificationError, verify
from segl.update.versions import PACKAGE_NAME, Version

# How long the started service has to answer as the version it should be.
SETTLE_SECONDS = 60.0
# The exit status of --check when a newer release is out, as `dnf check-update`.
AVAILABLE = 100
# How long apt waits for another apt, such as the night's unattended upgrades.
APT_LOCK_SECONDS = 300
# Room the update wants left on the disk after the database is copied.
ROOM_TO_SPARE = 200 * 1024 * 1024
PREFIX = "segl update"

Say = Callable[[str], None]
Confirm = Callable[[str], bool]

# The name lookup of the check after the install needs this codec. It is
# loaded here, before apt can take the file away.
"127.0.0.1".encode("idna")


class UpdateError(Exception):
    """The update cannot start: another is running, or its folder is not safe."""


class _Failed(Exception):
    """A step after the install began failed, so the update goes back."""


def local_get(url: str) -> bytes:
    """Ask segl on this host, directly: never through a proxy from the environment."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as answer:
        return answer.read(65536)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Updater:
    """Updates one installation. Tests replace what it reaches outside itself."""

    paths: Paths
    installed: Version
    # The releases API (segl.update.releases).
    update_url: str
    # segl's own version route on this host.
    version_url: str
    database: Path
    http: Http
    run: Runner = run_command
    probe: Callable[[str], bytes] = local_get
    say: Say = print
    now: Callable[[], datetime] = _now
    sleep: Callable[[float], None] = time.sleep
    settle: float = SETTLE_SECONDS

    def check(self, target: Version | None = None) -> int:
        """Say whether a newer release is out. Change nothing.

        Returns:
            100 when a newer release is out, 0 when none is, and 1 when the
            releases could not be asked.
        """
        release = self._fetch(target)
        if release is None:
            return 1
        if release.version > self.installed:
            self._offer(release)
            self.say("To install it: sudo segl update")
            return AVAILABLE
        self._up_to_date(release)
        return 0

    def update(self, target: Version | None, confirm: Confirm, auto: bool = False) -> int:
        """Install the newest release if it is newer, or the one named.

        Args:
            target: A release to install even if it is older or the same, or
                None for the newest.
            confirm: Asks whether to go ahead.
            auto: The timer's update, with its stricter rules.

        Returns:
            0 when updated or up to date, and when the timer leaves out a
            release that failed last time. 1 when declined, refused, or
            failed and taken out again.

        Raises:
            UpdateError: When another update is running, or the update
                folder is not root's alone.
        """
        release = self._fetch(target)
        if release is None:
            return 1
        version = release.version
        if target is None:
            if version <= self.installed:
                self._up_to_date(release)
                return 0
            if auto and self._failed_before() == version:
                self.say(
                    f"{PREFIX}: {version} did not install last time, so it is not tried "
                    f"again until a newer release comes. To try it now: "
                    f"sudo segl update --version {version}"
                )
                return 0
            self._offer(release)
        else:
            self.say(f"segl {self.installed} is installed; {version} was asked for.")
        if not confirm(f"Install segl {version} now?"):
            self.say("Nothing was installed.")
            return 1
        with self._locked():
            try:
                artifacts = self._download(release)
            except ReleaseError as exc:
                self.say(f"{PREFIX}: {exc}")
                return 1
            return self._apply(version, artifacts, auto=auto, fetch_previous=True)

    def install_from(self, folder: Path, confirm: Confirm) -> int:
        """Install a release whose three files someone copied to this host.

        Returns:
            0 when updated. 1 when declined, refused, or failed and taken
            out again. 2 when the folder does not hold one release.

        Raises:
            UpdateError: As ``update``.
        """
        packages = [
            (path.name, named[1])
            for path in sorted(folder.glob("segl_*.deb"))
            if (named := PACKAGE_NAME.fullmatch(path.name))
        ]
        if len(packages) != 1:
            found = ", ".join(name for name, _ in packages) or "none"
            self.say(f"{PREFIX}: {folder} must hold one segl_<version>_amd64.deb (found: {found})")
            return 2
        version = Version.parse(packages[0][1])
        given = Artifacts.in_folder(folder, version.package)
        if not given.complete():
            self.say(f"{PREFIX}: {folder} must also hold {SUMS} and {SIG}")
            return 2
        self.say(f"segl {self.installed} is installed; {version} is in {folder}.")
        if not confirm(f"Install segl {version} now?"):
            self.say("Nothing was installed.")
            return 1
        with self._locked():
            # Checked and installed from root's own copy, which nobody else can swap.
            dest = self._fresh(version)
            for source in (given.package, given.sums, given.sig):
                shutil.copyfile(source, dest / source.name)
            artifacts = Artifacts.in_folder(dest, version.package)
            return self._apply(version, artifacts, auto=False, fetch_previous=False)

    def _fetch(self, target: Version | None) -> Release | None:
        try:
            return fetch_release(self.http, self.update_url, target)
        except ReleaseError as exc:
            self.say(f"{PREFIX}: {exc}")
            return None

    def _offer(self, release: Release) -> None:
        when = f" ({release.date})" if release.date else ""
        self.say(f"segl {self.installed} is installed; {release.version} is available{when}.")
        if release.page:
            self.say(f"  Release notes: {release.page}")

    def _up_to_date(self, release: Release) -> None:
        newer = (
            f", newer than the latest release ({release.version})"
            if self.installed > release.version
            else ""
        )
        self.say(f"segl {self.installed} is installed{newer}: up to date.")

    def _apply(
        self, version: Version, artifacts: Artifacts, *, auto: bool, fetch_previous: bool
    ) -> int:
        """Verify one release, then install and check it, or go back."""
        try:
            verify(artifacts, self.paths.signers, self.run)
        except VerificationError as exc:
            shutil.rmtree(artifacts.package.parent, ignore_errors=True)
            self._record("refused", version, str(exc))
            self.say(f"{PREFIX}: {exc}. Nothing was changed.")
            return 1
        self.say(f"{version.package} matches {SUMS}, and its signature verifies.")
        if self._nginx_here():
            tested = self.run(["nginx", "-t"], None, None)
            if tested.code != 0:
                self.say(
                    f"{PREFIX}: nginx -t fails as things are, so nothing was changed. "
                    f"Put nginx right first: {tail(tested.output)}"
                )
                return 1
        # apt is asked first whether it can install the package at all, such
        # as a package it depends on that this server cannot fetch. Finding
        # that out after segl is stopped would cost the boards their time.
        tried = self.run(["apt-get", "install", "--simulate", str(artifacts.package)], None, None)
        if tried.code != 0:
            self.say(
                f"{PREFIX}: apt cannot install {artifacts.package.name}, so nothing was "
                f"changed: {tail(tried.output)}"
            )
            return 1
        previous = self._previous(fetch_previous)
        if previous is None and auto:
            self.say(
                f"{PREFIX}: an unattended update does not start without a package to go "
                "back to. Nothing was changed. To install it yourself: sudo segl update"
            )
            return 1
        needed = backup.database_bytes(self.database) + ROOM_TO_SPARE
        free = shutil.disk_usage(self.paths.update_dir).free
        if free < needed:
            self.say(
                f"{PREFIX}: {self.paths.update_dir} has {free // 2**20} MiB free, and the "
                f"copy of the database needs {needed // 2**20} MiB. Nothing was changed."
            )
            return 1
        # Loads what the check after the install uses, while the files are there.
        with contextlib.suppress(OSError, ValueError):
            self.probe(self.version_url)
        was_running = self._systemctl("is-active", "--quiet") == 0
        try:
            saved = self._save(was_running)
        except (backup.BackupError, _Failed) as exc:
            if was_running:
                self._systemctl("start")
            self._record("failed", version, str(exc))
            self.say(f"{PREFIX}: {exc}. Nothing was changed.")
            return 1
        started = False
        try:
            self._install(artifacts.package)
            self._settle()
            if was_running:
                # From here the new version may have changed the database.
                started = True
                self._start()
                self._answers(version)
            else:
                self.say(f"{PREFIX}: {SERVICE} was not running, and is left stopped")
        except _Failed as exc:
            self.say(f"{PREFIX}: {version} failed: {exc}")
            self._go_back(previous, saved, was_running, started)
            self._record("failed", version, str(exc))
            return 1
        self._record("updated", version, "")
        self._prune(version)
        backup.prune(self.paths.backups, backup.PRE_UPDATE)
        self.say(f"{PREFIX}: updated {self.installed} -> {version}")
        return 0

    def _save(self, was_running: bool) -> Path:
        """Stop segl, then copy what the update may change."""
        if was_running:
            self.say(f"Stopping {SERVICE}, and saving the settings and the database.")
            if self._systemctl("stop") != 0:
                raise _Failed(f"{SERVICE} did not stop")
        folder = backup.new_backup(self.paths.backups, backup.PRE_UPDATE, self.now())
        backup.save_folder(folder, "etc", self.paths.etc)
        backup.save_folder(folder, "merged", self.paths.merged)
        for _, _, site in self.paths.nginx_pairs():
            backup.save_file(folder, f"nginx/{site.relative_to(self.paths.nginx_dir)}", site)
        backup.save_database(folder, self.database)
        return folder

    def _install(self, package: Path) -> None:
        self.say(f"Installing {package.name}.")
        done = self.run(
            [
                "apt-get",
                "install",
                "-y",
                "--allow-downgrades",
                "-o",
                f"DPkg::Lock::Timeout={APT_LOCK_SECONDS}",
                str(package),
            ],
            None,
            {"DEBIAN_FRONTEND": "noninteractive"},
        )
        if done.code != 0:
            raise _Failed(f"apt-get install failed: {tail(done.output)}")
        # What the package's own scripts said, such as the keys they added.
        for line in done.output.splitlines():
            if line.startswith("segl"):
                self.say(f"  {line}")

    def _settle(self) -> None:
        """The new version's files must be merged, and must check out."""
        binary, config = str(self.paths.binary), str(self.paths.config_file)
        merged = self.run([binary, "config", "merge", "--write", "--config", config], None, None)
        if merged.code != 0:
            raise _Failed(f"segl config merge failed: {tail(merged.output)}")
        checked = self.run([binary, "check", "--config", config], None, None)
        if checked.code != 0:
            raise _Failed(f"segl check failed: {tail(checked.output)}")
        if self._nginx_here():
            tested = self.run(["nginx", "-t"], None, None)
            if tested.code != 0:
                raise _Failed(f"nginx -t failed: {tail(tested.output)}")

    def _start(self) -> None:
        # Starts that failed count against the unit's limit, which would refuse this one.
        self._systemctl("reset-failed")
        if self._systemctl("start") != 0:
            raise _Failed(f"{SERVICE} did not start; see `journalctl -u segl`")

    def _answers(self, version: Version) -> None:
        """The started service must say it is this version."""
        last = "no answer"
        for _ in range(int(self.settle // 2) + 1):
            try:
                answered = json.loads(self.probe(self.version_url))["version"]
                if answered == str(version):
                    return
                last = f"it answers as {answered}"
            except (OSError, ValueError, KeyError, TypeError) as exc:
                last = str(exc)
            if self._systemctl("is-failed", "--quiet") == 0:
                # systemd gave up on it: a setting it cannot use, or the
                # start limit. Waiting longer changes nothing.
                raise _Failed(f"{SERVICE} failed to start; see `journalctl -u segl` ({last})")
            self.sleep(2)
        raise _Failed(f"{SERVICE} did not answer as {version} within {self.settle:g} s ({last})")

    def _go_back(
        self, previous: Artifacts | None, saved: Path, was_running: bool, started: bool
    ) -> None:
        self.say(f"{PREFIX}: going back to {self.installed}")
        if started:
            self._systemctl("stop")
        if previous is None:
            self.say(
                f"{PREFIX}: no package of {self.installed} is at hand, so the new one "
                "stays installed. The settings and the nginx files go back."
            )
        else:
            try:
                self._install(previous.package)
            except _Failed as exc:
                self.say(f"{PREFIX}: reinstalling {self.installed}: {exc}")
        nginx_changed = False
        try:
            backup.restore_folder(saved, "etc", self.paths.etc)
            backup.restore_folder(saved, "merged", self.paths.merged, exact=True)
            for _, _, site in self.paths.nginx_pairs():
                name = f"nginx/{site.relative_to(self.paths.nginx_dir)}"
                nginx_changed = backup.restore_file(saved, name, site) or nginx_changed
            if started and backup.restore_database(saved, self.database):
                self.say(f"{PREFIX}: the database is as it was before the update")
        except backup.BackupError as exc:
            self.say(f"{PREFIX}: {exc}")
        if nginx_changed and self._nginx_here():
            tested = self.run(["nginx", "-t"], None, None)
            if tested.code != 0:
                self.say(f"{PREFIX}: after going back, nginx -t fails: {tail(tested.output)}")
            elif self._nginx_active():
                self.run(["systemctl", "reload", NGINX_SERVICE], None, None)
        if not was_running:
            return
        try:
            self._start()
            self._answers(self.installed)
            self.say(f"{PREFIX}: {self.installed} answers again")
        except _Failed as exc:
            self.say(f"{PREFIX}: after going back, {exc}")

    def _previous(self, fetch: bool) -> Artifacts | None:
        """Return a verified package of the installed version, to go back to."""
        folder = self.paths.cache / str(self.installed)
        artifacts = Artifacts.in_folder(folder, self.installed.package)
        if not artifacts.complete() and fetch:
            with contextlib.suppress(ReleaseError):
                release = fetch_release(self.http, self.update_url, self.installed)
                artifacts = self._download(release)
        try:
            verify(artifacts, self.paths.signers, self.run)
        except VerificationError:
            self.say(
                f"{PREFIX}: no verified package of {self.installed} is at hand. If the "
                "new version fails, only the settings, the nginx files, and the database "
                "go back."
            )
            return None
        return artifacts

    def _download(self, release: Release) -> Artifacts:
        version = release.version
        urls = [(name, release.url(name)) for name in (version.package, SUMS, SIG)]
        dest = self._fresh(version)
        self.say(f"Downloading {version.package} to {dest}.")
        for name, url in urls:
            self.http.download(url, dest / name)
        return Artifacts.in_folder(dest, version.package)

    def _fresh(self, version: Version) -> Path:
        dest = self.paths.cache / str(version)
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(mode=0o700, parents=True)
        return dest

    def _prune(self, current: Version) -> None:
        """Keep the new version's package and the one it replaced."""
        keep = {str(current), str(self.installed)}
        for path in self.paths.cache.iterdir():
            if path.name not in keep:
                shutil.rmtree(path, ignore_errors=True)

    def _nginx_here(self) -> bool:
        return self.run(["nginx", "-v"], None, None).code == 0

    def _nginx_active(self) -> bool:
        asked = ["systemctl", "is-active", "--quiet", NGINX_SERVICE]
        return self.run(asked, None, None).code == 0

    def _systemctl(self, *args: str) -> int:
        return self.run(["systemctl", *args, SERVICE], None, None).code

    def _failed_before(self) -> Version | None:
        """Return the release the last update failed to install, if it failed."""
        try:
            record = json.loads(self.paths.record.read_text(encoding="utf-8"))
            if record.get("result") == "failed":
                return Version.parse(record["to"])
        except OSError, ValueError, KeyError, TypeError, AttributeError:
            pass
        return None

    def _record(self, result: str, version: Version, message: str) -> None:
        record = {
            "result": result,
            "from": str(self.installed),
            "to": str(version),
            "at": self.now().isoformat(),
            "message": message,
        }
        backup.replace_file(self.paths.record, (json.dumps(record, indent=1) + "\n").encode())

    @contextlib.contextmanager
    def _locked(self) -> Generator[None]:
        """Check that the update folder is root's alone, and hold its lock."""
        home = self.paths.update_dir
        try:
            info = home.lstat()
        except FileNotFoundError as exc:
            raise UpdateError(f"{home} is missing; install the package again") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise UpdateError(f"{home} is not a folder")
        if os.geteuid() == 0 and (info.st_uid != 0 or info.st_mode & 0o022):
            raise UpdateError(f"{home} must be root's, and only root may write in it")
        try:
            for sub in (self.paths.cache, self.paths.backups):
                sub.mkdir(mode=0o700, exist_ok=True)
            descriptor = os.open(self.paths.lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise UpdateError(f"{home} is not as the package made it: {exc}") from exc
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise UpdateError("another segl update is running") from exc
            yield
        finally:
            os.close(descriptor)
