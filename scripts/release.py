#!/usr/bin/env python3
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

"""Prepare a segl release from versions.toml. See docs/RELEASING.md."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "versions.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
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


def load_versions() -> dict:
    return tomllib.loads(VERSIONS.read_text(encoding="utf-8"))


def direct_rows(doc: dict) -> list[tuple[str, str, str, str]]:
    """Return (ecosystem, bucket, name, version) for pinned direct dependencies."""
    rows: list[tuple[str, str, str, str]] = []
    for ecosystem in ("python", "web"):
        block = doc.get(ecosystem, {})
        if not isinstance(block, dict):
            continue
        for bucket in ("dependencies", "dev", "build", "docs"):
            entries = block.get(bucket, {})
            if not isinstance(entries, dict):
                continue
            for name, version in entries.items():
                if isinstance(version, str) and version:
                    rows.append((ecosystem, bucket, name, version))
    return rows


def project_loc() -> int:
    completed = subprocess.run(
        [
            "cloc",
            ".",
            "--json",
            "--quiet",
            "--fullpath",
            f"--exclude-dir={CLOC_EXCLUDE_DIRS}",
            f"--not-match-f={LOCK_NAMES}",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(f"cloc failed:\n{completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    total = payload.get("SUM", {}).get("code")
    if not isinstance(total, int):
        raise SystemExit("cloc JSON did not include SUM.code")
    return total


def parse_unreleased(text: str) -> tuple[str, dict[str, list[str]]]:
    match = re.search(r"^## Unreleased\s*$", text, flags=re.MULTILINE)
    if match is None:
        raise SystemExit("CHANGELOG.md has no '## Unreleased' section")
    rest = text[match.end() :]
    next_heading = re.search(r"^## ", rest, flags=re.MULTILINE)
    body = rest[: next_heading.start()] if next_heading else rest
    topics: dict[str, list[str]] = {topic: [] for topic in TOPICS}
    summary_lines: list[str] = []
    current: str | None = None
    for line in body.splitlines():
        heading = re.match(r"^### (.+?)\s*$", line)
        if heading:
            name = heading.group(1).strip()
            current = name if name in topics else None
            continue
        bullet = re.match(r"^- (.+)$", line.strip())
        if bullet and current:
            topics[current].append(bullet.group(1).strip())
        elif current is None and line.strip():
            summary_lines.append(line.strip())
    return " ".join(summary_lines).strip(), topics


def summary_sentence_count(summary: str) -> int:
    if not summary:
        return 0
    parts = re.split(r"(?<=[.!?])\s+", summary)
    return len([part for part in parts if part.strip()])


def version_table(doc: dict, loc: int) -> list[str]:
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
    for _ecosystem, _bucket, name, version in direct_rows(doc):
        if name in seen:
            continue
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


def lock_details(doc: dict) -> list[str]:
    blocks: list[str] = []
    direct = {name for _eco, _bucket, name, _version in direct_rows(doc)}
    project_name = str(doc.get("project", {}).get("name", "segl"))
    uv_lock = ROOT / "uv.lock"
    if uv_lock.is_file():
        data = tomllib.loads(uv_lock.read_text(encoding="utf-8"))
        transitive = []
        for package in data.get("package", []):
            name = package.get("name")
            version = package.get("version")
            if name and version and name not in direct and name != project_name:
                transitive.append((str(name), str(version)))
        blocks.extend(_details("Python sub-dependencies", transitive))
    npm_lock = ROOT / "web" / "package-lock.json"
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


def render_notes(doc: dict, topics: dict[str, list[str]], summary: str, loc: int) -> str:
    version = str(doc.get("project", {}).get("version", "0.0.0"))
    today = dt.date.today().isoformat()
    lines = [f"## {version} — {today}", ""]
    if summary:
        lines.extend([summary, ""])
    for topic in TOPICS:
        bullets = topics[topic]
        if not bullets:
            continue
        lines.extend([f"### {topic}", ""])
        lines.extend(f"- {bullet}" for bullet in bullets)
        lines.append("")
    lines.extend(version_table(doc, loc))
    lines.extend(lock_details(doc))
    return "\n".join(lines).rstrip() + "\n"


def pypi_latest(name: str) -> str:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30) as response:
        payload = json.load(response)
    return str(payload["info"]["version"])


def npm_latest(name: str) -> str:
    with urllib.request.urlopen(
        f"https://registry.npmjs.org/{name}/latest", timeout=30
    ) as response:
        payload = json.load(response)
    return str(payload["version"])


def latest_of(ecosystem: str, name: str) -> str:
    if ecosystem == "python":
        return pypi_latest(name)
    if ecosystem == "web":
        return npm_latest(name)
    raise SystemExit(f"unknown ecosystem {ecosystem}")


# A stable CPython build in `uv python list` output. Pre-releases (3.16.0a1)
# and build variants (3.15.2+freethreaded) do not match.
STABLE_CPYTHON = re.compile(r"\bcpython-(\d+)\.(\d+)\.(\d+)-")


def uv_cpython_versions() -> list[tuple[int, ...]] | None:
    """Return the stable CPython versions uv can install here, or None if uv fails."""
    try:
        completed = subprocess.run(
            ["uv", "python", "list", "--all-versions"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    found = {
        tuple(int(part) for part in match) for match in STABLE_CPYTHON.findall(completed.stdout)
    }
    return sorted(found) or None


def dotted(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def python_status(pin: str) -> str:
    """Compare the exact Python pin with the newest CPython that uv offers."""
    parts = pin.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return f"python cpython {pin}: not an exact X.Y.Z pin (D2-016)"
    current = tuple(int(part) for part in parts)
    versions = uv_cpython_versions()
    if versions is None:
        return f"python cpython {pin}: lookup failed (uv python list did not answer)"
    marks: list[str] = []
    same_minor = max((v for v in versions if v[:2] == current[:2]), default=current)
    if same_minor > current:
        marks.append(f"newer {dotted(same_minor)}")
    newest = max(versions)
    if newest[:2] > current[:2]:
        marks.append(f"newer minor {dotted(newest)}")
    return f"python cpython {pin}: {', '.join(marks) if marks else 'current'}"


def cmd_check() -> int:
    doc = load_versions()
    runtime_python = str(doc.get("runtime", {}).get("python", ""))
    print(f"segl {doc.get('project', {}).get('version')}  Python {runtime_python}")
    if runtime_python:
        print(python_status(runtime_python))
    rows = direct_rows(doc)
    if not rows:
        print("no direct dependencies listed yet")
        return 0
    for ecosystem, _bucket, name, current in rows:
        try:
            latest = latest_of(ecosystem, name)
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            print(f"{ecosystem} {name} {current}: lookup failed ({exc})")
            continue
        mark = "current" if latest == current else f"newer {latest}"
        print(f"{ecosystem} {name} {current}: {mark}")
    return 0


def cmd_notes() -> int:
    doc = load_versions()
    summary, topics = parse_unreleased(CHANGELOG.read_text(encoding="utf-8"))
    sys.stdout.write(render_notes(doc, topics, summary, project_loc()))
    sys.stdout.flush()
    if str(doc.get("project", {}).get("version")) == "0.0.0":
        print(
            "\nPreview only. project.version is 0.0.0, which is not a publishable release.",
            file=sys.stderr,
        )
    return 0


def bump_version(current: str, topics: dict[str, list[str]]) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current)
    if match is None:
        raise SystemExit(f"project.version {current!r} is not MAJOR.MINOR.PATCH")
    major, minor, patch = (int(part) for part in match.groups())
    if current == "0.0.0" or topics["New"] or topics["Changed"]:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def cmd_cut(publish: bool) -> int:
    """Upgrade, test, and publish once the application suite exists.

    Until pyproject.toml is present there is nothing to test, so this command
    changes no files. T01 creates the suite and T01b finishes this command
    to the contract in docs/RELEASING.md.
    """
    summary, topics = parse_unreleased(CHANGELOG.read_text(encoding="utf-8"))
    sentences = summary_sentence_count(summary)
    if sentences < 1 or sentences > 3:
        raise SystemExit("Unreleased needs a one to three sentence summary before it can be cut")
    if not any(topics.values()):
        raise SystemExit("Unreleased has no New, Changed, Fixed, or Additional Notes bullets")
    if not (ROOT / "pyproject.toml").is_file():
        raise SystemExit(
            "Not cutting a release. pyproject.toml is not in the tree yet, "
            "so there is no suite to run against newer dependency versions. "
            "Use 'notes' to preview the announcement. T01 creates the project, "
            "and T01b finishes this command before it changes versions.toml."
        )
    doc = load_versions()
    new_version = bump_version(str(doc["project"]["version"]), topics)
    if publish:
        raise SystemExit(
            f"Publishing {new_version} arrives with T01b as 'release.py publish', "
            "after the upgrade-and-test loop. "
            "Refusing to upload from a tree that has not run that loop."
        )
    raise SystemExit(
        f"Would cut {new_version} after testing dependency upgrades. "
        "T01b finishes the upgrade loop that runs T01's suite."
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cut a segl release from versions.toml")
    parser.add_argument("command", choices=("check", "notes", "cut"))
    parser.add_argument(
        "--publish",
        action="store_true",
        help="with cut, upload a GitHub Release and publish to PyPI",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "check":
        return cmd_check()
    if args.command == "notes":
        return cmd_notes()
    return cmd_cut(publish=args.publish)


if __name__ == "__main__":
    raise SystemExit(main())
