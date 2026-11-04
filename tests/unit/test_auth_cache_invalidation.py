"""Tests for auth cache invalidation and session revocation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.core import auth as auth_module
from app.core.auth import invalidate_auth_cache
from app.services.session_service import SessionService

from tests.fakes import FakeClickHouse


def test_session_service_revoke_all_for_user() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    ch = FakeClickHouse()
    ch.on(
        "SELECT session_id, user_id, token_hash, created_at, expires_at",
        [
            {
                "session_id": "sess_1",
                "user_id": "usr_1",
                "token_hash": "hash_1",
                "created_at": now,
                "expires_at": now + timedelta(days=30),
            },
            {
                "session_id": "sess_2",
                "user_id": "usr_1",
                "token_hash": "hash_2",
                "created_at": now,
                "expires_at": now + timedelta(days=30),
            },
        ],
    )
    svc = SessionService(ch)
    revoked = svc.revoke_all_for_user("usr_1")
    assert revoked == 2
    assert len(ch.inserts) == 1
    table, rows, cols = ch.inserts[0]
    assert table == "sys_user_session"
    assert len(rows) == 2
    assert "revoked_at" in cols


def test_session_service_revoke_other_sessions() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    ch = FakeClickHouse()
    ch.on(
        "SELECT session_id, user_id, token_hash, created_at, expires_at",
        [
            {
                "session_id": "sess_other",
                "user_id": "usr_1",
                "token_hash": "hash_2",
                "created_at": now,
                "expires_at": now + timedelta(days=30),
            }
        ],
    )
    svc = SessionService(ch)
    revoked = svc.revoke_other_sessions("usr_1", keep_session_id="sess_current")
    assert revoked == 1
    assert len(ch.inserts) == 1
    _table, rows, _cols = ch.inserts[0]
    assert rows[0][0] == "sess_other"


def test_invalidate_auth_cache_clears_entries() -> None:
    with patch.object(auth_module._CACHE, "clear") as mock_clear:
        invalidate_auth_cache()
        assert mock_clear.called
