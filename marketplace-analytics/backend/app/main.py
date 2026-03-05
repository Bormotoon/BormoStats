"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis import Redis

from app.api.v1 import admin, ads, funnel, kpis, sales, stocks
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.ch import build_client

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="Marketplace Analytics API", version="0.1.0")

app.include_router(sales.router, prefix="/api/v1")
app.include_router(stocks.router, prefix="/api/v1")
app.include_router(funnel.router, prefix="/api/v1")
app.include_router(ads.router, prefix="/api/v1")
app.include_router(kpis.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


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
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
