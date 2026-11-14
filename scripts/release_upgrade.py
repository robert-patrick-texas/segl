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
suite on the tree as it was, and then for each of them alone.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import release_edits as edits
from release_components import (
    CURRENT,
    NEWER,
    STALE,
    UNKNOWN,
    LookupFailed,
    Sources,
    Status,
    load_versions,
    report,
    workflow_files,
)
from release_proc import CommandError, Runner
from release_versions import at_precision

# The commands CI runs (docs/DEVELOPMENT.md, "Checks"), in CI's order.
#
# Both environments are brought to the pins first: `uv sync` and `npm install`
# resolve the lockfiles again after a pin moved, and pytest holds
# web/package-lock.json to versions.toml. The web build comes before pytest,
# which compares its stand-in for the build with the real one, and before the
# browser tests, which Python serves it to. Those need a browser of the pinned
# Playwright version (docs/DEVELOPMENT.md).
PYTHON_SYNC: tuple[str, ...] = ("uv", "sync")
PYTHON_CHECKS: tuple[tuple[str, ...], ...] = (
    ("uv", "run", "ruff", "check", "."),
    ("uv", "run", "ruff", "format", "--check", "."),
    ("uv", "run", "ty", "check"),
)
PYTHON_TESTS: tuple[str, ...] = ("uv", "run", "pytest")
WEB_SYNC: tuple[str, ...] = ("npm", "--prefix", "web", "install", "--no-audit", "--no-fund")
WEB_CHECKS: tuple[tuple[str, ...], ...] = (
    ("npm", "--prefix", "web", "run", "check"),
    ("npm", "--prefix", "web", "test"),
    ("npm", "--prefix", "web", "run", "format:check"),
    ("npm", "--prefix", "web", "run", "build"),
)
# The browser tests, in as many groups at once as the machine has room for.
WEB_E2E: tuple[str, ...] = (sys.executable, "scripts/e2e.py")
WEB_FORMAT: tuple[str, ...] = ("npm", "--prefix", "web", "run", "format:check")
WEB_TYPES: tuple[str, ...] = ("npm", "--prefix", "web", "run", "check")

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
_FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (\S+)", flags=re.MULTILINE)


def has_web(root: Path) -> bool:
    """Report whether the tree at ``root`` has the web package."""
    return (root / "web" / "package.json").is_file()


def sync_commands(root: Path) -> tuple[tuple[str, ...], ...]:
    """Return the commands that bring the environments to the pins."""
    return (PYTHON_SYNC, WEB_SYNC) if has_web(root) else (PYTHON_SYNC,)


def suite_commands(root: Path) -> tuple[tuple[str, ...], ...]:
    """Return the suite for the tree at ``root``."""
    if not has_web(root):
        return (PYTHON_SYNC, *PYTHON_CHECKS, PYTHON_TESTS)
    return (*sync_commands(root), *PYTHON_CHECKS, *WEB_CHECKS, PYTHON_TESTS, WEB_E2E)


def narrow_commands(root: Path, status: Status) -> tuple[tuple[str, ...], ...] | None:
    """Return the checks that cover a component's move, or None for the whole suite.

    An empty answer means nothing here can test the move: a GitHub Action runs
    in CI alone, and the push is its test.
    """
    component = status.component
    if component.kind == "action":
        return ()
    if component.kind == "python" and component.name in NARROW_PYTHON:
        return (PYTHON_SYNC, *NARROW_PYTHON[component.name])
    if component.kind == "web" and component.name in NARROW_WEB and has_web(root):
        return (WEB_SYNC, *NARROW_WEB[component.name])
    return None


def run_suite(runner: Runner, root: Path) -> str | None:
    """Run the suite. Return None when it passes, or what failed first."""
    return run_commands(runner, suite_commands(root))


def run_commands(runner: Runner, commands: Sequence[tuple[str, ...]]) -> str | None:
    """Run commands in order. Return None when all pass, or what failed first."""
    for argv in commands:
        command = " ".join(argv)
        try:
            result = runner.run(argv, check=False)
        except CommandError as exc:
            return str(exc)
        if result.returncode != 0:
            failed = _FAILED_TEST.search(result.output)
            tail = "\n".join(result.output.strip().splitlines()[-15:])
            print(f"  `{command}` failed:\n{tail}")
            return failed[1] if failed else f"`{command}` failed"
    return None


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
    return [root / name for name in names] + workflow_files(root)


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


def apply_move(root: Path, status: Status, sources: Sources) -> None:
    """Write the newest release of one component into versions.toml and its mirrors.

    Raises:
        release_edits.EditError: When a mirror does not hold the old pin.
        LookupFailed: When the commit of an Actions release cannot be found.
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
    # Whether a whole-suite run has passed, on the tree or on the tree with moves.
    tree_is_good = False
    if wide:
        # The components that can break anything, together, and the suite
        # once. A pass shows the tree and every one of these moves to be good.
        start = snapshot(root)
        moved = [status for status in wide if move(status)]
        labels = ", ".join(f"{s.component.label} {target_of(s)}" for s in moved)
        reason = None
        if moved:
            print(f"trying together: {labels}")
            reason = run_suite(runner, root)
        if reason is None:
            tree_is_good = bool(moved)
            for status in moved:
                keep(status)
        else:
            # Something failed: the tree as it was, or one of the moves.
            restore(start)
            print(f"the suite fails with those moves ({reason}); running it before any move")
            baseline = run_suite(runner, root)
            if baseline is not None:
                print(f"the suite fails before any move ({baseline}); nothing was changed")
                return 1
            tree_is_good = True
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
                    alone = run_suite(runner, root)
                    if alone is None:
                        keep(status)
                        continue
                    restore(saved)
                    hold(status, alone)
                    held += 1
    for status in narrow:
        commands = narrow_commands(root, status)
        assert commands is not None
        component = status.component
        if commands and not tree_is_good:
            # No whole-suite run has shown the tree to be good. These checks
            # take seconds, so run them as the tree stands first.
            before = run_commands(runner, commands)
            if before is not None:
                print(f"{component.label}: its check fails before the move ({before}); not tried")
                unknown.append(status)
                continue
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
        hold(status, reason)
        held += 1
    if held:
        # Put the environments back on the pins that were kept.
        for argv in sync_commands(root):
            runner.run(argv, check=False)
    load_versions(root)  # fails loudly if an edit left invalid TOML
    return 1 if unknown else 0
