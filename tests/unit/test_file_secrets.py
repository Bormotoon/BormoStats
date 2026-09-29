from __future__ import annotations

from pathlib import Path

import pytest

from common.file_secrets import load_file_secrets


def test_file_secret_fills_missing_variable(tmp_path: Path) -> None:
    secret = tmp_path / "ch_password"
    secret.write_text("s3cret\n", encoding="utf-8")
    env = {"CH_PASSWORD_FILE": str(secret), "ADMIN_API_KEY": "set", "ADMIN_API_KEY_FILE": "/nope"}
    assert load_file_secrets(env) == ["CH_PASSWORD"]
    assert env["CH_PASSWORD"] == "s3cret"
    assert env["ADMIN_API_KEY"] == "set"  # explicit value wins, file is not read


def test_missing_secret_file_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="REDIS_PASSWORD_FILE"):
        load_file_secrets({"REDIS_PASSWORD_FILE": str(tmp_path / "missing")})
