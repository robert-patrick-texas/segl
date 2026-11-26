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

`cut` changes files only after the gate and the suite pass, and keeps them
only when the checks of the version change pass too. It runs the suite only
for what changed since a tree known to be good (scripts/suite.py). `publish`
runs a preflight in the order docs/RELEASING.md gives and stops at the first
failure.
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
from release_log import logged
from release_proc import CommandError, Runner
from release_progress import PACKAGE_STAGES, UPDATE_STAGES, Progress, say
from suite import run_changed, work_tree

UNPUBLISHED = "0.0.0"
BRANCH = "main"
REMOTE = "origin"
PASSING = frozenset({"success", "neutral", "skipped"})
# Installs a .deb in a container that booted with systemd (docs/TEST-PLAN.md
# T-017). publish gives it the one in dist/. Given none, it builds one in a
# folder of its own, and dist/ does not get it.
PACKAGE_TEST = "deploy/debian/package-test.sh"
# Builds the .deb into dist/ alone.
BUILD = "deploy/debian/build-deb.sh"
# The package CI's `package` job keeps from each run, for seven days, after it
# installed and tested it (.github/workflows/ci.yml).
CI_PACKAGE = "segl-deb"
# Installs an earlier GitHub release in a container, and updates it to this
# version with its own `segl update`: from the signed files given, or from
# GitHub. CI cannot run it: only the release key signs what a release takes.
REAL_UPDATE = "deploy/debian/real-update-test.sh"


def has_package(root: Path) -> bool:
    """Report whether the tree at ``root`` can build the Debian package."""
    return (root / PACKAGE_TEST).is_file()


def has_real_update(root: Path) -> bool:
    """Report whether the tree can check the update from an earlier release."""
    return (root / REAL_UPDATE).is_file()


def previous_release(runner: Runner, repo: str, tag: str) -> str | None:
    """Return the newest published release on GitHub other than ``tag``, or None.

    Raises:
        CommandError: When GitHub cannot be asked, or its answer cannot be read.
    """
    published = ["--exclude-drafts", "--exclude-pre-releases", "--limit", "50"]
    listed = runner.run(
        ["gh", "release", "list", "--repo", repo, *published, "--json", "tagName,publishedAt"]
    )
    try:
        releases = json.loads(listed.stdout)
        found = [(str(r["publishedAt"]), str(r["tagName"])) for r in releases]
    except (ValueError, LookupError, TypeError) as exc:
        raise CommandError(f"gh release list gave no list of releases: {exc}") from exc
    earlier = sorted((when, name) for when, name in found if name != tag)
    return earlier[-1][1] if earlier else None


def real_update(runner: Runner, previous: str, folder: str | None) -> tuple[bool, str]:
    """Run the update from ``previous`` to this version, and say its steps as they come."""
    argv = [REAL_UPDATE, previous, *([folder] if folder else [])]
    result = runner.run(argv, check=False, progress=Progress(UPDATE_STAGES))
    last = next(
        (line for line in reversed(result.output.splitlines()) if line.startswith("real-update:")),
        "",
    )
    if result.returncode != 0:
        tail = "\n".join(result.output.strip().splitlines()[-15:])
        print(f"  `{' '.join(argv)}` failed:\n{tail}")
        return False, last or f"`{REAL_UPDATE}` failed"
    return True, last.removeprefix("real-update: ")


def package_path(root: Path, version: str) -> Path:
    """Return where the package build writes the .deb of ``version``."""
    return root / "dist" / f"segl_{version}_amd64.deb"


def log_path(root: Path, version: str) -> Path:
    """Return where `publish` keeps all it printed for ``version``."""
    return root / "dist" / f"publish-{version}.log"


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
    failure = run_changed(runner, root)
    if failure is not None:
        print(f"not cut: the suite fails ({failure})")
        return 1
    # The tree the suite has just shown to be good, before the version moves.
    good = work_tree(root)
    names = ("versions.toml", "pyproject.toml", "CHANGELOG.md", "uv.lock")
    saved = {name: (root / name).read_bytes() for name in names if (root / name).is_file()}
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
    if good is None:
        say("not a git checkout: the version change itself is not checked")
    else:
        say(f"checking the version change to {new}")
        failure = run_changed(runner, root, base=good, base_name="the tree before the change")
        if failure is not None:
            for name, content in saved.items():
                (root / name).write_bytes(content)
            print(f"not cut: the version change fails the suite ({failure}); files put back")
            return 1
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
        """Build the package into dist/, and see that it installs.

        The package build repeats: the same tree gives the same bytes. When CI
        built, installed, and tested the same bytes for HEAD, that test is this
        package's, and the install test does not run again here. Otherwise it
        runs here, on the package in dist/. Given no package, the install test
        builds one in a folder of its own, which it removes.
        """
        built = package_path(self.root, self.version)
        with tempfile.TemporaryDirectory(prefix="segl-ci-package-") as folder:
            tested, which = self.ci_package(Path(folder))
            if tested is None:
                say(
                    f"     the package builds and installs: {which}; building it, "
                    f"then running `{PACKAGE_TEST}` on it"
                )
            else:
                say(
                    f"     the package builds and installs: CI tested its package for HEAD "
                    f"({which}); building it here to compare"
                )
            failed = self.build(built)
            if failed is not None:
                return False, failed
            if tested is not None:
                if built.read_bytes() == tested.read_bytes():
                    return (
                        True,
                        f"dist/{built.name} is the package CI installed and tested ({which})",
                    )
                say(f"     dist/{built.name} is not the package CI tested: installing it here")
        return self.install_test([PACKAGE_TEST, f"dist/{built.name}"])

    def build(self, built: Path) -> str | None:
        """Build the package into dist/. Return why it failed, or None."""
        # Minutes of work: say each of its steps, and not only its end.
        result = self.runner.run([BUILD, "dist"], check=False, progress=Progress(PACKAGE_STAGES))
        if result.returncode != 0:
            tail = "\n".join(result.output.strip().splitlines()[-15:])
            print(f"  `{BUILD}` failed:\n{tail}")
            return f"`{BUILD}` failed"
        if not built.is_file():
            return f"dist/{built.name} was not built"
        return None

    def ci_package(self, folder: Path) -> tuple[Path | None, str]:
        """Download the package CI tested for HEAD into ``folder``.

        Returns its path and the run, or None and why there is none.
        """
        sha = self.runner.run(["git", "rev-parse", "HEAD"]).stdout.strip()
        repo = ["--repo", self.repo] if self.repo else []
        query = ["--commit", sha, "--workflow", "ci.yml", "--status", "success", "--limit", "1"]
        listed = self.runner.run(
            ["gh", "run", "list", *repo, *query, "--json", "databaseId"], check=False
        )
        try:
            runs = json.loads(listed.stdout) if listed.returncode == 0 else []
            run = str(int(runs[0]["databaseId"]))
        except (ValueError, LookupError, TypeError):
            return None, "no passed CI run for HEAD was found"
        got = self.runner.run(
            ["gh", "run", "download", run, *repo, "--name", CI_PACKAGE, "--dir", str(folder)],
            check=False,
        )
        package = folder / package_path(self.root, self.version).name
        if got.returncode != 0 or not package.is_file():
            return None, f"CI's package of run {run} could not be downloaded (it is kept 7 days)"
        return package, f"run {run}"

    def install_test(self, argv: list[str]) -> tuple[bool, str]:
        """Run the install test on the package in dist/, and say each of its steps."""
        result = self.runner.run(argv, check=False, progress=Progress(PACKAGE_STAGES))
        if result.returncode != 0:
            tail = "\n".join(result.output.strip().splitlines()[-15:])
            print(f"  `{PACKAGE_TEST}` failed:\n{tail}")
            return False, f"`{PACKAGE_TEST}` failed"
        return True, f"{argv[-1]} passed the install test"

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


def _plain_notes(text: str) -> str:
    """Return notes as they read: GitHub may end a line or the text otherwise."""
    return text.replace("\r\n", "\n").rstrip()


class Released:
    """The checks `publish` makes once the release is out, as GitHub serves it.

    They look at what a person or a server gets: the tag on origin, the
    release GitHub calls the latest, its files, and its notes. Each check
    runs and says how it went, since a failure cannot take the release back.
    """

    def __init__(
        self, runner: Runner, repo: str, tag: str, notes_sent: str, files: list[Path]
    ) -> None:
        self.runner, self.repo, self.tag = runner, repo, tag
        self.notes_sent, self.files = notes_sent, files

    def steps(self) -> list[tuple[str, Callable[[], tuple[bool, str]]]]:
        """Return each check with its name, in the order they run."""
        steps = [
            (f"tag {self.tag} on {REMOTE} is HEAD", self.tag_on_head),
            (f"releases/latest is {self.tag}", self.latest),
        ]
        if self.files:
            steps.append(("the release has the files from dist/", self.release_files))
        steps.append(("the notes on GitHub are the notes sent", self.notes))
        return steps

    def release(self, which: str) -> dict:
        """Return what GitHub's API says of ``releases/<which>``.

        Raises:
            CommandError: When GitHub cannot be asked, or its answer cannot be read.
        """
        answer = self.runner.run(["gh", "api", f"repos/{self.repo}/releases/{which}"]).stdout
        try:
            found = json.loads(answer)
        except ValueError as exc:
            raise CommandError(f"releases/{which} gave no JSON: {exc}") from exc
        if not isinstance(found, dict):
            raise CommandError(f"releases/{which} gave no release")
        return found

    def tag_on_head(self) -> tuple[bool, str]:
        head = self.runner.run(["git", "rev-parse", "HEAD"]).stdout.strip()
        peeled = f"refs/tags/{self.tag}^{{}}"
        listed = self.runner.run(["git", "ls-remote", "--tags", REMOTE, peeled]).stdout.split()
        if not listed:
            return False, f"{REMOTE} has no tag {self.tag}"
        if listed[0] != head:
            return False, f"it is on {listed[0][:7]}, and HEAD is {head[:7]}"
        return True, head[:7]

    def latest(self) -> tuple[bool, str]:
        found = self.release("latest")
        name = found.get("tag_name")
        if name != self.tag:
            return False, f"it is {name}"
        return True, f"published {found.get('published_at')}"

    def release_files(self) -> tuple[bool, str]:
        assets = self.release(f"tags/{self.tag}").get("assets") or []
        digests = {str(asset.get("name")): asset.get("digest") for asset in assets}
        names = [path.name for path in self.files]
        problems = []
        missing = [name for name in names if name not in digests]
        if missing:
            problems.append(f"missing {', '.join(missing)}")
        other = [
            path.name
            for path in self.files
            if path.name in digests and digests[path.name] != f"sha256:{signing.sha256_of(path)}"
        ]
        if other:
            problems.append(f"not the bytes in dist/: {', '.join(other)}")
        extra = sorted(set(digests) - set(names))
        if extra:
            problems.append(f"not sent: {', '.join(extra)}")
        if problems:
            return False, "; ".join(problems)
        return True, ", ".join(names)

    def notes(self) -> tuple[bool, str]:
        shown = _plain_notes(str(self.release(f"tags/{self.tag}").get("body") or ""))
        sent = _plain_notes(self.notes_sent)
        if shown == sent:
            return True, f"{len(sent):,} characters"
        pairs = zip(shown.splitlines(), sent.splitlines(), strict=False)
        line = next((n for n, (a, b) in enumerate(pairs, 1) if a != b), None)
        if line is None:
            return False, "GitHub's notes are longer or shorter than those sent"
        return False, f"line {line} differs"

    def run(self) -> tuple[int, int]:
        """Run every check. Return how many ran and how many failed."""
        steps = self.steps()
        failed = 0
        for name, step in steps:
            try:
                ok, detail = step()
            except CommandError as exc:
                ok, detail = False, str(exc)
            print(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")
            failed += not ok
        return len(steps), failed


def publish(root: Path, runner: Runner, sources: Sources, now: dt.datetime | None = None) -> int:
    """Tag the release and create the GitHub Release. Return the exit status.

    All it prints goes to dist/publish-<version>.log as well, so the run can
    be read afterwards. Each run adds to the log.
    """
    preflight = Preflight(root, runner, sources)
    log = log_path(root, preflight.version)
    head = runner.run(["git", "rev-parse", "--short", "HEAD"], check=False).stdout.strip()
    when = (now or dt.datetime.now().astimezone()).isoformat(timespec="seconds")
    with logged(log, f"== publish {preflight.version} at {when}, HEAD {head or 'unknown'}"):
        say(f"     log: {log.relative_to(root)}")
        return _publish(root, runner, preflight)


def _publish(root: Path, runner: Runner, preflight: Preflight) -> int:
    """Do the work of `publish`, once its log is open."""
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
    previous = None
    if has_package(root) and has_real_update(root):
        # The newest release a server can have now, and so the one this
        # version must update. Checked before the tag, with the signed files.
        try:
            previous = previous_release(runner, preflight.repo, tag)
        except CommandError as exc:
            print(f"not published: the releases on GitHub cannot be listed ({exc})")
            return 1
        if previous is None:
            print("ok   no earlier release is on GitHub: no update from one to check")
        else:
            say(f"     {previous} updates to {version}: running `{REAL_UPDATE} {previous} dist`")
            good, said = real_update(runner, previous, "dist")
            if not good:
                print(f"not published: {previous} does not update to {version} ({said})")
                return 1
            print(f"ok   {previous} updates to {version}, from the signed files: {said}")
    runner.run(["git", "tag", "-a", tag, "-m", f"segl {version}"])
    runner.run(["git", "push", REMOTE, tag])
    ran, failed = 0, 0
    if destinations.get("github"):
        with tempfile.TemporaryDirectory() as folder:
            notes_file = Path(folder) / "notes.md"
            notes_file.write_text(body, encoding="utf-8")
            create = ["gh", "release", "create", tag, "--verify-tag", "--repo", preflight.repo]
            create += ["--title", f"segl {version}", "--notes-file", str(notes_file)]
            runner.run(create + packages)
        print(f"published {tag} to {preflight.repo}")
        # As a person sees the release: the tag, the latest, the files, the notes.
        released = Released(runner, preflight.repo, tag, body, [Path(p) for p in packages])
        ran, failed = released.run()
        if previous is not None:
            # As a server sees the release: from GitHub, with its own files.
            server = f"a server on {previous} takes {version} from GitHub"
            say(f"     {server}: running `{REAL_UPDATE} {previous}`")
            good, said = real_update(runner, previous, None)
            print(f"{'ok  ' if good else 'FAIL'} {server}: {said}")
            ran, failed = ran + 1, failed + (not good)
    if destinations.get("pypi"):
        with tempfile.TemporaryDirectory() as folder:
            runner.run(["uv", "build", "--out-dir", folder])
            built = sorted(str(path) for path in Path(folder).iterdir())
            runner.run(["uv", "publish", *built])
        print(f"published {version} to PyPI")
    if failed:
        print(f"done: {tag} is published, but {failed} of {ran} checks after it failed")
        return 1
    print(f"done: {tag} is published, and every check passed")
    return 0
