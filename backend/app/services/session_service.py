"""Sign-in with e-mail and password, and the browser sessions it opens.

A session token is ``bss_<session_id>_<secret>``: ``session_id`` finds the row, only a
salted scrypt hash of ``secret`` is stored (``app.core.security``), exactly like API keys.
Passwords are hashed the same way in ``dim_user_credential``.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.security import hash_secret, verify_secret
from app.db.ch import utc_now
from clickhouse_connect.driver import Client

SESSION_PREFIX = "bss_"
_HEX = frozenset("0123456789abcdef")
SESSION_TTL = timedelta(days=30)
MIN_PASSWORD_LENGTH = 8
# a verifiable hash of a random secret, so an unknown e-mail costs the same scrypt time
_DUMMY_HASH = hash_secret(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class IssuedSession:
    session_id: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class ParsedSession:
    session_id: str
    secret: str


def parse_session_token(raw: str) -> ParsedSession | None:
    token = raw.strip()
    if not token.startswith(SESSION_PREFIX) or len(token) > 256:
        return None
    session_id, sep, secret = token[len(SESSION_PREFIX) :].partition("_")
    if not (sep and session_id and secret) or any(c not in _HEX for c in session_id):
        return None
    return ParsedSession(session_id=session_id, secret=secret)


class SessionService:
    def __init__(self, ch: Client) -> None:
        self._ch = ch

    # -- passwords --

    def set_password(self, user_id: str, password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
        self._ch.insert(
            "dim_user_credential",
            [[user_id, hash_secret(password), utc_now()]],
            column_names=["user_id", "password_hash", "updated_at"],
        )

    def check_password(self, user_id: str, password: str) -> bool:
        rows = self._ch.query(
            "SELECT password_hash FROM dim_user_credential FINAL WHERE user_id = {uid:String}",
            parameters={"uid": user_id},
        ).result_rows
        stored = str(rows[0][0]) if rows else ""
        return bool(stored) and verify_secret(password, stored)

    def verify_login(self, email: str, password: str) -> str | None:
        """The user id of an active user with this e-mail and password, else ``None``."""
        rows = self._ch.query(
            "SELECT u.user_id, c.password_hash"
            " FROM (SELECT user_id FROM dim_user FINAL"
            "       WHERE lower(email) = lower({email:String}) AND is_active = 1) AS u"
            " INNER JOIN (SELECT user_id, password_hash FROM dim_user_credential FINAL) AS c"
            " ON u.user_id = c.user_id"
            " LIMIT 1",
            parameters={"email": email.strip()},
        ).result_rows
        if not rows or not rows[0][1]:
            verify_secret(password, _DUMMY_HASH)
            return None
        user_id, password_hash = str(rows[0][0]), str(rows[0][1])
        return user_id if verify_secret(password, password_hash) else None

    # -- sessions --

    def create_session(self, user_id: str) -> IssuedSession:
        session_id = secrets.token_hex(12)
        secret = secrets.token_urlsafe(32)
        now = utc_now()
        expires_at = now + SESSION_TTL
        self._ch.insert(
            "sys_user_session",
            [[session_id, user_id, hash_secret(secret), now, expires_at, None, now]],
            column_names=[
                "session_id",
                "user_id",
                "token_hash",
                "created_at",
                "expires_at",
                "revoked_at",
                "updated_at",
            ],
        )
        return IssuedSession(
            session_id=session_id,
            token=f"{SESSION_PREFIX}{session_id}_{secret}",
            expires_at=expires_at,
        )

    def authenticate(self, token: str) -> tuple[str, datetime] | None:
        """``(user_id, expires_at)`` of a live session, else ``None``."""
        parsed = parse_session_token(token)
        if parsed is None:
            return None
        rows = self._ch.query(
            "SELECT user_id, token_hash, expires_at, revoked_at FROM sys_user_session FINAL"
            " WHERE session_id = {sid:String}",
            parameters={"sid": parsed.session_id},
        ).result_rows
        if not rows:
            return None
        user_id, token_hash, expires_at, revoked_at = rows[0]
        if revoked_at is not None or not verify_secret(parsed.secret, str(token_hash)):
            return None
        expires = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=utc_now().tzinfo)
        if expires <= utc_now():
            return None
        return str(user_id), expires

    def revoke(self, token: str) -> bool:
        parsed = parse_session_token(token)
        if parsed is None:
            return False
        rows = self._ch.query(
            "SELECT user_id, token_hash, created_at, expires_at FROM sys_user_session FINAL"
            " WHERE session_id = {sid:String} AND revoked_at IS NULL",
            parameters={"sid": parsed.session_id},
        ).result_rows
        if not rows:
            return False
        user_id, token_hash, created_at, expires_at = rows[0]
        now = utc_now()
        self._ch.insert(
            "sys_user_session",
            [[parsed.session_id, user_id, token_hash, created_at, expires_at, now, now]],
            column_names=[
                "session_id",
                "user_id",
                "token_hash",
                "created_at",
                "expires_at",
                "revoked_at",
                "updated_at",
            ],
        )
        return True
