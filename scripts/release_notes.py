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

"""The release-note body: summary, topic bullets, version table, sub-dependencies.

The shape is in docs/RELEASING.md, "Release note shape".
"""

from __future__ import annotations

import datetime as dt
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from release_components import direct_rows
from release_proc import CommandError, Runner

TOPICS = ("New", "Changed", "Fixed", "Additional Notes")
CLOC_EXCLUDE_DIRS = ",".join(
    [
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "vendor",
        "third_party",
        "site-packages",
        "_site",
    ]
)
LOCK_NAMES = r"(uv\.lock|package-lock\.json|pnpm-lock\.yaml)"
UNRELEASED = r"Unreleased"


def version_heading(version: str) -> str:
    """Return a pattern for the heading text of a released version's section."""
    return rf"v?\[?{re.escape(version)}\]?(?:\s.*)?"


def project_loc(runner: Runner) -> int:
    """Return cloc's code count for the first-party files of the repository."""
    argv = [
        "cloc",
        ".",
        "--json",
        "--quiet",
        "--fullpath",
        f"--exclude-dir={CLOC_EXCLUDE_DIRS}",
        f"--not-match-f={LOCK_NAMES}",
    ]
    try:
        payload = json.loads(runner.run(argv).stdout)
    except (CommandError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cloc failed: {exc}") from exc
    total = payload.get("SUM", {}).get("code")
    if not isinstance(total, int):
        raise SystemExit("cloc JSON did not include SUM.code")
    return total


def section_body(text: str, heading: str) -> str | None:
    """Return the text under the ``## <heading>`` line, up to the next ``## ``."""
    match = re.search(rf"^## {heading}\s*$", text, flags=re.MULTILINE)
    if match is None:
        return None
    rest = text[match.end() :]
    following = re.search(r"^## ", rest, flags=re.MULTILINE)
    return rest[: following.start()] if following else rest


def parse_section(text: str, heading: str = UNRELEASED) -> tuple[str, dict[str, list[str]]]:
    """Return the summary and the bullets under each topic of one section."""
    body = section_body(text, heading)
    if body is None:
        raise SystemExit(f"CHANGELOG.md has no section matching '## {heading}'")
    topics: dict[str, list[str]] = {topic: [] for topic in TOPICS}
    summary_lines: list[str] = []
    current: str | None = None
    in_topic = False
    for line in body.splitlines():
        topic = re.match(r"^### (.+?)\s*$", line)
        if topic:
            name = topic.group(1).strip()
            current = name if name in topics else None
            in_topic = True
            continue
        bullet = re.match(r"^- (.+)$", line.strip())
        if bullet and current:
            topics[current].append(bullet.group(1).strip())
        elif not in_topic and line.strip():
            summary_lines.append(line.strip())
    return " ".join(summary_lines).strip(), topics


def summary_sentence_count(summary: str) -> int:
    """Return the number of sentences in a summary."""
    if not summary:
        return 0
    return len([part for part in re.split(r"(?<=[.!?])\s+", summary) if part.strip()])


def hold_bullets(doc: dict[str, Any]) -> list[str]:
    """Return an Additional Notes bullet for each held component."""
    bullets = []
    for name, hold in sorted(doc.get("held", {}).items()):
        if isinstance(hold, dict):
            bullets.append(
                f"Kept {name} at {hold.get('version')}. Version {hold.get('skipped')} failed "
                f"{hold.get('reason')}. It is tried again when {name} publishes a newer release."
            )
    return bullets


def version_table(doc: dict[str, Any], loc: int) -> list[str]:
    """Return the table: the line count, then the application and its pins."""
    runtime = doc.get("runtime", {})
    project = doc.get("project", {})
    rows = [
        ("Project lines of code", str(loc)),
        ("Python", str(runtime.get("python", ""))),
    ]
    node = str(runtime.get("node", "") or "")
    if node:
        rows.append(("Node", node))
    rows.append((str(project.get("name", "segl")), str(project.get("version", ""))))
    seen: set[str] = set()
    for _ecosystem, _table, name, version in direct_rows(doc):
        if name not in seen:
            seen.add(name)
            rows.append((name, version))
    lines = ["| Item | Value |", "|---|---|"]
    lines.extend(f"| {item} | {value} |" for item, value in rows)
    return lines


def _details(title: str, rows: list[tuple[str, str]]) -> list[str]:
    if not rows:
        return []
    lines = [
        "",
        "<details>",
        f"<summary>{title} ({len(rows)})</summary>",
        "",
        "| Package | Version |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | {version} |" for name, version in sorted(rows))
    lines.extend(["", "</details>", ""])
    return lines


def lock_details(root: Path, doc: dict[str, Any]) -> list[str]:
    """Return collapsed tables of the lockfiles' transitive dependencies."""
    blocks: list[str] = []
    direct = {name for _eco, _table, name, _version in direct_rows(doc)}
    project_name = str(doc.get("project", {}).get("name", "segl"))
    uv_lock = root / "uv.lock"
    if uv_lock.is_file():
        data = tomllib.loads(uv_lock.read_text(encoding="utf-8"))
        transitive = []
        for package in data.get("package", []):
            name = package.get("name")
            version = package.get("version")
            if name and version and name not in direct and name != project_name:
                transitive.append((str(name), str(version)))
        blocks.extend(_details("Python sub-dependencies", transitive))
    npm_lock = root / "web" / "package-lock.json"
    if npm_lock.is_file():
        data = json.loads(npm_lock.read_text(encoding="utf-8"))
        transitive = []
        for key, meta in data.get("packages", {}).items():
            if not key.startswith("node_modules/") or not isinstance(meta, dict):
                continue
            version = meta.get("version")
            if version:
                transitive.append((key.removeprefix("node_modules/"), str(version)))
        blocks.extend(_details("Web sub-dependencies", transitive))
    return blocks


def render_notes(
    root: Path,
    doc: dict[str, Any],
    summary: str,
    topics: dict[str, list[str]],
    loc: int,
    date: str | None = None,
) -> str:
    """Return the release-note body. ``date`` None leaves the heading out."""
    version = str(doc.get("project", {}).get("version", "0.0.0"))
    lines = [f"## {version} — {date}", ""] if date else []
    if summary:
        lines.extend([summary, ""])
    holds = [b for b in hold_bullets(doc) if b not in topics["Additional Notes"]]
    for topic in TOPICS:
        bullets = topics[topic] + (holds if topic == "Additional Notes" else [])
        if not bullets:
            continue
        lines.extend([f"### {topic}", ""])
        lines.extend(f"- {bullet}" for bullet in bullets)
        lines.append("")
    lines.extend(version_table(doc, loc))
    lines.extend(lock_details(root, doc))
    return "\n".join(lines).rstrip() + "\n"


def preview(root: Path, runner: Runner, doc: dict[str, Any]) -> str:
    """Return the notes for Unreleased, or for the current version once it is cut."""
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    summary, topics = parse_section(changelog)
    version = str(doc.get("project", {}).get("version", "0.0.0"))
    if not summary and not any(topics.values()):
        cut = section_body(changelog, version_heading(version))
        if cut is not None:
            summary, topics = parse_section(changelog, version_heading(version))
    today = dt.date.today().isoformat()
    return render_notes(root, doc, summary, topics, project_loc(runner), today)
