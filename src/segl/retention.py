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

"""Which of a slot's revisions stay (docs/DATA-MODEL.md, "Which revisions stay").

The newest ``history_limit`` stay. Of the older ones, the newest of each clock
minute stays for an hour, of each clock hour for a day, and of each clock day
for a week, in UTC. A revision marked kept stays a week whatever the count,
up to 20 a slot. The repository asks this module after each write that adds
or marks a revision, and deletes the rest. No SQL here.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

# Each tier: the length of its clock bucket in seconds, and how many buckets
# it covers, the current one with them.
TIERS: tuple[tuple[int, int], ...] = (
    (60, 60),  # each minute of the last hour
    (3600, 24),  # each hour of the last day
    (86400, 7),  # each day of the last week
)

# How long a kept revision stays, and how many a slot keeps at most.
KEPT_FOR = timedelta(days=7)
KEPT_AT_MOST = 20

# Why a revision was kept: the scene before what came next.
REASONS = ("delete", "restore", "import")


@dataclass(frozen=True)
class Row:
    """What the rules read of one revision."""

    revision: int
    created_at: datetime
    kept: str | None = None


def staying(rows: Iterable[Row], now: datetime, limit: int) -> set[int]:
    """Return the revision numbers that stay, of one slot's revisions.

    ``now`` is the time of the write, in UTC. A revision from after it, as
    after a clock that went back, counts as now.
    """
    newest_first: Sequence[Row] = sorted(rows, key=lambda row: row.revision, reverse=True)
    stay = {row.revision for row in newest_first[:limit]}
    moment = now.timestamp()
    for size, count in TIERS:
        current = int(moment // size)
        seen: set[int] = set()
        for row in newest_first:
            bucket = int(row.created_at.timestamp() // size)
            if bucket in seen:
                continue
            # The first row of a bucket, newest first, is its newest.
            seen.add(bucket)
            if current - bucket < count:
                stay.add(row.revision)
    marked = [row for row in newest_first if row.kept and now - row.created_at < KEPT_FOR]
    stay.update(row.revision for row in marked[:KEPT_AT_MOST])
    return stay
