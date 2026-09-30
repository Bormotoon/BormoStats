"""Browser cache headers for the web UI's static files."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.static_files import (
    DEFAULT_CACHE_CONTROL,
    IMMUTABLE_CACHE_CONTROL,
    REVALIDATE_CACHE_CONTROL,
    CachedStaticFiles,
    cache_control_for,
)
from starlette.applications import Starlette
from starlette.testclient import TestClient


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("index.html", REVALIDATE_CACHE_CONTROL),
        ("assets/index-B0iVlrdM.js", IMMUTABLE_CACHE_CONTROL),
        ("assets/charts-fChiw7Dz.js", IMMUTABLE_CACHE_CONTROL),
        ("assets/index-Bj7c0lgs.css", IMMUTABLE_CACHE_CONTROL),
        # Unhashed files (the legacy UI, favicon) may change between releases.
        ("app.js", DEFAULT_CACHE_CONTROL),
        ("favicon.svg", DEFAULT_CACHE_CONTROL),
        ("assets/app.js", DEFAULT_CACHE_CONTROL),
    ],
)
def test_cache_control_rules(path: str, expected: str) -> None:
    assert cache_control_for(path) == expected


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>")
    (tmp_path / "assets" / "index-B0iVlrdM.js").write_text("console.log(1)")
    app = Starlette()
    app.mount("/ui", CachedStaticFiles(directory=tmp_path, html=True), name="ui")
    return TestClient(app)


def test_index_is_revalidated(client: TestClient) -> None:
    response = client.get("/ui/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == REVALIDATE_CACHE_CONTROL
    assert response.headers["etag"]


def test_hashed_bundle_is_immutable_and_keeps_header_on_304(client: TestClient) -> None:
    response = client.get("/ui/assets/index-B0iVlrdM.js")
    assert response.headers["cache-control"] == IMMUTABLE_CACHE_CONTROL

    revalidated = client.get(
        "/ui/assets/index-B0iVlrdM.js", headers={"If-None-Match": response.headers["etag"]}
    )
    assert revalidated.status_code == 304
    assert revalidated.headers["cache-control"] == IMMUTABLE_CACHE_CONTROL
