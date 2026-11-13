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
import logging
import re
import time
import unicodedata
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from segl.access import LOCK_SECONDS, Access, CodeLimit
from segl.assets import MEDIA_TYPES, AssetStore
from segl.collab import Rooms, serve
from segl.config import Settings
from segl.importing import ImportedFile, InvalidDocument, NotJson, TooLarge, read_document
from segl.names import AllocationLimit, load_display_names, retry_after
from segl.networks import InternalNetworks
from segl.origin import OriginCheck
from segl.repository import (
    SYSTEM_LABEL,
    InvalidSlot,
    Repository,
    RevisionNotFound,
    RevisionSummary,
    Slot,
)
from segl.room import NEEDS_CODE, FileEntry, encode, named_files, stored_name
from segl.versions import app_version
from segl.web import ROOT_PAGE, SLOT_PAGE, WebBuild, load_web_build, render_page

logger = logging.getLogger("segl.access")

# The only texts that name a slot. int() would also take "01", "+1", and the
# digits of other scripts.
_SLOT_TEXTS = {str(number): number for number in range(1, 10)}

# The longest slot title, in characters.
MAX_TITLE_LENGTH = 80
# The largest body of a title change. A title is at most 80 characters.
_TITLE_BODY_BYTES = 4096

# The largest body of a restore: a revision number and a display name.
_RESTORE_BODY_BYTES = 4096

# The largest body of an access code. A code is at most 256 characters.
_ACCESS_BODY_BYTES = 4096

# The texts that can name a revision: a whole number from 1, as the server
# writes it. Sixteen digits is more than a slot will ever count, and fits the
# database's integer.
_REVISION_TEXT = re.compile(r"[1-9][0-9]{0,15}")
MAX_REVISION = 10**16 - 1

# An uploaded file is whatever a browser sent. It is served as bytes and
# nothing else: never as a page, an image, or a script of this site, whatever
# its content, and a browser asked to open one may run nothing in it. The page
# fetches the bytes and hands them to the editor itself. A file is named by its
# hash, so a copy a browser holds never goes stale.
_ASSET_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cache-Control": "max-age=31536000, immutable",
}


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


def clean_title(value: object) -> str | None:
    """Return a slot title as it is stored, or None when it is not usable.

    A title is one line of text: 1 to 80 characters once the spaces around it
    are dropped, with no control characters.
    """
    if not isinstance(value, str):
        return None
    title = value.strip()
    if not 1 <= len(title) <= MAX_TITLE_LENGTH:
        return None
    # Cc is a control character, such as a line break. Cs is half of a
    # surrogate pair, which JSON can carry and SQLite cannot store.
    if any(unicodedata.category(character) in ("Cc", "Cs") for character in title):
        return None
    return title


async def _body(request: Request, limit: int) -> bytes | JSONResponse:
    """Return a request's body, or the error to answer with when it is over ``limit`` bytes."""
    too_large = _error(413, "payload_too_large", f"The body is larger than {limit} bytes.")
    declared = request.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > limit:
        # Refused before any of it is read.
        return too_large
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            return too_large
    return bytes(body)


async def _json_object(request: Request, limit: int) -> dict[str, Any] | JSONResponse:
    """Return a request's body as a JSON object, or the error to answer with."""
    body = await _body(request, limit)
    if isinstance(body, JSONResponse):
        return body
    try:
        parsed = json.loads(body)
    except ValueError, RecursionError:
        parsed = None
    if not isinstance(parsed, dict):
        return _error(400, "bad_request", "The body is a JSON object.")
    return parsed


def header_name(value: str | None) -> str | None:
    """Return the label an ``X-Segl-Display-Name`` header carries, or None.

    A header is ASCII, and a name is not, so the browser percent-encodes the
    label it stores. It is then taken as ``hello`` takes it.
    """
    if value is None:
        return None
    try:
        return stored_name(unquote(value, errors="strict"))
    except UnicodeDecodeError:
        return None


def _store(assets: AssetStore, files: list[ImportedFile]) -> list[FileEntry]:
    """Store the bytes of an import's files, and return the files as a slot lists them."""
    return [
        {"id": file.file_id, "hash": assets.save(file.data), "mimeType": file.media_type}
        for file in files
    ]


def _expires_at(until: float | None) -> str | None:
    """Return when a pass ends as a response carries it: UTC, to the millisecond."""
    if until is None:
        return None
    moment = datetime.fromtimestamp(until, UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _slot_json(slot: Slot) -> dict[str, object]:
    return {
        "number": slot.number,
        "title": slot.title,
        "epoch": slot.epoch,
        "savedAt": slot.saved_at,
    }


def _revision_json(row: RevisionSummary) -> dict[str, object]:
    return {
        "revision": row.revision,
        "epoch": row.epoch,
        "authorLabel": row.author_label,
        "createdAt": row.created_at,
    }


def _scene_json(repository: Repository, slot: int, scene_json: str) -> dict[str, object]:
    """Return a stored scene as a response carries it, with the files its images name."""
    document = json.loads(scene_json)
    elements = document.get("elements") if isinstance(document, dict) else None
    files = [
        {"id": file.file_id, "hash": file.hash, "mimeType": file.media_type}
        for file in repository.list_files(slot)
    ]
    return {
        "scene": document,
        # For the page to fetch. A deleted image still names its file.
        "files": named_files(files, elements if isinstance(elements, list) else []),
    }


def _ascii_json(body: dict[str, object]) -> Response:
    """Return a response that holds a scene.

    Written as the socket writes a scene: ASCII, so half of a surrogate pair
    in an element's text stays an escape. The framework's JSON response would
    fail on it, and the slot could not be loaded.
    """
    return Response(encode(body), media_type="application/json")


def _add_web_routes(app: FastAPI, build: WebBuild, edit_required: bool) -> None:
    """Serve the web application: the pages, then the files the build emitted."""
    # Made once. A new build, or a changed list of access codes, takes a restart.
    pages = {
        root: render_page(build.index, root=root, edit_required=edit_required)
        for root in (ROOT_PAGE, SLOT_PAGE)
    }

    def page(root: str) -> HTMLResponse:
        # The page names its files by content hash, so it is the one response
        # a browser must ask for again after an upgrade.
        return HTMLResponse(pages[root], headers={"Cache-Control": "no-cache"})

    # The access page, where a browser enters an access code, is at segl's
    # root as `/` is (docs/ARCHITECTURE.md, edit gate). It is the same
    # application, and the app's own router shows the page.
    @app.get("/", include_in_schema=False)
    @app.get("/s", include_in_schema=False)
    @app.get("/access", include_in_schema=False)
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


def create_app(
    settings: Settings, repository: Repository, *, clock: Callable[[], float] = time.time
) -> FastAPI:
    """Build the application for these settings, over a bootstrapped repository.

    ``clock`` gives the time in Unix seconds, which a pass is issued at and
    ends by. A test moves it.

    The application closes the repository when it shuts down. It serves the
    web application when ``settings.web_dir`` holds a build, and the API alone
    when it does not. The display-name words are read here, once, so a
    replaced file takes a restart. Uploaded files go under
    ``settings.assets_dir``, which is made when the first one arrives.

    Raises:
        DisplayNamesError: When ``display_names`` is missing or has no usable words.
        WebBuildError: When ``web_dir`` has an ``index.html`` segl cannot use.
    """
    words = load_display_names(settings.display_names)
    allocation_limit = AllocationLimit()
    access = Access(
        settings.access_codes,
        settings.access_secret,
        pass_seconds=settings.access_pass_seconds,
        passes_after=settings.access_passes_after_seconds,
        clock=clock,
    )
    code_limit = CodeLimit()

    def may_edit(request: Request) -> bool:
        # The header's name is from when it carried a token. It carries the pass.
        return access.admit(request.headers.get("x-segl-edit-token")).may_edit

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        yield
        # The one place that runs on every stop. After SIGTERM, uvicorn ends
        # the process as soon as this returns, so code after uvicorn.run does
        # not run. First every room's unwritten scene goes to its head. Then
        # closing folds the write-ahead log back into the database file.
        try:
            await rooms.close()
        finally:
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
    app.state.access = access
    app.state.code_limit = code_limit
    assets = AssetStore(settings.assets_dir)
    app.state.assets = assets
    rooms = Rooms(repository, settings, assets)
    app.state.rooms = rooms
    # Before every route: a mutation or a WebSocket handshake from a page on
    # another site is refused with bad_origin (docs/SECURITY.md).
    app.add_middleware(OriginCheck)
    if settings.internal_networks:
        # Added last, so it runs first: an address outside the site's networks
        # is answered outside_network, and nothing else is looked at.
        app.add_middleware(InternalNetworks, networks=settings.internal_networks)
    web_build = load_web_build(settings.web_dir)
    app.state.web_build = web_build

    @app.exception_handler(InvalidSlot)
    async def invalid_slot(request: Request, exc: InvalidSlot) -> JSONResponse:
        return _error(404, "invalid_slot", "Slots are numbered 1 to 9.")

    @app.exception_handler(RevisionNotFound)
    async def revision_not_found(request: Request, exc: RevisionNotFound) -> JSONResponse:
        return _error(
            404,
            "revision_not_found",
            "The slot has no such revision. The oldest ones are dropped as new ones are kept.",
        )

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
        # The fact only: that editing needs an access code, and none of them.
        return {"editRequired": access.required}

    @app.post("/api/v1/access")
    async def enter_code(request: Request) -> JSONResponse:
        if not access.required:
            return _error(
                404, "no_access_codes", "This segl asks for no access code. Everyone can edit."
            )
        # The address uvicorn settled on, as the name limit counts by.
        client = request.client.host if request.client else ""
        wait = code_limit.wait(client)
        if wait > 0:
            # Before the body is read: while an address waits, no code of its is looked at.
            return _error(
                429,
                "rate_limited",
                "Too many wrong access codes came from this address. Try again later.",
                {"Retry-After": retry_after(wait)},
            )
        body = await _json_object(request, _ACCESS_BODY_BYTES)
        if isinstance(body, JSONResponse):
            return body
        given = body.get("code")
        if not isinstance(given, str):
            return _error(400, "bad_request", 'The body is { "code" }, and a code is text.')
        code = access.code(given)
        if code is None:
            if code_limit.wrong(client):
                # The address, and never what it sent.
                logger.warning(
                    "wrong access codes from %s: its codes wait %d minutes",
                    client or "an unknown address",
                    LOCK_SECONDS // 60,
                )
            return _error(403, "wrong_code", "That is not one of this segl's access codes.")
        code_limit.right(client)
        issued, until = access.issue(code)
        # Each answer is a pass of its own, so no cache may keep one.
        return JSONResponse(
            {"pass": issued, "expiresAt": _expires_at(until)},
            headers={"Cache-Control": "no-store"},
        )

    # The slot routes are plain functions, which FastAPI runs in worker
    # threads, so a slow disk does not hold up the event loop.

    @app.get("/api/v1/slots")
    def slots() -> dict[str, list[dict[str, object]]]:
        return {"slots": [_slot_json(slot) for slot in repository.list_slots()]}

    # One route for both methods, so that the 405 for any other method names
    # both in its Allow header.
    @app.api_route("/api/v1/slots/{n}", methods=["GET", "PATCH"])
    async def slot(n: str, request: Request) -> JSONResponse:
        number = _slot_number(n)
        if request.method == "GET":
            return JSONResponse(_slot_json(await run_in_threadpool(repository.get_slot, number)))
        if not may_edit(request):
            return _error(403, "view_only", NEEDS_CODE)
        body = await _json_object(request, _TITLE_BODY_BYTES)
        if isinstance(body, JSONResponse):
            return body
        title = clean_title(body.get("title"))
        if title is None:
            return _error(
                422,
                "invalid_title",
                f"A title is 1 to {MAX_TITLE_LENGTH} characters on one line.",
            )
        # Stored, then sent to the slot's room as a `slot` message.
        return JSONResponse(_slot_json(await rooms.retitle(number, title)))

    @app.get("/api/v1/slots/{n}/scene")
    def scene(n: str) -> Response:
        number = _slot_number(n)
        head = repository.get_head(number)
        stored = _scene_json(repository, number, head.scene_json)
        return _ascii_json(
            {
                "scene": stored["scene"],
                "epoch": head.epoch,
                "savedAt": head.saved_at,
                "editorLabel": head.editor_label,
                "files": stored["files"],
            }
        )

    @app.get("/api/v1/slots/{n}/revisions")
    def revisions(n: str) -> dict[str, list[dict[str, object]]]:
        # Newest first, and without the scenes: a list is read far more often
        # than any one of its scenes.
        rows = repository.list_revisions(_slot_number(n))
        return {"revisions": [_revision_json(row) for row in rows]}

    @app.get("/api/v1/slots/{n}/revisions/{revision}")
    def revision(n: str, revision: str) -> Response:
        number = _slot_number(n)
        if _REVISION_TEXT.fullmatch(revision) is None:
            # No revision has such a name, as no slot is named `01`.
            raise RevisionNotFound(number, 0)
        row = repository.get_revision(number, int(revision))
        return _ascii_json(
            {**_revision_json(row), **_scene_json(repository, number, row.scene_json)}
        )

    @app.post("/api/v1/slots/{n}/restore")
    async def restore(n: str, request: Request) -> JSONResponse:
        number = _slot_number(n)
        if not may_edit(request):
            return _error(403, "view_only", NEEDS_CODE)
        body = await _json_object(request, _RESTORE_BODY_BYTES)
        if isinstance(body, JSONResponse):
            return body
        chosen = body.get("revision")
        # `true` is an int in Python, and is not a revision.
        if (
            isinstance(chosen, bool)
            or not isinstance(chosen, int)
            or not 1 <= chosen <= MAX_REVISION
        ):
            return _error(422, "invalid_revision", "A revision is a whole number, 1 or more.")
        # Who restored, for the history row: the label the browser stores, as
        # `hello` carries it. A request has no other name.
        label = stored_name(body.get("displayName")) or SYSTEM_LABEL
        # Written, then sent to the slot's room as a `scene` of the new epoch.
        replacement = await rooms.restore(number, chosen, label)
        return JSONResponse(
            {
                "revision": replacement.revision,
                "epoch": replacement.epoch,
                "savedAt": replacement.saved_at,
            }
        )

    @app.post("/api/v1/slots/{n}/import")
    async def import_document(n: str, request: Request) -> JSONResponse:
        number = _slot_number(n)
        if not may_edit(request):
            return _error(403, "view_only", NEEDS_CODE)
        # The file as the editor exported it, with the files of its images inside.
        body = await _body(request, settings.max_scene_bytes)
        if isinstance(body, JSONResponse):
            return body
        try:
            # A large document takes a while to read, so not on the event loop.
            document = await run_in_threadpool(
                read_document,
                body,
                max_scene_bytes=settings.max_scene_bytes,
                max_asset_bytes=settings.max_asset_bytes,
            )
        except NotJson:
            return _error(400, "bad_request", "The body is a JSON object.")
        except TooLarge as exc:
            return _error(413, "payload_too_large", str(exc))
        except InvalidDocument as exc:
            return _error(422, "invalid_document", f"That is not an Excalidraw scene: {exc}.")
        # Who imported, for the history row. The body is the document, so the
        # label the browser stores comes in a header.
        label = header_name(request.headers.get("x-segl-display-name")) or SYSTEM_LABEL
        # The bytes first, as an upload comes before the message that names it.
        files = await run_in_threadpool(_store, assets, document.files)
        # Written, then sent to the slot's room as a `scene` of the new epoch.
        replacement = await rooms.import_scene(number, document.elements, files, label)
        return JSONResponse(
            {
                "revision": replacement.revision,
                "epoch": replacement.epoch,
                "savedAt": replacement.saved_at,
            }
        )

    @app.post("/api/v1/slots/{n}/assets")
    async def upload(n: str, request: Request) -> JSONResponse:
        _slot_number(n)
        if not may_edit(request):
            return _error(403, "view_only", NEEDS_CODE)
        media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type not in MEDIA_TYPES:
            return _error(
                415,
                "unsupported_media_type",
                "An upload is an image, and its Content-Type says which kind.",
            )
        body = await _body(request, settings.max_asset_bytes)
        if isinstance(body, JSONResponse):
            return body
        if not body:
            return _error(400, "bad_request", "The body is the file's bytes.")
        name = await run_in_threadpool(assets.save, body)
        return JSONResponse({"hash": name, "mediaType": media_type})

    @app.get("/api/v1/assets/{name}")
    def asset(name: str) -> Response:
        # The name is a SHA-256 or it is nothing: no path is built from any
        # other text (docs/SECURITY.md).
        path = assets.path(name)
        if path is None or not path.is_file():
            raise HTTPException(404, "Not Found")
        return FileResponse(path, media_type="application/octet-stream", headers=_ASSET_HEADERS)

    @app.post("/api/v1/display-name")
    def display_name(request: Request) -> JSONResponse:
        # No pass: a viewer has a name too. The address is the one
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

    @app.websocket("/collab")
    async def collab(websocket: WebSocket) -> None:
        await serve(websocket, rooms, access)

    if web_build is not None:
        _add_web_routes(app, web_build, settings.edit_required)
    return app
