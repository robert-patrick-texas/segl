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

"""``segl config merge``: bring a site's settings and nginx files up to this version.

The package never overwrites what a site edits. This command puts a new
version's statements into those files and keeps the rest:

- ``segl.toml`` gets the keys this version added, each with its note
  (``settings_merge``).
- Each of the three nginx files a site installs from ``/opt/segl/share/nginx``
  gets what this version changed in it, by a three-way merge with ``diff3``:
  the site's file, the package's file as it was last merged, and the
  package's file now. A change the site already made the same way is kept
  once. Then ``nginx -t`` must pass, and nginx is reloaded.

If the site and this version changed the same lines of an nginx file, or
``nginx -t`` fails, every nginx file stays as it was, and the command exits
with status 1. A copy of each file it changes is kept under
``/opt/segl/update/backups``.

The package's ``postinst`` runs it on every install and upgrade, and
``segl update`` runs it again to learn how it went. It changes nothing a
second time.
"""

import difflib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from segl.update import backup
from segl.update.paths import NGINX_SERVICE, Paths
from segl.update.process import Runner, tail
from segl.update.settings_merge import Merged, SettingsMergeError, merge_settings

Say = Callable[[str], None]
PREFIX = "segl config merge"


@dataclass(frozen=True)
class _NginxFile:
    """One nginx file, and what the merge makes of it."""

    name: str
    site: Path
    shipped: bytes
    # "same": nothing to do. "absent": the site has no such file.
    # "unknown": the site's file differs and there is no record to merge from.
    # "replace" and "merge": ``text`` goes in its place. "conflict": it cannot.
    action: str
    text: bytes = b""
    detail: str = ""


def _now() -> datetime:
    return datetime.now(UTC)


def _three_way(name: str, site: Path, base: Path, shipped: Path, run: Runner) -> tuple[str, bytes]:
    """Merge with diff3. Return the action, and the merged text or the reason."""
    try:
        site.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return "conflict", b"it is not UTF-8 text"
    # -E brackets only a true overlap. A change the site and this version
    # both made, the same way, is no conflict: the site did it first.
    done = run(["diff3", "-m", "-E", str(site), str(base), str(shipped)], None, None)
    if done.code == 0:
        return "merge", done.output.encode("utf-8")
    if done.code == 1:
        return "conflict", f"the site and this version changed the same lines of {name}".encode()
    return "conflict", f"diff3 failed: {tail(done.output)}".encode()


def plan_nginx(paths: Paths, run: Runner) -> list[_NginxFile]:
    """Work out what each nginx file needs. Change nothing."""
    plan = []
    for name, shipped_path, site in paths.nginx_pairs():
        if not shipped_path.is_file():
            continue
        shipped = shipped_path.read_bytes()
        base_path = paths.merged / name
        base = base_path.read_bytes() if base_path.is_file() else None
        if not site.is_file():
            plan.append(_NginxFile(name, site, shipped, "absent"))
        elif site.read_bytes() == shipped or base == shipped:
            # The site has this version's file, or this version did not change it.
            plan.append(_NginxFile(name, site, shipped, "same"))
        elif base is None:
            plan.append(_NginxFile(name, site, shipped, "unknown"))
        elif site.read_bytes() == base:
            plan.append(_NginxFile(name, site, shipped, "replace", shipped))
        else:
            action, result = _three_way(name, site, base_path, shipped_path, run)
            if action == "merge" and result == site.read_bytes():
                # The site's file already has everything this version changed.
                plan.append(_NginxFile(name, site, shipped, "same"))
            elif action == "merge":
                plan.append(_NginxFile(name, site, shipped, action, result))
            else:
                plan.append(_NginxFile(name, site, shipped, action, detail=result.decode()))
    return plan


def _diff(old: bytes, new: bytes, path: Path) -> list[str]:
    before = old.decode("utf-8", "replace").splitlines()
    after = new.decode("utf-8", "replace").splitlines()
    return list(difflib.unified_diff(before, after, str(path), "merged", lineterm="", n=2))


@dataclass
class Merge:
    """One run of ``segl config merge``."""

    paths: Paths
    run: Runner
    say: Say = print
    now: Callable[[], datetime] = _now

    def __post_init__(self) -> None:
        self._backup: Path | None = None

    def apply(self, write: bool) -> int:
        """Merge the settings and the nginx files, or say what a merge would do.

        Returns:
            0 when everything is merged, or would be. 1 when something
            cannot be: the settings file is not TOML, an nginx file
            conflicts, or ``nginx -t`` fails.
        """
        settings_ok = self._settings(write)
        nginx_ok = self._nginx(write)
        if write and self._backup is not None:
            backup.prune(self.paths.backups, backup.MERGE)
        return 0 if settings_ok and nginx_ok else 1

    def _keep(self, name: str, source: Path) -> None:
        """Copy a file that is about to change into this run's backup."""
        if self._backup is None:
            self._backup = backup.new_backup(self.paths.backups, backup.MERGE, self.now())
        backup.save_file(self._backup, name, source)

    def _settings(self, write: bool) -> bool:
        target, example = self.paths.config_file, self.paths.example
        if not target.is_file() or not example.is_file():
            return True
        try:
            merged: Merged = merge_settings(
                target.read_text(encoding="utf-8"), example.read_text(encoding="utf-8")
            )
        except (SettingsMergeError, UnicodeDecodeError) as exc:
            self.say(f"{PREFIX}: {target}: {exc}")
            return False
        if not merged.added:
            return True
        keys = ", ".join(merged.added)
        if not write:
            self.say(f"{PREFIX}: would add {keys} to {target}:")
            for line in merged.lines:
                self.say(f"  + {line}")
            return True
        try:
            self._keep(f"etc/{target.name}", target)
            backup.replace_file(target, merged.text.encode("utf-8"))
        except (backup.BackupError, OSError) as exc:
            self.say(f"{PREFIX}: {target}: {exc}")
            return False
        self.say(f"{PREFIX}: added {keys} to {target}")
        return True

    def _nginx(self, write: bool) -> bool:
        plan = plan_nginx(self.paths, self.run)
        conflicts = [item for item in plan if item.action == "conflict"]
        changes = [item for item in plan if item.action in ("replace", "merge")]
        for item in conflicts:
            self.say(
                f"{PREFIX}: {item.site}: {item.detail}. It is left as it is. Compare it "
                f"with {self.paths.share / 'nginx' / item.name} and merge it by hand."
            )
        if conflicts:
            # All of them or none: the three files work together.
            for item in changes:
                self.say(f"{PREFIX}: {item.site} is left as it is too")
            return False
        if changes and self.run(["nginx", "-v"], None, None).code != 0:
            for item in changes:
                self.say(f"{PREFIX}: nginx is not installed here: {item.site} is left as it is")
            return True
        if not write:
            for item in changes:
                self.say(f"{PREFIX}: would merge this version's {item.name} into {item.site}:")
                for line in _diff(item.site.read_bytes(), item.text, item.site):
                    self.say(f"  {line}")
            return True
        if changes and not self._write_nginx(changes):
            return False
        self._remember(plan)
        return True

    def _write_nginx(self, changes: list[_NginxFile]) -> bool:
        """Put the merged files in place, test them, and reload nginx."""
        before = {item.site: item.site.read_bytes() for item in changes}
        try:
            for item in changes:
                self._keep(f"nginx/{item.site.relative_to(self.paths.nginx_dir)}", item.site)
            for item in changes:
                backup.replace_file(item.site, item.text)
        except (backup.BackupError, OSError) as exc:
            self._put_back(before)
            self.say(f"{PREFIX}: {exc}")
            return False
        tested = self.run(["nginx", "-t"], None, None)
        if tested.code != 0:
            self._put_back(before)
            self.say(
                f"{PREFIX}: nginx -t failed with the merged files, so they are as they "
                f"were: {tail(tested.output)}"
            )
            return False
        for item in changes:
            self.say(f"{PREFIX}: merged this version's {item.name} into {item.site}")
        if self.run(["systemctl", "is-active", "--quiet", NGINX_SERVICE], None, None).code != 0:
            self.say(f"{PREFIX}: nginx is not running, so it was not reloaded")
            return True
        reloaded = self.run(["systemctl", "reload", NGINX_SERVICE], None, None)
        if reloaded.code != 0:
            self.say(f"{PREFIX}: nginx did not reload: {tail(reloaded.output)}")
            return False
        self.say(f"{PREFIX}: nginx -t passed, and nginx was reloaded")
        return True

    def _put_back(self, before: dict[Path, bytes]) -> None:
        for site, data in before.items():
            if site.read_bytes() != data:
                backup.replace_file(site, data)

    def _remember(self, plan: list[_NginxFile]) -> None:
        """Record the package's files as the ones the site's now build on."""
        self.paths.merged.mkdir(mode=0o700, parents=True, exist_ok=True)
        for item in plan:
            record = self.paths.merged / item.name
            if item.action == "unknown":
                self.say(
                    f"{PREFIX}: {item.site} differs from this version's {item.name}, and "
                    "there is no record of the version it came from. It is left as it "
                    "is, and later versions are merged into it from here on."
                )
            if not record.is_file() or record.read_bytes() != item.shipped:
                backup.replace_file(record, item.shipped)
