"""Dependency helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

import clickhouse_connect
import structlog
from app.core.config import Settings, get_settings
from app.db.ch import build_raw_client
from app.models.admin import AdminRequestContext
from app.models.organization import OrgMemberRole
from app.models.user import User, UserRole
from fastapi import Depends, Header, HTTPException, Request, status

LOGGER = structlog.get_logger(__name__)


def get_app_settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def _get_cached_ch_client(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    pool_maxsize: int,
) -> clickhouse_connect.driver.Client:
    return build_raw_client(
        host=host,
        port=port,
        username=user,
        password=password,
        database=database,
        pool_maxsize=pool_maxsize,
    )


def get_ch_client(
    settings: Settings = Depends(get_app_settings),
) -> clickhouse_connect.driver.Client:
    return _get_cached_ch_client(
        host=settings.ch_host,
        port=settings.ch_port,
        user=settings.ch_user,
        password=settings.ch_password,
        database=settings.ch_db,
        pool_maxsize=settings.ch_pool_maxsize,
    )


def get_admin_request_context(request: Request) -> AdminRequestContext:
    client_host = request.client.host if request.client is not None else "unknown"
    return AdminRequestContext(
        path=request.url.path,
        method=request.method,
        remote_addr=client_host,
        forwarded_for=request.headers.get("X-Forwarded-For"),
        user_agent=request.headers.get("User-Agent"),
    )


def require_admin_api_key(
    request: Request,
    x_api_key: str = Header(default="", alias="X-API-Key"),
    settings: Settings = Depends(get_app_settings),
) -> None:
    if not settings.admin_api_key:
        LOGGER.warning(
            "admin_request_rejected",
            reason="admin_disabled",
            path=request.url.path,
            method=request.method,
            remote_addr=request.client.host if request.client is not None else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin access unavailable",
        )

    if x_api_key != settings.admin_api_key:
        LOGGER.warning(
            "admin_request_rejected",
            reason="invalid_api_key",
            path=request.url.path,
            method=request.method,
            remote_addr=request.client.host if request.client is not None else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthorized",
            headers={"WWW-Authenticate": "ApiKey"},
        )


ChClientDependency = Annotated[clickhouse_connect.driver.Client, Depends(get_ch_client)]
SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
AdminRequestContextDependency = Annotated[
    AdminRequestContext,
    Depends(get_admin_request_context),
]


def get_current_user(
    request: Request,
    ch: ChClientDependency,
    x_api_key: str = Header(default="", alias="X-API-Key"),
) -> User:
    if not x_api_key:
        LOGGER.warning(
            "user_auth_rejected",
            reason="missing_api_key",
            path=request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing api key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    rows = ch.query(
        "SELECT user_id, name, email, api_key, role, organization_id, is_active, "
        "created_at, updated_at"
        " FROM dim_user FINAL WHERE api_key = {key:String} AND is_active = 1",
        parameters={"key": x_api_key},
    )
    for r in rows.named_results():
        return User(
            user_id=r["user_id"],
            name=r["name"],
            email=r["email"],
            api_key=r["api_key"],
            role=UserRole(r["role"]),
            organization_id=r.get("organization_id", "default"),
            is_active=bool(r["is_active"]),
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        )

    LOGGER.warning(
        "user_auth_rejected",
        reason="invalid_api_key",
        path=request.url.path,
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="unauthorized",
        headers={"WWW-Authenticate": "ApiKey"},
    )


CurrentUserDependency = Annotated[User, Depends(get_current_user)]


def require_admin_key_or_org_role(min_role: OrgMemberRole) -> Any:
    """Accept either the master admin API key or a user API key with sufficient org role."""

    def _checker(
        request: Request,
        ch: ChClientDependency,
        settings: SettingsDependency,
        x_api_key: str = Header(default="", alias="X-API-Key"),
    ) -> None:
        if not x_api_key:
            LOGGER.warning("auth_rejected", reason="missing_api_key", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing api key",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        if settings.admin_api_key and x_api_key == settings.admin_api_key:
            return

        user = get_current_user(request, ch, x_api_key)

        rows = ch.query(
            "SELECT role FROM dim_organization_member FINAL"
            " WHERE organization_id = {oid:String} AND user_id = {uid:String}",
            parameters={"oid": user.organization_id, "uid": user.user_id},
        )
        actual_role = OrgMemberRole.viewer
        for r in rows.named_results():
            actual_role = OrgMemberRole(r["role"])

        if actual_role.value > min_role.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permissions",
            )

    return _checker
