"""Guard rails around marketplace side effects (bid and price changes).

Every planned change goes through :func:`execute_action`, which

1. de-duplicates by an idempotency key (same rule/target/value/day → one record);
2. only simulates when the rule is in dry-run mode or the global kill switch
   ``MARKETPLACE_ACTIONS_ENABLED`` is off;
3. calls the marketplace otherwise and stores status, HTTP code and response
   body with before/after values in ``sys_marketplace_actions``.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import clickhouse_connect
import structlog
from app.utils.metrics import observe_marketplace_action

from collectors.marketplace_actions import ActionResult

LOGGER = structlog.get_logger(__name__)

STATUS_SIMULATED = "simulated"
STATUS_BLOCKED = "blocked_kill_switch"
STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"
STATUS_UNSUPPORTED = "unsupported"
STATUS_DUPLICATE = "skipped_duplicate"
DEFAULT_MAX_ACTIONS_PER_RUN = 100

_INSERT = (
    "INSERT INTO sys_marketplace_actions"
    " (action_id, organization_id, source, rule_id, marketplace, account_id, target_type,"
    " target_id, before_value, after_value, dry_run, status, response_status, response_body,"
    " idempotency_key, created_at)"
    " VALUES ({action_id:String}, {organization_id:String}, {source:String}, {rule_id:String},"
    " {marketplace:String}, {account_id:String}, {target_type:String}, {target_id:String},"
    " {before_value:Nullable(Float64)}, {after_value:Float64}, {dry_run:UInt8},"
    " {status:String}, {response_status:UInt16}, {response_body:String},"
    " {idempotency_key:String}, {created_at:DateTime})"
)


@dataclass(frozen=True)
class PlannedAction:
    organization_id: str
    source: str
    rule_id: str
    marketplace: str
    account_id: str
    target_type: str
    target_id: str
    before_value: float | None
    after_value: float
    dry_run: bool

    def idempotency_key(self, now: datetime | None = None) -> str:
        day = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
        raw = "|".join(
            (
                self.source,
                self.rule_id,
                self.marketplace,
                self.account_id,
                self.target_type,
                self.target_id,
                f"{self.after_value:.2f}",
                "dry" if self.dry_run else "live",
                day,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def actions_enabled() -> bool:
    """Global kill switch; live marketplace writes happen only when explicitly enabled."""
    return os.getenv("MARKETPLACE_ACTIONS_ENABLED", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def max_actions_per_run() -> int:
    try:
        return max(1, int(os.getenv("MARKETPLACE_ACTIONS_MAX_PER_RUN", "")))
    except ValueError:
        return DEFAULT_MAX_ACTIONS_PER_RUN


def _already_recorded(client: clickhouse_connect.driver.Client, key: str) -> bool:
    rows = client.query(
        "SELECT count() FROM sys_marketplace_actions"
        " WHERE idempotency_key = {key:String} AND status != {failed:String}",
        parameters={"key": key, "failed": STATUS_FAILED},
    ).result_rows
    return bool(rows and rows[0][0])


def _record(
    client: clickhouse_connect.driver.Client,
    action: PlannedAction,
    *,
    key: str,
    status: str,
    result: ActionResult | None,
) -> None:
    client.command(
        _INSERT,
        parameters={
            "action_id": str(uuid.uuid4()),
            "organization_id": action.organization_id,
            "source": action.source,
            "rule_id": action.rule_id,
            "marketplace": action.marketplace,
            "account_id": action.account_id,
            "target_type": action.target_type,
            "target_id": action.target_id,
            "before_value": action.before_value,
            "after_value": action.after_value,
            "dry_run": 1 if action.dry_run else 0,
            "status": status,
            "response_status": result.status_code if result else 0,
            "response_body": result.body if result else "",
            "idempotency_key": key,
            "created_at": datetime.now(UTC).replace(microsecond=0),
        },
    )


def execute_action(
    client: clickhouse_connect.driver.Client,
    action: PlannedAction,
    executor: Callable[[], ActionResult] | None,
) -> str:
    """Apply (or simulate) one change and return the recorded status.

    ``executor`` is ``None`` when the marketplace/operation has no supported API
    or credentials; the change is then recorded as ``unsupported``.
    """
    key = action.idempotency_key()
    if _already_recorded(client, key):
        observe_marketplace_action(action.source, STATUS_DUPLICATE)
        return STATUS_DUPLICATE

    result: ActionResult | None = None
    if action.dry_run:
        status = STATUS_SIMULATED
    elif not actions_enabled():
        status = STATUS_BLOCKED
    elif executor is None:
        status = STATUS_UNSUPPORTED
    else:
        result = executor()
        status = STATUS_APPLIED if result.ok else STATUS_FAILED

    _record(client, action, key=key, status=status, result=result)
    observe_marketplace_action(action.source, status)
    LOGGER.info(
        "marketplace_action",
        source=action.source,
        rule_id=action.rule_id,
        marketplace=action.marketplace,
        target_type=action.target_type,
        target_id=action.target_id,
        before_value=action.before_value,
        after_value=action.after_value,
        status=status,
        response_status=result.status_code if result else None,
    )
    return status
