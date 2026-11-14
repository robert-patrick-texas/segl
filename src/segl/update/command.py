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

"""The commands beside serving: ``segl check``, ``segl config merge``, ``segl update``."""

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

from segl.config import ConfigError, Settings, load_settings
from segl.names import DisplayNamesError, load_display_names
from segl.update.merge import Merge
from segl.update.paths import INSTALLED
from segl.update.process import run_command
from segl.update.releases import Https, proxy_problem, shown_proxy
from segl.update.updater import Confirm, UpdateError, Updater
from segl.update.versions import Version
from segl.versions import app_version
from segl.web import WebBuildError, load_web_build

USAGE = 2


def _config_option(parser: argparse.ArgumentParser) -> None:
    # A command's own --config is left out of its result unless it was given,
    # so one written before the command still counts.
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        default=argparse.SUPPRESS,
        help=f"the settings file (default {INSTALLED.config_file})",
    )


def add_commands(parser: argparse.ArgumentParser) -> None:
    """Add the three commands to the ``segl`` parser."""
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", title="commands")

    check = commands.add_parser(
        "check",
        help="read the settings as the server would, and report",
        description="Read the settings file, the display names, and the web application as "
        "the server does when it starts, and say what is wrong. It changes nothing and "
        "does not open the database.",
    )
    _config_option(check)

    group = commands.add_parser("config", help="work on the settings and the nginx files")
    actions = group.add_subparsers(dest="config_command", metavar="ACTION", required=True)
    merge = actions.add_parser(
        "merge",
        help="add this version's new statements to the settings and the nginx files",
        description="Add the settings this version brought to the settings file, and merge "
        "what it changed in its nginx files into the site's copies in /etc/nginx. Every "
        "line the site wrote stays. Without --write it only says what it would do.",
    )
    _config_option(merge)
    merge.add_argument("--write", action="store_true", help="change the files")

    update = commands.add_parser(
        "update",
        help="install a newer signed release, as root",
        description="Install the newest signed release if it is newer than this one. The "
        "settings and the database are saved first, and the previous version goes back "
        "if the new one fails its checks.",
    )
    _config_option(update)
    update.add_argument(
        "--check",
        action="store_true",
        help="only say whether a newer release is out (exit status 100 when one is)",
    )
    update.add_argument("--yes", action="store_true", help="install without asking")
    update.add_argument(
        "--auto",
        action="store_true",
        help="for the timer: install a newer release without asking, unless it failed "
        "to install last time",
    )
    update.add_argument(
        "--version",
        dest="target",
        metavar="VERSION",
        help="install this release, even if it is older or the same",
    )
    update.add_argument(
        "--from",
        dest="source",
        type=Path,
        metavar="FOLDER",
        help="install the release whose package, SHA256SUMS, and SHA256SUMS.sig are in "
        "this folder, with no download",
    )
    update.add_argument(
        "--proxy",
        metavar="URL",
        help="reach GitHub through this proxy, as in http://proxy.example.com:3128/ "
        "(default: update_proxy in the settings, then https_proxy)",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Run the command that was parsed, and return its exit status."""
    config = args.config or INSTALLED.config_file
    try:
        if args.command == "check":
            return check(config)
        if args.command == "config":
            merge = Merge(replace(INSTALLED, config_file=config), run_command)
            return merge.apply(write=args.write)
        return update(parser, args, config)
    except PermissionError as exc:
        print(f"segl: {exc.filename}: permission denied. Run it with sudo.", file=sys.stderr)
        return USAGE


def _settings(config: Path) -> Settings | None:
    try:
        return load_settings(config)
    except ConfigError as exc:
        print(f"segl: {exc}", file=sys.stderr)
        return None


def check(config: Path) -> int:
    """Read what the server reads when it starts. Return 0, or 2 for a setting, or 1."""
    settings = _settings(config)
    if settings is None:
        return USAGE
    try:
        words = load_display_names(settings.display_names)
        build = load_web_build(settings.web_dir)
    except (DisplayNamesError, WebBuildError) as exc:
        print(f"segl: {exc}", file=sys.stderr)
        return 1
    if not config.is_file():
        print(f"segl check: {config} does not exist, so every setting has its default")
    web = "the web application" if build else "no web application (the API only)"
    print(f"segl check: ok: the settings, {len(words)} display names, and {web}")
    return 0


def _asker(yes: bool) -> Confirm:
    """Return what asks at the terminal. Without a terminal, the answer is no."""

    def ask(question: str) -> bool:
        if yes:
            return True
        if not sys.stdin.isatty():
            print(f"{question} There is no terminal to ask at: add --yes to go ahead.")
            return False
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")

    return ask


def version_url(settings: Settings) -> str:
    """Return the address of segl's version route on this host."""
    host = settings.host
    if host in ("", "0.0.0.0"):
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    host = f"[{host}]" if ":" in host else host
    return f"http://{host}:{settings.port}/api/v1/version"


def update(parser: argparse.ArgumentParser, args: argparse.Namespace, config: Path) -> int:
    """Check for, or install, a release."""
    if args.auto and (args.check or args.target or args.source):
        parser.error("--auto goes with none of --check, --version, and --from")
    if args.source and (args.check or args.target):
        parser.error("--from goes with neither --check nor --version")
    if args.proxy and (why := proxy_problem(args.proxy)):
        parser.error(f"--proxy: {why}")
    try:
        target = Version.parse(args.target) if args.target else None
    except ValueError as exc:
        parser.error(f"--version: {exc}")
    settings = _settings(config)
    if settings is None:
        return USAGE
    proxy = args.proxy or settings.update_proxy
    if proxy and not args.source:
        print(f"Through the proxy {shown_proxy(proxy)}.")
    paths = replace(INSTALLED, config_file=config)
    updater = Updater(
        paths=paths,
        installed=Version.parse(app_version()),
        update_url=settings.update_url,
        version_url=version_url(settings),
        database=settings.database,
        http=Https(proxy),
    )
    if args.check:
        return updater.check(target)
    if not paths.signers.is_file():
        print(
            "segl update: segl is not installed from its package here. "
            "It updates an installed package.",
            file=sys.stderr,
        )
        return USAGE
    if os.geteuid() != 0:
        print("segl update: installing needs root: sudo segl update", file=sys.stderr)
        return USAGE
    try:
        if args.source:
            return updater.install_from(args.source, _asker(args.yes))
        return updater.update(target, _asker(args.yes or args.auto), auto=args.auto)
    except UpdateError as exc:
        print(f"segl update: {exc}", file=sys.stderr)
        return 1
