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

"""scripts/suite.py: the suite by stage, the trees known to be good, and what covers a change."""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
import release_proc
import suite
from capacity import Machine
from release_proc import Result, Runner
from release_progress import Progress

ROOT = Path(__file__).resolve().parents[1]
# A machine with every core free, and one with none.
IDLE = Machine(cores=8, busy_cores=0.0, free_bytes=64 * 1024**3)
BUSY = Machine(cores=8, busy_cores=8.0, free_bytes=64 * 1024**3)
# How long a test waits for a thread before it calls the suite stuck.
PATIENCE = 10.0


class Scripted(Runner):
    """A runner whose commands are functions of their argv and the cancel event."""

    def __init__(self, replies: dict[str, Callable[[threading.Event | None], Result]]) -> None:
        super().__init__(Path("."))
        self.replies = replies
        self.lock = threading.Lock()
        self.events: list[str] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = True,
        capture: bool = True,
        stdin: str | None = None,
        progress: Progress | None = None,
        cancel: threading.Event | None = None,
    ) -> Result:
        label = suite.label_of(argv)
        self.note(f"start {label}")
        reply = self.replies.get(label, lambda _cancel: Result(0))
        result = reply(cancel)
        self.note(f"end {label}")
        return result

    def note(self, event: str) -> None:
        with self.lock:
            self.events.append(event)


def blocks_until(event: threading.Event, then: Result | None = None):
    """Return a reply that waits for ``event``, then passes or returns ``then``."""

    def reply(_cancel: threading.Event | None) -> Result:
        assert event.wait(PATIENCE), "never released"
        return then or Result(0)

    return reply


def until_cancelled(cancel: threading.Event | None) -> Result:
    """A command that runs until the suite stops it, as a real one is stopped."""
    assert cancel is not None
    assert cancel.wait(PATIENCE), "the suite never stopped it"
    return Result(130, "", stopped=True)


# --- The commands and their stages ------------------------------------------


def test_the_whole_suite_is_cis_checks_in_cis_order() -> None:
    assert suite.whole_suite(ROOT) == (
        suite.PYTHON_SYNC,
        suite.WEB_SYNC,
        *suite.PYTHON_CHECKS,
        suite.WEB_TYPES,
        suite.WEB_TESTS,
        suite.WEB_FORMAT,
        suite.WEB_BUILD,
        suite.PYTHON_TESTS,
        suite.WEB_E2E,
    )


def test_the_environments_come_first_and_the_long_steps_last() -> None:
    stages = {suite.label_of(argv): suite.step_of(argv).stage for argv in suite.whole_suite(ROOT)}
    assert stages == {
        "uv sync": suite.SYNC,
        "web install": suite.SYNC,
        "ruff check": suite.QUICK,
        "ruff format": suite.QUICK,
        "ty": suite.QUICK,
        "web check": suite.QUICK,
        "web test": suite.QUICK,
        "web format:check": suite.QUICK,
        "web build": suite.QUICK,
        "pytest": suite.LONG,
        "e2e": suite.LONG,
    }
    assert suite.step_of(suite.INSTALL_TEST).stage == suite.LONG
    assert suite.step_of(suite.DOCS).stage == suite.QUICK
    # Narrowed, a command keeps its name and its stage.
    assert suite.step_of((*suite.PYTHON_TESTS, "tests/test_room.py")).label == "pytest"
    assert suite.step_of((*suite.WEB_E2E, "--", "e2e/slot.spec.ts")).stage == suite.LONG
    assert suite.label_of((*suite.WEB_RELATED, "src/titles.ts")) == "web test"


def test_the_quick_checks_run_side_by_side() -> None:
    quick = [argv for argv in suite.whole_suite(ROOT) if suite.step_of(argv).stage == suite.QUICK]
    # Each check waits until all of them have started: one at a time, the
    # first would wait for ever.
    together = threading.Barrier(len(quick), timeout=PATIENCE)

    def meet(_cancel: threading.Event | None) -> Result:
        together.wait()
        return Result(0)

    runner = Scripted({suite.label_of(argv): meet for argv in quick})

    assert suite.run(runner, quick) is None


def test_a_stage_starts_when_the_one_before_it_has_ended() -> None:
    runner = Scripted({})

    assert suite.run(runner, suite.whole_suite(ROOT), look=lambda: BUSY, every=0.01) is None

    stage_of = {suite.label_of(argv): suite.step_of(argv).stage for argv in suite.whole_suite(ROOT)}
    order = [suite.SYNC, suite.QUICK, suite.LONG]
    last_end = {stage: -1 for stage in order}
    first_start = {stage: len(runner.events) for stage in order}
    for index, event in enumerate(runner.events):
        kind, label = event.split(" ", 1)
        stage = stage_of[label]
        if kind == "end":
            last_end[stage] = max(last_end[stage], index)
        else:
            first_start[stage] = min(first_start[stage], index)
    assert last_end[suite.SYNC] < first_start[suite.QUICK]
    assert last_end[suite.QUICK] < first_start[suite.LONG]


def test_the_longest_step_starts_first_and_the_next_waits_while_there_is_no_room() -> None:
    release = threading.Event()
    looks: list[Machine] = []

    def look() -> Machine:
        looks.append(BUSY)
        if len(looks) == 3:
            release.set()  # the browser tests end after three looks found no room
        return BUSY

    runner = Scripted({"e2e": blocks_until(release)})

    assert suite.run(runner, [suite.PYTHON_TESTS, suite.WEB_E2E], look=look, every=0.01) is None
    assert runner.events == ["start e2e", "end e2e", "start pytest", "end pytest"]


def test_a_long_step_starts_beside_another_once_two_looks_in_a_row_find_room(
    capsys: pytest.CaptureFixture[str],
) -> None:
    beside = threading.Event()
    answers = [IDLE, BUSY, IDLE, IDLE]
    looks: list[Machine] = []

    def look() -> Machine:
        looks.append(answers[min(len(looks), len(answers) - 1)])
        return looks[-1]

    def pytest_starts(_cancel: threading.Event | None) -> Result:
        beside.set()
        return Result(0)

    runner = Scripted({"e2e": blocks_until(beside), "pytest": pytest_starts})

    assert suite.run(runner, [suite.WEB_E2E, suite.PYTHON_TESTS], look=look, every=0.01) is None
    # Room, none, room, room: it started after the fourth look, while the
    # browser tests still ran.
    assert len(looks) == 4
    assert runner.events.index("start pytest") < runner.events.index("end e2e")
    assert "  pytest starts beside the others (0.0 of 8 cores busy" in capsys.readouterr().out


def test_a_failure_stops_the_steps_beside_it_and_names_the_failing_test(
    capsys: pytest.CaptureFixture[str],
) -> None:
    failed = Result(1, "....\nFAILED tests/test_room.py::test_join - assert 1 == 2\n1 failed\n")
    runner = Scripted({"web build": until_cancelled, "ty": lambda _cancel: failed})

    commands = [suite.TY_CHECK, suite.WEB_BUILD, suite.PYTHON_TESTS]
    assert suite.run(runner, commands, look=lambda: IDLE, every=0.01) == (
        "tests/test_room.py::test_join"
    )
    out = capsys.readouterr().out
    assert "web build: stopped" in out
    assert "ty: failed" in out
    # The stage after it does not start.
    assert "start pytest" not in runner.events


def test_of_two_failures_side_by_side_the_first_in_the_suite_is_reported() -> None:
    failed = Result(1, "error\n")
    # Prettier fails at once, and the type check only after it.
    late = threading.Event()

    def prettier(_cancel: threading.Event | None) -> Result:
        late.set()
        return failed

    def types(_cancel: threading.Event | None) -> Result:
        assert late.wait(PATIENCE)
        return failed

    runner = Scripted({"web format:check": prettier, "web check": types})

    assert suite.run(runner, [suite.WEB_TYPES, suite.WEB_FORMAT]) == (
        f"`{' '.join(suite.WEB_TYPES)}` failed"
    )


def test_ctrl_c_stops_every_running_step() -> None:
    seen: list[bool] = []

    def browser_tests(cancel: threading.Event | None) -> Result:
        result = until_cancelled(cancel)
        seen.append(True)
        return result

    def look() -> Machine:
        raise KeyboardInterrupt

    runner = Scripted({"e2e": browser_tests})

    with pytest.raises(KeyboardInterrupt):
        suite.run(runner, [suite.WEB_E2E, suite.PYTHON_TESTS], look=look, every=0.01)
    assert seen == [True], "the browser tests were told to stop and ended before it returned"


# --- The runner stops a command and what it started -------------------------

CHILD = """
import signal, subprocess, sys, time
# A grandchild that ignores Ctrl+C and has let go of the output, as a server
# that writes a log of its own: only the kill of the group at the end ends it.
leaves = sys.argv[2] == "grandchild-ignores"
if leaves:
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # the grandchild takes this with it
quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL} if leaves else {}
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **quiet)
signal.signal(signal.SIGINT, signal.default_int_handler)
if sys.argv[2] == "ignore":
    signal.signal(signal.SIGINT, signal.SIG_IGN)
with open(sys.argv[1], "w") as out:
    out.write(str(child.pid))
print("started", flush=True)
time.sleep(60)
"""


def gone(pid: int) -> bool:
    """Report whether a process has ended (a zombie counts as ended)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0]
    except FileNotFoundError, IndexError:
        return True
    return state == "Z"


@pytest.mark.parametrize(
    "mode",
    ["plain", "ignore", "grandchild-ignores"],
    ids=["stops", "is-killed", "what-it-left-is-killed"],
)
def test_a_cancelled_command_and_what_it_started_are_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(release_proc, "STOP_SECONDS", 1.0)
    monkeypatch.setattr(release_proc, "WATCH_SECONDS", 0.1)
    pid_file = tmp_path / "pid"
    cancel = threading.Event()
    lines: list[str] = []
    argv = [sys.executable, "-c", CHILD, str(pid_file), mode]
    result: list[Result] = []
    thread = threading.Thread(
        target=lambda: result.append(
            Runner(tmp_path).run(
                argv, check=False, progress=Progress(write=lines.append), cancel=cancel
            )
        ),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + PATIENCE
    while not pid_file.is_file() or not pid_file.read_text():
        assert time.monotonic() < deadline, "the command never started its child"
        time.sleep(0.05)
    grandchild = int(pid_file.read_text())

    started = time.monotonic()
    cancel.set()
    thread.join(PATIENCE)

    assert not thread.is_alive()
    assert result[0].stopped
    assert result[0].returncode != 0
    took = time.monotonic() - started
    assert took < (5 if mode == "ignore" else 3)
    deadline = time.monotonic() + PATIENCE
    while not gone(grandchild):
        assert time.monotonic() < deadline, "what the command started still runs"
        time.sleep(0.05)


def test_a_command_that_ends_on_its_own_is_not_marked_stopped(tmp_path: Path) -> None:
    result = Runner(tmp_path).run(
        [sys.executable, "-c", "raise SystemExit(3)"],
        check=False,
        progress=Progress(write=lambda _line: None),
        cancel=threading.Event(),
    )
    assert (result.returncode, result.stopped) == (3, False)


# --- Trees known to be good ---------------------------------------------------


def git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path, git_env: None) -> Path:
    """A git checkout with one commit: a module, a test, and an ignored folder."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "scripts" / "thing.py").write_text("VALUE = 1\n")
    (root / "tests" / "test_thing.py").write_text("import thing\n")
    (root / "tests" / "test_plain.py").write_text("import os\n")
    (root / ".gitignore").write_text("ignored/\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "first")
    return root


def test_the_work_tree_is_what_git_add_all_would_commit_and_the_index_is_left_alone(
    checkout: Path,
) -> None:
    assert suite.work_tree(checkout) == git(checkout, "rev-parse", "HEAD^{tree}")
    status = git(checkout, "status", "--porcelain")

    (checkout / "ignored").mkdir()
    (checkout / "ignored" / "big.bin").write_text("not part of the tree\n")
    assert suite.work_tree(checkout) == git(checkout, "rev-parse", "HEAD^{tree}")

    (checkout / "scripts" / "new.py").write_text("NEW = 2\n")
    changed = suite.work_tree(checkout)
    assert changed is not None
    assert changed != git(checkout, "rev-parse", "HEAD^{tree}")
    assert suite.changed_files(checkout, "HEAD", changed) == ("scripts/new.py",)
    # The real index still does not hold the new file.
    assert git(checkout, "diff", "--cached", "--name-only") == ""
    assert status == ""
    assert git(checkout, "status", "--porcelain") == "?? scripts/new.py"


def test_a_change_with_the_stat_data_of_the_indexed_file_is_seen(checkout: Path) -> None:
    """git trusts a file's size and times when they match its index entry.

    git looks again only at a file whose time is as new as the index, to the
    second. A change of the same size, at the time the index holds, in an
    older second, fools git itself. Under load a copy of the index gave the
    old tree now and then, when a second had passed. The work tree's hash
    trusts no stat data.
    """
    git(checkout, "config", "core.trustctime", "false")  # a file's ctime cannot be set
    thing = checkout / "scripts" / "thing.py"
    past = time.time_ns() - 5 * 10**9
    os.utime(thing, ns=(past, past))
    git(checkout, "add", "scripts/thing.py")  # the index now holds that time
    thing.write_text("VALUE = 9\n")
    os.utime(thing, ns=(past, past))
    assert git(checkout, "status", "--porcelain") == "", "git itself does not see it"

    tree = suite.work_tree(checkout)

    assert tree is not None
    assert suite.changed_files(checkout, "HEAD", tree) == ("scripts/thing.py",)


def test_outside_a_git_checkout_no_tree_is_known_good(tmp_path: Path, fake_runner) -> None:
    assert suite.work_tree(tmp_path) is None
    assert suite.known_good(tmp_path, fake_runner(tmp_path)) is None


def test_a_pass_of_the_whole_suite_is_kept_against_its_tree(checkout: Path, fake_runner) -> None:
    runner = fake_runner(checkout, {(sys.executable,): ""})

    assert suite.run_whole(runner, checkout) is None

    kept = suite.recorded_pass(checkout)
    assert kept is not None
    assert kept[0] == suite.work_tree(checkout)
    # In the git folder, so nothing in the work tree changed.
    assert git(checkout, "status", "--porcelain") == ""


def test_a_failed_run_keeps_no_pass(checkout: Path, fake_runner) -> None:
    runner = fake_runner(checkout, {("uv", "run", "pytest"): Result(1, "1 failed\n")})

    assert suite.run_whole(runner, checkout) is not None
    assert suite.recorded_pass(checkout) is None


def test_a_file_changed_while_the_suite_ran_keeps_no_pass(checkout: Path, fake_runner) -> None:
    def edits(_argv: Sequence[str]) -> Result:
        (checkout / "scripts" / "thing.py").write_text("VALUE = 2\n")
        return Result(0)

    runner = fake_runner(checkout, {("uv", "run", "pytest"): edits})

    assert suite.run_whole(runner, checkout) is None
    assert suite.recorded_pass(checkout) is None


def ci_passed_on(*commits: str) -> Result:
    return Result(0, json.dumps([{"headSha": sha} for sha in commits]))


def test_the_good_tree_nearest_the_work_tree_is_chosen(checkout: Path, fake_runner) -> None:
    first = git(checkout, "rev-parse", "HEAD")
    (checkout / "scripts" / "thing.py").write_text("VALUE = 2\n")
    git(checkout, "commit", "-q", "-am", "second")
    second = git(checkout, "rev-parse", "HEAD")
    unknown = "0" * 40
    runner = fake_runner(checkout, {("gh", "run", "list"): ci_passed_on(unknown, first)})
    # The whole suite passed here on the second commit's tree.
    suite.record_pass(checkout, git(checkout, "rev-parse", "HEAD^{tree}"))
    (checkout / "tests" / "test_other.py").write_text("import thing\n")

    good = suite.known_good(checkout, runner)

    assert good is not None
    assert good.changed == ("tests/test_other.py",)
    assert good.what.startswith("the whole suite passed here (")

    # CI passed on the second commit too: as near, and the kept pass is first.
    runner = fake_runner(checkout, {("gh", "run", "list"): ci_passed_on(second)})
    tie = suite.known_good(checkout, runner)
    assert tie is not None
    assert tie.what.startswith("the whole suite passed here")

    # Without the kept pass, CI's commit that git knows is the one.
    Path(checkout / ".git" / suite.STAMP).unlink()
    runner = fake_runner(checkout, {("gh", "run", "list"): ci_passed_on(unknown, first)})
    good = suite.known_good(checkout, runner)
    assert good is not None
    assert good.what == f"CI passed on {first[:7]}"
    assert good.changed == ("scripts/thing.py", "tests/test_other.py")


@pytest.mark.parametrize(
    "reply",
    [Result(1, "", "gh: not logged in"), Result(0, "not json"), Result(0, '{"a": 1}')],
    ids=["gh-fails", "not-json", "not-a-list"],
)
def test_without_an_answer_from_github_only_the_kept_pass_counts(
    checkout: Path, fake_runner, reply: Result
) -> None:
    runner = fake_runner(checkout, {("gh", "run", "list"): reply})
    assert suite.ci_passes(runner) == []
    assert suite.known_good(checkout, runner) is None


def test_nothing_changed_since_a_good_tree_runs_nothing(
    checkout: Path, fake_runner, capsys: pytest.CaptureFixture[str]
) -> None:
    head = git(checkout, "rev-parse", "HEAD")
    runner = fake_runner(checkout, {("gh", "run", "list"): ci_passed_on(head)})

    assert suite.run_changed(runner, checkout) is None

    assert [call[0] for call in runner.calls] == ["gh"]
    said = capsys.readouterr().out.splitlines()
    assert said == [
        f"known good: CI passed on {head[:7]}. Changed since: 0 files",
        "nothing to run",
    ]


def test_with_no_good_tree_the_whole_suite_runs(checkout: Path, fake_runner) -> None:
    runner = fake_runner(checkout)

    assert suite.run_changed(runner, checkout) is None

    assert runner.called("uv", "sync")
    assert runner.called("uv", "run", "pytest") == [["uv", "run", "pytest"]]
    assert suite.recorded_pass(checkout) is not None


def test_a_change_runs_only_what_covers_it(
    checkout: Path, fake_runner, capsys: pytest.CaptureFixture[str]
) -> None:
    head = git(checkout, "rev-parse", "HEAD")
    runner = fake_runner(checkout, {("gh", "run", "list"): ci_passed_on(head)})
    (checkout / "scripts" / "thing.py").write_text("VALUE = 2\n")

    assert suite.run_changed(runner, checkout) is None

    assert runner.called("uv", "run", "pytest") == [["uv", "run", "pytest", "tests/test_thing.py"]]
    assert not runner.called("uv", "sync")
    # Its pass is kept, and says what passed: the next run starts from it.
    kept = suite.recorded_pass(checkout)
    assert kept is not None
    assert (kept[0], kept[2]) == (suite.work_tree(checkout), suite.CHANGES)
    runner = fake_runner(checkout, {("gh", "run", "list"): ci_passed_on(head)})
    assert suite.run_changed(runner, checkout) is None
    assert not runner.called("uv")
    assert "known good: the checks of what changed passed here (" in capsys.readouterr().out


def test_a_failed_run_of_what_changed_keeps_no_pass(checkout: Path, fake_runner) -> None:
    head = git(checkout, "rev-parse", "HEAD")
    runner = fake_runner(
        checkout,
        {
            ("gh", "run", "list"): ci_passed_on(head),
            ("uv", "run", "pytest"): Result(1, "1 failed\n"),
        },
    )
    (checkout / "scripts" / "thing.py").write_text("VALUE = 2\n")

    assert suite.run_changed(runner, checkout) is not None
    assert suite.recorded_pass(checkout) is None


def test_a_base_given_is_taken_as_good(checkout: Path, fake_runner) -> None:
    (checkout / "tests" / "test_thing.py").write_text("import thing\nimport os\n")
    runner = fake_runner(checkout)

    good = suite.known_good(checkout, runner, explicit="HEAD")

    assert good is not None
    assert (good.what, good.changed) == ("HEAD (--base)", ("tests/test_thing.py",))
    assert not runner.calls, "GitHub is not asked"
    with pytest.raises(SystemExit, match="git cannot compare"):
        suite.known_good(checkout, runner, explicit="no-such-ref")


def test_the_command_says_its_plan_and_runs_nothing(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (checkout / "scripts" / "thing.py").write_text("VALUE = 3\n")

    assert suite.main(["--changed", "--plan", "--base", "HEAD"], root=checkout) == 0

    said = capsys.readouterr().out.splitlines()
    assert said[:2] == [
        "known good: HEAD (--base). Changed since: 1 file",
        "  scripts/thing.py: ruff and ty, pytest (1 file)",
    ]
    assert "  would run: uv run pytest tests/test_thing.py" in said
    assert suite.recorded_pass(checkout) is None


def test_plan_and_base_need_changed() -> None:
    with pytest.raises(SystemExit):
        suite.main(["--plan"])


# --- What covers a change: the rules, on this repository ----------------------


@functools.cache
def root_graph() -> suite.Graph:
    """This repository's Python files, read once for every test here."""
    return suite.Graph(ROOT, suite.tracked_files(ROOT))


def root_plan(*changed: str) -> suite.Plan:
    return suite.plan(ROOT, changed, graph=root_graph())


def commands_for(*changed: str) -> list[str]:
    return [" ".join(argv) for argv in root_plan(*changed).commands]


def pytest_files(commands: Sequence[str]) -> set[str]:
    """Return the test files pytest is given, or {"all"} for the whole of it."""
    prefix = " ".join(suite.PYTHON_TESTS)
    for command in commands:
        if command == prefix:
            return {"all"}
        if command.startswith(prefix + " "):
            return set(command.removeprefix(prefix + " ").split(" "))
    return set()


E2E = " ".join(suite.WEB_E2E)
INSTALL = " ".join(suite.INSTALL_TEST)
DOCS = " ".join(suite.DOCS)
BUILD = " ".join(suite.WEB_BUILD)
CASES: list[tuple[str, set[str], set[str], set[str]]] = [
    # (changed file, commands that must run, that must not, pytest files that must run)
    ("docs/DEVELOPMENT.md", {DOCS}, {E2E, INSTALL, BUILD}, {"tests/test_license_headers.py"}),
    (
        "src/segl/room.py",
        {E2E, BUILD},
        {INSTALL, DOCS},
        {"tests/test_room.py", "tests/test_mount.py"},
    ),
    ("src/segl/update/updater.py", {INSTALL}, {E2E}, {"tests/test_update_updater.py"}),
    (
        "web/src/titles.ts",
        {" ".join((*suite.WEB_RELATED, "src/titles.ts")), BUILD, E2E},
        {INSTALL},
        set(),
    ),
    ("web/e2e/slot.spec.ts", {f"{E2E} -- e2e/slot.spec.ts", BUILD}, {E2E, INSTALL}, set()),
    ("web/e2e/pages.ts", {E2E}, {INSTALL}, set()),
    ("deploy/debian/postinst", {INSTALL}, {E2E}, {"tests/test_package.py"}),
    ("deploy/nginx/segl-board.conf", {E2E, INSTALL}, set(), {"tests/test_mount.py"}),
    ("deploy/Containerfile", set(), {INSTALL, E2E}, set()),
    ("uv.lock", {"uv sync", "uv run pytest"}, {E2E}, {"all"}),
    (
        "web/package-lock.json",
        {"npm --prefix web install --no-audit --no-fund", "npm --prefix web test", E2E},
        set(),
        {"tests/test_pins.py"},
    ),
    ("scripts/capacity.py", set(), {E2E}, {"tests/test_capacity.py", "tests/test_e2e_groups.py"}),
    ("tests/conftest.py", set(), set(), {"tests/test_room.py", "tests/test_release_check.py"}),
    (
        "tests/reconcile_cases.json",
        {f"{E2E} -- e2e/reconcile.spec.ts"},
        {E2E},
        {"tests/test_reconcile.py"},
    ),
    ("versions.toml", {f"{E2E} -- e2e/slot.spec.ts"}, {E2E}, {"tests/test_versions.py"}),
    ("CHANGELOG.md", {DOCS}, {E2E}, {"tests/test_release_publish.py"}),
    (".github/workflows/ci.yml", set(), {E2E}, {"tests/test_release_check.py"}),
]


@pytest.mark.parametrize(
    ("changed", "runs", "skips", "tests"), CASES, ids=[case[0] for case in CASES]
)
def test_a_change_runs_what_covers_it(
    changed: str, runs: set[str], skips: set[str], tests: set[str]
) -> None:
    assert (ROOT / changed).is_file(), "the table names files that exist"
    commands = commands_for(changed)
    assert runs <= set(commands)
    assert not skips & set(commands)
    chosen = pytest_files(commands)
    assert "all" in chosen or tests <= chosen


def test_a_change_to_a_module_runs_the_tests_that_import_it_and_no_others() -> None:
    chosen = pytest_files(commands_for("scripts/capacity.py"))
    assert "tests/test_room.py" not in chosen
    assert "tests/test_update_updater.py" not in chosen


def test_every_change_runs_the_license_header_test() -> None:
    for changed in ("docs/DEVELOPMENT.md", "web/src/titles.ts", "LICENSE"):
        assert "tests/test_license_headers.py" in pytest_files(commands_for(changed))


def test_the_version_change_of_a_cut_runs_no_browser_test_but_the_one_that_reads_it() -> None:
    plan = root_plan("versions.toml", "pyproject.toml", "uv.lock", "CHANGELOG.md")
    commands = [" ".join(argv) for argv in plan.commands]
    assert "uv run pytest" in commands
    assert [command for command in commands if command.startswith(E2E)] == [
        f"{E2E} -- e2e/slot.spec.ts"
    ]


def test_a_file_nothing_covers_is_said() -> None:
    plan = root_plan("LICENSE")
    assert plan.uncovered == ["LICENSE"]


# --- The rules, on small trees ------------------------------------------------


def small_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "small"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def chosen_for(tmp_path: Path, files: dict[str, str], changed: str) -> set[str]:
    root = small_tree(tmp_path, files)
    return suite.Graph(root, sorted(files)).tests_of(changed)


def test_an_import_is_followed_through_a_helper(tmp_path: Path) -> None:
    files = {
        "scripts/base.py": "X = 1\n",
        "tests/helper.py": "import base\n",
        "tests/test_a.py": "import helper\n",
        "tests/test_b.py": "import os\n",
    }
    assert chosen_for(tmp_path, files, "scripts/base.py") == {"tests/test_a.py"}


def test_a_module_that_is_gone_still_finds_its_importers(tmp_path: Path) -> None:
    files = {"tests/test_a.py": "from gone import thing\n", "tests/test_b.py": "\n"}
    assert chosen_for(tmp_path, files, "scripts/gone.py") == {"tests/test_a.py"}


def test_what_a_conftest_imports_is_not_followed_but_a_change_to_it_runs_its_folder(
    tmp_path: Path,
) -> None:
    files = {
        "scripts/big.py": "\n",
        "tests/conftest.py": "import big\n",
        "tests/test_a.py": "\n",
        "tools/md2html/test_c.py": "\n",
    }
    assert chosen_for(tmp_path, files, "scripts/big.py") == set()
    assert chosen_for(tmp_path, files, "tests/conftest.py") == {"tests/test_a.py"}
    assert chosen_for(tmp_path, files, "conftest.py") == {
        "tests/test_a.py",
        "tools/md2html/test_c.py",
    }


def test_a_test_that_starts_segl_depends_on_all_of_it(tmp_path: Path) -> None:
    files = {
        "src/segl/room.py": "\n",
        "tests/harness.py": 'ARGS = [sys.executable, "-m", "segl", "--config"]\n',
        "tests/test_a.py": "import harness\n",
        "tests/test_b.py": "\n",
    }
    assert chosen_for(tmp_path, files, "src/segl/room.py") == {"tests/test_a.py"}
    assert chosen_for(tmp_path, files, "src/segl/migrations/001.sql") == {"tests/test_a.py"}


@pytest.mark.parametrize(
    ("source", "reads"),
    [
        ('PATH = ROOT / "deploy" / "nginx"\n', True),
        ('PATH = ROOT / "deploy" / name\n', True),
        ('PATH = Path("deploy/nginx/segl.conf")\n', True),
        ('NAME = "segl.conf"\n', True),
        ('PREFIX = "deploy/"\n', False),
        ('PATH = ROOT / "deploy" / "debian"\n', False),
        ('HELP = "see deploy/nginx for the files"\n', False),
    ],
    ids=["chain", "chain-to-a-name", "path-string", "file-name", "folder-label", "other", "prose"],
)
def test_a_test_that_names_a_file_runs_when_it_changes(
    tmp_path: Path, source: str, reads: bool
) -> None:
    files = {"tests/test_a.py": source}
    chosen = chosen_for(tmp_path, files, "deploy/nginx/segl.conf")
    assert chosen == ({"tests/test_a.py"} if reads else set())


def test_a_browser_test_that_reads_a_file_runs_alone_and_a_helper_runs_them_all(
    tmp_path: Path,
) -> None:
    files = {
        "web/package.json": "{}",
        "web/e2e/a.spec.ts": "readFileSync(new URL('../../tests/cases.json', import.meta.url))",
        "web/e2e/b.spec.ts": "// LICENSE-2.0 and cases.jsonx are not it",
        "web/e2e/pages.ts": "const NAMES = '../../deploy/names.txt';",
        "tests/cases.json": "[]",
        "deploy/names.txt": "Guest\n",
    }
    root = small_tree(tmp_path, files)
    spec = suite.plan(root, ["tests/cases.json"], sorted(files)).commands
    assert (*suite.WEB_E2E, "--", "e2e/a.spec.ts") in spec
    helper = suite.plan(root, ["deploy/names.txt"], sorted(files)).commands
    assert suite.WEB_E2E in helper


def test_the_tests_of_a_change_under_every_rule_exist() -> None:
    """Every test file the rules can name is one pytest collects."""
    graph = root_graph()
    for test in graph.tests:
        assert suite.is_test_file(test)
        assert (ROOT / test).is_file()
    assert "tests/test_suite.py" in graph.tests
