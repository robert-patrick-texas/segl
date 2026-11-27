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

"""Move each outdated component, run what it can break, and hold a failure.

`upgrade` keeps a move when its checks pass. Otherwise it restores the files
it changed and records ``[held.<name>]`` in versions.toml with the first
failing test (docs/RELEASING.md).

It does not run the whole suite for every component. A tool that can only
break its own check gets that check, which takes seconds. The others move
together and the suite runs once. Only when that run fails does it run the
suite on the tree as it was, unless that tree is known to be good already
(scripts/suite.py), and then for each of them alone.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from pathlib import Path

import release_edits as edits
from release_components import (
    CURRENT,
    NEWER,
    NODE_IMAGE,
    STALE,
    UNKNOWN,
    LookupFailed,
    Sources,
    Status,
    container_files,
    image_pins,
    load_versions,
    report,
    workflow_files,
)
from release_proc import Runner
from release_versions import at_precision, parse_version
from suite import (
    INSTALL_TEST,
    PYTHON_CHECKS,
    PYTHON_SYNC,
    PYTHON_TESTS,
    WEB_FORMAT,
    WEB_SYNC,
    WEB_TYPES,
    has_web,
    known_good,
    run,
    run_whole,
    whole_suite,
)

# What the move of a tool can break, when that is less than everything: the
# commands of the suite that use the tool. A component that is not named
# here gets the whole suite. So does one whose reach is not certain: Vitest
# is not here, because vite.config.ts takes its `defineConfig` from it, and
# so the build does too.
NARROW_PYTHON: dict[str, tuple[tuple[str, ...], ...]] = {
    # The linter and formatter, and the type checker: each runs as one check.
    "ruff": PYTHON_CHECKS[:2],
    "ty": PYTHON_CHECKS[2:],
    # The test runner and the test client's transport: only pytest uses them.
    "pytest": (PYTHON_TESTS,),
    "pytest-xdist": (PYTHON_TESTS,),
    "httpx2": (PYTHON_TESTS,),
    # md2html's packages, which its tests in tools/ cover.
    "markdown-it-py": (PYTHON_TESTS,),
    "mdit-py-plugins": (PYTHON_TESTS,),
}
NARROW_WEB: dict[str, tuple[tuple[str, ...], ...]] = {
    "prettier": (WEB_FORMAT,),
    # Type checking alone: Vite does not build with tsc.
    "typescript": (WEB_TYPES,),
    "@types/node": (WEB_TYPES,),
    "@types/react": (WEB_TYPES,),
    "@types/react-dom": (WEB_TYPES,),
}
MD2HTML = "tools/md2html/md2html.py"


def sync_commands(root: Path) -> tuple[tuple[str, ...], ...]:
    """Return the commands that bring the environments to the pins."""
    return (PYTHON_SYNC, WEB_SYNC) if has_web(root) else (PYTHON_SYNC,)


def suite_commands(root: Path) -> tuple[tuple[str, ...], ...]:
    """Return the suite for the tree at ``root``: CI's checks, in CI's order.

    Both environments are brought to the pins first: `uv sync` and `npm
    install` resolve the lockfiles again after a pin moved, and pytest holds
    web/package-lock.json to versions.toml. The web build comes before pytest,
    which compares its stand-in for the build with the real one, and before
    the browser tests, which Python serves it to. Those need a browser of the
    pinned Playwright version (docs/DEVELOPMENT.md). scripts/suite.py runs
    them by stage, side by side where it can.
    """
    return whole_suite(root)


def narrow_commands(root: Path, status: Status) -> tuple[tuple[str, ...], ...] | None:
    """Return the checks that cover a component's move, or None for the whole suite.

    An empty answer means nothing here can test the move: a GitHub Action runs
    in CI alone, and the push is its test. An image or a Go tool gets the
    whole suite, and the install test with it (``run_suite``).
    """
    component = status.component
    if component.kind == "action":
        return ()
    if component.kind == "python" and component.name in NARROW_PYTHON:
        return (PYTHON_SYNC, *NARROW_PYTHON[component.name])
    if component.kind == "web" and component.name in NARROW_WEB and has_web(root):
        return (WEB_SYNC, *NARROW_WEB[component.name])
    return None


def run_suite(runner: Runner, root: Path, package: bool = False) -> str | None:
    """Run the whole suite. Return None when it passes, or what failed first.

    With ``package``, the install test runs with it. The suite builds no
    image, and the install test builds the package's builder image from
    deploy/debian/Containerfile, so it is what tests a move of an image or a
    Go tool, and a Node move, which takes Node's image lines with it.
    """
    return run_whole(runner, root, (INSTALL_TEST,) if package else ())


def containers_changed(root: Path, saved: dict[Path, bytes | None]) -> bool:
    """Report whether a container file differs from ``snapshot``'s copy."""
    return any(saved.get(path) != path.read_bytes() for path in container_files(root))


def run_commands(runner: Runner, commands: Sequence[tuple[str, ...]]) -> str | None:
    """Run commands of the suite. Return None when all pass, or what failed first.

    They run by stage, side by side where they can (scripts/suite.py). Each
    is named as it starts and says when it ends, and one that takes long says
    so meanwhile (release_progress).
    """
    return run(runner, commands)


def tracked_files(root: Path) -> list[Path]:
    """Return the files a move may change."""
    names = [
        "versions.toml",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        MD2HTML,
        "web/package.json",
        "web/package-lock.json",
        "web/.node-version",
    ]
    return [root / name for name in names] + workflow_files(root) + container_files(root)


def snapshot(root: Path) -> dict[Path, bytes | None]:
    """Return the contents of every file a move may change."""
    return {path: path.read_bytes() if path.is_file() else None for path in tracked_files(root)}


def restore(saved: dict[Path, bytes | None]) -> None:
    """Put back the files as ``snapshot`` found them."""
    for path, content in saved.items():
        if content is None:
            path.unlink(missing_ok=True)
        elif not path.is_file() or path.read_bytes() != content:
            path.write_bytes(content)


def rewrite(path: Path, change: Callable[[str], str]) -> None:
    """Apply a text edit to a file."""
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")


def target_of(status: Status) -> str:
    """Return the version a move writes: the newest release, at the pin's precision."""
    component = status.component
    if component.kind == "action" and component.ref == component.version:
        return at_precision(component.version, status.latest)
    return status.latest


def move_image(root: Path, sources: Sources, name: str, old: str, new: str) -> None:
    """Move every pin of image ``name`` at version ``old`` to ``new``, with its digest.

    A tag keeps its variant: ``26.13.1-trixie-slim`` becomes ``26.14.0-trixie-slim``.
    """
    digests: dict[str, str] = {}
    for path in container_files(root):
        text = path.read_text(encoding="utf-8")
        tags = sorted({t for n, t, v in image_pins(text) if n == name and v == old})
        for tag in tags:
            moved = new + tag.removeprefix(old)
            if moved not in digests:
                digests[moved] = sources.image_digest(name, moved)
            text = edits.set_image(text, name, tag, moved, digests[moved])
        if tags:
            path.write_text(text, encoding="utf-8")


def apply_move(root: Path, status: Status, sources: Sources) -> None:
    """Write the newest release of one component into versions.toml and its mirrors.

    Raises:
        release_edits.EditError: When a mirror does not hold the old pin.
        LookupFailed: When the commit of an Actions release, or the digest of
            an image's new tag, cannot be found.
    """
    component, new = status.component, target_of(status)
    old = component.version
    versions = root / "versions.toml"
    if component.kind == "runtime" and component.name == "python":
        rewrite(versions, lambda t: edits.set_entry(t, "runtime", "python", new))
        (root / ".python-version").write_text(f"{new}\n", encoding="utf-8")
        if edits.minor_of(old) != edits.minor_of(new):
            rewrite(root / "pyproject.toml", lambda t: edits.set_python_minor(t, old, new))
    elif component.kind == "runtime":
        rewrite(versions, lambda t: edits.set_entry(t, "runtime", "node", new))
        (root / "web" / ".node-version").write_text(f"{new}\n", encoding="utf-8")
        move_image(root, sources, NODE_IMAGE, old, new)
    elif component.kind == "image":
        move_image(root, sources, component.name, old, new)
    elif component.kind == "go":
        old_major, new_major = (parse_version(v) for v in (old, new))
        if old_major is None or new_major is None or old_major.release[0] != new_major.release[0]:
            # Go puts a major version above 1 in the module path (/v2/), so
            # the line needs more than a new version: a person moves it.
            raise edits.EditError(f"{new} is a new major version, and its module path changes")
        for path in container_files(root):
            try:
                rewrite(path, lambda t: edits.set_go_install(t, component.ref, old, new))
            except edits.EditError:
                continue
    elif component.kind == "python":
        table = f"python.{component.table}"
        rewrite(versions, lambda t: edits.set_entry(t, table, component.name, new))
        rewrite(
            root / "pyproject.toml", lambda t: edits.set_requirement(t, component.name, old, new)
        )
        if component.table == "docs":
            rewrite(root / MD2HTML, lambda t: edits.set_requirement(t, component.name, old, new))
    elif component.kind == "web":
        table = f"web.{component.table}"
        rewrite(versions, lambda t: edits.set_entry(t, table, component.name, new))
        rewrite(
            root / "web" / "package.json",
            lambda t: edits.set_package_json(t, component.name, old, new),
        )
    else:
        pinned_by_commit = component.ref != component.version
        ref = sources.action_commit(component.name, new) if pinned_by_commit else new
        note = new if pinned_by_commit else ""
        for path in workflow_files(root):
            text = path.read_text(encoding="utf-8")
            try:
                changed = edits.set_action(text, component.name, component.ref, ref, note)
            except edits.EditError:
                continue
            path.write_text(changed, encoding="utf-8")


def upgrade(root: Path, runner: Runner, sources: Sources, today: dt.date | None = None) -> int:
    """Move every outdated component, one at a time. Return the exit status."""
    since = (today or dt.date.today()).isoformat()
    statuses = report(root, sources)
    unknown = [status for status in statuses if status.state == UNKNOWN]
    for status in unknown:
        print(status.line)
    stale_holds = [s for s in statuses if s.state == CURRENT and s.detail]
    outdated = [status for status in statuses if status.state in (NEWER, STALE)]
    versions = root / "versions.toml"
    for status in stale_holds:
        rewrite(versions, lambda t, s=status: edits.clear_hold(t, s.component.name))
        print(f"{status.component.label}: current, hold removed")
    if not outdated:
        print("nothing to upgrade")
        return 1 if unknown else 0
    narrow = [s for s in outdated if narrow_commands(root, s) is not None]
    wide = [s for s in outdated if narrow_commands(root, s) is None]

    def keep(status: Status) -> None:
        component = status.component
        rewrite(versions, lambda t: edits.clear_hold(t, component.name))
        print(f"{component.label}: moved to {target_of(status)}")

    def hold(status: Status, reason: str) -> None:
        component = status.component
        rewrite(
            versions,
            lambda t: edits.set_hold(
                t, component.name, component.version, status.latest, reason, since
            ),
        )
        print(f"{component.label}: kept, {status.latest} held ({reason})")

    def move(status: Status) -> bool:
        """Write one move. Say so and return False when it cannot be written."""
        saved = snapshot(root)
        try:
            apply_move(root, status, sources)
        except (edits.EditError, LookupFailed) as exc:
            restore(saved)
            print(f"{status.component.label}: could not be moved ({exc})")
            unknown.append(status)
            return False
        return True

    held = 0
    # The tree as it stands may be known to be good already: the whole suite
    # passed on it here, or CI passed on a commit with the same files.
    good = known_good(root, runner)
    tree_was_good = good is not None and not good.changed
    # The tools first, each with its own check, so that the suite's one run
    # below covers their moves too, and the pass it records is of the tree
    # this leaves: `cut` then has nothing to run again.
    for status in narrow:
        commands = narrow_commands(root, status)
        assert commands is not None
        component = status.component
        saved = snapshot(root)
        if not move(status):
            continue
        if not commands:
            keep(status)
            print(f"{component.label}: nothing here runs it; CI on the push is its test")
            continue
        reason = run_commands(runner, commands)
        if reason is None:
            keep(status)
            continue
        restore(saved)
        if not tree_was_good:
            # The check fails with the move. Run it on the tree as it was too,
            # unless that is known to be good, to tell a broken tree from a
            # broken move, as the suite below does.
            before = run_commands(runner, commands)
            if before is not None:
                print(
                    f"{component.label}: its check fails without the move too ({before}); not held"
                )
                unknown.append(status)
                continue
        hold(status, reason)
        held += 1
    if wide:
        # The components that can break anything, together, and the suite
        # once. A pass shows the tree and every one of these moves to be good.
        start = snapshot(root)
        moved = [status for status in wide if move(status)]
        labels = ", ".join(f"{s.component.label} {target_of(s)}" for s in moved)
        package = containers_changed(root, start)
        reason = None
        if moved:
            print(f"trying together: {labels}")
            reason = run_suite(runner, root, package)
        if reason is None:
            for status in moved:
                keep(status)
        else:
            # Something failed: the tree as it was, or one of the moves.
            restore(start)
            if tree_was_good:
                assert good is not None
                print(f"the suite fails with those moves ({reason}); before any move,")
                print(f"  {good.what}: not run again")
                baseline = None
                if package:
                    # The suite builds no image, so that says nothing of the install test.
                    print("  the install test, which that does not cover, runs before any move")
                    baseline = run_commands(runner, (INSTALL_TEST,))
            else:
                print(f"the suite fails with those moves ({reason}); running it before any move")
                baseline = run_suite(runner, root, package)
            if baseline is not None:
                print(f"the suite fails before any move ({baseline}); nothing was changed")
                return 1
            if len(moved) == 1:
                # It ran alone already.
                hold(moved[0], reason)
                held += 1
            else:
                for status in moved:
                    print(f"{status.component.label}: trying {target_of(status)} alone")
                    saved = snapshot(root)
                    if not move(status):
                        continue
                    alone = run_suite(runner, root, containers_changed(root, saved))
                    if alone is None:
                        keep(status)
                        continue
                    restore(saved)
                    hold(status, alone)
                    held += 1
    if held:
        # Put the environments back on the pins that were kept.
        for argv in sync_commands(root):
            runner.run(argv, check=False)
    load_versions(root)  # fails loudly if an edit left invalid TOML
    return 1 if unknown else 0
