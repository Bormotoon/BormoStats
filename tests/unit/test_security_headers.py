"""Tests for HTTP security headers and CORS configuration."""

from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient


def test_security_headers_present_on_api_response() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert (
            response.headers.get("Permissions-Policy")
            == "geolocation=(), camera=(), microphone=(), payment=()"
        )
        assert response.headers.get("X-API-Version") == "1"
        assert "X-Request-ID" in response.headers


def test_api_content_security_policy() -> None:
    with TestClient(app) as client:
        # Accessing an api path (even if unauthorized) returns CSP
        response = client.get("/api/v1/sales/summary")
        assert (
            response.headers.get("Content-Security-Policy")
            == "default-src 'none'; frame-ancestors 'none'"
        )
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
