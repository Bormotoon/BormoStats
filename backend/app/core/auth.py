"""Authentication and authorization.

Every protected endpoint receives an :class:`AuthContext`. Tenant scoping always
comes from this context — never from request bodies or query strings:

* master admin key → platform principal; the organization is taken from the
  ``X-Organization-Id`` header (default ``default``), which only this principal
  may choose;
* user API key → the user's organization and membership role; a user without a
  membership row in that organization is rejected with 403.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

import clickhouse_connect
import structlog
from app.core.config import Settings
from app.core.deps import get_app_settings, get_ch_client
from app.core.security import (
    constant_time_equals,
    hash_secret,
    needs_rehash,
    parse_api_key,
    verify_secret,
)
from app.db.ch import insert_values_sql
from app.models.organization import ORGANIZATION_ID_PATTERN, OrgMemberRole
from app.services.user_service import StoredUser, UserService
from fastapi import Depends, Header, HTTPException, Request, status

LOGGER = structlog.get_logger(__name__)

PLATFORM_PRINCIPAL_ID = "platform-admin"
ANONYMOUS_PRINCIPAL_ID = "anonymous"
DEFAULT_ORGANIZATION_ID = "default"
_ORG_ID_RE = re.compile(ORGANIZATION_ID_PATTERN)
_USAGE_WRITE_INTERVAL_SECONDS = 300.0
_AUTH_CACHE_MAX_ENTRIES = 2048


class AuthMethod(StrEnum):
    admin_key = "admin_key"
    user_key = "user_key"
    anonymous = "anonymous"


class Scope(StrEnum):
    read_analytics = "read:analytics"
    write_catalog = "write:catalog"
    write_settings = "write:settings"
    manage_users = "manage:users"
    execute_marketplace = "execute:marketplace"
    platform_admin = "admin:platform"


# Explicit policy: which *required* roles each *actual* role satisfies. The enum's
# numeric order is deliberately not used for authorization decisions.
ROLE_GRANTS: dict[OrgMemberRole, frozenset[OrgMemberRole]] = {
    OrgMemberRole.owner: frozenset(OrgMemberRole),
    OrgMemberRole.admin: frozenset(
        {
            OrgMemberRole.admin,
            OrgMemberRole.manager,
            OrgMemberRole.analyst,
            OrgMemberRole.viewer,
        }
    ),
    OrgMemberRole.manager: frozenset(
        {OrgMemberRole.manager, OrgMemberRole.analyst, OrgMemberRole.viewer}
    ),
    OrgMemberRole.analyst: frozenset({OrgMemberRole.analyst, OrgMemberRole.viewer}),
    OrgMemberRole.viewer: frozenset({OrgMemberRole.viewer}),
}

ROLE_SCOPES: dict[OrgMemberRole, frozenset[Scope]] = {
    OrgMemberRole.viewer: frozenset({Scope.read_analytics}),
    OrgMemberRole.analyst: frozenset({Scope.read_analytics}),
    OrgMemberRole.manager: frozenset({Scope.read_analytics, Scope.write_catalog}),
    OrgMemberRole.admin: frozenset(
        {
            Scope.read_analytics,
            Scope.write_catalog,
            Scope.write_settings,
            Scope.manage_users,
            Scope.execute_marketplace,
        }
    ),
    OrgMemberRole.owner: frozenset(
        {
            Scope.read_analytics,
            Scope.write_catalog,
            Scope.write_settings,
            Scope.manage_users,
            Scope.execute_marketplace,
        }
    ),
}


def role_allows(actual: OrgMemberRole, required: OrgMemberRole) -> bool:
    return required in ROLE_GRANTS[actual]


@dataclass(frozen=True)
class AuthContext:
    principal_id: str
    organization_id: str
    role: OrgMemberRole
    auth_method: AuthMethod
    scopes: frozenset[Scope] = field(default_factory=frozenset)
    name: str = ""
    email: str = ""
    api_key_expires_at: datetime | None = None

    @property
    def is_platform_admin(self) -> bool:
        return self.auth_method is AuthMethod.admin_key

    def allows(self, required: OrgMemberRole) -> bool:
        return role_allows(self.role, required)

    def has_scope(self, scope: Scope) -> bool:
        return scope in self.scopes

    @property
    def platform_organization_filter(self) -> str | None:
        """``None`` for the platform admin (all tenants), otherwise the caller's org."""
        return None if self.is_platform_admin else self.organization_id


# -- In-process auth cache ------------------------------------------------------------


class _AuthCache:
    """Short-lived cache of verified user keys to avoid scrypt on every request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, AuthContext]] = {}
        self._usage_written: dict[str, float] = {}

    def get(self, digest: str) -> AuthContext | None:
        with self._lock:
            entry = self._entries.get(digest)
            if entry is None:
                return None
            expires_at, ctx = entry
            if expires_at < time.monotonic():
                del self._entries[digest]
                return None
            return ctx

    def put(self, digest: str, ctx: AuthContext, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            if len(self._entries) >= _AUTH_CACHE_MAX_ENTRIES:
                self._entries.clear()
            self._entries[digest] = (time.monotonic() + ttl_seconds, ctx)

    def should_record_usage(self, key_id: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._usage_written.get(key_id)
            if last is not None and now - last < _USAGE_WRITE_INTERVAL_SECONDS:
                return False
            if len(self._usage_written) >= _AUTH_CACHE_MAX_ENTRIES:
                self._usage_written.clear()
            self._usage_written[key_id] = now
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._usage_written.clear()


_CACHE = _AuthCache()


def invalidate_auth_cache() -> None:
    """Drop cached principals, e.g. after a key rotation or revocation."""
    _CACHE.clear()


# -- Resolution -----------------------------------------------------------------------


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "ApiKey"},
    )


def _forbidden(detail: str = "insufficient permissions") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else ""


def admin_network_allowed(remote_addr: str, allowed_networks: str) -> bool:
    specs = [item.strip() for item in allowed_networks.split(",") if item.strip()]
    if not specs:
        return True
    try:
        address = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False
    for spec in specs:
        try:
            if address in ipaddress.ip_network(spec, strict=False):
                return True
        except ValueError:
            LOGGER.warning("admin_allowed_network_invalid", network=spec)
    return False


def _platform_context(organization_header: str) -> AuthContext:
    organization_id = organization_header.strip() or DEFAULT_ORGANIZATION_ID
    if not _ORG_ID_RE.fullmatch(organization_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid X-Organization-Id header",
        )
    return AuthContext(
        principal_id=PLATFORM_PRINCIPAL_ID,
        organization_id=organization_id,
        role=OrgMemberRole.owner,
        auth_method=AuthMethod.admin_key,
        scopes=frozenset(Scope),
        name="Platform admin",
    )


def _record_key_usage(ch: clickhouse_connect.driver.Client, stored: StoredUser) -> None:
    if not _CACHE.should_record_usage(stored.user.api_key_id):
        return
    try:
        ch.command(
            insert_values_sql(
                "sys_api_key_usage",
                (
                    ("api_key_id", "String"),
                    ("user_id", "String"),
                    ("last_used_at", "DateTime"),
                ),
            ),
            parameters={
                "api_key_id": stored.user.api_key_id,
                "user_id": stored.user.user_id,
                "last_used_at": datetime.now(UTC).replace(microsecond=0),
            },
        )
    except Exception as exc:
        LOGGER.warning("api_key_usage_write_failed", error=str(exc))


def _authenticate_user_key(
    request: Request,
    ch: clickhouse_connect.driver.Client,
    raw_key: str,
) -> AuthContext:
    parsed = parse_api_key(raw_key)
    if parsed is None:
        LOGGER.warning("auth_rejected", reason="malformed_api_key", path=request.url.path)
        raise _unauthorized("unauthorized")

    service = UserService(ch)
    stored = service.find_by_key_id(parsed.key_id)
    if stored is None or not stored.api_key_hash:
        LOGGER.warning("auth_rejected", reason="unknown_api_key", path=request.url.path)
        raise _unauthorized("unauthorized")
    if not verify_secret(parsed.secret, stored.api_key_hash):
        LOGGER.warning("auth_rejected", reason="invalid_api_key", path=request.url.path)
        raise _unauthorized("unauthorized")

    user = stored.user
    now = datetime.now(UTC)
    if user.api_key_revoked_at is not None:
        LOGGER.warning("auth_rejected", reason="revoked_api_key", user_id=user.user_id)
        raise _unauthorized("api key revoked")
    expires_at = user.api_key_expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            LOGGER.warning("auth_rejected", reason="expired_api_key", user_id=user.user_id)
            raise _unauthorized("api key expired")

    if needs_rehash(stored.api_key_hash):
        service.upgrade_key_hash(stored, hash_secret(parsed.secret))

    role = service.get_member_role(user.organization_id, user.user_id)
    if role is None:
        LOGGER.warning(
            "auth_rejected",
            reason="no_membership",
            user_id=user.user_id,
            organization_id=user.organization_id,
        )
        raise _forbidden("user is not a member of its organization")

    _record_key_usage(ch, stored)
    return AuthContext(
        principal_id=user.user_id,
        organization_id=user.organization_id,
        role=role,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[role],
        name=user.name,
        email=user.email,
        api_key_expires_at=user.api_key_expires_at,
    )


def resolve_auth_context(
    request: Request,
    ch: clickhouse_connect.driver.Client,
    settings: Settings,
    api_key: str,
    organization_header: str = "",
    *,
    allow_anonymous: bool = False,
) -> AuthContext:
    key = api_key.strip()
    if not key:
        if allow_anonymous and settings.public_read_api:
            return AuthContext(
                principal_id=ANONYMOUS_PRINCIPAL_ID,
                organization_id=DEFAULT_ORGANIZATION_ID,
                role=OrgMemberRole.viewer,
                auth_method=AuthMethod.anonymous,
                scopes=frozenset({Scope.read_analytics}),
            )
        LOGGER.warning("auth_rejected", reason="missing_api_key", path=request.url.path)
        raise _unauthorized("missing api key")

    if settings.admin_api_key and constant_time_equals(key, settings.admin_api_key):
        remote = _client_ip(request)
        if not admin_network_allowed(remote, settings.admin_allowed_networks):
            LOGGER.warning("auth_rejected", reason="admin_network_denied", remote_addr=remote)
            raise _forbidden("admin key not allowed from this network")
        return _platform_context(organization_header)

    if organization_header.strip():
        # Only the platform principal may pick a tenant; users are pinned to theirs.
        LOGGER.info("organization_header_ignored_for_user_key", path=request.url.path)

    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    cached = _CACHE.get(digest)
    if cached is not None:
        return cached
    ctx = _authenticate_user_key(request, ch, key)
    _CACHE.put(digest, ctx, settings.auth_cache_ttl_seconds)
    return ctx


# -- FastAPI dependencies --------------------------------------------------------------

ApiKeyHeader = Annotated[str, Header(alias="X-API-Key")]
OrganizationHeader = Annotated[str, Header(alias="X-Organization-Id")]


def get_auth_context(
    request: Request,
    ch: Annotated[clickhouse_connect.driver.Client, Depends(get_ch_client)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_api_key: ApiKeyHeader = "",
    x_organization_id: OrganizationHeader = "",
) -> AuthContext:
    ctx = resolve_auth_context(request, ch, settings, x_api_key, x_organization_id)
    request.state.auth = ctx
    return ctx


def require_role(
    min_role: OrgMemberRole,
    *,
    scope: Scope | None = None,
    allow_anonymous: bool = False,
) -> Callable[..., AuthContext]:
    """Dependency factory: authenticate, then enforce role (and optional scope)."""

    def _dependency(
        request: Request,
        ch: Annotated[clickhouse_connect.driver.Client, Depends(get_ch_client)],
        settings: Annotated[Settings, Depends(get_app_settings)],
        x_api_key: ApiKeyHeader = "",
        x_organization_id: OrganizationHeader = "",
    ) -> AuthContext:
        ctx = resolve_auth_context(
            request,
            ch,
            settings,
            x_api_key,
            x_organization_id,
            allow_anonymous=allow_anonymous,
        )
        request.state.auth = ctx
        if not ctx.allows(min_role) or (scope is not None and not ctx.has_scope(scope)):
            LOGGER.warning(
                "auth_forbidden",
                principal_id=ctx.principal_id,
                organization_id=ctx.organization_id,
                role=ctx.role.name,
                required_role=min_role.name,
                required_scope=str(scope) if scope else None,
                path=request.url.path,
            )
            raise _forbidden()
        return ctx

    return _dependency


def require_platform_admin(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_api_key: ApiKeyHeader = "",
) -> None:
    """Platform-level operations (ops, org management) accept only the master key."""
    if not settings.admin_api_key:
        LOGGER.warning(
            "admin_request_rejected",
            reason="admin_disabled",
            path=request.url.path,
            method=request.method,
            remote_addr=_client_ip(request) or "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin access unavailable",
        )
    if not x_api_key or not constant_time_equals(x_api_key.strip(), settings.admin_api_key):
        LOGGER.warning(
            "admin_request_rejected",
            reason="invalid_api_key",
            path=request.url.path,
            method=request.method,
            remote_addr=_client_ip(request) or "unknown",
        )
        raise _unauthorized("unauthorized")
    remote = _client_ip(request)
    if not admin_network_allowed(remote, settings.admin_allowed_networks):
        LOGGER.warning("admin_request_rejected", reason="network_denied", remote_addr=remote)
        raise _forbidden("admin key not allowed from this network")
    request.state.auth = _platform_context(request.headers.get("X-Organization-Id", ""))


AuthContextDependency = Annotated[AuthContext, Depends(get_auth_context)]
ViewerAuth = Annotated[AuthContext, Depends(require_role(OrgMemberRole.viewer))]
AnalyticsReadAuth = Annotated[
    AuthContext,
    Depends(require_role(OrgMemberRole.viewer, scope=Scope.read_analytics, allow_anonymous=True)),
]
ManagerAuth = Annotated[AuthContext, Depends(require_role(OrgMemberRole.manager))]
CatalogWriteAuth = Annotated[
    AuthContext, Depends(require_role(OrgMemberRole.manager, scope=Scope.write_catalog))
]
AdminAuth = Annotated[
    AuthContext, Depends(require_role(OrgMemberRole.admin, scope=Scope.write_settings))
]
UserAdminAuth = Annotated[
    AuthContext, Depends(require_role(OrgMemberRole.admin, scope=Scope.manage_users))
]
MarketplaceExecuteAuth = Annotated[
    AuthContext,
    Depends(require_role(OrgMemberRole.admin, scope=Scope.execute_marketplace)),
]


def ensure_scope(ctx: AuthContext, scope: Scope, reason: str) -> None:
    """Raise 403 unless ``ctx`` holds ``scope`` (for conditional, payload-driven checks)."""
    if not ctx.has_scope(scope):
        raise _forbidden(f"{scope} scope required to {reason}")
