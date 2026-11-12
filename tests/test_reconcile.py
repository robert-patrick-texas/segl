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

"""Which copy of an element the server keeps (D2-025).

``tests/reconcile_cases.json`` is one table of cases. This file holds
``segl.reconcile`` to it, and ``web/e2e/reconcile.spec.ts`` holds the pinned
editor's ``reconcileElements`` to the same table.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from segl.reconcile import BadElement, adopt_element, check_element, merge, ordered, wins

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "reconcile_cases.json").read_text(encoding="utf-8")
)["cases"]


def element(identifier: str, version: int, nonce: int, **more: object) -> dict[str, Any]:
    return {"id": identifier, "version": version, "versionNonce": nonce, **more}


def summary(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": each["id"],
            "version": each["version"],
            "versionNonce": each["versionNonce"],
            "isDeleted": each["isDeleted"],
        }
        for each in elements
    ]


def test_the_table_has_cases() -> None:
    assert len(CASES) >= 15
    assert len({case["name"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_the_server_keeps_what_the_table_says(case: dict[str, Any]) -> None:
    scene = {each["id"]: each for each in case["stored"]}

    winners = merge(scene, case["incoming"])

    assert [each["id"] for each in winners] == case["winners"]
    assert summary(ordered(scene.values())) == case["result"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_the_result_is_the_same_whichever_side_arrives(case: dict[str, Any]) -> None:
    scene = {each["id"]: each for each in case["incoming"]}

    merge(scene, case["stored"])

    assert summary(ordered(scene.values())) == case["result"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_applying_the_same_elements_again_changes_nothing(case: dict[str, Any]) -> None:
    scene = {each["id"]: each for each in case["stored"]}
    merge(scene, case["incoming"])

    assert merge(scene, case["incoming"]) == []
    assert summary(ordered(scene.values())) == case["result"]


def test_the_higher_version_wins() -> None:
    assert wins(element("a", 2, 9), element("a", 1, 1))
    assert not wins(element("a", 1, 1), element("a", 2, 9))


def test_on_equal_versions_the_lower_nonce_wins() -> None:
    assert wins(element("a", 2, 1), element("a", 2, 9))
    assert not wins(element("a", 2, 9), element("a", 2, 1))


def test_the_same_copy_does_not_win() -> None:
    assert not wins(element("a", 2, 5), element("a", 2, 5))


def test_anything_wins_over_nothing() -> None:
    assert wins(element("a", 0, 0), None)


def test_an_element_named_twice_in_a_batch_is_settled_by_the_rule() -> None:
    scene: dict[str, dict[str, Any]] = {}

    winners = merge(scene, [element("a", 1, 5), element("a", 3, 5), element("a", 2, 5)])

    assert scene == {"a": element("a", 3, 5)}
    assert winners == [element("a", 3, 5)]


def test_winners_keep_the_order_they_arrived_in() -> None:
    scene = {"b": element("b", 5, 5)}

    winners = merge(scene, [element("c", 1, 1), element("b", 1, 1), element("a", 1, 1)])

    assert [each["id"] for each in winners] == ["c", "a"]


def test_the_kept_element_is_the_one_that_arrived_whole() -> None:
    scene: dict[str, dict[str, Any]] = {}
    drawn = element("a", 1, 1, type="text", text="segl", customData={"any": ["thing"]})

    merge(scene, [drawn])

    assert scene["a"] is drawn


def test_elements_are_ordered_by_index_and_then_by_id() -> None:
    elements = [
        element("z", 1, 1, index="a1"),
        element("b", 1, 1, index="a2"),
        element("a", 1, 1, index="a2"),
        element("y", 1, 1, index="Zz"),
        element("x", 1, 1, index="a0V"),
    ]

    # As text, the way the editor compares them: capitals sort before small letters.
    assert [each["id"] for each in ordered(elements)] == ["y", "x", "z", "a", "b"]


def test_elements_without_an_index_keep_their_place_at_the_end() -> None:
    elements = [
        element("old-2", 1, 1),
        element("b", 1, 1, index="a1"),
        element("old-1", 1, 1, index=None),
        element("a", 1, 1, index="a0"),
    ]

    assert [each["id"] for each in ordered(elements)] == ["a", "b", "old-2", "old-1"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "a",
        7,
        [],
        {},
        {"version": 1, "versionNonce": 1},
        {"id": "", "version": 1, "versionNonce": 1},
        {"id": 7, "version": 1, "versionNonce": 1},
        {"id": "a", "versionNonce": 1},
        {"id": "a", "version": 1},
        {"id": "a", "version": "1", "versionNonce": 1},
        {"id": "a", "version": 1.5, "versionNonce": 1},
        {"id": "a", "version": 1, "versionNonce": None},
        {"id": "a", "version": True, "versionNonce": 1},
        {"id": "a", "version": 1, "versionNonce": False},
    ],
)
def test_what_is_not_an_element_is_refused(value: object) -> None:
    with pytest.raises(BadElement):
        check_element(value)


def test_an_element_is_returned_as_it_came() -> None:
    drawn = element("a", 3, -7, type="rectangle", isDeleted=True)

    assert check_element(drawn) is drawn


def test_a_stored_element_without_a_version_gets_the_editors_defaults() -> None:
    assert adopt_element({"id": "a", "type": "rectangle"}) == {
        "id": "a",
        "type": "rectangle",
        "version": 1,
        "versionNonce": 0,
    }
    assert adopt_element({"id": "a", "version": 4, "versionNonce": 9}) == element("a", 4, 9)


def test_adopting_does_not_change_the_stored_value() -> None:
    stored = {"id": "a"}

    adopt_element(stored)

    assert stored == {"id": "a"}


@pytest.mark.parametrize("value", [None, "a", 7, [], {}, {"id": ""}, {"id": 7}, {"version": 1}])
def test_a_stored_value_that_is_not_an_element_is_left_out(value: object) -> None:
    assert adopt_element(value) is None
