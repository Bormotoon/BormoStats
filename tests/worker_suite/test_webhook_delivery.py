from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.tasks import webhooks
from app.tasks.webhooks import Subscription, build_body, send_signed

from common.secret_box import SecretBoxError, decrypt_secret, encrypt_secret
from common.webhooks import MAX_DELIVERY_ATTEMPTS, verify_signature
from tests.fakes import FakeClickHouse

SUB = Subscription(
    subscription_id="s1",
    organization_id="org-a",
    endpoint_url="https://hooks.example.com/in",
    encrypted_secret="",
    events=["*"],
    is_active=True,
)


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("common.url_safety.resolve_host", lambda host, port: ("93.184.216.34",))


def test_signed_delivery_is_verifiable_and_pinned() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    body = build_body("evt-1", "webhook.test", "org-a", {"x": 1})
    outcome = send_signed(
        SUB, "shh", "evt-1", "webhook.test", body, transport=httpx.MockTransport(handler)
    )
    assert outcome.success
    request = captured[0]
    assert request.url.host == "93.184.216.34"  # connection pinned to the validated IP
    assert request.headers["Host"] == "hooks.example.com"
    assert request.headers["Idempotency-Key"] == "evt-1"
    ts = int(request.headers["X-BormoStats-Timestamp"])
    assert verify_signature("shh", ts, request.content, request.headers["X-BormoStats-Signature"])
    assert not verify_signature(
        "other", ts, request.content, request.headers["X-BormoStats-Signature"]
    )
    assert not verify_signature(
        "shh", ts, request.content, request.headers["X-BormoStats-Signature"], now=ts + 3600
    )


def test_private_targets_are_blocked_at_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("common.url_safety.resolve_host", lambda host, port: ("10.0.0.7",))
    outcome = send_signed(SUB, "shh", "e", "webhook.test", b"{}")
    assert outcome.status == "blocked"


def test_redirects_are_not_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})

    outcome = send_signed(
        SUB, "s", "e", "webhook.test", b"{}", transport=httpx.MockTransport(handler)
    )
    assert outcome.status == "failed" and outcome.response_status == 302


def _run_delivery(
    monkeypatch: pytest.MonkeyPatch, attempt: int, status_code: int
) -> tuple[FakeClickHouse, list[dict[str, Any]]]:
    monkeypatch.setenv("WEBHOOK_SECRET_KEY", "k")
    ch = FakeClickHouse().on(
        "FROM webhook_subscriptions",
        [
            {
                "subscription_id": "s1",
                "organization_id": "org-a",
                "endpoint_url": SUB.endpoint_url,
                "secret": encrypt_secret("shh", "k"),
                "events": ["*"],
                "is_active": 1,
            }
        ],
    )
    scheduled: list[dict[str, Any]] = []
    monkeypatch.setattr(webhooks, "get_ch_client", lambda: ch)
    monkeypatch.setattr(
        webhooks.current_app, "send_task", lambda name, **kw: scheduled.append({"name": name, **kw})
    )
    real_client = httpx.Client

    def client_factory(**kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(lambda r: httpx.Response(status_code))
        return real_client(**kwargs)

    monkeypatch.setattr(webhooks.httpx, "Client", client_factory)
    webhooks.deliver_to_subscription("org-a", "s1", "evt", "webhook.test", {}, attempt=attempt)
    return ch, scheduled


def test_failed_delivery_is_retried_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    ch, scheduled = _run_delivery(monkeypatch, attempt=1, status_code=500)
    ((_, log),) = ch.commands_matching("INSERT INTO webhook_logs")
    assert log["status"] == "retrying" and log["next_retry_at"] is not None
    assert scheduled[0]["kwargs"]["attempt"] == 2 and scheduled[0]["countdown"] == 30


def test_last_failure_goes_to_dead_letter(monkeypatch: pytest.MonkeyPatch) -> None:
    ch, scheduled = _run_delivery(monkeypatch, attempt=MAX_DELIVERY_ATTEMPTS, status_code=503)
    ((_, log),) = ch.commands_matching("INSERT INTO webhook_logs")
    assert log["status"] == "dead_letter" and scheduled == []


def test_success_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    ch, scheduled = _run_delivery(monkeypatch, attempt=1, status_code=200)
    ((_, log),) = ch.commands_matching("INSERT INTO webhook_logs")
    assert log["status"] == "delivered" and log["success"] == 1 and scheduled == []


def test_secret_box_rejects_wrong_key() -> None:
    token = encrypt_secret("value", "k1")
    assert decrypt_secret(token, "k1") == "value"
    with pytest.raises(SecretBoxError):
        decrypt_secret(token, "k2")
    with pytest.raises(SecretBoxError):
        encrypt_secret("value", "")
