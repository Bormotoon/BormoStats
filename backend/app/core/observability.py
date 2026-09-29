"""Request correlation, HTTP metrics and the audit trail for mutating API calls."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from prometheus_client import Histogram
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

LOGGER = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

HTTP_REQUEST_SECONDS = Histogram(
    "backend_http_request_duration_seconds",
    "Backend HTTP request latency",
    ["method", "route", "status"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

_AUDIT_INSERT = (
    "INSERT INTO sys_audit_log"
    " (event, action, path, method, remote_addr, forwarded_for, user_agent, details_json,"
    " actor, organization_id, request_id, status_code)"
    " VALUES ({event:String}, {action:String}, {path:String}, {method:String},"
    " {remote_addr:String}, {forwarded_for:Nullable(String)}, {user_agent:Nullable(String)},"
    " {details_json:String}, {actor:String}, {organization_id:String}, {request_id:String},"
    " {status_code:UInt16})"
)


def resolve_request_id(raw: str | None) -> str:
    if raw and _REQUEST_ID_RE.fullmatch(raw):
        return raw
    return uuid.uuid4().hex


def current_request_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("request_id")
    return str(value) if value else None


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


def _write_audit(app: FastAPI, row: dict[str, Any]) -> None:
    client = getattr(app.state, "ch_client", None)
    if client is None:
        return
    try:
        client.command(_AUDIT_INSERT, parameters=row)
    except Exception as exc:
        LOGGER.warning("audit_write_failed", action=row.get("action"), error=str(exc))


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers["X-API-Version"] = "1"
            return response
        finally:
            route = _route_template(request)
            HTTP_REQUEST_SECONDS.labels(
                method=request.method, route=route, status=str(status_code)
            ).observe(time.perf_counter() - started)
            if request.method in _MUTATING_METHODS and request.url.path.startswith("/api/"):
                await self._audit(request, route, status_code, request_id)
            structlog.contextvars.unbind_contextvars("request_id")

    async def _audit(self, request: Request, route: str, status_code: int, request_id: str) -> None:
        auth = getattr(request.state, "auth", None)
        actor = getattr(auth, "principal_id", "") or "unauthenticated"
        organization_id = getattr(auth, "organization_id", "") or ""
        details = {
            "route": route,
            "path_params": dict(request.path_params),
            "auth_method": str(getattr(auth, "auth_method", "") or ""),
            "role": getattr(getattr(auth, "role", None), "name", ""),
        }
        row = {
            "event": "api_mutation",
            "action": f"{request.method} {route}",
            "path": request.url.path,
            "method": request.method,
            "remote_addr": request.client.host if request.client else "unknown",
            "forwarded_for": request.headers.get("X-Forwarded-For"),
            "user_agent": request.headers.get("User-Agent"),
            "details_json": json.dumps(details, ensure_ascii=True, default=str),
            "actor": actor,
            "organization_id": organization_id,
            "request_id": request_id,
            "status_code": status_code,
        }
        LOGGER.info(
            "api_mutation",
            action=row["action"],
            actor=actor,
            organization_id=organization_id,
            status_code=status_code,
        )
        await run_in_threadpool(_write_audit, request.app, row)
