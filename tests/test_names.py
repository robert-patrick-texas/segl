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

"""Display names (S-009, docs/TEST-PLAN.md T-014): the word file, the route
that allocates the next name, the limit per client address, and the title case
of a name a person types.

The limit's last case runs through nginx with the deploy/nginx/ files, where a
client cannot choose the address segl counts. The browser's side of T-014, a
stored label kept across a reload, is ``web/e2e/names.spec.ts``. The rename
reaches other browsers in T06.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import harness
import pytest
from fastapi.testclient import TestClient
from harness import (
    BOARD_SITE,
    DISPLAY_NAMES_FILE,
    GATED,
    ROOT,
    ROOT_SITE,
    Mount,
    NginxTools,
    assert_no_secrets,
    make_settings,
)

from segl import cli
from segl.app import create_app
from segl.names import (
    ALLOCATIONS_PER_WINDOW,
    WINDOW_SECONDS,
    AllocationLimit,
    DisplayNamesError,
    load_display_names,
    parse_display_names,
    retry_after,
    title_case_name,
)
from segl.repository import Repository

ROUTE = "/api/v1/display-name"
CASES_FILE = ROOT / "tests" / "display_name_cases.json"
CASES: list[tuple[str, str | None]] = [
    (text, shown) for text, shown in json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
]


class Clock:
    """A clock the test moves."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def words_file(tmp_path: Path) -> Path:
    """The temporary word file of T-014."""
    path = tmp_path / "display-names.txt"
    path.write_text("Guest\nStaff\n", encoding="utf-8")
    return path


@pytest.fixture
def client(repository: Repository, words_file: Path) -> TestClient:
    return TestClient(create_app(make_settings(display_names=words_file), repository))


# The word file.


def test_the_packaged_list_has_at_least_100_unique_words() -> None:
    entries = [
        line
        for line in DISPLAY_NAMES_FILE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]

    assert len(entries) >= 100
    assert len(set(entries)) == len(entries)
    assert all(re.fullmatch(r"^[A-Za-z]{1,10}$", entry) for entry in entries)
    # segl reads the same entries, in the file's order.
    assert list(load_display_names(DISPLAY_NAMES_FILE)) == entries
    assert entries[:3] == ["Alpha", "Bravo", "Charlie"]


def test_the_packaged_list_is_the_default_in_a_checkout() -> None:
    assert ROOT / cli.load_settings(None).display_names == DISPLAY_NAMES_FILE


def test_comments_and_blank_lines_are_skipped_and_spelling_is_kept() -> None:
    text = "# A site's own list.\n\nGuest\n  # indented comment\nMcKinley\n\n   \nstaff\n"

    assert parse_display_names(text) == ("Guest", "McKinley", "staff")


def test_line_endings_and_spaces_around_a_word_do_not_matter() -> None:
    assert parse_display_names("Guest\r\n  Staff \r\n\r\nCrew") == ("Guest", "Staff", "Crew")


def test_a_repeated_word_is_kept() -> None:
    assert parse_display_names("Guest\nGuest\nStaff\n") == ("Guest", "Guest", "Staff")


@pytest.mark.parametrize(
    "line", ["Guest1", "two words", "Elevenchars", "naïve", "Guest,Staff", "-", "\uff21"]
)
def test_a_line_that_is_not_a_word_is_refused_with_its_line_number(line: str) -> None:
    with pytest.raises(DisplayNamesError, match=r"names\.txt, line 3: .* is not a word of 1 to 10"):
        parse_display_names(f"Guest\n# comment\n{line}\n", "names.txt")


@pytest.mark.parametrize("text", ["", "\n\n", "# only a comment\n", "   \n#\n"])
def test_a_file_without_words_is_refused(text: str) -> None:
    with pytest.raises(DisplayNamesError, match="has no words"):
        parse_display_names(text)


def test_a_missing_file_is_refused_by_name(tmp_path: Path) -> None:
    absent = tmp_path / "absent.txt"

    with pytest.raises(
        DisplayNamesError, match=re.escape(f"cannot read the display-name file {absent}")
    ):
        load_display_names(absent)


def test_a_file_that_is_not_text_is_refused(tmp_path: Path) -> None:
    binary = tmp_path / "names.txt"
    binary.write_bytes(b"Guest\n\xff\xfe\n")

    with pytest.raises(DisplayNamesError, match="cannot read the display-name file"):
        load_display_names(binary)


def test_a_byte_order_mark_is_not_part_of_the_first_word(tmp_path: Path) -> None:
    marked = tmp_path / "names.txt"
    marked.write_bytes(b"\xef\xbb\xbfGuest\r\nStaff\r\n")

    assert load_display_names(marked) == ("Guest", "Staff")


def test_the_application_does_not_start_without_words(
    repository: Repository, tmp_path: Path
) -> None:
    empty = tmp_path / "names.txt"
    empty.write_text("# nothing yet\n", encoding="utf-8")

    with pytest.raises(DisplayNamesError, match="has no words"):
        create_app(make_settings(display_names=empty), repository)
    with pytest.raises(DisplayNamesError, match="cannot read"):
        create_app(make_settings(display_names=tmp_path / "absent.txt"), repository)


@pytest.mark.parametrize(
    ("content", "message"),
    [("# nothing yet\n", "has no words"), ("Guest\nnot a word\n", "line 2: 'not a word'")],
)
def test_the_command_reports_a_word_file_it_cannot_use_and_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: str,
    message: str,
) -> None:
    names = tmp_path / "names.txt"
    names.write_text(content, encoding="utf-8")
    config = tmp_path / "segl.toml"
    config.write_text(
        f'database = "{tmp_path / "segl.sqlite"}"\ndisplay_names = "{names}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **options: pytest.fail("segl served"))

    assert cli.main(["--config", str(config)]) == 1

    error = capsys.readouterr().err
    assert error.startswith(f"segl: the display-name file {names}")
    assert message in error
    assert "Traceback" not in error


# The route.


def test_three_new_clients_get_guest1_staff2_guest3(client: TestClient) -> None:
    replies = [client.post(ROUTE) for _ in range(3)]

    assert [reply.status_code for reply in replies] == [200, 200, 200]
    assert [reply.json() for reply in replies] == [
        {"displayName": "Guest1"},
        {"displayName": "Staff2"},
        {"displayName": "Guest3"},
    ]


def test_a_name_is_never_cached_and_sets_no_cookie(client: TestClient) -> None:
    reply = client.post(ROUTE)

    assert reply.headers["cache-control"] == "no-store"
    assert reply.headers["content-type"] == "application/json"
    assert "set-cookie" not in reply.headers


def test_the_counter_survives_a_restart(tmp_path: Path, words_file: Path) -> None:
    database = tmp_path / "segl.sqlite"
    settings = make_settings(database=database, display_names=words_file)
    with Repository(database) as first:
        first.bootstrap()
        client = TestClient(create_app(settings, first))
        assert client.post(ROUTE).json() == {"displayName": "Guest1"}
        assert client.post(ROUTE).json() == {"displayName": "Staff2"}

    with Repository(database) as second:
        second.bootstrap()
        client = TestClient(create_app(settings, second))
        assert client.post(ROUTE).json() == {"displayName": "Guest3"}


def test_the_packaged_list_starts_alpha1_bravo2_charlie3(repository: Repository) -> None:
    client = TestClient(create_app(make_settings(), repository))

    assert [client.post(ROUTE).json()["displayName"] for _ in range(3)] == [
        "Alpha1",
        "Bravo2",
        "Charlie3",
    ]


def test_a_name_needs_no_pass(repository: Repository, words_file: Path) -> None:
    settings = make_settings(**GATED, display_names=words_file)
    client = TestClient(create_app(settings, repository))

    reply = client.post(ROUTE)

    assert (reply.status_code, reply.json()) == (200, {"displayName": "Guest1"})
    assert_no_secrets(reply.text)


def test_a_name_is_not_read_with_get(client: TestClient) -> None:
    reply = client.get(ROUTE)

    assert reply.status_code == 405
    assert reply.json()["error"] == "method_not_allowed"
    assert reply.headers["allow"] == "POST"
    # The refused call took no name.
    assert client.post(ROUTE).json() == {"displayName": "Guest1"}


def test_the_31st_name_in_a_minute_is_refused(client: TestClient) -> None:
    replies = [client.post(ROUTE) for _ in range(ALLOCATIONS_PER_WINDOW + 1)]

    assert [reply.status_code for reply in replies] == [200] * 30 + [429]
    assert [reply.json()["displayName"] for reply in replies[:30]] == [
        f"{('Guest', 'Staff')[n % 2]}{n + 1}" for n in range(30)
    ]
    refused = replies[-1]
    assert refused.json() == {
        "error": "rate_limited",
        "message": "Too many names were asked for from this address. Try again in a minute.",
    }
    assert 1 <= int(refused.headers["retry-after"]) <= 60
    assert "set-cookie" not in refused.headers


def test_a_refused_call_takes_no_number(repository: Repository, client: TestClient) -> None:
    for _ in range(ALLOCATIONS_PER_WINDOW + 5):
        client.post(ROUTE)

    assert repository.allocate_display_name(["Guest"]) == "Guest31"


def test_each_application_counts_on_its_own(repository: Repository, words_file: Path) -> None:
    """The count is in memory, in the application, so a restart forgets it."""
    settings = make_settings(display_names=words_file)
    first = TestClient(create_app(settings, repository))
    for _ in range(ALLOCATIONS_PER_WINDOW):
        first.post(ROUTE)
    assert first.post(ROUTE).status_code == 429

    second = TestClient(create_app(settings, repository))

    assert second.post(ROUTE).json() == {"displayName": "Guest31"}


# The limit.


def test_the_limit_is_30_a_minute() -> None:
    assert (ALLOCATIONS_PER_WINDOW, WINDOW_SECONDS) == (30, 60.0)


def test_a_client_is_admitted_30_times_in_a_window() -> None:
    clock = Clock()
    limit = AllocationLimit(clock=clock)

    assert [limit.admit("192.0.2.1") for _ in range(30)] == [0.0] * 30
    assert limit.admit("192.0.2.1") == 60.0


def test_another_address_has_its_own_count() -> None:
    limit = AllocationLimit(limit=2, clock=Clock())
    limit.admit("192.0.2.1")
    limit.admit("192.0.2.1")

    assert limit.admit("192.0.2.1") > 0
    assert limit.admit("192.0.2.2") == 0
    assert limit.admit("2001:db8::1") == 0


def test_the_window_slides_with_the_oldest_admitted_call() -> None:
    clock = Clock()
    limit = AllocationLimit(limit=2, window=60.0, clock=clock)
    limit.admit("a")
    clock.now += 20
    limit.admit("a")
    clock.now += 30

    # 50 seconds after the first call: ten more until it leaves the window.
    assert limit.admit("a") == 10.0
    clock.now += 9.5
    assert limit.admit("a") == 0.5
    clock.now += 0.5
    assert limit.admit("a") == 0
    # The call from 20 seconds in is the oldest now, and the window is full again.
    assert limit.admit("a") == 20.0


def test_refused_calls_do_not_extend_the_wait() -> None:
    clock = Clock()
    limit = AllocationLimit(limit=1, window=60.0, clock=clock)
    limit.admit("a")

    for _ in range(100):
        clock.now += 0.5
        assert limit.admit("a") > 0
    clock.now += 10

    assert limit.admit("a") == 0


def test_addresses_that_stopped_asking_are_forgotten() -> None:
    clock = Clock()
    limit = AllocationLimit(limit=2, window=60.0, clock=clock)
    for n in range(500):
        limit.admit(f"192.0.2.{n}")
    assert limit.clients() == 500

    clock.now += 30
    limit.admit("recent")
    clock.now += 30
    limit.admit("now")

    # The 500 are a window old. The one from 30 seconds ago is still counted.
    assert limit.clients() == 2
    assert limit.admit("recent") == 0
    assert limit.admit("recent") == 30.0


@pytest.mark.parametrize(
    ("seconds", "header"), [(60.0, "60"), (59.01, "60"), (0.2, "1"), (1.0, "1"), (1.5, "2")]
)
def test_retry_after_is_whole_seconds_and_never_zero(seconds: float, header: str) -> None:
    assert retry_after(seconds) == header


# A name a person types.


@pytest.mark.parametrize(("text", "shown"), CASES, ids=[repr(text)[:24] for text, _ in CASES])
def test_a_typed_name_is_title_cased(text: str, shown: str | None) -> None:
    assert title_case_name(text) == shown


def test_the_cases_cover_the_examples_in_the_manual() -> None:
    cases = dict(CASES)

    assert cases["john smith"] == "John Smith"
    assert cases["NASA"] == "Nasa"
    assert None in cases.values()


def test_title_case_is_stable() -> None:
    for _, shown in CASES:
        if shown is not None:
            assert title_case_name(shown) == shown


# Client addresses, with a real process and through nginx.


def test_a_trusted_proxy_names_the_client_the_limit_counts(tmp_path: Path) -> None:
    # The default trusts 127.0.0.1, where this request comes from, so each
    # X-Forwarded-For is a different client. nginx is what makes that safe.
    with harness.running_segl(tmp_path) as server:
        replies = [server.post(ROUTE, {"X-Forwarded-For": f"203.0.113.{n}"}) for n in range(1, 32)]

    assert [reply.status for reply in replies] == [200] * 31


def test_an_untrusted_connection_cannot_name_its_way_past_the_limit(tmp_path: Path) -> None:
    with harness.running_segl(tmp_path, "trusted_proxies = []\n") as server:
        replies = [server.post(ROUTE, {"X-Forwarded-For": f"203.0.113.{n}"}) for n in range(1, 32)]

    assert [reply.status for reply in replies] == [200] * 30 + [429]


@pytest.fixture
def mount(tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path) -> Iterator[Mount]:
    """A segl of this test's own, so its limit and its counter start fresh."""
    with harness.running_mount(tools, certificate, tmp_path) as mount:
        yield mount


def test_through_nginx_31_names_from_one_address_are_limited_at_30(mount: Mount) -> None:
    """T-014's rate-limit case: each call sends a different X-Forwarded-For."""
    replies = [
        mount.post(BOARD_SITE, f"/board{ROUTE}", {"X-Forwarded-For": f"203.0.113.{n}"})
        for n in range(1, 32)
    ]

    assert [reply.status for reply in replies] == [200] * 30 + [429]
    # Against the temporary word file: Guest1, Staff2, Guest3, and on.
    assert [reply.json()["displayName"] for reply in replies[:3]] == ["Guest1", "Staff2", "Guest3"]
    assert replies[29].json() == {"displayName": "Staff30"}
    refused = replies[30]
    assert refused.json()["error"] == "rate_limited"
    assert 1 <= int(refused.headers["Retry-After"]) <= 60
    for reply in replies:
        assert reply.headers["Set-Cookie"] is None
        assert reply.headers["Content-Type"] == "application/json"
    # nginx replaced every one of those headers with the address it saw.
    assert "203.0.113." not in mount.segl.log()

    # The same address is limited at the host root too: one segl, one count.
    assert mount.post(ROOT_SITE, ROUTE).status == 429
    # The refusals took no number. A different address, named by a proxy segl
    # trusts, gets the 31st.
    other = mount.segl.post(ROUTE, {"X-Forwarded-For": "198.51.100.7"})
    assert (other.status, other.json()) == (200, {"displayName": "Guest31"})


def test_through_nginx_a_name_is_allocated_at_a_host_root(mount: Mount) -> None:
    reply = mount.post(ROOT_SITE, ROUTE)

    assert (reply.status, reply.json()) == (200, {"displayName": "Guest1"})
    assert reply.headers["Cache-Control"] == "no-store"
    assert reply.headers["Set-Cookie"] is None
