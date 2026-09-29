"""API key generation, hashing and constant-time verification.

User API keys have the form ``bsk_<key_id>_<secret>``. Only ``key_id`` (used for
lookup) and a salted scrypt hash of ``secret`` are stored. Keys issued before
hashing was introduced are migrated by ``0021_api_key_hashing.sql`` to an
unsalted SHA-256 digest (acceptable for 128-bit random tokens) and upgraded to
scrypt on first successful use.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

KEY_PREFIX = "bsk_"
KEY_ID_HEX_LENGTH = 16
LEGACY_KEY_ID_PREFIX = "legacy_"
LEGACY_KEY_ID_HEX_LENGTH = 24

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16


@dataclass(frozen=True)
class ParsedApiKey:
    key_id: str
    secret: str
    legacy: bool


@dataclass(frozen=True)
class IssuedApiKey:
    """A freshly generated key: ``plaintext`` is shown to the caller exactly once."""

    key_id: str
    plaintext: str
    key_hash: str


def generate_api_key() -> IssuedApiKey:
    key_id = secrets.token_hex(KEY_ID_HEX_LENGTH // 2)
    secret = secrets.token_urlsafe(32)
    return IssuedApiKey(
        key_id=key_id,
        plaintext=f"{KEY_PREFIX}{key_id}_{secret}",
        key_hash=hash_secret(secret),
    )


def legacy_key_id(raw_key: str) -> str:
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"{LEGACY_KEY_ID_PREFIX}{digest[:LEGACY_KEY_ID_HEX_LENGTH]}"


def parse_api_key(raw_key: str) -> ParsedApiKey | None:
    key = raw_key.strip()
    if not key or len(key) > 256:
        return None
    id_end = len(KEY_PREFIX) + KEY_ID_HEX_LENGTH
    if key.startswith(KEY_PREFIX):
        key_id = key[len(KEY_PREFIX) : id_end]
        well_formed = (
            len(key) > id_end + 1
            and key[id_end] == "_"
            and all(ch in "0123456789abcdef" for ch in key_id)
        )
        if not well_formed:
            return None
        return ParsedApiKey(key_id=key_id, secret=key[id_end + 1 :], legacy=False)
    return ParsedApiKey(key_id=legacy_key_id(key), secret=key, legacy=True)


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _scrypt(secret, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            _b64encode(salt),
            _b64encode(digest),
        )
    )


def verify_secret(secret: str, stored_hash: str) -> bool:
    parts = stored_hash.split("$")
    try:
        if parts[0] == "scrypt" and len(parts) == 6:
            n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
            expected = _b64decode(parts[5])
            actual = _scrypt(secret, _b64decode(parts[4]), n, r, p, dklen=len(expected))
            return hmac.compare_digest(actual, expected)
        if parts[0] == "sha256" and len(parts) == 2:
            actual_hex = hashlib.sha256(secret.encode("utf-8")).hexdigest()
            return hmac.compare_digest(actual_hex, parts[1])
    except ValueError, TypeError:
        return False
    return False


def needs_rehash(stored_hash: str) -> bool:
    return not stored_hash.startswith(f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}$")


def constant_time_equals(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _scrypt(secret: str, salt: bytes, n: int, r: int, p: int, dklen: int = _SCRYPT_DKLEN) -> bytes:
    return hashlib.scrypt(
        secret.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=64 * 1024 * 1024
    )


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
