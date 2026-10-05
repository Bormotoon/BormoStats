from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _as(token: str) -> dict[str, str]:
    return {"X-API-Key": token}


def test_password_sign_in_opens_a_session_that_signs_out(
    integration_runtime: Any, api_client: TestClient
) -> None:
    created = api_client.post(
        "/api/v1/users",
        json={"name": "Owner", "email": "Owner@Example.com", "role": 1, "org_role": 1},
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["user_id"]

    assert (
        api_client.put(
            f"/api/v1/auth/users/{user_id}/password", json={"password": "short"}
        ).status_code
        == 422
    )
    assert (
        api_client.put(
            f"/api/v1/auth/users/{user_id}/password", json={"password": "correct horse"}
        ).status_code
        == 200
    )

    wrong = api_client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "nope"},
        headers={"X-API-Key": ""},
    )
    assert wrong.status_code == 401
    unknown = api_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "correct horse"},
        headers={"X-API-Key": ""},
    )
    assert unknown.status_code == 401

    # e-mail is matched case-insensitively
    login = api_client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct horse"},
        headers={"X-API-Key": ""},
    )
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    assert token.startswith("bss_")

    me = api_client.get("/api/v1/users/me", headers=_as(token))
    assert me.status_code == 200
    assert me.json()["auth_method"] == "session"
    assert me.json()["principal_id"] == user_id

    bad_change = api_client.post(
        "/api/v1/auth/password",
        json={"current_password": "wrong", "new_password": "battery staple"},
        headers=_as(token),
    )
    assert bad_change.status_code == 400
    change = api_client.post(
        "/api/v1/auth/password",
        json={"current_password": "correct horse", "new_password": "battery staple"},
        headers=_as(token),
    )
    assert change.status_code == 200
    relogin = api_client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "battery staple"},
        headers={"X-API-Key": ""},
    )
    assert relogin.status_code == 200

    assert api_client.post("/api/v1/auth/logout", headers=_as(token)).json() == {"revoked": True}
    assert api_client.get("/api/v1/users/me", headers=_as(token)).status_code == 401
