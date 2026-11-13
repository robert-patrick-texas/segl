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

"""scripts/e2e.py: the browser tests in several groups at once.

The groups here are small stand-ins for `playwright test`. The real thing
runs in CI, in the dev container, and from scripts/testplan.py.
"""

import json
import re
import socket
import sys
from collections.abc import Sequence
from pathlib import Path

import e2e
import pytest

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "web" / "e2e" / "sites.ts"

# What a group does in these tests: say its port base and its place among
# the groups, write a report with one passed test, or fail when told to.
STAND_IN = """
import json, os, sys
index, groups, fail = sys.argv[1:4]
print("port base", os.environ["SEGL_E2E_PORT"], "group", index, "of", groups)
print("arguments", sys.argv[4:])
suite = {"title": f"group-{index}.spec.ts", "specs": []}
stats = {"expected": int(index), "unexpected": int(fail == index), "skipped": 0, "flaky": 0,
         "duration": 1000.0 * int(index), "startTime": f"2026-11-13T00:00:0{index}.000Z"}
with open(os.environ["PLAYWRIGHT_JSON_OUTPUT_FILE"], "w") as report:
    json.dump({"suites": [suite], "errors": [], "stats": stats}, report)
sys.exit(1 if fail == index else 0)
"""


@pytest.fixture
def stand_in(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """Put the stand-in where `playwright test` goes. Set `fail` to a group's number."""
    options = {"fail": "0"}

    def command(index: int, groups: int, extra: Sequence[str]) -> list[str]:
        return [sys.executable, "-c", STAND_IN, str(index), str(groups), options["fail"], *extra]

    monkeypatch.setattr(e2e, "group_command", command)
    monkeypatch.setattr(e2e, "WEB", tmp_path)
    monkeypatch.delenv("SEGL_E2E_PORT", raising=False)
    monkeypatch.setattr(e2e, "FIRST_PORT", free_port_base())
    return options


def free_port_base() -> int:
    """Return a port with nothing listening on it or on the thirty after it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1] - 40


def test_each_group_has_ports_of_its_own() -> None:
    assert e2e.port_bases(1, 18950) == [18950]
    assert e2e.port_bases(3, 18950) == [18950, 18960, 18970]
    # A group's servers take their ports from its base, and no group reaches the next.
    offsets = [int(n) for n in re.findall(r"PORT \+ (\d+)", SITES.read_text(encoding="utf-8"))]
    assert max(offsets) + 1 == e2e.PORTS_A_GROUP
    assert e2e.PORTS_A_GROUP <= e2e.PORT_STEP
    assert "process.env['SEGL_E2E_PORT'] ?? 18950" in SITES.read_text(encoding="utf-8")
    assert e2e.FIRST_PORT == 18950


def test_one_group_is_a_plain_run_and_several_are_shards() -> None:
    assert e2e.group_command(1, 1, []) == [
        "npx",
        "playwright",
        "test",
        "--reporter=list,json",
        "--output=test-results/group-1",
    ]
    assert e2e.group_command(2, 3, ["--project", "board"]) == [
        "npx",
        "playwright",
        "test",
        "--reporter=list,json",
        "--output=test-results/group-2",
        "--shard=2/3",
        "--project",
        "board",
    ]


def test_a_port_in_use_is_found() -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]

        assert e2e.busy_ports([port - 3]) == [port]
    assert e2e.busy_ports([port - 3]) == []


def test_the_reports_of_the_groups_become_one() -> None:
    one = {
        "suites": [{"title": "a.spec.ts"}],
        "errors": [],
        "stats": {
            "expected": 80,
            "unexpected": 1,
            "duration": 200.0,
            "startTime": "2026-11-13T10:00:01Z",
        },
    }
    two = {
        "suites": [{"title": "b.spec.ts"}, {"title": "c.spec.ts"}],
        "errors": [{"message": "x"}],
        "stats": {
            "expected": 70,
            "unexpected": 0,
            "duration": 250.0,
            "startTime": "2026-11-13T10:00:00Z",
        },
    }

    merged = e2e.merge_reports([one, two])

    assert [suite["title"] for suite in merged["suites"]] == ["a.spec.ts", "b.spec.ts", "c.spec.ts"]
    assert merged["errors"] == [{"message": "x"}]
    # Counts add up. The groups ran side by side, so the time is the longest one's.
    assert merged["stats"] == {
        "expected": 150,
        "unexpected": 1,
        "duration": 250.0,
        "startTime": "2026-11-13T10:00:00Z",
    }
    assert e2e.merge_reports([]) == {"suites": [], "errors": [], "stats": {}}


def test_the_groups_run_side_by_side_each_on_its_ports(
    stand_in: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SEGL_TEST_GROUPS", "3")
    report = tmp_path / "all.json"
    base = e2e.FIRST_PORT

    assert e2e.main(["--report", str(report)]) == 0

    out = capfd.readouterr().out
    assert "capacity: 3 group(s), set by SEGL_TEST_GROUPS" in out
    # Each group's lines carry its number.
    for index in (1, 2, 3):
        assert f"[{index}] port base {base + 10 * (index - 1)} group {index} of 3\n" in out
    assert re.search(r"e2e: 3 group\(s\) in \d+\.\d minutes: 6 passed, 0 failed", out)
    merged = json.loads(report.read_text())
    assert sorted(suite["title"] for suite in merged["suites"]) == [
        "group-1.spec.ts",
        "group-2.spec.ts",
        "group-3.spec.ts",
    ]
    assert merged["stats"]["expected"] == 6


def test_one_group_that_fails_fails_the_run_and_the_others_still_finish(
    stand_in: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SEGL_TEST_GROUPS", "3")
    stand_in["fail"] = "2"
    report = tmp_path / "all.json"

    assert e2e.main(["--report", str(report)]) == 1

    out = capfd.readouterr().out
    assert "e2e: group(s) 2 failed" in out
    assert "1 failed" in out
    assert len(json.loads(report.read_text())["suites"]) == 3


def test_one_group_runs_without_a_label_and_passes_its_arguments_on(
    stand_in: dict[str, str], monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SEGL_TEST_GROUPS", "1")
    monkeypatch.setenv("SEGL_E2E_PORT", str(e2e.FIRST_PORT + 100))

    assert e2e.main(["--", "--project", "board"]) == 0

    out = capfd.readouterr().out
    assert f"\nport base {e2e.FIRST_PORT + 100} group 1 of 1\n" in out
    assert "\narguments ['--project', 'board']\n" in out
    assert "[1]" not in out


def test_a_run_does_not_start_beside_another_on_the_same_ports(
    stand_in: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEGL_TEST_GROUPS", "2")
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", e2e.FIRST_PORT + 10))
        taken.listen()

        with pytest.raises(SystemExit, match=f"already listens on port {e2e.FIRST_PORT + 10}"):
            e2e.main([])


def test_a_group_that_leaves_no_report_leaves_none_for_the_reader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SEGL_TEST_GROUPS", "2")
    monkeypatch.setattr(e2e, "WEB", tmp_path)
    monkeypatch.setattr(e2e, "FIRST_PORT", free_port_base())
    monkeypatch.setattr(
        e2e, "group_command", lambda *_: [sys.executable, "-c", "raise SystemExit(3)"]
    )
    report = tmp_path / "all.json"

    assert e2e.main(["--report", str(report)]) == 1
    assert not report.exists()
