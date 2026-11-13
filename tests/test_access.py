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

"""Access codes and passes (S-008, D2-033; docs/TEST-PLAN.md T-008 and T-019).

A code and its normal form, the pass a code buys and each reason to refuse
one, the count of wrong codes, the route, and every gate a pass opens: with a
clock the test moves, in process, from a real ``python -m segl --config``
process with the codes in its TOML, and through nginx.
"""

import json
import logging
import re
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from harness import (
    ACCESS_CODE,
    ACCESS_SECRET,
    BOARD_SITE,
    GATED,
    GATED_TOML,
    PASS_HEADER,
    ROOT,
    ROOT_SITE,
    NginxTools,
    assert_no_secrets,
    issue_pass,
    make_settings,
    next_message,
    running_mount,
    running_segl,
    say_hello,
)
from test_collab import element, hello, received

from segl.access import (
    LOCK_SECONDS,
    PASS_AHEAD_SECONDS,
    WRONG_CODES,
    Access,
    Admission,
    CodeLimit,
    letters_and_digits,
    normalize,
)
from segl.app import create_app
from segl.repository import Repository
from segl.room import Connection, Hello, Room

ROUTE = "/api/v1/access"
CODE = normalize(ACCESS_CODE)
OTHER = "night.shift.1836"
HOUR = 3600.0
# What a request header carries whole (docs/SECURITY.md): printable ASCII,
# with no space at either end. web/src/pass.ts takes nothing else from a
# browser's storage, and tests/header_value_cases.json holds both to one table.
HEADER_VALUE = re.compile(r"[\x21-\x7e](?:[\x20-\x7e]{0,254}[\x21-\x7e])?")
HEADER_CASES: list[tuple[str, bool]] = [
    (text, sendable)
    for text, sendable in json.loads(
        (ROOT / "tests" / "header_value_cases.json").read_text(encoding="utf-8")
    )["cases"]
]
PASS_SHAPE = re.compile(r"[0-9]{10}\.[A-Za-z0-9_-]{24}")


class Clock:
    """A clock the test moves."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def access(clock: Clock, *codes: str, **more: Any) -> Access:
    more.setdefault("pass_seconds", 12 * HOUR)
    return Access(codes or (CODE,), ACCESS_SECRET, clock=clock, **more)


# A code and its normal form.


@pytest.mark.parametrize(
    ("typed", "compared"),
    [
        ("Maple River 42", "maple.river.42"),
        ("maple.river.42", "maple.river.42"),
        ("  MAPLE   RIVER\t42\n", "maple.river.42"),
        ("maple-river_42", "maple.river.42"),
        ("...maple//river!!42??", "maple.river.42"),
        ("mapleriver42", "mapleriver42"),
        ("Maple River 4 2", "maple.river.4.2"),
        ("", ""),
        (" - ", ""),
        # A letter outside ASCII parts two words. It is never a letter of a code.
        ("lykilor\u00f0 1234", "lykilor.1234"),
        ("maple\u00a0river", "maple.river"),
    ],
)
def test_a_code_is_compared_in_its_normal_form(typed: str, compared: str) -> None:
    assert normalize(typed) == compared
    # The normal form of a normal form is itself.
    assert normalize(compared) == compared


def test_the_length_of_a_code_is_its_letters_and_digits() -> None:
    assert letters_and_digits("maple.river.42") == 12
    assert letters_and_digits("a.b.c") == 3
    assert letters_and_digits("") == 0


@pytest.mark.parametrize(
    "typed", ["Maple River 42", "maple.river.42", "MAPLE-RIVER-42", "  maple  river  42  "]
)
def test_a_typed_code_is_found_whatever_its_case_and_separators(typed: str) -> None:
    assert access(Clock(), CODE, OTHER).code(typed) == CODE


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "maple river",
        "maple river 43",
        "mapleriver42",
        "maple river 42 x",
        "x maple river 42",
        "maple.river.42.night.shift.1836",
        ACCESS_SECRET,
    ],
)
def test_any_other_text_is_no_code(typed: str) -> None:
    assert access(Clock(), CODE, OTHER).code(typed) is None


def test_each_code_of_the_list_is_found_as_itself() -> None:
    codes = access(Clock(), CODE, OTHER)

    assert codes.code("Night Shift 1836") == OTHER
    assert codes.code("Maple River 42") == CODE
    assert codes.required


def test_without_codes_no_text_is_one_and_everyone_edits() -> None:
    nobody = Access((), "")

    assert not nobody.required
    assert nobody.code("") is None
    assert nobody.code("anything") is None
    for sent in (None, "", "anything", issue_pass()):
        assert nobody.admit(sent) == Admission(may_edit=True, until=None)


# The pass.


def test_a_pass_is_the_time_of_issue_and_a_signature() -> None:
    clock = Clock(1_800_000_000.75)
    issued, until = access(clock).issue(CODE)

    stamp, _, signature = issued.partition(".")
    assert stamp == "1800000000"
    assert PASS_SHAPE.fullmatch(issued)
    assert len(signature) == 24
    assert until == 1_800_000_000 + 12 * HOUR
    # What a page can send in a header, and far under its 256 characters.
    assert HEADER_VALUE.fullmatch(issued)
    assert len(issued) == 35
    # Nothing of the code or the secret is in it.
    assert_no_secrets(issued)


@pytest.mark.parametrize(("text", "sendable"), HEADER_CASES)
def test_the_rule_for_a_header_is_the_pages_rule(text: str, sendable: bool) -> None:
    # The same table as web/src/pass.test.ts, so "sendable" means one thing.
    assert (HEADER_VALUE.fullmatch(text) is not None) is sendable


def test_every_pass_is_one_a_page_can_send() -> None:
    assert sum(sendable for _, sendable in HEADER_CASES) >= 5
    assert sum(not sendable for _, sendable in HEADER_CASES) >= 5
    for at in (0.0, 1.0, 999_999_999.0, 1_800_000_000.0, 99_999_999_999.0):
        for code in (CODE, OTHER, "x" * 256):
            issued, _ = Access((code,), ACCESS_SECRET, clock=lambda at=at: at).issue(code)
            assert HEADER_VALUE.fullmatch(issued), issued
            assert len(issued) <= 36


def test_a_pass_is_taken_until_it_ends() -> None:
    clock = Clock()
    codes = access(clock)
    issued, until = codes.issue(CODE)
    assert until is not None

    assert codes.admit(issued) == Admission(may_edit=True, until=until)
    clock.now = until - 0.001
    assert codes.admit(issued) == Admission(may_edit=True, until=until)
    # Reason four: it is older than access_pass_hours.
    clock.now = until
    assert codes.admit(issued) == Admission(may_edit=False)
    clock.now = until + 30 * 24 * HOUR
    assert codes.admit(issued) == Admission(may_edit=False)


def test_a_pass_lasts_as_long_as_the_setting_says_when_it_is_checked() -> None:
    clock = Clock()
    issued, _ = access(clock, pass_seconds=12 * HOUR).issue(CODE)
    clock.now += 2 * HOUR

    # A shorter setting ends passes already issued, and a longer one keeps them.
    assert not access(clock, pass_seconds=1 * HOUR).admit(issued).may_edit
    assert access(clock, pass_seconds=3 * HOUR).admit(issued).may_edit
    clock.now += 100 * HOUR
    assert not access(clock, pass_seconds=12 * HOUR).admit(issued).may_edit
    # No limit: it never ends, and the connection is told so.
    assert access(clock, pass_seconds=None).admit(issued) == Admission(may_edit=True, until=None)


def test_a_pass_without_a_limit_has_no_end() -> None:
    clock = Clock()
    codes = access(clock, pass_seconds=None)

    issued, until = codes.issue(CODE)

    assert until is None
    clock.now += 10 * 365 * 24 * HOUR
    assert codes.admit(issued) == Admission(may_edit=True, until=None)


def test_reason_one_no_code_of_the_list_signed_it() -> None:
    clock = Clock()
    codes = access(clock, CODE, OTHER)
    good, _ = codes.issue(CODE)
    stamp, _, signature = good.partition(".")
    assert codes.admit(good).may_edit

    # Signed with another secret, as a pass of another segl is.
    forged = Access((CODE,), "another-secret-of-thirty-two-chars!", clock=clock).issue(CODE)[0]
    assert forged != good
    assert not codes.admit(forged).may_edit
    # The time changed under the signature, forward and back.
    assert not codes.admit(f"{int(stamp) + 1}.{signature}").may_edit
    assert not codes.admit(f"{int(stamp) - 1}.{signature}").may_edit
    # The signature changed, in its first character and in its last.
    swapped = "B" if signature[0] != "B" else "C"
    assert not codes.admit(f"{stamp}.{swapped}{signature[1:]}").may_edit
    assert not codes.admit(f"{stamp}.{signature[:-1]}{swapped}").may_edit
    # A signature over the time alone, or over the time and no code.
    for code in ("", "maple", "maple.river.43"):
        other = Access((code,), ACCESS_SECRET, clock=clock).issue(code)[0]
        assert not codes.admit(other).may_edit, code


def test_taking_a_code_out_of_the_list_ends_the_passes_it_bought() -> None:
    clock = Clock()
    both = access(clock, CODE, OTHER)
    first, _ = both.issue(CODE)
    second, _ = both.issue(OTHER)
    assert first != second
    assert both.admit(first).may_edit
    assert both.admit(second).may_edit

    one = access(clock, OTHER)

    assert not one.admit(first).may_edit
    assert one.admit(second).may_edit
    # In either place of the list.
    assert access(clock, OTHER, "zebra.crossing").admit(second).may_edit
    assert access(clock, "zebra.crossing", OTHER).admit(second).may_edit


def test_reason_two_it_was_issued_before_passes_were_ended() -> None:
    clock = Clock()
    issued, _ = access(clock).issue(CODE)
    at = float(issued.partition(".")[0])

    # At that second, or before it, the pass stands.
    assert access(clock, passes_after=at).admit(issued).may_edit
    assert access(clock, passes_after=at - 60).admit(issued).may_edit
    # After it, by a second or by a fraction of one, it does not.
    assert not access(clock, passes_after=at + 1).admit(issued).may_edit
    assert not access(clock, passes_after=at + 0.001).admit(issued).may_edit
    # The codes still work: a pass bought now is taken.
    ended = access(clock, passes_after=at + 1)
    clock.now = at + 5
    assert ended.admit(ended.issue(CODE)[0]).may_edit


def test_reason_three_it_is_from_more_than_five_minutes_ahead() -> None:
    clock = Clock()
    codes = access(clock)
    issued, _ = codes.issue(CODE)

    # The server's clock was set back, or the pass came from a clock that is ahead.
    clock.now -= PASS_AHEAD_SECONDS
    assert codes.admit(issued).may_edit
    clock.now -= 1
    assert not codes.admit(issued).may_edit
    clock.now -= 24 * HOUR
    assert not codes.admit(issued).may_edit


def test_five_minutes_ahead_is_three_hundred_seconds() -> None:
    # In numbers of its own, so that the allowance cannot change with the constant.
    assert PASS_AHEAD_SECONDS == 300.0
    clock = Clock(1_800_000_000.0)
    codes = access(clock)
    issued, _ = codes.issue(CODE)

    clock.now = 1_800_000_000.0 - 300
    assert codes.admit(issued).may_edit
    clock.now = 1_800_000_000.0 - 301
    assert not codes.admit(issued).may_edit
    clock.now = 1_800_000_000.0 - 3000
    assert not codes.admit(issued).may_edit


def test_a_pass_is_never_stamped_before_the_time_passes_were_ended_at() -> None:
    clock = Clock()
    # The site wrote a time a little ahead of this server's clock, with a fraction.
    ahead = access(clock, passes_after=clock.now + 90.5)

    issued, until = ahead.issue(CODE)

    assert issued.partition(".")[0] == str(int(clock.now) + 91)
    assert until == int(clock.now) + 91 + 12 * HOUR
    assert ahead.admit(issued).may_edit
    # More than five minutes ahead, the pass is from too far ahead, until then.
    far = access(clock, passes_after=clock.now + 2 * HOUR)
    late, _ = far.issue(CODE)
    assert not far.admit(late).may_edit
    clock.now += 2 * HOUR - PASS_AHEAD_SECONDS
    assert far.admit(late).may_edit


@pytest.mark.parametrize(
    "sent",
    [
        None,
        "",
        " ",
        "pass",
        "1800000000",
        "1800000000.",
        ".AAAAAAAAAAAAAAAAAAAAAAAA",
        "1800000000.short",
        "1800000000.AAAAAAAAAAAAAAAAAAAAAAAA.more",
        "s.1800000000.AAAAAAAAAAAAAAAAAAAAAAAA",
        "-1800000000.AAAAAAAAAAAAAAAAAAAAAAAA",
        "+1800000000.AAAAAAAAAAAAAAAAAAAAAAAA",
        "1800000000.0.AAAAAAAAAAAAAAAAAAAAAAAA",
        "1e9.AAAAAAAAAAAAAAAAAAAAAAAA",
        # Digits of another script are not a time.
        "\u0661\u0668\u0660\u0660\u0660\u0660\u0660\u0660\u0660\u0660.AAAAAAAAAAAAAAAAAAAAAAAA",
        "1" * 13 + ".AAAAAAAAAAAAAAAAAAAAAAAA",
        "1800000000.AAAAAAAAAAAAAAAAAAAAAAA=",
        "1800000000.AAAAAAAAAAAAAAAAAAAAAAA+",
        ACCESS_CODE,
        ACCESS_SECRET,
        "x" * 5000,
    ],
)
def test_what_is_not_a_pass_is_refused(sent: str | None) -> None:
    assert access(Clock()).admit(sent) == Admission(may_edit=False)


def test_a_pass_with_anything_around_it_is_refused() -> None:
    clock = Clock()
    codes = access(clock)
    issued, _ = codes.issue(CODE)

    for sent in (f" {issued}", f"{issued} ", f"{issued}\n", issued.upper(), f"{issued}{issued}"):
        if sent != issued:
            assert not codes.admit(sent).may_edit, sent


# The count of wrong codes.


def test_five_wrong_codes_in_a_row_and_the_address_waits_fifteen_minutes() -> None:
    assert (WRONG_CODES, LOCK_SECONDS) == (5, 900.0)
    clock = Clock()
    limit = CodeLimit(clock=clock)

    for tried in range(1, 5):
        assert limit.wait("a") == 0
        assert limit.wrong("a") is False, tried
        clock.now += 1
    assert limit.wait("a") == 0
    assert limit.wrong("a") is True

    assert limit.wait("a") == 900.0
    clock.now += 899
    assert limit.wait("a") == 1.0
    clock.now += 1
    assert limit.wait("a") == 0
    # The count started again: four more are not a wait.
    for _ in range(4):
        assert limit.wrong("a") is False
    assert limit.wait("a") == 0


def test_the_wait_is_one_addresss_own() -> None:
    clock = Clock()
    limit = CodeLimit(clock=clock)
    for _ in range(5):
        limit.wrong("a")

    assert limit.wait("a") > 0
    assert limit.wait("b") == 0
    assert limit.wrong("b") is False


def test_a_right_code_starts_the_count_again() -> None:
    limit = CodeLimit(clock=Clock())
    for _ in range(4):
        limit.wrong("a")

    limit.right("a")

    for _ in range(4):
        assert limit.wrong("a") is False
    assert limit.wait("a") == 0
    assert limit.wrong("a") is True
    # A right code from an address that was never wrong is nothing.
    limit.right("never-seen")
    assert limit.clients() == 1


def test_wrong_codes_long_ago_are_not_in_a_row() -> None:
    clock = Clock()
    limit = CodeLimit(clock=clock)
    for _ in range(4):
        limit.wrong("a")

    clock.now += 900
    assert limit.wrong("a") is False
    for _ in range(3):
        assert limit.wrong("a") is False
    assert limit.wrong("a") is True


def test_the_wait_is_not_made_longer_by_asking() -> None:
    clock = Clock()
    limit = CodeLimit(clock=clock)
    for _ in range(5):
        limit.wrong("a")

    clock.now += 600
    for _ in range(50):
        assert limit.wait("a") == 300.0
    clock.now += 300
    assert limit.wait("a") == 0
    # Long after the wait there is none, and never less than none.
    for later in (1, 60, 900, 86400):
        clock.now += later
        assert limit.wait("a") == 0


def test_a_wait_that_ends_between_two_sweeps_is_over() -> None:
    clock = Clock()
    limit = CodeLimit(clock=clock)
    # The sweep runs once in fifteen minutes, counted from the start.
    clock.now += 100
    for _ in range(5):
        limit.wrong("a")

    clock.now += 800
    # This call sweeps, and the address is kept: its wait has 100 seconds left.
    assert limit.wait("a") == 100.0
    assert limit.clients() == 1
    clock.now += 101

    # No sweep is due, the address is still in the table, and its wait is over.
    assert limit.wait("a") == 0
    assert limit.clients() == 1
    assert limit.wrong("a") is False


def test_addresses_are_forgotten_once_their_wrong_codes_are_old() -> None:
    clock = Clock()
    limit = CodeLimit(clock=clock)
    for number in range(500):
        limit.wrong(f"198.51.100.{number}")
    assert limit.clients() == 500

    clock.now += 600
    limit.wrong("recent")
    clock.now += 300
    # The sweep runs when an address next asks, once a wait's length.
    assert limit.wait("anyone") == 0

    assert limit.clients() == 1


def test_a_smaller_limit_can_be_set() -> None:
    clock = Clock()
    limit = CodeLimit(tries=2, lock=10.0, clock=clock)

    assert limit.wrong("a") is False
    assert limit.wrong("a") is True
    assert limit.wait("a") == 10.0


# The route, in process.


def application(repository: Repository, clock: Clock | None = None, **settings: Any) -> TestClient:
    made = make_settings(**{**GATED, **settings})
    if clock is None:
        return TestClient(create_app(made, repository))
    return TestClient(create_app(made, repository, clock=clock))


@pytest.fixture
def gated(repository: Repository) -> Iterator[TestClient]:
    """A segl that asks for an access code."""
    with application(repository) as client:
        yield client


def enter(client: TestClient, code: object = ACCESS_CODE, **headers: str) -> Any:
    return client.post(ROUTE, json={"code": code}, headers=headers)


def title(client: TestClient, edit_pass: str | None, slot: int = 4) -> int:
    """Try to change a slot's title with a pass, and return the status."""
    headers = {} if edit_pass is None else {PASS_HEADER: edit_pass}
    return client.patch(
        f"/api/v1/slots/{slot}", json={"title": "Core"}, headers=headers
    ).status_code


def test_a_right_code_buys_a_pass_that_opens_the_gate(gated: TestClient) -> None:
    before = int(time.time())

    reply = enter(gated)

    assert reply.status_code == 200
    assert set(reply.json()) == {"pass", "expiresAt"}
    issued = reply.json()["pass"]
    assert PASS_SHAPE.fullmatch(issued)
    assert before <= int(issued.partition(".")[0]) <= int(time.time())
    # Each answer is a pass of its own: no cache may keep one, and no cookie carries it.
    assert reply.headers["cache-control"] == "no-store"
    assert "set-cookie" not in reply.headers
    assert_no_secrets(reply.text.replace(issued, ""))

    assert title(gated, None) == 403
    assert title(gated, issued) == 200


def test_the_answer_says_when_the_pass_ends(repository: Repository) -> None:
    clock = Clock(1_800_000_000.4)
    with application(repository, clock) as client:
        reply = enter(client)

    # Twelve hours on, in UTC, to the millisecond.
    assert reply.json() == {
        "pass": Access((CODE,), ACCESS_SECRET, clock=clock).issue(CODE)[0],
        "expiresAt": "2027-01-15T20:00:00.000Z",
    }


def test_a_pass_without_a_limit_ends_at_null(repository: Repository) -> None:
    with application(repository, access_pass_hours=0.0) as client:
        reply = enter(client)

    assert reply.status_code == 200
    assert reply.json()["expiresAt"] is None
    assert PASS_SHAPE.fullmatch(reply.json()["pass"])


@pytest.mark.parametrize("typed", ["maple river 42", "MAPLE.RIVER.42", " Maple-River-42 "])
def test_a_code_is_taken_however_it_is_typed(gated: TestClient, typed: str) -> None:
    reply = enter(gated, typed)

    assert reply.status_code == 200
    assert title(gated, reply.json()["pass"]) == 200


@pytest.mark.parametrize("typed", ["", "maple river", "Maple River 43", "mapleriver42", "x" * 3000])
def test_a_wrong_code_is_refused_in_words_and_buys_nothing(gated: TestClient, typed: str) -> None:
    reply = enter(gated, typed)

    assert reply.status_code == 403
    assert reply.json() == {
        "error": "wrong_code",
        "message": "That is not one of this segl's access codes.",
    }
    assert "set-cookie" not in reply.headers
    assert "pass" not in reply.json()
    if typed:
        assert typed not in reply.text


@pytest.mark.parametrize(
    ("body", "status", "error"),
    [
        (b"not json", 400, "bad_request"),
        (b"[]", 400, "bad_request"),
        (b'"maple river 42"', 400, "bad_request"),
        (b"{}", 400, "bad_request"),
        (b'{"code": 12345678}', 400, "bad_request"),
        (b'{"code": null}', 400, "bad_request"),
        (b'{"code": ["Maple River 42"]}', 400, "bad_request"),
        (b'{"code": {"code": "Maple River 42"}}', 400, "bad_request"),
        (b'{"code": "' + b"x" * 4096 + b'"}', 413, "payload_too_large"),
    ],
)
def test_a_body_that_is_not_a_code_is_refused_and_is_not_a_wrong_code(
    gated: TestClient, body: bytes, status: int, error: str
) -> None:
    for _ in range(WRONG_CODES + 1):
        reply = gated.post(ROUTE, content=body, headers={"Content-Type": "application/json"})

        assert (reply.status_code, reply.json()["error"]) == (status, error)
    # None of them was counted.
    assert enter(gated).status_code == 200


def test_the_route_takes_a_post_alone(gated: TestClient) -> None:
    for method in ("GET", "PUT", "PATCH", "DELETE"):
        reply = gated.request(method, ROUTE)

        assert (reply.status_code, reply.json()["error"]) == (405, "method_not_allowed"), method
        assert reply.headers["allow"] == "POST"


def test_a_segl_without_codes_has_none_to_take(repository: Repository) -> None:
    with TestClient(create_app(make_settings(), repository)) as client:
        for code in (ACCESS_CODE, "", "anything at all"):
            reply = enter(client, code)

            assert reply.status_code == 404
            assert reply.json() == {
                "error": "no_access_codes",
                "message": "This segl asks for no access code. Everyone can edit.",
            }
        # And nothing was counted: there is nothing to guess.
        assert limit_of(client).clients() == 0
        assert title(client, None) == 200


def test_a_code_from_a_page_of_another_site_is_bad_origin(gated: TestClient) -> None:
    # The route is a mutation for the Origin check (docs/SECURITY.md).
    for _ in range(WRONG_CODES + 1):
        reply = enter(gated, "a wrong code", Origin="https://evil.example")

        assert (reply.status_code, reply.json()["error"]) == (403, "bad_origin")
    # Refused before the route: nothing was counted against this address.
    own = enter(gated, Origin="http://testserver")
    assert own.status_code == 200


def limit_of(client: TestClient) -> CodeLimit:
    app = client.app
    assert isinstance(app, FastAPI)
    return app.state.code_limit


def test_after_five_wrong_codes_every_code_from_the_address_waits(
    gated: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock()
    limit_of(gated).clock = clock
    caplog.set_level(logging.WARNING, logger="segl.access")

    for tried in range(WRONG_CODES):
        assert not caplog.records, tried
        reply = enter(gated, f"wrong code {tried}")
        assert (reply.status_code, reply.json()["error"]) == (403, "wrong_code"), tried

    # The log has the address, once, and nothing that was sent.
    assert [record.getMessage() for record in caplog.records] == [
        "wrong access codes from testclient: its codes wait 15 minutes"
    ]
    # From here on a wrong code and the right one get the same answer.
    for code in ("wrong code 6", ACCESS_CODE):
        refused = enter(gated, code)

        assert refused.status_code == 429
        assert refused.json() == {
            "error": "rate_limited",
            "message": "Too many wrong access codes came from this address. Try again later.",
        }
        assert refused.headers["retry-after"] == "900"
        assert "set-cookie" not in refused.headers
    # Not even a body is read while the address waits.
    assert gated.post(ROUTE, content=b"not json").status_code == 429
    assert len(caplog.records) == 1

    clock.now += 899.5
    assert enter(gated).headers["retry-after"] == "1"
    clock.now += 0.5
    opened = enter(gated)
    assert opened.status_code == 200
    assert title(gated, opened.json()["pass"]) == 200


def test_a_right_code_among_the_wrong_ones_starts_the_count_again(gated: TestClient) -> None:
    for _ in range(3):
        for tried in range(WRONG_CODES - 1):
            assert enter(gated, f"wrong code {tried}").status_code == 403
        assert enter(gated).status_code == 200

    # Fifteen tries, twelve of them wrong, and no wait.
    assert enter(gated, "wrong again").status_code == 403


def test_the_wait_is_for_one_address(repository: Repository) -> None:
    app = create_app(make_settings(**GATED), repository)
    with (
        TestClient(app, client=("198.51.100.7", 50000)) as guesser,
        TestClient(app, client=("198.51.100.8", 50000)) as neighbour,
    ):
        for _ in range(WRONG_CODES):
            assert enter(guesser, "a wrong code").status_code == 403

        assert enter(guesser).status_code == 429
        assert enter(neighbour).status_code == 200


def test_a_pass_from_the_route_ends_when_the_clock_says(repository: Repository) -> None:
    clock = Clock()
    with application(repository, clock) as client:
        issued = enter(client).json()["pass"]

        assert title(client, issued) == 200
        clock.now += 12 * HOUR - 1
        assert title(client, issued) == 200
        clock.now += 1
        assert title(client, issued) == 403
        # A new one, for the same code, is taken.
        assert title(client, enter(client).json()["pass"]) == 200


def test_a_shorter_limit_from_the_file(repository: Repository) -> None:
    clock = Clock()
    with application(repository, clock, access_pass_hours=0.5) as client:
        reply = enter(client)
        issued = reply.json()["pass"]

        assert reply.json()["expiresAt"] == "2027-01-15T08:30:00.000Z"
        clock.now += 1799
        assert title(client, issued) == 200
        clock.now += 1
        assert title(client, issued) == 403


def test_ending_every_pass_leaves_the_codes_working(repository: Repository) -> None:
    clock = Clock()
    # Without the setting, the earlier pass is good.
    assert access(clock).admit(issue_pass(at=clock.now - 60)).may_edit
    earlier = issue_pass(at=clock.now - 60)
    ended = datetime.fromtimestamp(clock.now, UTC)
    with application(repository, clock, access_passes_after=ended) as client:
        assert title(client, earlier) == 403
        # At that very second a pass stands, and so does one bought afterwards.
        assert title(client, issue_pass(at=clock.now)) == 200
        clock.now += 30
        assert title(client, enter(client).json()["pass"]) == 200


# Each gate. test_sweep.py walks the routes; here each is held to the pass's end.

SCENE_FILE = json.dumps({"type": "excalidraw", "version": 2, "elements": []}).encode()
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(64))


def gates(client: TestClient, edit_pass: str | None) -> list[int]:
    """Ask each of the four gated routes, and return the statuses."""
    sent = {} if edit_pass is None else {PASS_HEADER: edit_pass}
    return [
        client.patch("/api/v1/slots/1", json={"title": "Core"}, headers=sent).status_code,
        client.post("/api/v1/slots/1/import", content=SCENE_FILE, headers=sent).status_code,
        client.post("/api/v1/slots/1/restore", json={"revision": 1}, headers=sent).status_code,
        client.post(
            "/api/v1/slots/1/assets", content=PNG, headers={"Content-Type": "image/png", **sent}
        ).status_code,
    ]


def test_each_gated_route_takes_a_pass_and_nothing_else(
    repository: Repository, tmp_path: Path
) -> None:
    clock = Clock()
    with application(repository, clock, assets_dir=tmp_path / "assets") as client:
        issued = enter(client).json()["pass"]

        assert gates(client, None) == [403] * 4
        for not_a_pass in ("", ACCESS_CODE, CODE, ACCESS_SECRET, issued[:-1], issued + "A"):
            assert gates(client, not_a_pass) == [403] * 4, not_a_pass
        assert gates(client, issued) == [200] * 4

        # And each stops taking it at the second it ends.
        clock.now += 12 * HOUR
        assert gates(client, issued) == [403] * 4
        for path in ("/api/v1/slots/1", "/api/v1/slots/1/scene", "/api/v1/slots/1/revisions"):
            assert client.get(path).status_code == 200


def test_hello_reads_the_pass(repository: Repository) -> None:
    clock = Clock()
    with application(repository, clock) as client:
        issued = enter(client).json()["pass"]

        def view_only(sent: str) -> bool:
            with client.websocket_connect("/collab?slot=2") as socket:
                return hello(socket, "Guest1", sent)[0]["viewOnly"]

        assert view_only(issued) is False
        for not_a_pass in ("", ACCESS_CODE, CODE, issued[:-1], issued.replace(".", ".."), "x"):
            assert view_only(not_a_pass) is True, not_a_pass
        clock.now += 12 * HOUR
        assert view_only(issued) is True


def test_a_pass_that_ends_while_its_socket_is_open_makes_the_connection_a_viewer(
    repository: Repository, tmp_path: Path
) -> None:
    clock = Clock()
    with (
        application(repository, clock, assets_dir=tmp_path / "assets") as client,
        client.websocket_connect("/collab?slot=5") as editor,
        client.websocket_connect("/collab?slot=5") as late,
        client.websocket_connect("/collab?slot=5") as viewer,
    ):
        first = enter(client).json()["pass"]
        assert hello(editor, "Guest1", first)[0]["viewOnly"] is False
        clock.now += 6 * HOUR
        second = enter(client).json()["pass"]
        assert hello(late, "Staff2", second)[0]["viewOnly"] is False
        assert received(editor)["type"] == "presence"
        hello(viewer, "Guest3")
        assert received(editor)["type"] == "presence"
        assert received(late)["type"] == "presence"
        uploaded = client.post(
            "/api/v1/slots/5/assets",
            content=PNG,
            headers={"Content-Type": "image/png", PASS_HEADER: second},
        ).json()["hash"]
        files = [{"id": "file-1", "hash": uploaded, "mimeType": "image/png"}]

        # Until the second it ends, the first connection edits.
        clock.now += 6 * HOUR - 1
        editor.send_json({"type": "elements", "epoch": 1, "elements": [element("a", 1)]})
        assert received(late)["elements"] == [element("a", 1)]
        assert received(viewer)["elements"] == [element("a", 1)]

        # At that second it is a viewer, for elements and for files, and nobody is told.
        clock.now += 1
        editor.send_json({"type": "elements", "epoch": 1, "elements": [element("b", 1)]})
        assert received(editor) == {
            "type": "error",
            "error": "view_only",
            "message": "Editing needs an access code.",
        }
        editor.send_json({"type": "files", "epoch": 1, "files": files})
        assert received(editor)["error"] == "view_only"
        # It still watches, has its name, and may change it.
        editor.send_json({"type": "rename", "displayName": "still here"})
        assert received(editor)["displayName"] == "Still Here"
        assert received(late)["displayName"] == "Still Here"
        assert received(viewer)["displayName"] == "Still Here"

        # The connection whose pass is six hours younger edits on, and the
        # first one sees it.
        late.send_json({"type": "elements", "epoch": 1, "elements": [element("c", 1)]})
        assert received(editor)["elements"] == [element("c", 1)]
        assert received(viewer)["elements"] == [element("c", 1)]
        late.send_json({"type": "files", "epoch": 1, "files": files})
        assert received(editor)["files"] == files

        # The clock set back does not make it an editor again.
        clock.now -= 3600
        editor.send_json({"type": "elements", "epoch": 1, "elements": [element("d", 1)]})
        assert received(editor)["error"] == "view_only"

        # What is stored is what the two passes let through.
        late.send_json({"type": "elements", "epoch": 1, "elements": [], "seq": 1})
        assert received(late)["type"] == "saved"
        scene = client.get("/api/v1/slots/5/scene").json()["scene"]
        assert [each["id"] for each in scene["elements"]] == ["a", "c"]


def test_a_connection_keeps_the_end_of_its_pass_from_hello() -> None:
    clock = Clock()
    sent: list[dict[str, Any]] = []
    room = Room.from_head(1, "Workspace 1", 1, '{"elements": []}')
    connection = Connection(
        lambda text: sent.append(json.loads(text)),
        Hello("client-1", "Guest1", ""),
        view_only=False,
        edit_until=clock.now + 10,
        clock=clock,
    )
    room.join(connection)
    assert sent[0]["viewOnly"] is False
    del sent[:]

    clock.now += 9.999
    assert connection.may_not_edit() is False
    room.receive(connection, {"type": "elements", "epoch": 1, "elements": [element("a", 1)]})
    assert sent == []
    assert list(room.elements) == ["a"]

    clock.now += 0.001
    room.receive(connection, {"type": "elements", "epoch": 1, "elements": [element("b", 1)]})
    assert [each["error"] for each in sent] == ["view_only"]
    assert list(room.elements) == ["a"]
    assert connection.view_only is True


def test_a_connection_without_an_end_edits_for_as_long_as_it_is_open() -> None:
    clock = Clock()
    room = Room.from_head(1, "Workspace 1", 1, '{"elements": []}')
    editor = Connection(lambda text: None, Hello("c", None, ""), view_only=False, clock=clock)
    viewer = Connection(
        lambda text: None, Hello("c", None, ""), view_only=True, edit_until=None, clock=clock
    )
    room.join(editor)
    room.join(viewer)

    clock.now += 10 * 365 * 24 * HOUR

    assert editor.may_not_edit() is False
    assert viewer.may_not_edit() is True


# A real process, with the codes in its TOML.


def post_code(server: Any, code: str, **headers: str) -> Any:
    return server.post(ROUTE, headers, json.dumps({"code": code}).encode())


def test_a_real_process_issues_a_pass_for_a_code_in_its_toml(tmp_path: Path) -> None:
    """T-008 from a running process: a code, the pass it buys, and each gate."""
    config = 'access_codes = ["Maple River 42", "night shift 1836"]\n' + GATED_TOML.split("\n")[1]
    with running_segl(tmp_path, config + "\n") as server:
        assert server.get("/api/v1/config").json() == {"editRequired": True}

        wrong = post_code(server, "maple river 43")
        assert (wrong.status, wrong.json()["error"]) == (403, "wrong_code")
        bought = post_code(server, "maple-river-42")
        assert bought.status == 200
        assert bought.headers["Cache-Control"] == "no-store"
        assert bought.headers["Set-Cookie"] is None
        issued = bought.json()["pass"]
        # The same code, the same second or the next: a pass the harness would issue too.
        assert issued in (issue_pass(), issue_pass(at=time.time() - 1))
        other = post_code(server, "Night Shift 1836").json()["pass"]
        assert other != issued

        with server.socket("/collab?slot=2") as editor, server.socket("/collab?slot=2") as viewer:
            assert say_hello(editor, "Guest1", edit_pass=issued)[0]["viewOnly"] is False
            assert say_hello(viewer, "Staff2", edit_pass=ACCESS_CODE)[0]["viewOnly"] is True
            assert next_message(editor)["type"] == "presence"
            editor.send(json.dumps({"type": "elements", "epoch": 1, "elements": [element("a", 1)]}))
            assert next_message(viewer)["elements"] == [element("a", 1)]
            viewer.send(json.dumps({"type": "elements", "epoch": 1, "elements": [element("b", 1)]}))
            assert next_message(viewer)["error"] == "view_only"

        for edit_pass, status in ((None, 403), ("", 403), (ACCESS_CODE, 403), (other, 200)):
            sent = {} if edit_pass is None else {PASS_HEADER: edit_pass}
            assert server.patch("/api/v1/slots/2", {"title": "Yes"}, sent).status == status

        # The codes, the secret, and the passes are in no log line.
        log = server.log()
        assert_no_secrets(log)
        for hidden in ("night", "Night", issued, other, issued.partition(".")[2]):
            assert hidden not in log


def test_a_real_process_counts_wrong_codes_by_the_address_it_believes(tmp_path: Path) -> None:
    # The default trusts 127.0.0.1, where this request comes from, so
    # X-Forwarded-For names the client, as nginx does.
    with running_segl(tmp_path, GATED_TOML) as server:
        guesser = {"X-Forwarded-For": "203.0.113.50"}
        for tried in range(WRONG_CODES):
            refused = post_code(server, f"wrong code {tried}", **guesser)
            assert (refused.status, refused.json()["error"]) == (403, "wrong_code"), tried

        waiting = post_code(server, ACCESS_CODE, **guesser)
        assert (waiting.status, waiting.json()["error"]) == (429, "rate_limited")
        assert 895 <= int(waiting.headers["Retry-After"] or 0) <= 900
        assert waiting.headers["Set-Cookie"] is None
        # Another address, and this host itself, are not kept waiting.
        assert post_code(server, ACCESS_CODE, **{"X-Forwarded-For": "203.0.113.51"}).status == 200
        assert post_code(server, ACCESS_CODE).status == 200

        line = server.logged_line("wrong access codes")
        assert line.endswith("wrong access codes from 203.0.113.50: its codes wait 15 minutes")
        assert_no_secrets(server.log())
        assert "wrong code" not in server.log()


def test_an_untrusted_connection_cannot_name_its_way_past_the_count(tmp_path: Path) -> None:
    with running_segl(tmp_path, GATED_TOML + "trusted_proxies = []\n") as server:
        for tried in range(WRONG_CODES):
            sent = {"X-Forwarded-For": f"203.0.113.{tried}"}
            assert post_code(server, "a wrong code", **sent).status == 403

        assert post_code(server, ACCESS_CODE, **{"X-Forwarded-For": "203.0.113.99"}).status == 429


def test_a_real_process_ends_a_pass_while_its_socket_is_open(tmp_path: Path) -> None:
    # 0.0005 hours is 1.8 seconds.
    with running_segl(tmp_path, GATED_TOML + "access_pass_hours = 0.0005\n") as server:
        bought = post_code(server, ACCESS_CODE).json()
        issued = bought["pass"]
        assert bought["expiresAt"].endswith("Z")

        with server.socket("/collab?slot=3") as editor:
            assert say_hello(editor, "Guest1", edit_pass=issued)[0]["viewOnly"] is False
            editor.send(json.dumps({"type": "elements", "epoch": 1, "elements": [element("a", 1)]}))
            # The pass was stamped with a whole second, up to one second ago.
            time.sleep(2.0)
            editor.send(json.dumps({"type": "elements", "epoch": 1, "elements": [element("b", 1)]}))
            assert next_message(editor)["error"] == "view_only"

        assert server.patch("/api/v1/slots/3", {"title": "No"}, {PASS_HEADER: issued}).status == 403
        scene = server.get("/api/v1/slots/3/scene").json()["scene"]
        assert [each["id"] for each in scene["elements"]] == ["a"]
        # A new pass, for the same code, edits again.
        again = post_code(server, ACCESS_CODE).json()["pass"]
        assert server.patch("/api/v1/slots/3", {"title": "Yes"}, {PASS_HEADER: again}).status == 200


def test_a_real_process_refuses_the_passes_from_before_the_time_in_its_toml(
    tmp_path: Path,
) -> None:
    earlier = issue_pass(at=time.time() - 120)
    ended = datetime.fromtimestamp(time.time() - 60, UTC).isoformat(timespec="seconds")
    with running_segl(tmp_path, GATED_TOML + f"access_passes_after = {ended}\n") as server:
        assert (
            server.patch("/api/v1/slots/1", {"title": "No"}, {PASS_HEADER: earlier}).status == 403
        )
        bought = post_code(server, ACCESS_CODE).json()["pass"]
        assert (
            server.patch("/api/v1/slots/1", {"title": "Yes"}, {PASS_HEADER: bought}).status == 200
        )
    with running_segl(tmp_path, GATED_TOML) as server:
        assert (
            server.patch("/api/v1/slots/1", {"title": "Old"}, {PASS_HEADER: earlier}).status == 200
        )


def test_a_real_process_stops_for_codes_it_cannot_use(tmp_path: Path) -> None:
    for config, said in (
        ('access_codes = ["Maple River 42"]\n', "access_codes needs access_secret"),
        (
            GATED_TOML.replace("Maple River 42", "short"),
            "access_codes entry 1 has fewer than 8 letters and digits",
        ),
        ('edit_token = "an-old-token"\n', "edit_token is gone: list access codes in access_codes"),
        ('internal_networks = ["everywhere"]\n', "internal_networks entry 'everywhere'"),
    ):
        with (
            pytest.raises(AssertionError, match="did not start") as stopped,
            running_segl(tmp_path, config),
        ):
            pass

        assert said in str(stopped.value)
        assert "an-old-token" not in str(stopped.value)


# Through nginx, with the files in deploy/nginx/.


def test_the_access_route_through_nginx_at_board_and_at_a_host_root(
    tools: NginxTools, certificate: tuple[Path, Path], tmp_path: Path
) -> None:
    with running_mount(tools, certificate, tmp_path, GATED_TOML) as mount:
        for site, prefix in ((BOARD_SITE, "/board"), (ROOT_SITE, "")):
            origin = mount.origin(site)
            body = json.dumps({"code": "maple river 42"}).encode()
            path = prefix + ROUTE

            # From a page of another site, and from the site's name without its port.
            for other in ("https://evil.example", f"https://{site}"):
                refused = mount.post(site, path, {"Origin": other}, body)
                assert (refused.status, refused.json()["error"]) == (403, "bad_origin"), other
                assert refused.headers["Set-Cookie"] is None

            wrong = mount.post(site, path, {"Origin": origin}, b'{"code": "maple river 43"}')
            assert (wrong.status, wrong.json()["error"]) == (403, "wrong_code")
            assert wrong.headers["Set-Cookie"] is None

            bought = mount.post(site, path, {"Origin": origin}, body)
            assert bought.status == 200
            assert bought.headers["Cache-Control"] == "no-store"
            assert bought.headers["Set-Cookie"] is None
            issued = bought.json()["pass"]

            # The pass opens a gate through the same mount, in the header and in hello.
            mine = {"Origin": origin, PASS_HEADER: issued}
            slot = f"{prefix}/api/v1/slots/7"
            assert mount.patch(site, slot, {"title": "No"}, {"Origin": origin}).status == 403
            assert mount.patch(site, slot, {"title": "Workspace 7"}, mine).status == 200
            with mount.socket(site, f"{prefix}/collab?slot=7", origin=origin) as editor:
                assert say_hello(editor, "Guest1", edit_pass=issued)[0]["viewOnly"] is False

        # nginx names every client 127.0.0.1, whatever the client says of itself,
        # so both sites count as one address. Each right code above started
        # the count again.
        for tried in range(WRONG_CODES):
            sent = {"X-Forwarded-For": f"203.0.113.{tried}"}
            refused = mount.post(BOARD_SITE, f"/board{ROUTE}", sent, b'{"code": "wrong code"}')
            assert refused.status == 403, tried
        waiting = mount.post(ROOT_SITE, ROUTE, {}, b'{"code": "maple river 42"}')
        assert (waiting.status, waiting.json()["error"]) == (429, "rate_limited")
        assert waiting.headers["Set-Cookie"] is None

        # The code went in a body, and the pass in a header and in hello: neither is in a log.
        assert_no_secrets(mount.segl.log())
        for log in ("access.log", "error.log"):
            assert_no_secrets((mount.prefix / log).read_text(encoding="utf-8"), log)
