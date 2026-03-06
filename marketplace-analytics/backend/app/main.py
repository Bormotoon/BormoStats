"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

import structlog
from app.api.v1 import admin, ads, funnel, kpis, sales, stocks
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.ops_metrics import refresh_operational_metrics
from app.db.ch import build_client
from app.models.api import ApiError, ApiErrorResponse
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

settings = get_settings()
configure_logging(settings.log_level)
LOGGER = structlog.get_logger(__name__)

app = FastAPI(title="Marketplace Analytics API", version="0.1.0")

app.include_router(sales.router, prefix="/api/v1")
app.include_router(stocks.router, prefix="/api/v1")
app.include_router(funnel.router, prefix="/api/v1")
app.include_router(ads.router, prefix="/api/v1")
app.include_router(kpis.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.mount(
    "/ui", StaticFiles(directory=Path(__file__).resolve().parent / "ui", html=True), name="ui"
)


def _error_payload(
    *,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return ApiErrorResponse(
        detail=message,
        error=ApiError(code=code, message=message, details=details or []),
    ).model_dump(mode="json")


def _http_error_code(status_code: int) -> str:
    if status_code == 401:
        return "unauthorized"
    if status_code == 404:
        return "not_found"
    if status_code == 422:
        return "validation_error"
    if status_code == 503:
        return "service_unavailable"
    return "http_error"


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    LOGGER.info(
        "api_request_validation_failed",
        path=request.url.path,
        method=request.method,
        errors=exc.errors(),
    )
    details = [
        {
            "loc": ".".join(str(part) for part in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            code="validation_error", message="validation failed", details=details
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    LOGGER.info(
        "api_http_exception",
        path=request.url.path,
        method=request.method,
        status_code=exc.status_code,
        detail=exc.detail,
    )
    message = exc.detail if isinstance(exc.detail, str) else "request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(code=_http_error_code(exc.status_code), message=message),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    LOGGER.exception(
        "api_unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
    )
    return JSONResponse(
        status_code=500,
        content=_error_payload(code="internal_error", message="internal server error"),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    try:
        ch_client = build_client(settings)
        try:
            ch_client.query("SELECT 1")
        finally:
            ch_client.close()

        redis_client = Redis.from_url(settings.redis_url)
        redis_client.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"not ready: {exc}") from exc

    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    refresh_operational_metrics(settings)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")
