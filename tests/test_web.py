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

"""The web application as Python serves it: the page for ``/`` and ``/s/N``
with URLs relative to that page, the injected config, and the build's files
(docs/ARCHITECTURE.md, "Mount and navigation").

These tests use a small stand-in for ``web/dist``, shaped as Vite writes it.
The browser tests in ``web/e2e`` run against the real build.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from harness import (
    DISPLAY_NAMES_FILE,
    GATED,
    ROOT,
    assert_no_secrets,
    make_settings,
    running_segl,
)

from segl import cli
from segl.app import create_app
from segl.repository import Repository
from segl.web import WebBuildError, load_web_build, page_config, render_page

# index.html as `vite build` writes it with `base: './'`.
INDEX = """\
<!doctype html>
<html lang="en">
\t<head>
\t\t<meta charset="utf-8" />
\t\t<title>segl</title>
\t\t<link rel="icon" href="./favicon.svg" type="image/svg+xml" />
\t\t<script type="module" crossorigin src="./assets/index-Dw_CZwxO.js"></script>
\t\t<link rel="modulepreload" crossorigin href="./assets/react-dom-DhMY2cgr.js">
\t\t<link rel="stylesheet" crossorigin href="./assets/index-DJbIRlYD.css">
\t</head>
\t<body>
\t\t<div id="root"></div>
\t</body>
</html>
"""
SCRIPT = "export const segl = 1;\n"
CONFIG = re.compile(r"<script>window\.SEGL_CONFIG = (\{.*?\});</script>")
# Every URL an element of the page loads.
URLS = re.compile(r'\b(?:src|href)="([^"]*)"')


def make_build(folder: Path) -> Path:
    """Write a stand-in for web/dist and return it."""
    (folder / "assets").mkdir(parents=True)
    (folder / "fonts" / "Virgil").mkdir(parents=True)
    (folder / "index.html").write_text(INDEX, encoding="utf-8")
    (folder / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", "utf-8")
    (folder / "assets" / "index-Dw_CZwxO.js").write_text(SCRIPT, encoding="utf-8")
    (folder / "assets" / "index-DJbIRlYD.css").write_text("body { margin: 0 }\n", "utf-8")
    (folder / "fonts" / "Virgil" / "Virgil-Regular.woff2").write_bytes(b"wOF2 not a real font")
    return folder


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    return make_build(tmp_path / "dist")


@pytest.fixture
def client(repository: Repository, web_dir: Path) -> TestClient:
    return TestClient(create_app(make_settings(web_dir=web_dir), repository))


def injected(page: str) -> dict[str, object]:
    """Return the one ``SEGL_CONFIG`` a page sets."""
    (found,) = CONFIG.findall(page)
    return json.loads(found)


def test_the_root_page_keeps_its_urls_and_gets_its_config() -> None:
    page = render_page(INDEX, root="./", edit_required=False)

    assert URLS.findall(page) == URLS.findall(INDEX)
    assert injected(page) == {"root": "./", "editRequired": False}
    assert page.replace(page_config("./", False) + "\n", "") == INDEX


def test_a_slot_page_names_its_files_one_level_up() -> None:
    page = render_page(INDEX, root="../", edit_required=True)

    assert URLS.findall(page) == [
        "../favicon.svg",
        "../assets/index-Dw_CZwxO.js",
        "../assets/react-dom-DhMY2cgr.js",
        "../assets/index-DJbIRlYD.css",
    ]
    assert injected(page) == {"root": "../", "editRequired": True}


def test_the_config_is_set_inside_head_before_the_page_body() -> None:
    page = render_page(INDEX, root="../", edit_required=False)

    assert page.index("window.SEGL_CONFIG") < page.index("</head>") < page.index("<body>")
    assert page.count("window.SEGL_CONFIG") == 1


def test_the_config_script_cannot_be_ended_from_inside() -> None:
    assert "<" not in page_config("</script><script>alert(1)", False).removeprefix(
        "<script>"
    ).removesuffix("</script>")


@pytest.mark.parametrize(
    ("path", "root"),
    [
        ("/", "./"),
        ("/s", "./"),
        # The access page is at segl's root, as `/` is.
        ("/access", "./"),
        ("/s/", "../"),
        ("/s/1", "../"),
        ("/s/9", "../"),
    ],
)
def test_a_page_knows_the_way_to_segls_root(client: TestClient, path: str, root: str) -> None:
    reply = client.get(path)

    assert reply.status_code == 200
    assert reply.headers["content-type"] == "text/html; charset=utf-8"
    assert injected(reply.text) == {"root": root, "editRequired": False}
    assert all(url.startswith(root) for url in URLS.findall(reply.text))


@pytest.mark.parametrize("path", ["/", "/s/1", "/access"])
def test_no_url_in_a_page_starts_at_the_host_root(client: TestClient, path: str) -> None:
    """One build serves every mount point: nothing names a path from ``/`` (D2-007)."""
    urls = URLS.findall(client.get(path).text)

    assert urls
    assert not [url for url in urls if url.startswith("/") or "://" in url]


@pytest.mark.parametrize("path", ["/s/0", "/s/10", "/s/abc", "/s/01"])
def test_a_slot_that_does_not_exist_still_gets_the_page(client: TestClient, path: str) -> None:
    """The page sends it to slot 1. The API, not the page route, says invalid_slot."""
    reply = client.get(path)

    assert reply.status_code == 200
    assert injected(reply.text)["root"] == "../"


@pytest.mark.parametrize(
    "path",
    ["/s/1/", "/s/1/history", "/t/1", "/index.html", "/board/s/1", "/access/", "/access/1"],
)
def test_other_paths_are_not_pages(client: TestClient, path: str) -> None:
    reply = client.get(path)

    assert (reply.status_code, reply.json()["error"]) == (404, "not_found")


def test_the_page_says_a_code_is_needed_and_holds_none(
    repository: Repository, web_dir: Path
) -> None:
    settings = make_settings(web_dir=web_dir, **GATED)
    client = TestClient(create_app(settings, repository))

    for path in ("/", "/s/1", "/access"):
        page = client.get(path).text
        assert injected(page)["editRequired"] is True
        assert_no_secrets(page, path)


@pytest.mark.parametrize(
    "path", ["/", "/s/1", "/access", "/favicon.svg", "/assets/index-Dw_CZwxO.js"]
)
def test_the_web_application_sets_no_cookie(client: TestClient, path: str) -> None:
    assert "set-cookie" not in client.get(path).headers


def test_a_page_is_checked_again_after_an_upgrade(client: TestClient) -> None:
    assert client.get("/s/1").headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("/assets/index-Dw_CZwxO.js", "text/javascript"),
        ("/assets/index-DJbIRlYD.css", "text/css"),
        ("/fonts/Virgil/Virgil-Regular.woff2", "font/woff2"),
        ("/favicon.svg", "image/svg+xml"),
    ],
)
def test_the_builds_files_are_served_with_their_types(
    client: TestClient, path: str, media_type: str
) -> None:
    reply = client.get(path)

    assert reply.status_code == 200
    # A browser refuses a module script that is not served as JavaScript.
    assert reply.headers["content-type"].split(";")[0] == media_type


@pytest.mark.parametrize(
    "path",
    ["/assets/absent.js", "/assets/", "/assets", "/fonts/Virgil/", "/assets/../index.html"],
)
def test_a_file_the_build_lacks_is_an_error_in_the_api_shape(client: TestClient, path: str) -> None:
    reply = client.get(path)

    assert (reply.status_code, reply.json()["error"]) == (404, "not_found")


def test_a_build_cannot_reach_outside_its_folder(
    repository: Repository, web_dir: Path, tmp_path: Path
) -> None:
    (tmp_path / "secret.toml").write_text('access_secret = "correct-horse"\n', encoding="utf-8")
    (web_dir / "assets" / "link.toml").symlink_to(tmp_path / "secret.toml")
    (web_dir / "linked").symlink_to(tmp_path)
    client = TestClient(create_app(make_settings(web_dir=web_dir), repository))

    for path in ("/assets/link.toml", "/linked/secret.toml", "/assets/%2e%2e/%2e%2e/secret.toml"):
        reply = client.get(path)
        assert reply.status_code == 404, path
        assert "correct-horse" not in reply.text


def test_a_build_cannot_shadow_the_api_or_the_slots(repository: Repository, web_dir: Path) -> None:
    for name in ("api", "s"):
        (web_dir / name / "v1").mkdir(parents=True)
        (web_dir / name / "v1" / "health").write_text("shadowed", encoding="utf-8")
        (web_dir / name / "1").write_text("shadowed", encoding="utf-8")
    client = TestClient(create_app(make_settings(web_dir=web_dir), repository))

    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert "SEGL_CONFIG" in client.get("/s/1").text


def test_the_build_is_listed_without_its_index_and_hidden_entries(web_dir: Path) -> None:
    (web_dir / ".vite").mkdir()
    (web_dir / ".DS_Store").write_text("", encoding="utf-8")

    build = load_web_build(web_dir)

    assert build is not None
    assert (build.folders, build.files) == (("assets", "fonts"), ("favicon.svg",))
    assert build.index == INDEX


def test_a_folder_without_a_build_serves_the_api_alone(
    repository: Repository, tmp_path: Path
) -> None:
    assert load_web_build(tmp_path / "absent") is None
    (tmp_path / "empty").mkdir()
    assert load_web_build(tmp_path / "empty") is None
    client = TestClient(create_app(make_settings(web_dir=tmp_path / "absent"), repository))

    assert client.get("/api/v1/health").json() == {"status": "ok"}
    for path in ("/", "/s/1", "/access", "/assets/index.js"):
        reply = client.get(path)
        assert (reply.status_code, reply.json()["error"]) == (404, "not_found")


def test_an_index_that_is_not_a_build_stops_the_application(
    repository: Repository, tmp_path: Path
) -> None:
    (tmp_path / "index.html").write_text("<p>not a build</p>", encoding="utf-8")

    with pytest.raises(WebBuildError, match="has no </head>"):
        create_app(make_settings(web_dir=tmp_path), repository)


def test_the_command_refuses_an_index_that_is_not_a_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<p>not a build</p>", encoding="utf-8")
    config = tmp_path / "segl.toml"
    config.write_text(
        f'database = "{tmp_path / "segl.sqlite"}"\nweb_dir = "{tmp_path / "web"}"\n'
        f'display_names = "{DISPLAY_NAMES_FILE}"\n',
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config)]) == 1
    assert "has no </head>" in capsys.readouterr().err


def test_the_process_serves_the_page_and_its_files(tmp_path: Path) -> None:
    web_dir = make_build(tmp_path / "dist")

    with running_segl(tmp_path / "segl", f'web_dir = "{web_dir}"\n') as server:
        page = server.get("/s/2")
        script = server.get("/assets/index-Dw_CZwxO.js")

        assert (page.status, injected(page.body.decode())) == (
            200,
            {"root": "../", "editRequired": False},
        )
        assert (script.status, script.body.decode()) == (200, SCRIPT)
        assert page.headers["Set-Cookie"] is None
        assert "no web application" not in server.log()


def test_the_process_says_when_it_has_no_web_application(tmp_path: Path) -> None:
    with running_segl(tmp_path / "segl", f'web_dir = "{tmp_path / "absent"}"\n') as server:
        assert server.get("/api/v1/health").status == 200
        assert server.get("/").status == 404
        line = server.logged_line("no web application")

    assert str(tmp_path / "absent") in line
    assert "serving the API only" in line


def test_the_stand_in_matches_what_vite_writes() -> None:
    """Hold the stand-in to the real build when there is one in web/dist."""
    built = ROOT / "web" / "dist" / "index.html"
    if not built.is_file():
        pytest.skip("web/dist is not built: `npm --prefix web run build`")
    urls = URLS.findall(built.read_text(encoding="utf-8"))

    assert urls
    assert all(url.startswith("./") for url in urls), urls
    assert "</head>" in built.read_text(encoding="utf-8")
