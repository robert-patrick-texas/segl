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

"""Server settings: the TOML keys in docs/DEPLOY.md, and their defaults.

``segl --config PATH`` reads that file over the production defaults. Without
``--config``, segl uses the development defaults, and reads ``segl.toml`` from
the working directory when that file exists.
"""

import ipaddress
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from segl.access import (
    MAX_CODE_LENGTH,
    MIN_CODE_CHARACTERS,
    MIN_SECRET_CHARACTERS,
    letters_and_digits,
    normalize,
)

DEFAULT_BIND = "127.0.0.1:8888"

# Every key, with the value deploy/segl.toml.example ships.
DEFAULTS: Mapping[str, object] = {
    "bind": DEFAULT_BIND,
    "trusted_proxies": ["127.0.0.1", "::1"],
    "internal_networks": [],
    "access_codes": [],
    "access_secret": "",
    "access_pass_hours": 12,
    "access_passes_after": "",
    "database": "/opt/segl/var/segl.sqlite",
    "assets_dir": "/opt/segl/var/assets",
    "display_names": "/opt/segl/etc/display-names.txt",
    "web_dir": "/opt/segl/app/web/dist",
    "max_asset_bytes": 10485760,
    "max_scene_bytes": 52428800,
    "history_limit": 50,
    "history_interval_seconds": 1,
    "head_flush_seconds": 0.2,
}

# What differs without --config. The paths are relative to the working directory.
DEVELOPMENT_DEFAULTS: Mapping[str, object] = {
    "database": "var/segl.sqlite",
    "assets_dir": "var/assets",
    "display_names": "deploy/display-names.txt",
    "web_dir": "web/dist",
}

# Read from the working directory when --config is absent. Git ignores it.
DEVELOPMENT_FILE = Path("segl.toml")


class ConfigError(ValueError):
    """The configuration file has a value segl cannot use."""


@dataclass(frozen=True)
class Settings:
    """The settings the server runs with."""

    host: str
    port: int
    trusted_proxies: tuple[str, ...]
    # The networks segl answers, or none for every address (docs/SECURITY.md).
    internal_networks: tuple[str, ...]
    # The access codes, each in its normal form (segl.access.normalize). Kept
    # out of the repr, with the secret, so that a logged Settings carries neither.
    access_codes: tuple[str, ...] = field(repr=False)
    access_secret: str = field(repr=False)
    # How long a pass lasts from its issue, in hours. 0 is no limit.
    access_pass_hours: float
    # A pass issued before this time is refused. None for no such time.
    access_passes_after: datetime | None
    database: Path
    assets_dir: Path
    display_names: Path
    # The built web application, `web/dist` as Vite writes it.
    web_dir: Path
    max_asset_bytes: int
    max_scene_bytes: int
    history_limit: int
    history_interval_seconds: float
    head_flush_seconds: float

    @property
    def bind(self) -> str:
        """Return the bind address as ``host:port``, with an IPv6 host in brackets."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    @property
    def edit_required(self) -> bool:
        """Return whether a mutation needs a pass, which an access code buys."""
        return bool(self.access_codes)

    @property
    def access_pass_seconds(self) -> float | None:
        """Return how long a pass lasts, in seconds, or None for no limit."""
        return self.access_pass_hours * 3600 or None

    @property
    def access_passes_after_seconds(self) -> float | None:
        """Return ``access_passes_after`` in Unix seconds, or None."""
        after = self.access_passes_after
        return None if after is None else after.timestamp()


def parse_bind(value: object) -> tuple[str, int]:
    """Split ``host:port`` into its parts. An IPv6 host is written ``[::1]:8888``.

    Raises:
        ConfigError: When the value is not a host and a port from 1 to 65535.
    """
    if not isinstance(value, str):
        raise ConfigError(f"bind must be a string such as {DEFAULT_BIND!r}, not {value!r}")
    host, separator, port_text = value.rpartition(":")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    elif ":" in host:
        raise ConfigError(f"bind {value!r}: write an IPv6 host in brackets, as in '[::1]:8888'")
    if not separator or not host or not port_text.isascii() or not port_text.isdigit():
        raise ConfigError(f"bind {value!r} is not host:port")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise ConfigError(f"bind {value!r}: the port must be from 1 to 65535")
    return host, port


def parse_trusted_proxies(value: object) -> tuple[str, ...]:
    """Return the addresses and networks whose forwarded headers segl believes.

    An entry is an IP address or a network such as ``10.0.0.0/8``. An empty
    list believes nobody. ``*`` is refused: it would let any client choose the
    address segl records for it.

    Raises:
        ConfigError: When the value is not a list of addresses and networks.
    """
    if not isinstance(value, list):
        raise ConfigError(f"trusted_proxies must be a list of addresses, not {value!r}")
    proxies: list[str] = []
    for entry in value:
        try:
            if not isinstance(entry, str):
                raise ValueError
            # Strict: uvicorn would keep 10.0.0.1/8 as a name that matches nothing.
            parsed = ipaddress.ip_network(entry) if "/" in entry else ipaddress.ip_address(entry)
        except ValueError:
            raise ConfigError(
                f"trusted_proxies entry {entry!r} is not an IP address or a network"
            ) from None
        proxies.append(str(parsed))
    return tuple(proxies)


def parse_internal_networks(value: object) -> tuple[str, ...]:
    """Return the networks segl answers, each as ``ipaddress`` writes it.

    An entry is an IPv4 or IPv6 network in CIDR form, such as ``10.0.0.0/8``
    or ``2001:db8::/32``. One address is a network of that address alone. An
    empty list is no limit: segl answers every address.

    Raises:
        ConfigError: When the value is not a list of networks.
    """
    if not isinstance(value, list):
        raise ConfigError(f"internal_networks must be a list of networks, not {value!r}")
    networks: list[str] = []
    for entry in value:
        try:
            if not isinstance(entry, str):
                raise ValueError
            # Strict, as trusted_proxies is: 10.0.0.1/8 names a host, not a network.
            network = ipaddress.ip_network(entry.strip())
        except ValueError:
            raise ConfigError(
                f"internal_networks entry {entry!r} is not a network such as "
                "'10.0.0.0/8' or '2001:db8::/32'"
            ) from None
        networks.append(str(network))
    return tuple(networks)


def parse_access_codes(value: object) -> tuple[str, ...]:
    """Return the access codes in their normal form, in the list's order.

    A code is a word or a phrase of at least 8 ASCII letters and digits, and
    no two entries are one code once case and separators are set aside.

    Raises:
        ConfigError: When the value is not such a list. The message gives an
            entry's place in the list and never its text: it may be most of a
            real code.
    """
    if not isinstance(value, list):
        raise ConfigError("access_codes must be a list of codes, [] for none")
    codes: list[str] = []
    for place, entry in enumerate(value, start=1):
        where = f"access_codes entry {place}"
        if not isinstance(entry, str):
            raise ConfigError(f"{where} must be text, in quotes")
        if not entry.isascii():
            # A letter outside ASCII would count as a separator, and the code
            # would be a different one from what was written.
            raise ConfigError(f"{where} has a character outside ASCII")
        if len(entry) > MAX_CODE_LENGTH:
            raise ConfigError(f"{where} is longer than {MAX_CODE_LENGTH} characters")
        code = normalize(entry)
        if letters_and_digits(code) < MIN_CODE_CHARACTERS:
            raise ConfigError(
                f"{where} has fewer than {MIN_CODE_CHARACTERS} letters and digits, "
                "which is too easy to guess"
            )
        if code in codes:
            raise ConfigError(
                f"{where} is the same code as entry {codes.index(code) + 1}: "
                "case, spaces, and punctuation do not tell two codes apart"
            )
        codes.append(code)
    return tuple(codes)


_SECRET_HINT = "`openssl rand -base64 32` writes one"


def _access_secret(value: object, codes: tuple[str, ...]) -> str:
    # The messages leave the value out, as those about a code do.
    if not isinstance(value, str):
        raise ConfigError('access_secret must be text, "" for none')
    if value and len(value) < MIN_SECRET_CHARACTERS:
        raise ConfigError(
            f"access_secret must be at least {MIN_SECRET_CHARACTERS} characters: {_SECRET_HINT}"
        )
    if codes and not value:
        raise ConfigError(
            f"access_codes needs access_secret, which signs the passes: {_SECRET_HINT}"
        )
    return value


def _pass_hours(value: object) -> float:
    usable = not isinstance(value, bool) and isinstance(value, int | float)
    if not usable or not math.isfinite(value) or value < 0:
        raise ConfigError(
            f"access_pass_hours must be a number of hours, 0 for no limit, not {value!r}"
        )
    return float(value)


def _passes_after(value: object) -> datetime | None:
    if value == "":
        return None
    # A time without an offset would mean another moment on another server.
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ConfigError(
            "access_passes_after must be a time with its offset, such as "
            f'2026-11-12T15:00:00Z, or "" for none, not {value!r}'
        )
    return value


def _path(key: str, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a path, not {value!r}")
    return Path(value)


def _count(key: str, value: object) -> int:
    # bool is an int in Python, and `true` is not a count.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{key} must be a whole number, 1 or more, not {value!r}")
    return value


def _seconds(key: str, value: object) -> float:
    usable = not isinstance(value, bool) and isinstance(value, int | float)
    # TOML also has inf and nan, and a timer cannot wait for either.
    if not usable or not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{key} must be a number of seconds above 0, not {value!r}")
    return float(value)


# The one static token of an earlier build, which no release shipped (D2-033).
_REPLACED = "edit_token"


def _read(path: Path) -> dict[str, object]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        # A misspelled access_codes would otherwise leave the slots open to edits.
        known = ", ".join(DEFAULTS)
        message = f"{path}: unknown key {', '.join(unknown)}. The keys are: {known}"
        if _REPLACED in unknown:
            message += (
                f". {_REPLACED} is gone: list access codes in access_codes, "
                "with access_secret (docs/DEPLOY.md)"
            )
        raise ConfigError(message)
    return data


def load_settings(path: Path | None = None) -> Settings:
    """Return the settings for ``--config path``, or for no ``--config``.

    With a path, the file's keys replace the production defaults, and a path
    that does not exist gives those defaults. Without one, ``segl.toml`` in the
    working directory, when present, replaces the development defaults.

    Raises:
        ConfigError: When the file is not valid TOML, has a key segl does not
            know, or has a value segl cannot use.
    """
    values = dict(DEFAULTS)
    if path is None:
        values.update(DEVELOPMENT_DEFAULTS)
        path = DEVELOPMENT_FILE
    if path.is_file():
        values.update(_read(path))
    host, port = parse_bind(values["bind"])
    codes = parse_access_codes(values["access_codes"])
    return Settings(
        host=host,
        port=port,
        trusted_proxies=parse_trusted_proxies(values["trusted_proxies"]),
        internal_networks=parse_internal_networks(values["internal_networks"]),
        access_codes=codes,
        access_secret=_access_secret(values["access_secret"], codes),
        access_pass_hours=_pass_hours(values["access_pass_hours"]),
        access_passes_after=_passes_after(values["access_passes_after"]),
        database=_path("database", values["database"]),
        assets_dir=_path("assets_dir", values["assets_dir"]),
        display_names=_path("display_names", values["display_names"]),
        web_dir=_path("web_dir", values["web_dir"]),
        max_asset_bytes=_count("max_asset_bytes", values["max_asset_bytes"]),
        max_scene_bytes=_count("max_scene_bytes", values["max_scene_bytes"]),
        history_limit=_count("history_limit", values["history_limit"]),
        history_interval_seconds=_seconds(
            "history_interval_seconds", values["history_interval_seconds"]
        ),
        head_flush_seconds=_seconds("head_flush_seconds", values["head_flush_seconds"]),
    )
