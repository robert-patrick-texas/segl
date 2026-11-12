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

"""Every pinned component beside its newest stable release, and the gate.

The components are Python, Node, the direct Python and web dependencies in
versions.toml, and the GitHub Actions the workflows pin (docs/RELEASING.md).
"""

from __future__ import annotations

import json
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from release_proc import CommandError, Runner
from release_versions import is_newer, newest_stable, parse_version, within_pin

PYTHON_TABLES = ("dependencies", "dev", "build", "docs")
WEB_TABLES = ("dependencies", "dev")
WORKFLOWS = ".github/workflows"

CURRENT = "current"
NEWER = "newer"
HELD = "held"
STALE = "stale hold"
UNKNOWN = "unknown"

_USES = re.compile(
    r"""^\s*(?:-\s*)?uses:\s*["']?(?P<target>[^\s"'#]+)["']?\s*(?:\#\s*(?P<note>.*?))?\s*$"""
)
_NOTE_VERSION = re.compile(r"(?<![\w.])(v?\d+(?:\.\d+)*)")
_SHA = re.compile(r"^[0-9a-f]{40}$")
# A stable CPython build in `uv python list` output. Pre-releases (3.16.0a1)
# and build variants (3.15.2+freethreaded) do not match.
_STABLE_CPYTHON = re.compile(r"\bcpython-(\d+\.\d+\.\d+)-")


class LookupFailed(Exception):
    """The newest release of a component could not be found."""


@dataclass(frozen=True)
class Component:
    """One pinned component.

    ``kind`` is ``runtime`` (Python or Node), ``python`` or ``web`` (a direct
    dependency), or ``action``. ``name`` is also the ``[held.<name>]`` key.
    ``table`` is the versions.toml table of a dependency. ``ref`` is the text
    after ``@`` in a workflow, and ``version`` is then the tag, or the version
    in the comment after a commit pin.
    """

    kind: str
    name: str
    version: str
    table: str = ""
    ref: str = ""

    @property
    def label(self) -> str:
        """Return the component as `check` prints it."""
        kind = "python" if self.name == "python" else self.kind
        name = "cpython" if self.name == "python" else self.name
        return f"{kind} {name} {self.version or self.ref}"


@dataclass(frozen=True)
class Status:
    """A component compared with its newest stable release."""

    component: Component
    state: str
    latest: str = ""
    detail: str = ""

    @property
    def blocks(self) -> bool:
        """Report whether this component fails the gate."""
        return self.state in (NEWER, STALE, UNKNOWN)

    @property
    def line(self) -> str:
        """Return the line `check` prints."""
        return f"{self.component.label}: {self.detail or self.state}"


def fetch_json(url: str) -> Any:
    """Return the JSON document at ``url``."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


class Sources:
    """Looks up the newest stable release of a component.

    PyPI, the npm registry, and nodejs.org are read over HTTPS. CPython comes
    from ``uv python list``, and GitHub Actions from ``gh api``.
    """

    def __init__(self, runner: Runner, fetch: Callable[[str], Any] = fetch_json) -> None:
        self.runner = runner
        self.fetch = fetch

    def latest(self, component: Component) -> str:
        """Return the newest stable release of ``component``.

        Raises:
            LookupFailed: When the source did not answer or named no stable release.
        """
        try:
            if component.kind == "runtime":
                found = self._python() if component.name == "python" else self._node()
            elif component.kind == "python":
                found = self._pypi(component.name)
            elif component.kind == "web":
                found = self._npm(component.name)
            else:
                found = self._github(component.name)
        except (urllib.error.URLError, TimeoutError, CommandError, ValueError) as exc:
            raise LookupFailed(str(exc)) from exc
        except (KeyError, TypeError, AttributeError) as exc:
            raise LookupFailed(f"unexpected answer ({exc!r})") from exc
        if not found:
            raise LookupFailed("no stable release found")
        return found

    def action_commit(self, repo: str, tag: str) -> str:
        """Return the commit a release tag of a GitHub Action points at.

        Raises:
            LookupFailed: When ``gh`` could not resolve the tag.
        """
        try:
            payload = json.loads(
                self.runner.run(["gh", "api", f"repos/{repo}/commits/{tag}"]).stdout
            )
            sha = str(payload["sha"])
        except (CommandError, ValueError, KeyError, TypeError) as exc:
            raise LookupFailed(f"cannot resolve {repo}@{tag}: {exc}") from exc
        if not _SHA.match(sha):
            raise LookupFailed(f"cannot resolve {repo}@{tag}: {sha!r} is not a commit")
        return sha

    def _python(self) -> str | None:
        listing = self.runner.run(["uv", "python", "list", "--all-versions"]).stdout
        return newest_stable(_STABLE_CPYTHON.findall(listing))

    def _node(self) -> str | None:
        releases = self.fetch("https://nodejs.org/dist/index.json")
        return newest_stable(str(r["version"]).removeprefix("v") for r in releases if r.get("lts"))

    def _pypi(self, name: str) -> str | None:
        payload = self.fetch(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
        # A release with no files, or with every file yanked, is not installable.
        return newest_stable(
            version
            for version, files in payload["releases"].items()
            if any(not file.get("yanked") for file in files)
        )

    def _npm(self, name: str) -> str | None:
        quoted = urllib.parse.quote(name, safe="@")
        version = str(self.fetch(f"https://registry.npmjs.org/{quoted}/latest")["version"])
        return newest_stable([version])

    def _github(self, repo: str) -> str | None:
        out = self.runner.run(["gh", "api", f"repos/{repo}/releases/latest"]).stdout
        return newest_stable([str(json.loads(out)["tag_name"])])


def load_versions(root: Path) -> dict[str, Any]:
    """Return the parsed versions.toml of the repository at ``root``."""
    return tomllib.loads((root / "versions.toml").read_text(encoding="utf-8"))


def direct_rows(doc: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Return (ecosystem, table, name, version) for pinned direct dependencies."""
    rows: list[tuple[str, str, str, str]] = []
    for ecosystem, tables in (("python", PYTHON_TABLES), ("web", WEB_TABLES)):
        block = doc.get(ecosystem, {})
        for table in tables:
            entries = block.get(table, {}) if isinstance(block, dict) else {}
            if not isinstance(entries, dict):
                continue
            for name, version in entries.items():
                if isinstance(version, str) and version:
                    rows.append((ecosystem, table, name, version))
    return rows


def workflow_files(root: Path) -> list[Path]:
    """Return the workflow files, in name order."""
    folder = root / WORKFLOWS
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix in (".yml", ".yaml") and p.is_file())


def action_components(root: Path) -> list[Component]:
    """Return one component for each distinct Actions pin in the workflows."""
    found: list[Component] = []
    for path in workflow_files(root):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _USES.match(line)
            if match is None:
                continue
            target = match["target"]
            if target.startswith(("./", "docker://")) or "@" not in target:
                continue
            spec, ref = target.rsplit("@", 1)
            repo = "/".join(spec.split("/")[:2])
            if _SHA.match(ref):
                noted = _NOTE_VERSION.search(match["note"] or "")
                version = noted[1] if noted else ""
            else:
                version = ref
            component = Component("action", repo, version, ref=ref)
            if component not in found:
                found.append(component)
    return found


def discover(root: Path) -> list[Component]:
    """Return every pinned component of the repository at ``root``."""
    doc = load_versions(root)
    runtime = doc.get("runtime", {})
    found = [Component("runtime", "python", str(runtime.get("python", "")))]
    if runtime.get("node"):
        found.append(Component("runtime", "node", str(runtime["node"])))
    found.extend(
        Component(ecosystem, name, version, table=table)
        for ecosystem, table, name, version in direct_rows(doc)
    )
    found.extend(action_components(root))
    return found


def assess(component: Component, sources: Sources, holds: dict[str, Any]) -> Status:
    """Compare one component with its newest stable release and its hold."""
    pin = component.version
    if component.kind == "action" and parse_version(pin) is None:
        if _SHA.match(component.ref):
            detail = "pinned to a commit without a '# vX.Y.Z' comment"
        else:
            detail = f"ref {component.ref!r} is a branch, not a release"
        return Status(component, UNKNOWN, detail=detail)
    if parse_version(pin) is None:
        return Status(component, UNKNOWN, detail=f"{pin!r} is not an exact version")
    try:
        latest = sources.latest(component)
    except LookupFailed as exc:
        return Status(component, UNKNOWN, detail=f"lookup failed ({exc})")
    hold = holds.get(component.name)
    reduced = component.kind == "action" and not _SHA.match(component.ref)
    if within_pin(pin, latest) if reduced else not is_newer(latest, pin):
        detail = "current, and its hold can go" if hold else ""
        return Status(component, CURRENT, latest, detail)
    if isinstance(hold, dict):
        skipped = str(hold.get("skipped", ""))
        if is_newer(latest, skipped):
            detail = f"newer {latest}, and the hold only covers {skipped}"
            return Status(component, STALE, latest, detail)
        reason = str(hold.get("reason", "no reason recorded"))
        return Status(component, HELD, latest, f"held, {latest} skipped ({reason})")
    return Status(component, NEWER, latest, f"newer {latest}")


def report(root: Path, sources: Sources) -> list[Status]:
    """Return the status of every component."""
    holds = load_versions(root).get("held", {})
    return [assess(component, sources, holds) for component in discover(root)]


def gate_passes(statuses: list[Status]) -> bool:
    """Report whether every component is current or held."""
    return not any(status.blocks for status in statuses)
