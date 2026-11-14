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

"""``segl config merge``: a new version's statements go into a site's files.

diff3 runs for real. nginx and systemctl are played by the runner. The
install test runs the same command against a real nginx
(``deploy/debian/systemd-test.sh``).
"""

import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from update_helpers import Reply, ScriptedRunner, install_nginx_files, make_paths

from segl.update import backup
from segl.update.merge import Merge
from segl.update.paths import Paths
from segl.update.process import NOT_FOUND, RunResult

PROXY = "segl-proxy.conf"
BOARD = "segl-board.conf"
# What a later release adds to its segl-proxy.conf, and where.
ADDED = "proxy_next_upstream_tries 2;\n"
AFTER = "proxy_connect_timeout 5s;\n"
# What a site changes in its own copy, on another line.
SITE_OLD, SITE_NEW = "client_max_body_size 52m;", "client_max_body_size 60m;"
NOT_ACTIVE: dict[tuple[str, ...], Reply] = {("systemctl", "is-active"): 3}


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return make_paths(tmp_path)


class Run:
    """One installation, and what its merges said."""

    def __init__(self, paths: Paths, runner: ScriptedRunner | None = None) -> None:
        self.paths = paths
        self.runner = runner or ScriptedRunner()
        self.said: list[str] = []
        self.clock = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)

    def merge(self, write: bool = True) -> int:
        self.clock += timedelta(seconds=1)
        merge = Merge(self.paths, self.runner, self.said.append, lambda: self.clock)
        return merge.apply(write)

    def text(self) -> str:
        return "\n".join(self.said)

    def site(self, name: str) -> Path:
        return next(site for known, _, site in self.paths.nginx_pairs() if known == name)

    def shipped(self, name: str) -> Path:
        return self.paths.share / "nginx" / name

    def release(self, name: str = PROXY, old: str = AFTER, new: str = AFTER + ADDED) -> None:
        """A later release of the package changes one of its nginx files."""
        path = self.shipped(name)
        text = path.read_text(encoding="utf-8")
        assert text.count(old) == 1
        path.write_text(text.replace(old, new), encoding="utf-8")

    def edit_site(self, name: str = PROXY, old: str = SITE_OLD, new: str = SITE_NEW) -> None:
        path = self.site(name)
        text = path.read_text(encoding="utf-8")
        assert text.count(old) == 1
        path.write_text(text.replace(old, new), encoding="utf-8")


@pytest.fixture
def installed(paths: Paths) -> Run:
    """A site that installed the nginx files, and whose first merge has run."""
    run = Run(paths)
    install_nginx_files(paths)
    assert run.merge() == 0
    run.said.clear()
    run.runner.calls.clear()
    return run


def test_a_first_install_changes_nothing_and_records_the_packages_files(paths: Paths) -> None:
    run = Run(paths)
    before = paths.config_file.read_bytes()

    assert run.merge() == 0

    assert run.said == []
    assert paths.config_file.read_bytes() == before
    assert sorted(path.name for path in paths.merged.iterdir()) == sorted(
        name for name, _, _ in paths.nginx_pairs()
    )
    for name, shipped, site in paths.nginx_pairs():
        assert (paths.merged / name).read_bytes() == shipped.read_bytes()
        assert not site.exists()
    assert run.runner.called("nginx") == []
    assert not paths.backups.exists()


def test_nothing_happens_when_the_release_changed_no_nginx_file(installed: Run) -> None:
    installed.edit_site()
    before = installed.site(PROXY).read_bytes()

    assert installed.merge() == 0

    assert installed.said == []
    assert installed.site(PROXY).read_bytes() == before
    assert installed.runner.calls == []


def test_a_file_the_site_did_not_edit_becomes_the_new_releases_file(installed: Run) -> None:
    old = installed.site(PROXY).read_bytes()
    installed.release()

    assert installed.merge() == 0

    assert installed.site(PROXY).read_bytes() == installed.shipped(PROXY).read_bytes()
    assert ADDED in installed.site(PROXY).read_text(encoding="utf-8")
    assert "merged this version's segl-proxy.conf" in installed.text()
    # The file as it was is kept, at a path that says what it is.
    kept = backup.list_backups(installed.paths.backups, backup.MERGE)
    assert len(kept) == 1
    assert (kept[0] / "nginx/snippets" / PROXY).read_bytes() == old
    # diff3 was not needed.
    assert installed.runner.called("diff3") == []


def test_nginx_is_tested_and_then_reloaded(installed: Run) -> None:
    installed.release()

    assert installed.merge() == 0

    calls = [call for call in installed.runner.calls if call[0] in ("nginx", "systemctl")]
    assert calls == [
        ["nginx", "-v"],
        ["nginx", "-t"],
        ["systemctl", "is-active", "--quiet", "nginx.service"],
        ["systemctl", "reload", "nginx.service"],
    ]
    assert "nginx -t passed, and nginx was reloaded" in installed.text()


def test_the_sites_edit_and_the_releases_statement_are_both_kept(installed: Run) -> None:
    installed.edit_site()
    installed.release()

    assert installed.merge() == 0

    merged = installed.site(PROXY).read_text(encoding="utf-8")
    assert SITE_NEW in merged and SITE_OLD not in merged
    assert AFTER + ADDED in merged
    # Nothing else moved: taking both changes out gives the file as it shipped.
    original = merged.replace(SITE_NEW, SITE_OLD).replace(ADDED, "")
    assert original == (installed.shipped(PROXY).read_text(encoding="utf-8").replace(ADDED, ""))
    assert len(installed.runner.called("diff3")) == 1


def test_a_change_the_site_already_made_the_same_way_is_no_conflict(installed: Run) -> None:
    # The site read the release notes and added the statement by hand, and
    # has an edit of its own on another line.
    installed.edit_site()
    installed.edit_site(old=AFTER, new=AFTER + ADDED)
    before = installed.site(PROXY).read_bytes()
    installed.release()

    assert installed.merge() == 0

    assert installed.site(PROXY).read_bytes() == before
    assert before.count(ADDED.encode()) == 1
    # Nothing was written, so nginx was neither tested nor reloaded.
    assert installed.said == []
    assert installed.runner.called("nginx") == []
    assert not installed.paths.backups.exists()
    # And the record moved on: the next release merges from this one.
    assert (installed.paths.merged / PROXY).read_bytes() == installed.shipped(PROXY).read_bytes()


def test_a_merged_file_keeps_its_mode(installed: Run) -> None:
    installed.site(PROXY).chmod(0o600)
    installed.edit_site()
    installed.release()

    assert installed.merge() == 0

    assert installed.site(PROXY).stat().st_mode & 0o7777 == 0o600


def test_a_second_merge_changes_nothing(installed: Run) -> None:
    installed.edit_site()
    installed.release()
    assert installed.merge() == 0
    after = installed.site(PROXY).read_bytes()
    installed.said.clear()
    installed.runner.calls.clear()

    assert installed.merge() == 0

    assert installed.said == []
    assert installed.site(PROXY).read_bytes() == after
    assert installed.runner.called("nginx", "-t") == []
    assert len(backup.list_backups(installed.paths.backups, backup.MERGE)) == 1


def test_two_releases_in_a_row_both_merge(installed: Run) -> None:
    installed.edit_site()
    installed.release()
    assert installed.merge() == 0
    installed.release(
        old="proxy_redirect     off;\n", new="proxy_redirect     off;\nproxy_buffering on;\n"
    )

    assert installed.merge() == 0

    merged = installed.site(PROXY).read_text(encoding="utf-8")
    assert SITE_NEW in merged and ADDED in merged and "proxy_buffering on;\n" in merged


def test_the_same_line_changed_on_both_sides_is_a_conflict(installed: Run) -> None:
    installed.edit_site()
    installed.release(old=SITE_OLD, new="client_max_body_size 64m;")
    before = installed.site(PROXY).read_bytes()
    record = (installed.paths.merged / PROXY).read_bytes()

    assert installed.merge() == 1

    assert installed.site(PROXY).read_bytes() == before
    assert "the site and this version changed the same lines of segl-proxy.conf" in installed.text()
    assert str(installed.shipped(PROXY)) in installed.text()
    # No conflict markers anywhere, no test, no reload, and no new record:
    # the next merge still starts from the version the site's file came from.
    assert b"<<<<<<<" not in before
    assert installed.runner.called("nginx", "-t") == []
    assert installed.runner.called("systemctl", "reload") == []
    assert (installed.paths.merged / PROXY).read_bytes() == record
    installed.said.clear()
    assert installed.merge() == 1


def test_a_conflict_in_one_file_leaves_the_others_as_they_are_too(installed: Run) -> None:
    installed.edit_site()
    installed.release(old=SITE_OLD, new="client_max_body_size 64m;")
    installed.release(BOARD, old="    return 301 /board/;\n", new="    return 308 /board/;\n")
    board = installed.site(BOARD).read_bytes()

    assert installed.merge() == 1

    assert installed.site(BOARD).read_bytes() == board
    assert f"{installed.site(BOARD)} is left as it is too" in installed.text()


def test_a_failed_nginx_test_puts_every_file_back(paths: Paths) -> None:
    said = "nginx: [emerg] unknown directive in /etc/nginx/snippets/segl-proxy.conf:36"
    runner = ScriptedRunner({("nginx", "-t"): RunResult(1, said + "\nnginx: test failed\n")})
    run = Run(paths, runner)
    install_nginx_files(paths)
    assert run.merge() == 0
    run.edit_site()
    run.release()
    run.release(BOARD, old="    return 301 /board/;\n", new="    return 308 /board/;\n")
    before = {name: run.site(name).read_bytes() for name in (PROXY, BOARD)}
    record = (paths.merged / PROXY).read_bytes()

    assert run.merge() == 1

    assert {name: run.site(name).read_bytes() for name in (PROXY, BOARD)} == before
    assert "nginx -t failed with the merged files, so they are as they were" in run.text()
    assert "unknown directive" in run.text()
    assert runner.called("systemctl", "reload") == []
    assert (paths.merged / PROXY).read_bytes() == record


def test_nginx_that_is_not_running_is_not_reloaded(paths: Paths) -> None:
    run = Run(paths, ScriptedRunner(NOT_ACTIVE))
    install_nginx_files(paths)
    assert run.merge() == 0
    run.release()

    assert run.merge() == 0

    assert ADDED in run.site(PROXY).read_text(encoding="utf-8")
    assert run.runner.called("systemctl", "reload") == []
    assert "nginx is not running, so it was not reloaded" in run.text()


def test_a_reload_that_fails_is_a_failure(paths: Paths) -> None:
    run = Run(paths, ScriptedRunner({("systemctl", "reload"): RunResult(1, "Job failed.")}))
    install_nginx_files(paths)
    assert run.merge() == 0
    run.release()

    assert run.merge() == 1

    assert "nginx did not reload: Job failed." in run.text()


def test_without_nginx_on_the_host_its_files_are_left_alone(paths: Paths) -> None:
    run = Run(paths, ScriptedRunner({("nginx",): RunResult(NOT_FOUND, "nginx: not found")}))
    install_nginx_files(paths)
    assert run.merge() == 0
    run.release()
    before = run.site(PROXY).read_bytes()

    assert run.merge() == 0

    assert run.site(PROXY).read_bytes() == before
    assert "nginx is not installed here" in run.text()


def test_a_site_file_with_no_record_is_left_alone_and_merged_from_then_on(paths: Paths) -> None:
    run = Run(paths)
    install_nginx_files(paths)
    run.edit_site()
    before = run.site(PROXY).read_bytes()

    assert run.merge() == 0

    assert run.site(PROXY).read_bytes() == before
    assert "there is no record of the version it came from" in run.text()
    run.said.clear()
    # Said once. And the next release merges into it.
    assert run.merge() == 0
    assert run.said == []
    run.release()
    assert run.merge() == 0
    merged = run.site(PROXY).read_text(encoding="utf-8")
    assert SITE_NEW in merged and ADDED in merged


def test_a_site_file_that_is_not_utf8_is_a_conflict(installed: Run) -> None:
    installed.site(PROXY).write_bytes(installed.site(PROXY).read_bytes() + b"# caf\xe9\n")
    installed.release()

    assert installed.merge() == 1

    assert "it is not UTF-8 text" in installed.text()


def test_without_write_it_says_what_it_would_do_and_changes_nothing(installed: Run) -> None:
    installed.edit_site()
    installed.release()
    paths = installed.paths
    paths.config_file.write_text(
        'access_secret = "a-secret-that-is-long-enough-0123456789"\nbind = "127.0.0.1:8888"\n',
        encoding="utf-8",
    )
    before = {
        path: path.read_bytes()
        for path in (paths.config_file, installed.site(PROXY), paths.merged / PROXY)
    }

    assert installed.merge(write=False) == 0

    assert {path: path.read_bytes() for path in before} == before
    assert not paths.backups.exists()
    said = installed.text()
    assert "would add trusted_proxies, internal_networks, access_codes" in said
    assert '  + update_proxy = ""' in said
    assert f"would merge this version's segl-proxy.conf into {installed.site(PROXY)}" in said
    assert "  +proxy_next_upstream_tries 2;" in said
    # Only lines of the example are shown: nothing the site wrote in its settings.
    assert "a-secret-that-is-long-enough" not in said
    assert installed.runner.called("nginx", "-t") == []
    assert installed.runner.called("systemctl") == []


def test_without_write_a_conflict_still_ends_with_status_1(installed: Run) -> None:
    installed.edit_site()
    installed.release(old=SITE_OLD, new="client_max_body_size 64m;")

    assert installed.merge(write=False) == 1


def test_the_settings_get_the_new_keys_and_keep_their_mode(paths: Paths) -> None:
    site = (
        "# Ours.\n"
        'access_codes = ["maple river 42"]\n'
        'access_secret = "a-secret-that-is-long-enough-0123456789"\n'
    )
    paths.config_file.write_text(site, encoding="utf-8")
    paths.config_file.chmod(0o640)
    run = Run(paths)

    assert run.merge() == 0

    merged = paths.config_file.read_text(encoding="utf-8")
    assert merged.startswith(site) or all(line in merged for line in site.splitlines())
    assert tomllib.loads(merged) == {
        **tomllib.loads(paths.example.read_text(encoding="utf-8")),
        **tomllib.loads(site),
    }
    assert paths.config_file.stat().st_mode & 0o7777 == 0o640
    assert "added bind, trusted_proxies" in run.text()
    # The message names keys, and never a value.
    assert "maple" not in run.text() and "a-secret" not in run.text()
    kept = backup.list_backups(paths.backups, backup.MERGE)
    assert (kept[0] / "etc/segl.toml").read_text(encoding="utf-8") == site
    assert kept[0].stat().st_mode & 0o7777 == 0o700


def test_settings_that_are_not_toml_are_left_alone(paths: Paths) -> None:
    paths.config_file.write_text('bind = "unclosed\n', encoding="utf-8")
    run = Run(paths)

    assert run.merge() == 1

    assert paths.config_file.read_text(encoding="utf-8") == 'bind = "unclosed\n'
    assert "is not valid TOML" in run.text()
    assert not paths.backups.exists()


def test_the_settings_merge_even_when_an_nginx_file_conflicts(installed: Run) -> None:
    paths = installed.paths
    paths.config_file.write_text('bind = "127.0.0.1:8888"\n', encoding="utf-8")
    installed.edit_site()
    installed.release(old=SITE_OLD, new="client_max_body_size 64m;")

    assert installed.merge() == 1

    assert "update_url" in tomllib.loads(paths.config_file.read_text(encoding="utf-8"))


def test_without_a_settings_file_there_is_nothing_to_merge(paths: Paths) -> None:
    paths.config_file.unlink()
    run = Run(paths)

    assert run.merge() == 0

    assert not paths.config_file.exists()


def test_only_the_newest_three_copies_are_kept(installed: Run) -> None:
    for number in range(5):
        installed.release(old=AFTER, new=AFTER + f"# release {number}\n")
        assert installed.merge() == 0

    kept = backup.list_backups(installed.paths.backups, backup.MERGE)
    assert len(kept) == backup.KEPT == 3
    assert "# release 3" in (kept[0] / "nginx/snippets" / PROXY).read_text(encoding="utf-8")
