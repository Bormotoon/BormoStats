"""SQL generation and tenant scoping of domain services (against a recording fake)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from app.models.bidder import AdCampaign, AdRuleCreate, AdRuleUpdate
from app.models.insights import TaskUpdate
from app.models.integrations import WebhookSubscriptionCreate
from app.models.pim import BrandCreate, ProductPimUpdate
from app.models.pnl import AdditionalExpenseCreate
from app.services.bidder_service import BidderService
from app.services.insights_service import InsightsService
from app.services.integrations_service import IntegrationsService, InvalidSubscriptionError
from app.services.pim_service import PimService
from app.services.pnl_service import PnlService
from app.services.tenancy import AccountAccessError

from common.secret_box import decrypt_secret
from tests.fakes import FakeClickHouse

OWNED_ACCOUNT = [{"count()": 1}]


def _owned(ch: FakeClickHouse) -> FakeClickHouse:
    return ch.on("SELECT count() FROM dim_account", OWNED_ACCOUNT)


def test_sync_campaigns_binds_every_column_c03() -> None:
    ch = _owned(FakeClickHouse())
    synced = BidderService(ch, "org-a").sync_campaigns(
        [
            AdCampaign(
                campaign_id="42",
                marketplace="wb",
                account_id="default",
                title="Brand",
                status="active",
                current_cpm=120.0,
            )
        ]
    )
    assert synced == 1
    ((sql, params),) = ch.commands_matching("INSERT INTO dim_ad_campaign")
    assert "{campaign_id:String}" in sql and params["campaign_id"] == "42"
    assert params["current_cpm"] == 120.0
    assert params["updated_at"].tzinfo is UTC


def test_sync_campaigns_rejects_foreign_accounts() -> None:
    ch = FakeClickHouse().on("SELECT count() FROM dim_account", [{"count()": 0}])
    with pytest.raises(AccountAccessError):
        BidderService(ch, "org-a").sync_campaigns(
            [AdCampaign(campaign_id="1", marketplace="wb", account_id="other")]
        )
    assert ch.commands == []


def test_rules_are_created_dry_run_with_full_uuid() -> None:
    ch = _owned(FakeClickHouse())
    rule = BidderService(ch, "org-a").create_rule(
        AdRuleCreate(campaign_id="42", marketplace="wb", product_id="777", target_cpm=100)
    )
    assert rule.dry_run is True
    assert len(rule.rule_id) == 36
    ((_, params),) = ch.commands_matching("INSERT INTO dim_ad_rule")
    assert params["dry_run"] == 1 and params["product_id"] == "777"


def test_rule_lookup_is_scoped_to_org() -> None:
    ch = FakeClickHouse()
    assert BidderService(ch, "org-a").update_rule("r1", AdRuleUpdate(target_cpm=5)) is None
    sql, params = ch.queries[0]
    assert "organization_id = {oid:String}" in sql
    assert params == {"oid": "org-a", "rid": "r1"}


TASK_ROW = {
    "task_id": "t-1",
    "organization_id": "org-a",
    "trigger_type": "turnover",
    "marketplace": "wb",
    "account_id": "default",
    "product_id": "1",
    "campaign_id": None,
    "title": "Need supply",
    "description": "",
    "priority": "high",
    "status": "open",
    "dedupe_key": "k",
    "created_at": datetime(2026, 9, 1, tzinfo=UTC),
    "resolved_at": None,
}


@pytest.mark.parametrize(
    ("initial", "new_status", "resolved_expected"),
    [("open", "resolved", True), ("resolved", "open", False), ("open", "dismissed", True)],
)
def test_update_task_transitions_c04(
    initial: str, new_status: str, resolved_expected: bool
) -> None:
    row = {**TASK_ROW, "status": initial}
    if initial == "resolved":
        row["resolved_at"] = datetime(2026, 9, 2, tzinfo=UTC)
    ch = FakeClickHouse().on("FROM dim_actionable_task", [row])
    task = InsightsService(ch, "org-a").update_task("t-1", TaskUpdate(status=new_status))
    assert task is not None and task.status == new_status
    ((_, params),) = ch.commands_matching("INSERT INTO dim_actionable_task")
    assert params["status"] == new_status
    assert (params["resolved_at"] is not None) is resolved_expected
    assert params["created_at"] == row["created_at"]  # keeps the ReplacingMergeTree key


def test_update_task_of_other_org_is_not_found() -> None:
    ch = FakeClickHouse()  # the org filter returns nothing
    assert InsightsService(ch, "org-b").update_task("t-1", TaskUpdate(status="resolved")) is None
    assert ch.queries[0][1]["oid"] == "org-b"
    assert ch.commands == []


def test_pim_writes_use_caller_org_not_default() -> None:
    ch = FakeClickHouse()
    brand = PimService(ch, "org-a").create_brand(BrandCreate(name="Acme"))
    assert brand.organization_id == "org-a"
    assert ch.commands[0][1]["organization_id"] == "org-a"


def test_pim_product_search_uses_bound_parameter() -> None:
    ch = FakeClickHouse()
    PimService(ch, "org-a").list_products(q="100%_'drop")
    sql, params = ch.queries[0]
    assert "100%" not in sql
    assert params["q"] == "100%_'drop"


def test_pim_update_for_foreign_account_is_rejected() -> None:
    ch = FakeClickHouse().on("SELECT count() FROM dim_account", [{"count()": 0}])
    with pytest.raises(AccountAccessError):
        PimService(ch, "org-a").update_product("wb", "other", "1", ProductPimUpdate(title="x"))


def test_expenses_belong_to_caller_org() -> None:
    ch = FakeClickHouse()
    expense = PnlService(ch, "org-a").create_expense(
        AdditionalExpenseCreate(category="rent", amount_rub=10, month="2026-09")
    )
    assert expense.organization_id == "org-a"
    assert ch.commands[0][1]["month"] == "2026-09-01"


def _settings(**overrides: Any) -> Any:
    base = {
        "webhook_secret_key": "unit-test-key",
        "webhook_allow_private_targets": False,
        "authenticated_redis_url": "redis://localhost:6379/0",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_webhook_secret_is_encrypted_and_returned_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("common.url_safety.resolve_host", lambda host, port: ("93.184.216.34",))
    ch = FakeClickHouse()
    service = IntegrationsService(ch, _settings(), "org-a")
    created = service.create_subscription(
        WebhookSubscriptionCreate(
            name="erp", endpoint_url="https://hooks.example.com/x", events=["insight.created"]
        )
    )
    stored = ch.commands[0][1]
    assert stored["organization_id"] == "org-a"
    assert stored["secret"] != created.secret and stored["secret"].startswith("v1:")
    assert decrypt_secret(stored["secret"], "unit-test-key") == created.secret

    ch.on("FROM webhook_subscriptions", [{**stored}])
    listed = service.list_subscriptions()
    assert "secret" not in listed[0].model_dump()
    assert listed[0].has_secret


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/x",
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/x",
        "https://user:pw@hooks.example.com/x",
    ],
)
def test_webhook_urls_are_ssrf_checked(url: str) -> None:
    service = IntegrationsService(FakeClickHouse(), _settings(), "org-a")
    with pytest.raises(InvalidSubscriptionError):
        service.create_subscription(
            WebhookSubscriptionCreate(name="x", endpoint_url=url, events=["webhook.test"])
        )


def test_unknown_webhook_events_are_rejected() -> None:
    service = IntegrationsService(FakeClickHouse(), _settings(), "org-a")
    with pytest.raises(InvalidSubscriptionError):
        service.create_subscription(
            WebhookSubscriptionCreate(
                name="x", endpoint_url="https://93.184.216.34/x", events=["everything"]
            )
        )


def test_organization_service_inserts_bind_every_parameter() -> None:
    from app.models.organization import (
        OrganizationCreate,
        OrganizationMemberCreate,
        OrgMemberRole,
        ShopAccountCreate,
    )
    from app.services.organization_service import OrganizationService

    ch = FakeClickHouse()
    service = OrganizationService(ch)
    org = service.create_organization(OrganizationCreate(name="Acme"))
    service.add_member(
        org.organization_id, OrganizationMemberCreate(user_id="u1", role=OrgMemberRole.admin)
    )
    service.create_shop_account(
        ShopAccountCreate(account_id="acc", marketplace="wb", title="Shop"),
        organization_id=org.organization_id,
    )
    tables = [sql.split("(")[0].split()[-1] for sql, _ in ch.commands]
    assert tables == ["dim_organization", "dim_organization_member", "dim_account"]
    assert ch.commands[1][1]["role"] == "admin"
    assert len(org.organization_id) == 36
