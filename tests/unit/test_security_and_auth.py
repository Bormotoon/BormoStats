from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from app.core import auth as auth_module
from app.core.auth import (
    ROLE_GRANTS,
    AuthMethod,
    Scope,
    admin_network_allowed,
    invalidate_auth_cache,
    resolve_auth_context,
    role_allows,
)
from app.core.security import (
    generate_api_key,
    hash_secret,
    legacy_key_id,
    needs_rehash,
    parse_api_key,
    verify_secret,
)
from app.models.organization import OrgMemberRole
from app.models.user import UserRole
from fastapi import HTTPException

from tests.fakes import FakeClickHouse

ROLES = list(OrgMemberRole)
# Expected policy, written out explicitly: actual role (row) may act as required role (col).
EXPECTED = {
    OrgMemberRole.owner: set(ROLES),
    OrgMemberRole.admin: {
        OrgMemberRole.admin,
        OrgMemberRole.manager,
        OrgMemberRole.analyst,
        OrgMemberRole.viewer,
    },
    OrgMemberRole.manager: {OrgMemberRole.manager, OrgMemberRole.analyst, OrgMemberRole.viewer},
    OrgMemberRole.analyst: {OrgMemberRole.analyst, OrgMemberRole.viewer},
    OrgMemberRole.viewer: {OrgMemberRole.viewer},
}


@pytest.mark.parametrize("actual", ROLES)
@pytest.mark.parametrize("required", ROLES)
def test_role_policy_matrix(actual: OrgMemberRole, required: OrgMemberRole) -> None:
    assert role_allows(actual, required) is (required in EXPECTED[actual])
    assert set(ROLE_GRANTS[actual]) == EXPECTED[actual]


def test_generated_key_roundtrip_and_hash_is_salted() -> None:
    issued = generate_api_key()
    parsed = parse_api_key(issued.plaintext)
    assert parsed is not None and not parsed.legacy
    assert parsed.key_id == issued.key_id
    assert verify_secret(parsed.secret, issued.key_hash)
    assert not verify_secret(parsed.secret + "x", issued.key_hash)
    assert issued.plaintext not in issued.key_hash
    assert hash_secret("same") != hash_secret("same")
    assert not needs_rehash(issued.key_hash)


def test_legacy_key_matches_sql_migration_digest() -> None:
    legacy = "0123456789abcdef0123456789abcdef"
    parsed = parse_api_key(legacy)
    assert parsed is not None and parsed.legacy
    digest = hashlib.sha256(legacy.encode()).hexdigest()
    # 0021_api_key_hashing.sql: concat('legacy_', substring(hex(SHA256(api_key)), 1, 24))
    assert parsed.key_id == legacy_key_id(legacy) == f"legacy_{digest[:24]}"
    assert verify_secret(legacy, f"sha256${digest}")
    assert needs_rehash(f"sha256${digest}")


@pytest.mark.parametrize("value", ["", "bsk_nothex!!!!!!!!!_x", "x" * 300])
def test_malformed_keys_are_rejected(value: str) -> None:
    assert parse_api_key(value) is None


def test_admin_network_allowlist() -> None:
    assert admin_network_allowed("203.0.113.9", "")
    assert admin_network_allowed("10.1.2.3", "10.0.0.0/8, 192.168.0.0/16")
    assert not admin_network_allowed("203.0.113.9", "10.0.0.0/8")
    assert not admin_network_allowed("testclient", "10.0.0.0/8")


# -- resolve_auth_context -------------------------------------------------------------


def _settings(**overrides: Any) -> Any:
    base = {
        "admin_api_key": "master-key",
        "admin_allowed_networks": "",
        "public_read_api": False,
        "auth_cache_ttl_seconds": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _request(host: str = "10.0.0.5") -> Any:
    return SimpleNamespace(client=SimpleNamespace(host=host), url=SimpleNamespace(path="/x"))


def _user_row(issued: Any, **overrides: Any) -> dict[str, Any]:
    row = {
        "user_id": "u-1",
        "name": "Ann",
        "email": "ann@example.com",
        "role": "analyst",  # ClickHouse returns Enum8 values by name
        "organization_id": "org-a",
        "is_active": 1,
        "api_key_id": issued.key_id,
        "api_key_hash": issued.key_hash,
        "api_key_created_at": None,
        "api_key_expires_at": None,
        "api_key_revoked_at": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    invalidate_auth_cache()


def test_master_key_gets_platform_context_with_header_org() -> None:
    ctx = resolve_auth_context(_request(), FakeClickHouse(), _settings(), "master-key", "org-b")
    assert ctx.auth_method is AuthMethod.admin_key
    assert ctx.organization_id == "org-b"
    assert ctx.has_scope(Scope.platform_admin)


def test_master_key_rejected_outside_allowed_network() -> None:
    with pytest.raises(HTTPException) as exc:
        resolve_auth_context(
            _request("203.0.113.1"),
            FakeClickHouse(),
            _settings(admin_allowed_networks="10.0.0.0/8"),
            "master-key",
        )
    assert exc.value.status_code == 403


def test_missing_key_is_401_unless_public_read_enabled() -> None:
    with pytest.raises(HTTPException) as exc:
        resolve_auth_context(_request(), FakeClickHouse(), _settings(), "", allow_anonymous=True)
    assert exc.value.status_code == 401
    ctx = resolve_auth_context(
        _request(), FakeClickHouse(), _settings(public_read_api=True), "", allow_anonymous=True
    )
    assert ctx.auth_method is AuthMethod.anonymous
    assert ctx.scopes == frozenset({Scope.read_analytics})


def test_user_key_resolves_org_and_membership_role_ignoring_org_header() -> None:
    issued = generate_api_key()
    ch = (
        FakeClickHouse()
        .on("FROM dim_user", [_user_row(issued)])
        .on("FROM dim_organization_member", [{"role": "manager"}])
    )
    ctx = resolve_auth_context(_request(), ch, _settings(), issued.plaintext, "org-evil")
    assert ctx.organization_id == "org-a"
    assert ctx.role is OrgMemberRole.manager
    assert ctx.has_scope(Scope.write_catalog)
    assert not ctx.has_scope(Scope.execute_marketplace)
    lookup_sql, lookup_params = ch.queries[0]
    assert "api_key_id" in lookup_sql and lookup_params["kid"] == issued.key_id


def test_user_without_membership_is_forbidden_not_viewer() -> None:
    issued = generate_api_key()
    ch = FakeClickHouse().on("FROM dim_user", [_user_row(issued)])
    with pytest.raises(HTTPException) as exc:
        resolve_auth_context(_request(), ch, _settings(), issued.plaintext)
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"api_key_revoked_at": datetime(2026, 1, 1, tzinfo=UTC)}, "api key revoked"),
        ({"api_key_expires_at": datetime.now(UTC) - timedelta(days=1)}, "api key expired"),
    ],
)
def test_revoked_or_expired_keys_are_rejected(overrides: dict[str, Any], detail: str) -> None:
    issued = generate_api_key()
    ch = (
        FakeClickHouse()
        .on("FROM dim_user", [_user_row(issued, **overrides)])
        .on("FROM dim_organization_member", [{"role": "admin"}])
    )
    with pytest.raises(HTTPException) as exc:
        resolve_auth_context(_request(), ch, _settings(), issued.plaintext)
    assert exc.value.status_code == 401
    assert exc.value.detail == detail


def test_wrong_secret_for_known_key_id_is_rejected() -> None:
    issued = generate_api_key()
    ch = FakeClickHouse().on("FROM dim_user", [_user_row(issued)])
    forged = f"bsk_{issued.key_id}_forged-secret-value"
    with pytest.raises(HTTPException) as exc:
        resolve_auth_context(_request(), ch, _settings(), forged)
    assert exc.value.status_code == 401


def test_legacy_key_is_upgraded_to_scrypt_on_use() -> None:
    legacy = "0123456789abcdef0123456789abcdef"
    digest = hashlib.sha256(legacy.encode()).hexdigest()
    row = _user_row(
        SimpleNamespace(key_id=legacy_key_id(legacy), key_hash=f"sha256${digest}"), role=1
    )
    ch = (
        FakeClickHouse()
        .on("FROM dim_user", [row])
        .on("FROM dim_organization_member", [{"role": "viewer"}])
    )
    ctx = resolve_auth_context(_request(), ch, _settings(), legacy)
    assert ctx.role is OrgMemberRole.viewer
    upgrades = ch.commands_matching("INSERT INTO dim_user")
    assert len(upgrades) == 1
    params = upgrades[0][1]
    assert params["api_key_hash"].startswith("scrypt$")
    assert params["api_key"] == ""
    assert params["role"] == UserRole.admin.name


def test_enum_parse_accepts_names_and_numbers() -> None:
    assert OrgMemberRole.parse("admin") is OrgMemberRole.admin
    assert OrgMemberRole.parse(3) is OrgMemberRole.manager
    assert OrgMemberRole.parse("5") is OrgMemberRole.viewer
    with pytest.raises(ValueError):
        OrgMemberRole.parse("root")


def test_auth_logger_is_module_level() -> None:
    assert hasattr(auth_module, "LOGGER")
