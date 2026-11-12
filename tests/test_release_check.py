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

"""`check` and its gate: components, newest stable releases, and holds."""

import json
import tomllib
from pathlib import Path

import pytest
import release
import release_edits as edits
from release_components import (
    CURRENT,
    HELD,
    NEWER,
    STALE,
    UNKNOWN,
    Component,
    LookupFailed,
    Sources,
    discover,
    gate_passes,
    report,
)
from release_proc import CommandError, Result
from release_versions import at_precision, is_newer, newest_stable, parse_version, within_pin


def hold(root: Path, name: str, version: str, skipped: str) -> None:
    path = root / "versions.toml"
    text = edits.set_hold(
        path.read_text(), name, version, skipped, "tests/test_x.py::t", "2026-11-12"
    )
    path.write_text(text)


def state_of(root: Path, sources: Sources, name: str) -> str:
    (status,) = [s for s in report(root, sources) if s.component.name == name]
    return status.state


def test_prereleases_never_count_as_newest() -> None:
    versions = ["1.9.0", "2.0.0rc1", "2.0.0a1", "2.0.0.dev3", "2.0.0-beta.1", "1.10.0", "1.2"]

    assert newest_stable(versions) == "1.10.0"
    assert newest_stable(["2.0.0rc1"]) is None
    assert newest_stable(["1.0", "1.0.post1"]) == "1.0.post1"
    assert parse_version("main") is None


def test_version_order_and_reduced_precision() -> None:
    assert is_newer("1.10.0", "1.9.9")
    assert not is_newer("v1.0", "1.0.0")
    assert within_pin("v7", "v7.0.1")
    assert not within_pin("v7", "v8.0.0")
    assert at_precision("v7", "v8.1.2") == "v8"
    assert at_precision("1.2.3", "1.3.0") == "1.3.0"


def test_discover_lists_runtime_dependencies_and_actions(tree: Path) -> None:
    found = discover(tree)

    assert Component("runtime", "python", "3.15.2") in found
    assert Component("python", "good", "1.0.0", table="dependencies") in found
    assert Component("python", "markdown-it-py", "4.3.0", table="docs") in found
    assert Component("action", "actions/checkout", "v7", ref="v7") in found
    assert Component("action", "astral-sh/setup-uv", "v10.3.3", ref="a" * 40) in found
    assert not [c for c in found if c.name == "node"], "Node is listed once runtime.node is set"


def test_node_and_web_dependencies_are_listed_once_web_exists(tree: Path, fake_sources) -> None:
    path = tree / "versions.toml"
    text = edits.set_entry(path.read_text(), "runtime", "node", "24.22.1")
    path.write_text(
        text.replace("[web.dependencies]\n", '[web.dependencies]\n"@scope/pkg" = "1.0.0"\n')
    )
    sources = fake_sources(None, {"node": "24.23.0", "@scope/pkg": "1.0.0"})

    assert state_of(tree, sources, "node") == NEWER
    assert state_of(tree, sources, "@scope/pkg") == CURRENT


def test_gate_fails_for_an_unheld_newer_release(tree: Path, fake_runner, fake_sources) -> None:
    sources = fake_sources(fake_runner(tree), {"bad": "2.0.0"})

    assert state_of(tree, sources, "bad") == NEWER
    assert not gate_passes(report(tree, sources))
    assert release.cmd_check(tree, sources, gate=True) == 1
    assert release.cmd_check(tree, sources, gate=False) == 0


def test_gate_passes_for_a_held_release(tree: Path, fake_runner, fake_sources) -> None:
    hold(tree, "bad", "1.0.0", "2.0.0")
    sources = fake_sources(fake_runner(tree), {"bad": "2.0.0"})

    assert state_of(tree, sources, "bad") == HELD
    assert release.cmd_check(tree, sources, gate=True) == 0


def test_gate_fails_again_once_a_release_newer_than_the_held_one_appears(
    tree: Path, fake_runner, fake_sources, capsys: pytest.CaptureFixture[str]
) -> None:
    hold(tree, "bad", "1.0.0", "2.0.0")
    sources = fake_sources(fake_runner(tree), {"bad": "2.0.1"})

    assert state_of(tree, sources, "bad") == STALE
    assert release.cmd_check(tree, sources, gate=True) == 1
    assert (
        "python bad 1.0.0: newer 2.0.1, and the hold only covers 2.0.0" in capsys.readouterr().out
    )


def test_gate_fails_when_a_component_could_not_be_checked(tree: Path, fake_sources) -> None:
    sources = fake_sources(None, {"good": LookupFailed("timed out")})

    assert state_of(tree, sources, "good") == UNKNOWN
    assert not gate_passes(report(tree, sources))


def test_gate_passes_when_everything_is_current(tree: Path, fake_sources) -> None:
    assert gate_passes(report(tree, fake_sources(None)))


def test_action_pins(tree: Path, fake_sources) -> None:
    # A tag pin written as v7 stays current through 7.y.z and is behind at 8.
    assert (
        state_of(tree, fake_sources(None, {"actions/checkout": "v7.9.0"}), "actions/checkout")
        == CURRENT
    )
    assert (
        state_of(tree, fake_sources(None, {"actions/checkout": "v8.0.0"}), "actions/checkout")
        == NEWER
    )
    # A commit pin is compared by the version in its comment.
    sources = fake_sources(None, {"astral-sh/setup-uv": "v10.3.4"})
    assert state_of(tree, sources, "astral-sh/setup-uv") == NEWER


def test_an_action_pin_that_names_no_release_fails_the_gate(tree: Path, fake_sources) -> None:
    workflow = tree / ".github/workflows/ci.yml"
    workflow.write_text(
        f"steps:\n  - uses: a/branch@main\n  - uses: a/bare@{'c' * 40}\n  - uses: ./local\n"
    )
    statuses = {s.component.name: s for s in report(tree, fake_sources(None))}

    assert statuses["a/branch"].state == UNKNOWN
    assert "branch" in statuses["a/branch"].detail
    assert statuses["a/bare"].state == UNKNOWN
    assert "comment" in statuses["a/bare"].detail
    assert "./local" not in statuses


def test_real_sources_read_pypi_npm_node_uv_and_github(tree: Path, fake_runner) -> None:
    documents = {
        "https://pypi.org/pypi/good/json": {
            "releases": {
                "1.0.0": [{"yanked": False}],
                "1.1.0": [{"yanked": True}],
                "1.2.0": [],
                "2.0.0rc1": [{"yanked": False}],
            }
        },
        "https://registry.npmjs.org/@scope%2Fpkg/latest": {"version": "3.1.0"},
        "https://nodejs.org/dist/index.json": [
            {"version": "v25.1.0", "lts": False},
            {"version": "v24.22.1", "lts": "Krypton"},
            {"version": "v24.21.0", "lts": "Krypton"},
        ],
    }
    listing = (
        "cpython-3.16.0a1-linux-x86_64-gnu  <download available>\n"
        "cpython-3.15.3+freethreaded-linux-x86_64-gnu  <download available>\n"
        "cpython-3.15.2-linux-x86_64-gnu  /usr/bin/python3.15\n"
        "cpython-3.14.4-linux-x86_64-gnu  <download available>\n"
    )
    runner = fake_runner(
        tree,
        {
            ("uv", "python", "list"): listing,
            ("gh", "api", "repos/a/b/releases/latest"): json.dumps({"tag_name": "v2.0.0"}),
            ("gh", "api", "repos/a/b/commits/v2.0.0"): json.dumps({"sha": "d" * 40}),
            ("gh", "api", "repos/a/missing/releases/latest"): CommandError("gh: Not Found"),
        },
    )
    sources = Sources(runner, fetch=documents.__getitem__)

    assert sources.latest(Component("python", "good", "1.0.0")) == "1.0.0"
    assert sources.latest(Component("web", "@scope/pkg", "3.0.0")) == "3.1.0"
    assert sources.latest(Component("runtime", "node", "24.21.0")) == "24.22.1"
    assert sources.latest(Component("runtime", "python", "3.15.2")) == "3.15.2"
    assert sources.latest(Component("action", "a/b", "v1")) == "v2.0.0"
    assert sources.action_commit("a/b", "v2.0.0") == "d" * 40
    with pytest.raises(LookupFailed, match="Not Found"):
        sources.latest(Component("action", "a/missing", "v1"))
    with pytest.raises(LookupFailed):
        sources.latest(Component("python", "absent", "1.0.0"))


def test_hold_edits_keep_the_file_valid_and_its_comments(tree: Path) -> None:
    path = tree / "versions.toml"
    original = path.read_text()

    held = edits.set_hold(
        original, "astral-sh/setup-uv", "v1", "v2", 'said "no"\nloudly', "2026-11-12"
    )
    held = edits.set_hold(held, "bad", "1.0.0", "2.0.0", "first", "2026-11-12")
    held = edits.set_hold(held, "bad", "1.0.0", "2.0.1", "second", "2026-11-13")
    doc = tomllib.loads(held)

    assert doc["held"]["bad"] == {
        "version": "1.0.0",
        "skipped": "2.0.1",
        "reason": "second",
        "since": "2026-11-13",
    }
    assert doc["held"]["astral-sh/setup-uv"]["reason"] == 'said "no" loudly'
    assert doc["publish"]["github_repo"] == "example/segl"
    assert "# [held.example]" in held
    cleared = edits.clear_hold(edits.clear_hold(held, "bad"), "astral-sh/setup-uv")
    assert cleared == original


def test_set_entry_keeps_the_comment_and_refuses_a_missing_key(tree: Path) -> None:
    text = (tree / "versions.toml").read_text()

    assert 'python = "3.15.3"  # exact' in edits.set_entry(text, "runtime", "python", "3.15.3")
    with pytest.raises(edits.EditError):
        edits.set_entry(text, "python.dev", "good", "9")


def test_a_failed_command_names_the_program(tree: Path) -> None:
    from release_proc import Runner

    with pytest.raises(CommandError, match="command not found: segl-no-such-program"):
        Runner(tree).run(["segl-no-such-program"])
    with pytest.raises(CommandError, match="status 3"):
        Runner(tree).run(["sh", "-c", "exit 3"])
    assert Runner(tree).run(["sh", "-c", "echo out; echo err >&2"]) == Result(0, "out\n", "err\n")
