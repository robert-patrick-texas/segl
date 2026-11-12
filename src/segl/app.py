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

from fastapi import FastAPI

from segl.versions import app_version


def create_app() -> FastAPI:
    """Build the application."""
    # FastAPI's generated documentation pages are off. docs/API.md is the
    # contract, and those pages use absolute URLs that a path mount would break.
    app = FastAPI(
        title="segl",
        version=app_version(),
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
