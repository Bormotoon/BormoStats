"""Authenticated encryption for secrets stored in ClickHouse (e.g. webhook secrets).

Values are encrypted with AES-256-GCM under a key derived from ``WEBHOOK_SECRET_KEY``.
The stored format is ``v1:<nonce>:<ciphertext>`` (URL-safe base64, no padding).
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = "v1"
_NONCE_BYTES = 12
_AAD = b"bormostats-secret-box-v1"


class SecretBoxError(RuntimeError):
    """Raised when encryption is unavailable or a ciphertext cannot be decrypted."""


def _derive_key(master_key: str) -> bytes:
    if not master_key.strip():
        raise SecretBoxError("WEBHOOK_SECRET_KEY is not configured")
    return hashlib.sha256(f"bormostats:secret-box:{master_key}".encode()).digest()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encrypt_secret(plaintext: str, master_key: str) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_derive_key(master_key)).encrypt(nonce, plaintext.encode("utf-8"), _AAD)
    return f"{_VERSION}:{_b64e(nonce)}:{_b64e(ciphertext)}"


def decrypt_secret(token: str, master_key: str) -> str:
    parts = token.split(":")
    if len(parts) != 3 or parts[0] != _VERSION:
        raise SecretBoxError("unsupported secret format")
    try:
        plaintext = AESGCM(_derive_key(master_key)).decrypt(_b64d(parts[1]), _b64d(parts[2]), _AAD)
    except (InvalidTag, ValueError) as exc:
        raise SecretBoxError("secret could not be decrypted") from exc
    return plaintext.decode("utf-8")
