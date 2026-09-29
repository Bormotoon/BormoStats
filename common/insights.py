"""Actionable-task storage contract shared by the API and the insights generator."""

from __future__ import annotations

import hashlib

from common.sql import insert_values_sql

TASK_COLUMNS: tuple[tuple[str, str], ...] = (
    ("task_id", "String"),
    ("organization_id", "String"),
    ("trigger_type", "String"),
    ("marketplace", "String"),
    ("account_id", "String"),
    ("product_id", "Nullable(String)"),
    ("campaign_id", "Nullable(String)"),
    ("title", "String"),
    ("description", "String"),
    ("priority", "String"),
    ("status", "String"),
    ("dedupe_key", "String"),
    ("created_at", "DateTime"),
    ("resolved_at", "Nullable(DateTime)"),
)
TASK_COLS = ", ".join(name for name, _ in TASK_COLUMNS)
TASK_INSERT = insert_values_sql("dim_actionable_task", TASK_COLUMNS)
ACTIVE_STATUSES = ("open", "in_progress")
DISMISS_SUPPRESSION_DAYS = 7


def dedupe_key(
    organization_id: str,
    trigger_type: str,
    marketplace: str,
    account_id: str,
    product_id: str | None,
    campaign_id: str | None,
) -> str:
    """Logical identity of a recommendation: one open task per subject and trigger."""
    raw = "|".join(
        (
            organization_id,
            trigger_type,
            marketplace,
            account_id,
            product_id or "",
            campaign_id or "",
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
