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

"""Server settings from the TOML file named by ``--config``.

This task reads ``bind`` only. T02 adds the remaining keys in docs/DEPLOY.md.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BIND = "127.0.0.1:8000"


class ConfigError(ValueError):
    """The configuration file has a value segl cannot use."""


@dataclass(frozen=True)
class Settings:
    """The settings the server runs with."""

    host: str
    port: int

    @property
    def bind(self) -> str:
        """Return the bind address as ``host:port``, with an IPv6 host in brackets."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"


def parse_bind(value: object) -> tuple[str, int]:
    """Split ``host:port`` into its parts. An IPv6 host is written ``[::1]:8000``.

    Raises:
        ConfigError: When the value is not a host and a port from 1 to 65535.
    """
    if not isinstance(value, str):
        raise ConfigError(f"bind must be a string such as {DEFAULT_BIND!r}, not {value!r}")
    host, separator, port_text = value.rpartition(":")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    elif ":" in host:
        raise ConfigError(f"bind {value!r}: write an IPv6 host in brackets, as in '[::1]:8000'")
    if not separator or not host or not port_text.isascii() or not port_text.isdigit():
        raise ConfigError(f"bind {value!r} is not host:port")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise ConfigError(f"bind {value!r}: the port must be from 1 to 65535")
    return host, port


def load_settings(path: Path | None = None) -> Settings:
    """Return the settings from ``path``, or the defaults.

    A path that does not exist gives the defaults, so health still answers.

    Raises:
        ConfigError: When the file is not valid TOML or ``bind`` is unusable.
    """
    data: dict[str, object] = {}
    if path is not None and path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    host, port = parse_bind(data.get("bind", DEFAULT_BIND))
    return Settings(host=host, port=port)
