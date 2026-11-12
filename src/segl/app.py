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

"""The segl ASGI application. Routes follow docs/API.md."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from segl.config import Settings
from segl.names import AllocationLimit, load_display_names, retry_after
from segl.repository import InvalidSlot, Repository, Slot
from segl.versions import app_version
from segl.web import ROOT_PAGE, SLOT_PAGE, WebBuild, load_web_build, render_page

# The only texts that name a slot. int() would also take "01", "+1", and the
# digits of other scripts.
_SLOT_TEXTS = {str(number): number for number in range(1, 10)}


def _error(status: int, code: str, message: str, headers: Any = None) -> JSONResponse:
    """Return an error in the one shape docs/API.md gives."""
    return JSONResponse({"error": code, "message": message}, status_code=status, headers=headers)


def _slot_number(text: str) -> int:
    """Return the slot a path segment names.

    Raises:
        InvalidSlot: When the segment is not one of ``1`` to ``9``.
    """
    try:
        return _SLOT_TEXTS[text]
    except KeyError:
        raise InvalidSlot(text) from None


def _slot_json(slot: Slot) -> dict[str, object]:
    return {
        "number": slot.number,
        "title": slot.title,
        "epoch": slot.epoch,
        "savedAt": slot.saved_at,
    }


def _add_web_routes(app: FastAPI, build: WebBuild, edit_required: bool) -> None:
    """Serve the web application: the pages, then the files the build emitted."""
    # Made once. A new build, or a new token, takes a restart.
    pages = {
        root: render_page(build.index, root=root, edit_required=edit_required)
        for root in (ROOT_PAGE, SLOT_PAGE)
    }

    def page(root: str) -> HTMLResponse:
        # The page names its files by content hash, so it is the one response
        # a browser must ask for again after an upgrade.
        return HTMLResponse(pages[root], headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    @app.get("/s", include_in_schema=False)
    def root_page() -> HTMLResponse:
        return page(ROOT_PAGE)

    # Any one segment after /s/ gets the page, and the page sends a segment
    # that is not 1 to 9 to slot 1 (docs/ARCHITECTURE.md). A deeper path is
    # not a page: its root would be two levels up.
    @app.get("/s/", include_in_schema=False)
    @app.get("/s/{n}", include_in_schema=False)
    def slot_page() -> HTMLResponse:
        return page(SLOT_PAGE)

    # Only what the build holds is registered (docs/API.md, "Reserved paths"):
    # Vite's assets/, the editor's fonts/, and the favicon. They come after
    # every other route, so a build cannot shadow /api, /s, or /collab.
    for name in build.files:
        app.add_api_route(
            f"/{name}",
            lambda file=build.folder / name: FileResponse(file),
            methods=["GET"],
            include_in_schema=False,
        )
    for name in build.folders:
        app.mount(f"/{name}", StaticFiles(directory=build.folder / name), name=f"web-{name}")


def create_app(settings: Settings, repository: Repository) -> FastAPI:
    """Build the application for these settings, over a bootstrapped repository.

    The application closes the repository when it shuts down. It serves the
    web application when ``settings.web_dir`` holds a build, and the API alone
    when it does not. The display-name words are read here, once, so a
    replaced file takes a restart.

    Raises:
        DisplayNamesError: When ``display_names`` is missing or has no usable words.
        WebBuildError: When ``web_dir`` has an ``index.html`` segl cannot use.
    """
    words = load_display_names(settings.display_names)
    allocation_limit = AllocationLimit()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        yield
        # The one place that runs on every stop. After SIGTERM, uvicorn ends
        # the process as soon as this returns, so code after uvicorn.run does
        # not run. Closing folds the write-ahead log back into the database file.
        repository.close()

    # FastAPI's generated documentation pages are off. docs/API.md is the
    # contract, and those pages use absolute URLs that a path mount would break.
    #
    # The trailing-slash redirect is off for the same reason. It is absolute,
    # built from the path segl sees, so under /board/ it would send the browser
    # outside the mount. Any redirect segl does send must be relative.
    app = FastAPI(
        title="segl",
        version=app_version(),
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.display_names = words
    web_build = load_web_build(settings.web_dir)
    app.state.web_build = web_build

    @app.exception_handler(InvalidSlot)
    async def invalid_slot(request: Request, exc: InvalidSlot) -> JSONResponse:
        return _error(404, "invalid_slot", "Slots are numbered 1 to 9.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        # The framework's own answers, such as an unknown path (not_found) or a
        # method the path does not take (method_not_allowed).
        code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
        return _error(exc.status_code, code, f"{exc.detail}.", exc.headers)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        # The server log has the traceback. The response says nothing about the cause.
        return _error(500, "internal_error", "segl could not complete the request.")

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/config")
    def config() -> dict[str, bool]:
        # The fact only. The token itself is never sent to a browser.
        return {"editRequired": settings.edit_required}

    # The slot routes are plain functions, which FastAPI runs in worker
    # threads, so a slow disk does not hold up the event loop.

    @app.get("/api/v1/slots")
    def slots() -> dict[str, list[dict[str, object]]]:
        return {"slots": [_slot_json(slot) for slot in repository.list_slots()]}

    @app.get("/api/v1/slots/{n}")
    def slot(n: str) -> dict[str, object]:
        return _slot_json(repository.get_slot(_slot_number(n)))

    @app.get("/api/v1/slots/{n}/scene")
    def scene(n: str) -> JSONResponse:
        head = repository.get_head(_slot_number(n))
        # A JSONResponse, so the scene is not walked a second time by the
        # framework's response model.
        return JSONResponse(
            {
                "scene": json.loads(head.scene_json),
                "epoch": head.epoch,
                "savedAt": head.saved_at,
                "editorLabel": head.editor_label,
                # The head's uploaded files. T07 adds their storage.
                "files": [],
            }
        )

    @app.post("/api/v1/display-name")
    def display_name(request: Request) -> JSONResponse:
        # No edit token: a viewer has a name too. The address is the one
        # uvicorn settled on, which is X-Forwarded-For only when the connection
        # came from a trusted proxy (docs/SECURITY.md).
        client = request.client.host if request.client else ""
        wait = allocation_limit.admit(client)
        if wait > 0:
            return _error(
                429,
                "rate_limited",
                "Too many names were asked for from this address. Try again in a minute.",
                {"Retry-After": retry_after(wait)},
            )
        name = repository.allocate_display_name(words)
        # Each answer is a different name, so no cache may replay one.
        return JSONResponse({"displayName": name}, headers={"Cache-Control": "no-store"})

    if web_build is not None:
        _add_web_routes(app, web_build, settings.edit_required)
    return app
