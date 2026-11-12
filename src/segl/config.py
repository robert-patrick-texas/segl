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
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BIND = "127.0.0.1:8888"

# Every key, with the value deploy/segl.toml.example ships.
DEFAULTS: Mapping[str, object] = {
    "bind": DEFAULT_BIND,
    "trusted_proxies": ["127.0.0.1", "::1"],
    "edit_token": "",
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
    # Kept out of the repr so that a logged Settings does not carry the token.
    edit_token: str = field(repr=False)
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
        """Return whether a mutation needs the edit token."""
        return bool(self.edit_token)


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


# What a browser can send whole in the X-Segl-Edit-Token header: printable
# ASCII, space to tilde. A header loses a space at either end, and a browser
# refuses to send any other character, or sends it in an encoding of its own.
# web/src/editToken.ts has the same rule, and tests/edit_token_cases.json
# holds both to one table.
_EDIT_TOKEN = re.compile(r"[\x21-\x7e](?:[\x20-\x7e]{0,254}[\x21-\x7e])?")


def is_edit_token(text: str) -> bool:
    """Return whether ``text`` can be an edit token (docs/DEPLOY.md)."""
    return _EDIT_TOKEN.fullmatch(text) is not None


def _edit_token(value: object) -> str:
    # The messages leave the value out: it may be most of a real token.
    if not isinstance(value, str):
        raise ConfigError('edit_token must be a string, "" for none')
    if value and not is_edit_token(value):
        raise ConfigError(
            "edit_token must be 1 to 256 printable ASCII characters, with no space at "
            'either end, or "" for none: a browser sends it in a request header'
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


def _read(path: Path) -> dict[str, object]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        # A misspelled edit_token would otherwise leave the slots open to edits.
        known = ", ".join(DEFAULTS)
        raise ConfigError(f"{path}: unknown key {', '.join(unknown)}. The keys are: {known}")
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
    return Settings(
        host=host,
        port=port,
        trusted_proxies=parse_trusted_proxies(values["trusted_proxies"]),
        edit_token=_edit_token(values["edit_token"]),
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
