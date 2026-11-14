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

"""`cut` and `publish`: the version bump and changelog section, then the tag and release.

`cut` changes files only after the gate and the suite pass. `publish` runs a
preflight in the order docs/RELEASING.md gives and stops at the first failure.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

import release_edits as edits
import release_notes as notes
import release_sign as signing
from release_components import Sources, gate_passes, load_versions, report
from release_proc import CommandError, Runner
from release_progress import PACKAGE_STAGES, Progress, say
from release_upgrade import run_suite

UNPUBLISHED = "0.0.0"
BRANCH = "main"
REMOTE = "origin"
PASSING = frozenset({"success", "neutral", "skipped"})
# Builds the .deb into dist/ and installs it in a container that booted with
# systemd (docs/TEST-PLAN.md T-017).
PACKAGE_TEST = "deploy/debian/package-test.sh"


def has_package(root: Path) -> bool:
    """Report whether the tree at ``root`` can build the Debian package."""
    return (root / PACKAGE_TEST).is_file()


def package_path(root: Path, version: str) -> Path:
    """Return where the package build writes the .deb of ``version``."""
    return root / "dist" / f"segl_{version}_amd64.deb"


def bump_version(current: str, topics: dict[str, list[str]]) -> str:
    """Return the next version: a minor step for New or Changed, else a patch step."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current)
    if match is None:
        raise SystemExit(f"project.version {current!r} is not MAJOR.MINOR.PATCH")
    major, minor, patch = (int(part) for part in match.groups())
    if current == UNPUBLISHED or topics["New"] or topics["Changed"]:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def gate(root: Path, sources: Sources) -> bool:
    """Print every component that fails the gate. Return whether it passes."""
    statuses = report(root, sources)
    for status in statuses:
        if status.blocks:
            print(f"  {status.line}")
    return gate_passes(statuses)


def cut(root: Path, runner: Runner, sources: Sources, today: dt.date | None = None) -> int:
    """Write the next version and its changelog section. Return the exit status."""
    changelog_path, versions_path = root / "CHANGELOG.md", root / "versions.toml"
    changelog = changelog_path.read_text(encoding="utf-8")
    summary, topics = notes.parse_section(changelog)
    sentences = notes.summary_sentence_count(summary)
    if sentences < 1 or sentences > 3:
        print("not cut: Unreleased needs a summary of one to three sentences")
        return 1
    if not any(topics.values()):
        print("not cut: Unreleased has no New, Changed, Fixed, or Additional Notes bullets")
        return 1
    say("checking that every component is current")
    if not gate(root, sources):
        print("not cut: `check --gate` fails. Run `upgrade`, then try again.")
        return 1
    say("running the suite")
    failure = run_suite(runner, root)
    if failure is not None:
        print(f"not cut: the suite fails ({failure})")
        return 1
    current = str(load_versions(root)["project"]["version"])
    new = bump_version(current, topics)
    date = (today or dt.date.today()).isoformat()
    versions_path.write_text(
        edits.set_entry(versions_path.read_text(encoding="utf-8"), "project", "version", new),
        encoding="utf-8",
    )
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        edits.replace_once(
            pyproject.read_text(encoding="utf-8"),
            rf'^version = "{re.escape(current)}"',
            f'version = "{new}"',
            "pyproject.toml project version",
        ),
        encoding="utf-8",
    )
    changelog_path.write_text(
        edits.replace_once(
            changelog,
            r"^## Unreleased[ \t]*$",
            f"## Unreleased\n\n## {new} — {date}",
            "## Unreleased",
        ),
        encoding="utf-8",
    )
    # uv.lock records the project's own version.
    runner.run(["uv", "lock"])
    print(f"cut {new}. Commit and push, wait for CI, then run `release.py publish`.")
    return 0


def check_runs_pass(payload: dict) -> tuple[bool, str]:
    """Decide whether the GitHub check runs of a commit allow a release."""
    runs = payload.get("check_runs") or []
    if not runs:
        return False, "no check runs for this commit (is it pushed?)"
    pending = sorted(str(r.get("name")) for r in runs if r.get("status") != "completed")
    failed = sorted(
        str(r.get("name"))
        for r in runs
        if r.get("status") == "completed" and r.get("conclusion") not in PASSING
    )
    if pending or failed:
        parts = [f"pending: {', '.join(pending)}"] if pending else []
        parts += [f"failed: {', '.join(failed)}"] if failed else []
        return False, "; ".join(parts)
    return True, f"{len(runs)} check run(s) passed"


class Preflight:
    """The checks `publish` makes before it tags, in order."""

    def __init__(self, root: Path, runner: Runner, sources: Sources) -> None:
        self.root, self.runner, self.sources = root, runner, sources
        doc = load_versions(root)
        self.version = str(doc["project"]["version"])
        self.repo = str(doc.get("publish", {}).get("github_repo", ""))
        self.tag = f"v{self.version}"

    def steps(self) -> list[tuple[str, Callable[[], tuple[bool, str]]]]:
        """Return each check with its name, in the order they run."""
        steps = [
            ("the working tree is clean", self.clean_tree),
            (f"HEAD is on {BRANCH}", self.on_branch),
            (f"CHANGELOG.md has a {self.version} section", self.changelog_section),
            (f"the version is not {UNPUBLISHED}", self.publishable),
            (f"tag {self.tag} is new", self.tag_absent),
            ("GitHub checks passed for HEAD", self.ci_green),
            ("every component is current or held", self.currency),
        ]
        if has_package(self.root):
            # A server installs only a release signed with a key its package
            # lists. Without both halves of the key there is nothing to publish.
            steps.append((f"{signing.SIGNERS} lists a key", self.signers))
            steps.append(("the release key is there", self.release_key))
            # Last: it takes minutes, and it builds what the release carries.
            steps.append(("the package builds and installs", self.package))
        return steps

    def clean_tree(self) -> tuple[bool, str]:
        changed = len(self.runner.run(["git", "status", "--porcelain"]).stdout.splitlines())
        return changed == 0, f"{changed} changed or untracked path(s)"

    def on_branch(self) -> tuple[bool, str]:
        current = self.runner.run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        return current == BRANCH, f"HEAD is on {current}"

    def changelog_section(self) -> tuple[bool, str]:
        changelog = (self.root / "CHANGELOG.md").read_text(encoding="utf-8")
        body = notes.section_body(changelog, notes.version_heading(self.version))
        if body is None or not body.strip():
            return False, "run `release.py cut` first"
        return True, "found"

    def publishable(self) -> tuple[bool, str]:
        return self.version != UNPUBLISHED, f"project.version is {self.version}"

    def tag_absent(self) -> tuple[bool, str]:
        ref = f"refs/tags/{self.tag}"
        local = self.runner.run(["git", "rev-parse", "-q", "--verify", ref], check=False)
        if local.returncode == 0:
            return False, "the tag already exists locally"
        if self.runner.run(["git", "ls-remote", "--tags", REMOTE, ref]).stdout.strip():
            return False, f"the tag already exists on {REMOTE}"
        return True, f"absent locally and on {REMOTE}"

    def ci_green(self) -> tuple[bool, str]:
        sha = self.runner.run(["git", "rev-parse", "HEAD"]).stdout.strip()
        endpoint = f"repos/{self.repo}/commits/{sha}/check-runs?per_page=100"
        try:
            payload = json.loads(self.runner.run(["gh", "api", endpoint]).stdout)
        except json.JSONDecodeError as exc:
            return False, f"cannot read the check runs: {exc}"
        return check_runs_pass(payload)

    def currency(self) -> tuple[bool, str]:
        return gate(self.root, self.sources), "see `release.py check`"

    def signers(self) -> tuple[bool, str]:
        count = signing.signer_entries(self.root / signing.SIGNERS)
        if count == 0:
            return False, "add the release key's public half (docs/RELEASING.md, the release key)"
        return True, f"{count} key(s)"

    def release_key(self) -> tuple[bool, str]:
        key = signing.key_path()
        if not key.is_file():
            return False, f"no key at {key} (set {signing.KEY_VARIABLE} to another path)"
        return True, str(key)

    def package(self) -> tuple[bool, str]:
        # Minutes of work: say each of its steps, and not only its end.
        say(f"     the package builds and installs: running `{PACKAGE_TEST}`")
        result = self.runner.run([PACKAGE_TEST], check=False, progress=Progress(PACKAGE_STAGES))
        built = package_path(self.root, self.version)
        if result.returncode != 0:
            tail = "\n".join(result.output.strip().splitlines()[-15:])
            print(f"  `{PACKAGE_TEST}` failed:\n{tail}")
            return False, f"`{PACKAGE_TEST}` failed"
        if not built.is_file():
            return False, f"dist/{built.name} was not built"
        return True, f"dist/{built.name} passed the install test"

    def run(self) -> bool:
        """Run the checks and stop at the first failure."""
        for name, step in self.steps():
            try:
                ok, detail = step()
            except CommandError as exc:
                ok, detail = False, str(exc)
            print(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")
            if not ok:
                return False
        return True


def publish(root: Path, runner: Runner, sources: Sources) -> int:
    """Tag the release and create the GitHub Release. Return the exit status."""
    preflight = Preflight(root, runner, sources)
    if not preflight.run():
        print("not published")
        return 1
    doc = load_versions(root)
    destinations = doc.get("publish", {})
    version, tag = preflight.version, preflight.tag
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    summary, topics = notes.parse_section(changelog, notes.version_heading(version))
    body = notes.render_notes(root, doc, summary, topics, notes.count_lines(runner))
    # The package the preflight just built and installed, and no other file
    # that happens to be in dist/. Then its checksum, and the signature over
    # that, which is checked here as a server will check it. All of this
    # comes before the tag, so a failure leaves nothing published.
    packages: list[str] = []
    if has_package(root):
        package = package_path(root, version)
        sums = signing.write_sums([package], package.parent)
        try:
            signature = signing.sign(runner, signing.key_path(), sums)
        except CommandError as exc:
            print(f"not published: signing {sums.name} failed ({exc})")
            return 1
        good, said = signing.verify(runner, root / signing.SIGNERS, sums)
        if not good:
            print(f"not published: {signing.SIGNERS} does not vouch for the signature: {said}")
            return 1
        print(f"ok   {sums.name} is signed: {said}")
        packages = [str(package), str(sums), str(signature)]
    runner.run(["git", "tag", "-a", tag, "-m", f"segl {version}"])
    runner.run(["git", "push", REMOTE, tag])
    if destinations.get("github"):
        with tempfile.TemporaryDirectory() as folder:
            notes_file = Path(folder) / "notes.md"
            notes_file.write_text(body, encoding="utf-8")
            create = ["gh", "release", "create", tag, "--verify-tag", "--repo", preflight.repo]
            create += ["--title", f"segl {version}", "--notes-file", str(notes_file)]
            runner.run(create + packages)
        print(f"published {tag} to {preflight.repo}")
    if destinations.get("pypi"):
        with tempfile.TemporaryDirectory() as folder:
            runner.run(["uv", "build", "--out-dir", folder])
            built = sorted(str(path) for path in Path(folder).iterdir())
            runner.run(["uv", "publish", *built])
        print(f"published {version} to PyPI")
    return 0
