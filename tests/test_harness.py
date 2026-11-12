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


"""What the harness says when a server keeps a test waiting.

A handshake that is not answered, and a server that does not stop, used to
leave nothing to read: the test failed with the client's timeout, or passed
after a silent SIGKILL. Both now quote the servers' logs.
"""

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import warnings
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

import harness
import pytest
from harness import BOARD_SITE, NginxTools, log_tails, open_socket, running_mount, running_segl
from websockets.exceptions import InvalidStatus


@pytest.fixture
def silent_port() -> Iterator[int]:
    """A port where something accepts a connection and never answers it."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        yield listener.getsockname()[1]


@contextmanager
def frozen(process: subprocess.Popen[bytes], seconds: float) -> Generator[None]:
    """Stop a server where it stands for ``seconds``, as a host that stalls would.

    It is there and does not answer. A timer lets it go, not the end of the
    block: through nginx, the client that gave up on a handshake waits for
    the connection to end before it raises, and nginx keeps the connection
    for as long as segl is silent, up to its two-minute timeout.
    """
    os.kill(process.pid, signal.SIGSTOP)
    thaw = threading.Timer(seconds, os.kill, (process.pid, signal.SIGCONT))
    thaw.start()
    try:
        yield
    finally:
        thaw.cancel()
        thaw.join()
        os.kill(process.pid, signal.SIGCONT)


def test_the_end_of_each_log_is_quoted_under_its_name(tmp_path: Path) -> None:
    long = tmp_path / "segl.log"
    long.write_text("".join(f"line {number}\n" for number in range(1, 101)), encoding="utf-8")
    short = tmp_path / "error.log"
    short.write_text("upstream timed out\n", encoding="utf-8")

    text = log_tails({"segl": long, "nginx error.log": short})

    lines = text.splitlines()
    assert lines[0] == f"--- segl ({long}), the last 40 of 100 lines:"
    assert lines[1:41] == [f"line {number}" for number in range(61, 101)]
    assert lines[41] == f"--- nginx error.log ({short}), the last 1 of 1 lines:"
    assert lines[42:] == ["upstream timed out"]


def test_a_log_that_is_empty_or_missing_is_said_to_be(tmp_path: Path) -> None:
    empty = tmp_path / "access.log"
    empty.write_text("", encoding="utf-8")
    missing = tmp_path / "absent.log"

    text = log_tails({"nginx access.log": empty, "segl": missing})

    assert f"--- nginx access.log ({empty}): empty" in text
    assert f"--- segl ({missing}): cannot be read: " in text
    assert log_tails({}) == ""


def test_a_log_that_is_not_text_is_still_quoted(tmp_path: Path) -> None:
    log = tmp_path / "segl.log"
    log.write_bytes(b"started\n\xff\xfe not utf-8\n")

    assert "started" in log_tails({"segl": log})


def test_a_handshake_that_is_not_answered_fails_with_the_logs(
    silent_port: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "HANDSHAKE_SECONDS", 0.3)
    log = tmp_path / "segl.log"
    log.write_text("INFO:     Application startup complete.\n", encoding="utf-8")
    began = time.monotonic()

    with pytest.raises(AssertionError) as failure:
        open_socket(silent_port, "/collab?slot=1", logs={"segl": log})

    assert time.monotonic() - began < 5
    message = str(failure.value)
    assert message.startswith(
        f"the WebSocket handshake for /collab?slot=1 on port {silent_port} was not answered "
        "in 0.3 seconds (timed out"
    )
    assert f"--- segl ({log}), the last 1 of 1 lines:" in message
    assert "Application startup complete." in message
    # The client's own error is kept as the cause.
    assert isinstance(failure.value.__cause__, TimeoutError)


def test_a_handshake_that_is_not_answered_fails_without_logs_too(
    silent_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "HANDSHAKE_SECONDS", 0.3)

    with pytest.raises(AssertionError, match=r"was not answered in 0\.3 seconds"):
        open_socket(silent_port, "/collab?slot=1")


def test_a_running_servers_socket_names_its_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with running_segl(tmp_path) as server:
        monkeypatch.setattr(harness, "HANDSHAKE_SECONDS", 0.5)
        with frozen(server.process, 1.5), pytest.raises(AssertionError) as failure:
            server.socket("/collab?slot=1")

        message = str(failure.value)
        assert f"--- segl ({server.log_file}), the last " in message
        # What segl had logged: it started, and answered the health check.
        assert "Uvicorn running on" in message
        assert "GET /api/v1/health" in message
        monkeypatch.setattr(harness, "HANDSHAKE_SECONDS", 10.0)
        # Let go again, it answers, and stops when it is told to.
        with server.socket("/collab?slot=1") as socket_:
            assert harness.say_hello(socket_)[0]["slot"] == 1


def test_a_socket_through_nginx_that_is_not_answered_fails_with_all_three_logs(
    tools: NginxTools,
    certificate: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CI failure of 2026-11-12, made on purpose: nginx is up, and segl does not answer."""
    with running_mount(tools, certificate, tmp_path) as mount:
        # One request first, so that nginx's access log has a line.
        assert mount.get(BOARD_SITE, "/board/api/v1/health").status == 200
        monkeypatch.setattr(harness, "HANDSHAKE_SECONDS", 0.5)
        began = time.monotonic()
        with frozen(mount.segl.process, 1.5), pytest.raises(AssertionError) as failure:
            mount.socket(BOARD_SITE, "/board/collab?slot=1", origin=mount.origin(BOARD_SITE))
        # Not nginx's two minutes: the failure came once segl was let go.
        assert time.monotonic() - began < 30

        message = str(failure.value)
        assert message.startswith(
            f"the WebSocket handshake for /board/collab?slot=1 on port {mount.https_port} "
            "was not answered in 0.5 seconds"
        )
        assert f"--- nginx error.log ({mount.prefix / 'error.log'})" in message
        assert f"--- nginx access.log ({mount.prefix / 'access.log'}), the last " in message
        assert "GET /board/api/v1/health" in message
        assert f"--- segl ({mount.segl.log_file}), the last " in message
        # segl saw the health check with /board stripped.
        assert "GET /api/v1/health" in message


def test_a_refused_handshake_is_still_the_clients_own_error(tmp_path: Path) -> None:
    # Only a timeout is turned into a failure with logs. The tests of the
    # Origin check read the refusal's status and body.
    with running_segl(tmp_path) as server, pytest.raises(InvalidStatus) as refused:
        server.socket("/collab?slot=1", origin="https://evil.example")

    assert refused.value.response.status_code == 403


def stubborn(tmp_path: Path) -> tuple[subprocess.Popen[bytes], Path]:
    """Start a process that ignores SIGTERM, and return it once it does."""
    log = tmp_path / "stubborn.log"
    script = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('ignoring SIGTERM', flush=True)\n"
        "time.sleep(60)\n"
    )
    with log.open("wb") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", script], stdout=output, stderr=subprocess.STDOUT
        )
    deadline = time.monotonic() + 10
    while "ignoring SIGTERM" not in log.read_text(encoding="utf-8"):
        assert time.monotonic() < deadline, "the process did not start"
        time.sleep(0.02)
    return process, log


def test_a_server_that_had_to_be_killed_is_said_so_with_its_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "STOP_SECONDS", 0.3)
    process, log = stubborn(tmp_path)

    with pytest.warns(UserWarning) as caught:
        harness._stop(process, "segl", log)

    # It is gone all the same: by SIGKILL.
    assert process.returncode == -signal.SIGKILL
    (warning,) = caught
    message = str(warning.message)
    assert message.startswith("segl had not stopped 0.3 seconds after SIGTERM and was killed")
    assert f"--- segl ({log}), the last 1 of 1 lines:" in message
    assert "ignoring SIGTERM" in message


def test_a_server_that_stops_when_told_to_says_nothing(tmp_path: Path) -> None:
    log = tmp_path / "quiet.log"
    with log.open("wb") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=output
        )

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        harness._stop(process, "segl", log)

    assert process.returncode == -signal.SIGTERM


def test_a_real_server_stops_without_being_killed(tmp_path: Path) -> None:
    # segl's own stop, through the harness: no warning, and no SIGKILL.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with running_segl(tmp_path) as server:
            assert server.get("/api/v1/health").status == 200
    # uvicorn runs its shutdown, and then ends by the signal it was sent.
    assert server.process.returncode == -signal.SIGTERM
