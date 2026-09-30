"""Static file serving for the web UI with browser cache headers.

Vite writes content-hashed bundles to ``assets/`` (``index-B0iVlrdM.js``): a new build
gets new names, so those files can be cached forever. ``index.html`` references the
current bundles and must be revalidated on every load, otherwise a deploy would keep
serving the old UI. Revalidation is cheap: Starlette answers ``If-None-Match`` /
``If-Modified-Since`` with 304 from the ETag and mtime it already sends.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
REVALIDATE_CACHE_CONTROL = "no-cache"
DEFAULT_CACHE_CONTROL = "public, max-age=3600"

# Vite's default ``assets/[name]-[hash][extname]``; the hash is 8 url-safe characters.
_HASHED_ASSET = re.compile(r"^assets/.+-[A-Za-z0-9_-]{8}\.[A-Za-z0-9]+$")


def cache_control_for(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if path.suffix == ".html":
        return REVALIDATE_CACHE_CONTROL
    if _HASHED_ASSET.match(path.as_posix()):
        return IMMUTABLE_CACHE_CONTROL
    return DEFAULT_CACHE_CONTROL


class CachedStaticFiles(StaticFiles):
    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        relative = os.path.relpath(full_path, self.directory or ".").replace(os.sep, "/")
        response.headers["Cache-Control"] = cache_control_for(relative)
        return response
