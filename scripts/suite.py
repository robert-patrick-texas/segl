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

"""Run the suite, side by side where the machine has room, or only what changed.

    python3 scripts/suite.py                    # the whole suite
    python3 scripts/suite.py --changed          # what covers the files that changed
    python3 scripts/suite.py --changed --plan   # say what that would run, and why
    python3 scripts/suite.py --changed --base origin/main

The whole suite is CI's checks, in three stages. Both environments come to
the pins first (`uv sync`, `npm install`). The quick checks then run side by
side: ruff, ty, tsc, Vitest, Prettier, and the web build. The long ones come
last. The longest starts first, and the next starts beside it when
scripts/capacity.py finds a core free twice in a row, or when it ends. A
failure stops the rest.

A pass is kept against the tree it ran on, in the git folder: of the whole
suite, or of what covered the changes. `--changed` starts from a tree known
to be good: that one, or a commit CI passed on, whichever differs least from
the work tree. It runs
only the checks that cover the files that differ (`plan`). Where no tree is
known to be good, it runs everything. CI still runs everything on every
push, and a release is published only after CI passed on its commit
(docs/RELEASING.md).

The scripts run under the host's python3, so this is the standard library
alone (docs/DEVELOPMENT.md).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

import capacity
from release_proc import CommandError, Runner
from release_progress import PACKAGE_STAGES, SUITE_STAGES, Progress, say

ROOT = Path(__file__).resolve().parents[1]

# The commands CI runs (docs/DEVELOPMENT.md, "Checks").
PYTHON_SYNC: tuple[str, ...] = ("uv", "sync")
RUFF_CHECK: tuple[str, ...] = ("uv", "run", "ruff", "check", ".")
RUFF_FORMAT: tuple[str, ...] = ("uv", "run", "ruff", "format", "--check", ".")
TY_CHECK: tuple[str, ...] = ("uv", "run", "ty", "check")
PYTHON_CHECKS: tuple[tuple[str, ...], ...] = (RUFF_CHECK, RUFF_FORMAT, TY_CHECK)
PYTHON_TESTS: tuple[str, ...] = ("uv", "run", "pytest")
WEB_SYNC: tuple[str, ...] = ("npm", "--prefix", "web", "install", "--no-audit", "--no-fund")
WEB_TYPES: tuple[str, ...] = ("npm", "--prefix", "web", "run", "check")
WEB_TESTS: tuple[str, ...] = ("npm", "--prefix", "web", "test")
WEB_FORMAT: tuple[str, ...] = ("npm", "--prefix", "web", "run", "format:check")
WEB_BUILD: tuple[str, ...] = ("npm", "--prefix", "web", "run", "build")
WEB_CHECKS: tuple[tuple[str, ...], ...] = (WEB_TYPES, WEB_TESTS, WEB_FORMAT, WEB_BUILD)
# The browser tests, in as many groups at once as the machine has room for.
WEB_E2E: tuple[str, ...] = (sys.executable, "scripts/e2e.py")
# The browser of the pinned Playwright, fetched into the user's cache before
# the browser tests. Each Playwright release has a browser build of its own,
# so a moved pin needs a new one, and the command is quick when the build is
# there. CI fetches its own (`--with-deps`). Not when PW_WS_ENDPOINT names a
# browser running elsewhere (docs/DEVELOPMENT.md, browsers for the tests).
BROWSER: tuple[str, ...] = (
    *("npm", "--prefix", "web", "exec", "--"),
    *("playwright", "install", "chromium"),
)
# Vitest for the files named after it: a test file runs itself, and any other
# file the tests that import it. The paths are from web/.
WEB_RELATED: tuple[str, ...] = (
    *("npm", "--prefix", "web", "exec", "--"),
    *("vitest", "related", "--run", "--root", "web"),
)
# Not in CI's checks job, and not in the whole suite: the documentation
# site's links (the Pages workflow) and the install test (the package job).
# `--changed` runs each when a change reaches it.
DOCS: tuple[str, ...] = (sys.executable, "scripts/build_docs.py")
INSTALL_TEST: tuple[str, ...] = ("deploy/debian/package-test.sh",)

SYNC, QUICK, LONG = "sync", "quick", "long"
# About how long each long step takes on the development host, in minutes.
# The longest starts first, and the shorter ones run beside it when there
# is room.
LONG_MINUTES = {"e2e": 4.5, "install test": 3.5, "pytest": 0.6}
# How often a long step that waits looks for room, and how many looks in a
# row must find room before it starts beside another. A look takes a second.
LOOK_EVERY = 5.0
LOOKS_IN_A_ROW = 2
# The kept pass, in the git folder: never committed, and one for each work tree.
STAMP = "segl-suite-passed"
WHOLE = "the whole suite"
CHANGES = "the checks of what changed"
# Which lines of a step's output are said as they come. The install test says
# each of its sections, as `publish` shows it.
STAGE_LINES = {"install test": PACKAGE_STAGES}
# How many of CI's newest passes are compared with the work tree.
CI_PASSES = 20
_FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (\S+)", flags=re.MULTILINE)


def has_web(root: Path) -> bool:
    """Report whether the tree at ``root`` has the web package."""
    return (root / "web" / "package.json").is_file()


def browser_elsewhere() -> bool:
    """Report whether PW_WS_ENDPOINT names a browser running elsewhere."""
    return bool(os.environ.get("PW_WS_ENDPOINT"))


def with_browser(commands: Sequence[tuple[str, ...]]) -> list[tuple[str, ...]]:
    """Return the commands with the browser's fetch before the browser tests.

    Nothing is added when no browser test runs, or when the browser runs
    elsewhere.
    """
    fetch = not browser_elsewhere()
    out: list[tuple[str, ...]] = []
    for argv in commands:
        if fetch and argv[1:2] == WEB_E2E[1:2]:
            out.append(BROWSER)
            fetch = False
        out.append(argv)
    return out


def whole_suite(root: Path) -> tuple[tuple[str, ...], ...]:
    """Return the suite for the tree at ``root``, in CI's order."""
    if not has_web(root):
        return (PYTHON_SYNC, *PYTHON_CHECKS, PYTHON_TESTS)
    return tuple(
        with_browser((PYTHON_SYNC, WEB_SYNC, *PYTHON_CHECKS, *WEB_CHECKS, PYTHON_TESTS, WEB_E2E))
    )


@dataclass(frozen=True)
class Step:
    """One command of the suite, and the stage it runs in."""

    label: str
    argv: tuple[str, ...]
    stage: str
    order: int = 0  # its place in the suite, for which failure is reported

    @property
    def command(self) -> str:
        return " ".join(self.argv)


def label_of(argv: Sequence[str]) -> str:
    """Return the short name a command's lines carry while others run beside it."""
    argv = tuple(argv)
    if argv[:2] == ("uv", "run") and len(argv) > 2:
        return f"ruff {argv[3]}" if argv[2] == "ruff" and len(argv) > 3 else argv[2]
    if argv[:1] == ("uv",) and len(argv) > 1:
        return f"uv {argv[1]}"
    if argv[: len(WEB_RELATED)] == WEB_RELATED:
        return "web test"
    if argv == BROWSER:
        return "browser"
    if argv[:3] == ("npm", "--prefix", "web") and len(argv) > 3:
        rest = argv[3:]
        return f"web {rest[1]}" if rest[0] == "run" and len(rest) > 1 else f"web {rest[0]}"
    if len(argv) > 1 and argv[1] == WEB_E2E[1]:
        return "e2e"
    if len(argv) > 1 and argv[1] == DOCS[1]:
        return "docs"
    if argv[:1] == INSTALL_TEST:
        return "install test"
    return " ".join(argv[:2])


def step_of(argv: Sequence[str]) -> Step:
    """Return the step of one command: environments first, the long ones last."""
    label = label_of(argv)
    if tuple(argv) in (PYTHON_SYNC, WEB_SYNC):
        stage = SYNC
    elif label in LONG_MINUTES:
        stage = LONG
    else:
        stage = QUICK
    return Step(label, tuple(argv), stage)


def first_failure(step: Step, output: str) -> str:
    """Return what a failed step reports: the first failing test, or the command."""
    failed = _FAILED_TEST.search(output)
    return failed[1] if failed else f"`{step.command}` failed"


class _Stage:
    """The steps of one stage, as they run."""

    def __init__(self, runner: Runner, cancel: threading.Event) -> None:
        self.runner, self.cancel = runner, cancel
        self.lock = threading.Lock()
        self.ended = threading.Event()
        self.failures: list[tuple[int, str]] = []
        self.threads: list[threading.Thread] = []

    def start(self, step: Step) -> None:
        thread = threading.Thread(target=self._work, args=(step,), daemon=True)
        self.threads.append(thread)
        thread.start()

    def running(self) -> int:
        return sum(thread.is_alive() for thread in self.threads)

    def join(self) -> None:
        for thread in self.threads:
            thread.join()

    def _work(self, step: Step) -> None:
        try:
            failure = self._run(step)
        except BaseException as exc:  # a thread's error must still stop the rest
            failure = f"`{step.command}`: {exc}"
        with self.lock:
            if failure is not None:
                self.failures.append((step.order, failure))
                self.cancel.set()
            self.ended.set()

    def _run(self, step: Step) -> str | None:
        say(f"  {step.command}")
        progress = Progress(STAGE_LINES.get(step.label, SUITE_STAGES), label=step.label)
        try:
            result = self.runner.run(step.argv, check=False, progress=progress, cancel=self.cancel)
        except CommandError as exc:
            return str(exc)
        if result.returncode == 0:
            progress.done(True)
            return None
        if result.stopped:
            # Stopped, because another step failed first.
            progress.stopped()
            return None
        progress.done(False)
        tail = "\n".join(result.output.strip().splitlines()[-15:])
        print(f"  `{step.command}` failed:\n{tail}", flush=True)
        return first_failure(step, result.output)


def run(
    runner: Runner,
    commands: Iterable[Sequence[str]],
    *,
    look: Callable[[], capacity.Machine] = capacity.look,
    every: float = LOOK_EVERY,
) -> str | None:
    """Run commands of the suite by stage. Return None when all pass, or what failed first.

    Each command is named as it starts, and says when it ends. One that
    takes long says so meanwhile (release_progress). ``look`` measures the
    machine, and ``every`` is the seconds between two looks.
    """
    steps = [replace(step_of(argv), order=order) for order, argv in enumerate(commands)]
    cancel = threading.Event()
    for stage in (SYNC, QUICK, LONG):
        now = [step for step in steps if step.stage == stage]
        if not now:
            continue
        running = _Stage(runner, cancel)
        try:
            if stage != LONG:
                if len(now) > 1:
                    say(f"  side by side: {', '.join(step.label for step in now)}")
                for step in now:
                    running.start(step)
            else:
                waiting = sorted(now, key=lambda step: -LONG_MINUTES.get(step.label, 0.0))
                running.start(waiting.pop(0))
                for step in waiting:
                    if not _wait_for_room(running, cancel, look, every, step.label):
                        break
                    running.start(step)
            running.join()
        except BaseException:
            # Ctrl+C reaches this thread alone: stop every running command.
            cancel.set()
            running.join()
            raise
        if running.failures:
            # Of two that failed side by side, the one first in the suite.
            return min(running.failures)[1]
    return None


def _wait_for_room(
    running: _Stage,
    cancel: threading.Event,
    look: Callable[[], capacity.Machine],
    every: float,
    label: str,
) -> bool:
    """Wait until a long step may start. Return False when the suite was stopped.

    It starts when a running step ends, or beside them when the machine has
    room for one more on ``LOOKS_IN_A_ROW`` looks in a row.
    """
    found = 0
    with running.lock:
        running.ended.clear()
    while not cancel.is_set():
        if running.running() == 0 or running.ended.wait(every):
            return not cancel.is_set()
        machine = look()
        found = found + 1 if capacity.room(machine) >= 1 else 0
        if found >= LOOKS_IN_A_ROW:
            say(f"  {label} starts beside the others ({machine.summary})")
            return True
    return False


# --- Trees known to be good -------------------------------------------------


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> str | None:
    """Return a git command's output, or None when git is missing or fails."""
    try:
        done = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, env=env, check=False
        )
    except FileNotFoundError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def work_tree(root: Path) -> str | None:
    """Return the git tree of the work tree as `git add --all` would commit it.

    It is written with an index of its own, so the real index is not changed.
    That index starts from HEAD's files with no stat data, so git hashes every
    file again and trusts no file's size and times: a change git's own index
    cannot see is still seen. It also keeps a tracked file that .gitignore
    names. None outside a git checkout.
    """
    if _git(root, "rev-parse", "--git-dir") is None:
        return None
    with tempfile.TemporaryDirectory(prefix="segl-suite-") as folder:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(folder) / "index")}
        # Before a first commit there is no HEAD, and the index starts empty.
        _git(root, "read-tree", "HEAD", env=env)
        if _git(root, "add", "--all", ".", env=env) is None:
            return None
        return _git(root, "write-tree", env=env)


def _stamp_path(root: Path) -> Path | None:
    path = _git(root, "rev-parse", "--git-path", STAMP)
    return None if path is None else root / path


def record_pass(root: Path, tree: str, how: str = WHOLE, now: dt.datetime | None = None) -> None:
    """Keep the tree that the suite passed on, and what passed: ``WHOLE`` or ``CHANGES``."""
    path = _stamp_path(root)
    if path is None:
        return
    when = (now or dt.datetime.now().astimezone()).isoformat(timespec="seconds")
    kept = {"tree": tree, "passed": when, "how": how}
    path.write_text(json.dumps(kept) + "\n", encoding="utf-8")


def recorded_pass(root: Path) -> tuple[str, str, str] | None:
    """Return the kept tree, when the suite passed on it, and what passed, or None."""
    path = _stamp_path(root)
    if path is None or not path.is_file():
        return None
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
        return str(kept["tree"]), str(kept["passed"]), str(kept.get("how", WHOLE))
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def changed_files(root: Path, base: str, tree: str) -> tuple[str, ...] | None:
    """Return the files that differ between ``base`` and ``tree``, or None."""
    names = _git(root, "diff", "--name-only", "--no-renames", base, tree)
    if names is None:
        return None
    return tuple(sorted(name for name in names.splitlines() if name))


def ci_passes(runner: Runner) -> list[str]:
    """Return the commits of CI's newest passes, newest first. Empty offline."""
    argv = ["gh", "run", "list", "--workflow", "ci.yml", "--status", "success"]
    argv += ["--limit", str(CI_PASSES), "--json", "headSha"]
    try:
        result = runner.run(argv, check=False)
    except CommandError:
        return []
    if result.returncode != 0:
        return []
    try:
        rows = json.loads(result.stdout)
    except ValueError:
        return []
    commits: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        sha = row.get("headSha") if isinstance(row, dict) else None
        if isinstance(sha, str) and sha not in commits:
            commits.append(sha)
    return commits


@dataclass(frozen=True)
class Base:
    """A tree known to be good, and the files the work tree changed since."""

    ref: str
    what: str
    changed: tuple[str, ...]


def known_good(
    root: Path, runner: Runner, tree: str | None = None, explicit: str | None = None
) -> Base | None:
    """Return the good tree nearest the work tree, or None where none is known.

    A good tree is the one the suite last passed on here, whole or for what
    changed, or a commit that CI passed on. The nearest is the one with the fewest changed files.
    ``explicit`` is taken as good without asking.
    """
    tree = tree or work_tree(root)
    if tree is None:
        return None
    if explicit is not None:
        changed = changed_files(root, explicit, tree)
        if changed is None:
            raise SystemExit(f"suite: git cannot compare {explicit!r} with the work tree")
        return Base(explicit, f"{explicit} (--base)", changed)
    found: list[Base] = []
    kept = recorded_pass(root)
    if kept is not None:
        changed = changed_files(root, kept[0], tree)
        if changed is not None:
            found.append(Base(kept[0], f"{kept[2]} passed here ({kept[1]})", changed))
    for sha in ci_passes(runner):
        changed = changed_files(root, sha, tree)
        if changed is not None:
            found.append(Base(sha, f"CI passed on {sha[:7]}", changed))
    return min(found, key=lambda base: len(base.changed)) if found else None


# --- What covers a changed file ---------------------------------------------

PACKAGE = "src/segl"
# The folders on pytest's path (pyproject.toml): a module there is imported
# by its file name.
IMPORT_FOLDERS = ("scripts", "tools/md2html", "tests")
TEST_FOLDERS = ("tests", "tools/md2html")
PYTHON_ENV = ("pyproject.toml", "uv.lock", ".python-version")
WEB_ENV = ("web/package.json", "web/package-lock.json", "web/.node-version")
# What every change runs: each source file must carry the license header.
EVERY_CHANGE = ("tests/test_license_headers.py",)
# Started as a process (`python -m segl`), which an import does not show.
_RUNS_SEGL = re.compile(r"""["']-m["'],\s*["']segl["']|-m segl\b""")
_FILE_NAME = re.compile(r"^[\w.-]+\.\w+$")
# Standing for every file the web build writes: what reads the build.
BUILD_OUTPUT = "web/dist/index.html"
# What the browser tests run: segl and the nginx files. `segl update` is not
# part of the server.
SERVES = (PACKAGE + "/", "deploy/nginx/")
NOT_SERVED = (PACKAGE + "/update/",)
# What only the install test runs for real: what the package installs from
# deploy/, the command, and `segl update` (docs/TEST-PLAN.md T-017 and T-021).
# The dev container's recipe is not packaged.
INSTALLS = ("deploy/", PACKAGE + "/update/", PACKAGE + "/cli.py")
NOT_INSTALLED = ("deploy/Containerfile",)


def module_name(path: str) -> str | None:
    """Return the name a Python file is imported by, or None."""
    if path.startswith(PACKAGE + "/"):
        return "segl"
    pure = PurePosixPath(path)
    if pure.suffix == ".py" and str(pure.parent) in IMPORT_FOLDERS:
        return pure.stem
    return None


def is_test_file(path: str) -> bool:
    """Report whether pytest collects the file at ``path``."""
    pure = PurePosixPath(path)
    named = pure.suffix == ".py" and pure.name.startswith("test_")
    return named and str(pure.parent) in TEST_FOLDERS


@dataclass
class Module:
    """What one Python file, or the whole package, imports and names."""

    imports: set[str] = field(default_factory=set)
    paths: set[str] = field(default_factory=set)  # built as ROOT / "a" / "b", or "a/b"
    names: set[str] = field(default_factory=set)  # file names, such as "versions.toml"

    def names_file(self, path: str) -> bool:
        """Report whether this module could read the file at ``path``."""
        if PurePosixPath(path).name in self.names:
            return True
        return any(path == built or path.startswith(built + "/") for built in self.paths)


class _Mentions(ast.NodeVisitor):
    """Collects what a module imports, the paths it builds, and the file names it writes out."""

    def __init__(self, module: Module) -> None:
        self.module = module
        # What a name was set to, when that was a path: DEBIAN = DEPLOY / "debian".
        self.paths: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        self.module.imports.update(alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self.module.imports.add(node.module.split(".")[0])

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            built = self._built(node.value)
            if built is not None:
                self.paths[node.targets[0].id] = built[0]

    def _built(self, node: ast.expr) -> tuple[str, bool] | None:
        """Return the path an expression builds, and whether all of it is known."""
        if isinstance(node, ast.Name):
            return (self.paths[node.id], True) if node.id in self.paths else None
        text = _constant(node)
        if text is not None:
            return (text, True) if "/" in text else None
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            return None
        operands: list[ast.expr] = []
        left: ast.expr = node
        while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div):
            operands.insert(0, left.right)
            left = left.left
        start = _constant(left)
        if start is None and isinstance(left, ast.Name):
            start = self.paths.get(left.id)
        parts = [start] if start else []
        for operand in operands:
            text = _constant(operand)
            if text is None:
                return "/".join(parts), False
            parts.append(text)
        return "/".join(parts), True

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if not isinstance(node.op, ast.Div):
            self.generic_visit(node)
            return
        # ROOT / "deploy" / "nginx" / name: the joined constants after the
        # first operand, up to the first that is not a constant. A name set to
        # a path before starts it.
        built = self._built(node)
        assert built is not None
        # ROOT / "web" / name reads somewhere in web/, so a folder counts here.
        self._path(built[0], folder_alone=not built[1])
        operands: list[ast.expr] = []
        left: ast.expr = node
        while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div):
            operands.insert(0, left.right)
            left = left.left
        self.visit(left)
        for operand in operands:
            self.visit(operand)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            text = node.value.strip()
            if "/" in text and "\n" not in text and " " not in text:
                self._path(text, folder_alone=False)
            elif _FILE_NAME.match(text):
                self.module.names.add(text)

    def _path(self, text: str, folder_alone: bool) -> None:
        """Keep a path. A folder of the root alone, such as "tests/", is a
        label more often than a read, unless a path is built under it."""
        text = text.strip("/").removeprefix("./")
        if not text:
            return
        if "/" in text or folder_alone:
            self.module.paths.add(text)
        name = PurePosixPath(text).name
        if _FILE_NAME.match(name):
            self.module.names.add(name)


def _constant(node: ast.expr) -> str | None:
    """Return a string constant, or the one argument of Path("...")."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("Path", "PurePosixPath")
        and len(node.args) == 1
    ):
        return _constant(node.args[0])
    return None


def read_module(text: str, into: Module | None = None) -> Module:
    """Return what a Python file imports and names, added to ``into``."""
    module = into or Module()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return module
    if _RUNS_SEGL.search(text):
        module.imports.add("segl")
    _Mentions(module).visit(tree)
    return module


def tracked_files(root: Path) -> list[str]:
    """Return the files git tracks or would add, as paths from ``root``."""
    listed = _git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if listed is not None:
        return sorted(name for name in listed.splitlines() if (root / name).is_file())
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not {".git", "node_modules", ".venv"} & set(path.parts)
    )


class Graph:
    """The project's Python files, and what each test file can reach."""

    def __init__(self, root: Path, files: Sequence[str]) -> None:
        self.modules: dict[str, Module] = {}
        self.by_name: dict[str, list[str]] = {}
        for path in files:
            if not path.endswith(".py"):
                continue
            node = PACKAGE if path.startswith(PACKAGE + "/") else path
            text = (root / path).read_text(encoding="utf-8", errors="replace")
            self.modules[node] = read_module(text, self.modules.get(node))
            name = module_name(path)
            if name is not None and node not in self.by_name.setdefault(name, []):
                self.by_name[name].append(node)
        self.tests = sorted(path for path in files if is_test_file(path))
        self.reach: dict[str, tuple[set[str], set[str]]] = {
            test: self._closure(test) for test in self.tests
        }

    def _closure(self, test: str) -> tuple[set[str], set[str]]:
        """Return the files a test can reach, and every name imported on the way.

        What a conftest.py imports is not followed: it imports for many tests,
        and would tie each test to all of it. A change to a conftest.py runs
        every test of its folder (`tests_of`).
        """
        nodes = {test} if test in self.modules else set()
        names: set[str] = set()
        stack = list(nodes)
        while stack:
            for name in self.modules[stack.pop()].imports:
                names.add(name)
                for target in self.by_name.get(name, []):
                    if target not in nodes:
                        nodes.add(target)
                        stack.append(target)
        return nodes, names

    def tests_of(self, path: str) -> set[str]:
        """Return the test files that a change to ``path`` can break."""
        name = module_name(path) if path.endswith(".py") or path.startswith(PACKAGE + "/") else None
        node = PACKAGE if path.startswith(PACKAGE + "/") else path
        found = set()
        for test, (nodes, names) in self.reach.items():
            imports = node in nodes or (name is not None and name in names)
            if imports or any(self.modules[reached].names_file(path) for reached in nodes):
                found.add(test)
        if PurePosixPath(path).name == "conftest.py":
            folder = str(PurePosixPath(path).parent)
            found.update(t for t in self.tests if folder == "." or t.startswith(folder + "/"))
        return found


@dataclass
class Plan:
    """The commands that cover a set of changed files, and why."""

    commands: list[tuple[str, ...]]
    reasons: list[str]
    uncovered: list[str]


@dataclass
class _Needs:
    uv_sync: bool = False
    npm_install: bool = False
    python_checks: bool = False
    web_types: bool = False
    web_format: bool = False
    web_build: bool = False
    vitest_all: bool = False
    vitest: set[str] = field(default_factory=set)
    pytest_all: bool = False
    pytest: set[str] = field(default_factory=set)
    e2e_all: bool = False
    e2e: set[str] = field(default_factory=set)
    docs: bool = False
    install_test: bool = False


def _web_texts(root: Path, files: Sequence[str]) -> dict[str, str]:
    """Return the web tests' sources: Vitest's and the browser tests'."""
    texts = {}
    for path in files:
        typed = path.startswith(("web/src/", "web/e2e/")) and path.endswith((".ts", ".tsx"))
        if typed and (path.startswith("web/e2e/") or ".test." in path):
            texts[path] = (root / path).read_text(encoding="utf-8", errors="replace")
    return texts


def plan(
    root: Path,
    changed: Sequence[str],
    files: Sequence[str] | None = None,
    graph: Graph | None = None,
) -> Plan:
    """Return the checks that cover ``changed``, with a line of reasons for each file.

    ``files`` are the project's files, which git lists when not given, and
    ``graph`` their Python files, read from them when not given.
    """
    files = list(files) if files is not None else tracked_files(root)
    graph = graph or Graph(root, files)
    web_texts = _web_texts(root, files)
    needs = _Needs()
    reasons: list[str] = []
    uncovered: list[str] = []
    for path in sorted(set(changed)):
        what = _cover(path, graph, web_texts, needs)
        if what:
            reasons.append(f"{path}: {', '.join(what)}")
        else:
            uncovered.append(path)
    if changed:
        needs.pytest.update(test for test in EVERY_CHANGE if test in graph.tests)
    return Plan(_commands(needs, graph, has_web(root)), reasons, uncovered)


def _cover(path: str, graph: Graph, web_texts: dict[str, str], needs: _Needs) -> list[str]:
    """Add what covers one changed file to ``needs``. Return what it adds, in words."""
    what: list[str] = []
    pure = PurePosixPath(path)
    if path in PYTHON_ENV:
        needs.uv_sync = needs.python_checks = needs.pytest_all = True
        return ["the Python environment: uv sync, ruff, ty, and all of pytest"]
    if path in WEB_ENV:
        needs.npm_install = needs.web_types = needs.web_format = needs.web_build = True
        needs.vitest_all = needs.e2e_all = True
        what.append("the web environment: npm install, every web check, and the browser tests")
    if pure.suffix == ".py":
        needs.python_checks = True
        what.append("ruff and ty")
    if path.startswith("web/"):
        what += _cover_web(path, needs)
    if path.startswith(SERVES) and not path.startswith(NOT_SERVED):
        needs.e2e_all = True
        needs.web_build = True
        what.append("every browser test")
    if path.startswith(INSTALLS) and path not in NOT_INSTALLED and pure.suffix != ".md":
        needs.install_test = True
        what.append("the install test")
    if pure.suffix == ".md" or path.startswith(("tools/md2html/", "images/")):
        needs.docs = True
        what.append("the documentation site")
    # The tests that import it, start it, or name it.
    tests = graph.tests_of(path)
    if path.startswith("web/") and needs.web_build and not path.startswith("web/e2e/"):
        tests |= graph.tests_of(BUILD_OUTPUT)
    if tests:
        needs.pytest.update(tests)
        what.append(f"pytest {_count(tests, 'file')}")
    if not path.startswith("web/") and pure.name:
        # A web test that reads it names it in quotes: '../../versions.toml'.
        quoted = re.compile(r"(?<=[\"'`/])" + re.escape(pure.name) + r"(?=[\"'`])")
        named_by = sorted(test for test, text in web_texts.items() if quoted.search(text))
        specs = [test for test in named_by if test.endswith(".spec.ts")]
        helpers = [test for test in named_by if test.startswith("web/e2e/") and test not in specs]
        vitests = [test for test in named_by if test.startswith("web/src/")]
        if helpers:
            needs.e2e_all = needs.web_build = True
            what.append("every browser test, whose helpers read it")
        elif specs:
            needs.e2e.update(test.removeprefix("web/") for test in specs)
            needs.web_build = True
            what.append(f"the browser tests that read it {_count(specs, 'file')}")
        if vitests:
            needs.vitest.update(test.removeprefix("web/") for test in vitests)
            what.append(f"the Vitest tests that read it {_count(vitests, 'file')}")
    return what


def _cover_web(path: str, needs: _Needs) -> list[str]:
    """Add what covers a changed file in web/."""
    pure = PurePosixPath(path)
    typed = pure.suffix in (".ts", ".tsx")
    if typed:
        needs.web_types = True
    needs.web_format = True
    if path.startswith("web/e2e/"):
        if pure.name.endswith(".spec.ts"):
            needs.e2e.add(path.removeprefix("web/"))
            needs.web_build = True
            return ["tsc, Prettier, and this browser test"]
        needs.e2e_all = needs.web_build = True
        return ["tsc, Prettier, and every browser test"]
    if path.startswith("web/stretch/") or pure.name == "playwright.stretch.config.ts":
        return ["tsc and Prettier (the size runs are not run)"]
    if pure.name == "playwright.config.ts":
        needs.e2e_all = needs.web_build = True
        return ["tsc, Prettier, and every browser test"]
    if path.startswith("web/src/") and typed:
        needs.vitest.add(path.removeprefix("web/"))
        needs.web_build = needs.e2e_all = True
        return ["tsc, Prettier, the Vitest tests that import it, the build"]
    needs.web_build = needs.vitest_all = needs.e2e_all = True
    return ["Prettier, the build, and all of Vitest"]


def _count(items: Iterable[object], noun: str) -> str:
    total = len(list(items))
    return f"({total} {noun}{'' if total == 1 else 's'})"


def _commands(needs: _Needs, graph: Graph, web: bool) -> list[tuple[str, ...]]:
    """Return the commands for what is needed, in the suite's order."""
    commands: list[tuple[str, ...]] = []
    if needs.uv_sync:
        commands.append(PYTHON_SYNC)
    if web and needs.npm_install:
        commands.append(WEB_SYNC)
    if needs.python_checks:
        commands.extend(PYTHON_CHECKS)
    if web:
        if needs.web_types:
            commands.append(WEB_TYPES)
        if needs.vitest_all:
            commands.append(WEB_TESTS)
        elif needs.vitest:
            commands.append((*WEB_RELATED, *sorted(needs.vitest)))
        if needs.web_format:
            commands.append(WEB_FORMAT)
        if needs.web_build or needs.e2e_all or needs.e2e:
            commands.append(WEB_BUILD)
    if needs.docs:
        commands.append(DOCS)
    if needs.pytest_all or (needs.pytest and set(graph.tests) <= needs.pytest):
        commands.append(PYTHON_TESTS)
    elif needs.pytest:
        commands.append((*PYTHON_TESTS, *sorted(needs.pytest)))
    if web and needs.e2e_all:
        commands.append(WEB_E2E)
    elif web and needs.e2e:
        commands.append((*WEB_E2E, "--", *sorted(needs.e2e)))
    if needs.install_test:
        commands.append(INSTALL_TEST)
    return with_browser(commands)


# --- Running ----------------------------------------------------------------


def run_whole(runner: Runner, root: Path) -> str | None:
    """Run the whole suite, and keep the tree when it passes. Return what failed."""
    tree = work_tree(root)
    failure = run(runner, whole_suite(root))
    # A file changed while the suite ran: the pass is not that tree's.
    if failure is None and tree is not None and work_tree(root) == tree:
        record_pass(root, tree)
    return failure


def run_changed(
    runner: Runner,
    root: Path,
    *,
    base: str | None = None,
    base_name: str | None = None,
    dry_run: bool = False,
) -> str | None:
    """Run what covers the changes since a good tree. Return what failed, or None.

    ``base`` is a tree or commit taken as good, which ``base_name`` names on
    the terminal. Without it, the nearest good tree is looked for, and the
    whole suite runs when none is known.
    """
    tree = work_tree(root)
    good = known_good(root, runner, tree, base)
    if good is not None and base_name is not None:
        good = Base(good.ref, base_name, good.changed)
    if good is None:
        say("no tree is known to be good here: running the whole suite")
        return None if dry_run else run_whole(runner, root)
    files = len(good.changed)
    say(f"known good: {good.what}. Changed since: {files} file{'' if files == 1 else 's'}")
    if not good.changed:
        say("nothing to run")
        return None
    chosen = plan(root, good.changed)
    for line in chosen.reasons:
        say(f"  {line}")
    for path in chosen.uncovered:
        say(f"  {path}: nothing here covers it; CI runs everything")
    if dry_run:
        for argv in chosen.commands:
            say(f"  would run: {' '.join(argv)}")
        return None
    failure = run(runner, chosen.commands)
    # The tree is as good as the one before it, for the next run here. CI
    # still runs everything on the push.
    if failure is None and tree is not None and work_tree(root) == tree:
        record_pass(root, tree, CHANGES)
    return failure


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """Run the command and return its exit status."""
    parser = argparse.ArgumentParser(
        prog="suite.py", description="Run the suite, or only what covers what changed."
    )
    parser.add_argument("--changed", action="store_true", help="only what the changes reach")
    parser.add_argument("--base", help="the tree or commit to compare with, taken as good")
    parser.add_argument("--plan", action="store_true", help="say what would run; run nothing")
    args = parser.parse_args(argv)
    if (args.base or args.plan) and not args.changed:
        parser.error("--base and --plan go with --changed")
    runner = Runner(root)
    if args.changed:
        failure = run_changed(runner, root, base=args.base, dry_run=args.plan)
    else:
        failure = run_whole(runner, root)
    if failure is not None:
        say(f"suite: failed ({failure})")
        return 1
    say("suite: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
