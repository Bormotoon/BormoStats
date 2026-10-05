"""Permanent archive of every statistics row the collectors ingest.

The ``raw_*`` tables are a working set: ReplacingMergeTree keeps one version per key and
``prune_old_raw`` deletes old months. The archive records each *version* of every row in
the history store (repo = table name), so a status change of a posting, a recalculated
funnel day or a metric the marketplace later removes stays queryable forever.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.utils.history_store import (
    HistoryStore,
    Observation,
    RecordResult,
    history_enabled,
    ignore_patterns,
)

from common.history import load_json_or_text

LOGGER = logging.getLogger(__name__)

BACKFILL_MARKER_PREFIX = "history_backfill_done:"
BACKFILL_MARKER_ACCOUNT = "all"
STAT_IGNORE_ENV = "HISTORY_STAT_IGNORE_PATHS"


@dataclass(frozen=True)
class StatSpec:
    marketplace: str
    # columns identifying one logical row (the table's ORDER BY minus its time column)
    key: tuple[str, ...]
    # column that dates a row; drives the backfill windows and the retention cut-off
    time_column: str
    # columns describing the observation, not the state, so they never cause a commit
    volatile: tuple[str, ...] = ("run_id", "ingested_at")
    # column holding when the state was observed (falls back to ``ingested_at``, then now)
    observed_column: str | None = None
    # for a table holding several marketplaces: the column naming the row's marketplace
    marketplace_column: str | None = None
    # the table's datetimes are true instants (written timezone-aware), not the collectors'
    # naive-UTC convention that a backfill has to undo
    true_instants: bool = False


STAT_SPECS: dict[str, StatSpec] = {
    # a sale (S…) and its return (R…) share the srid; sale_id keeps them apart
    "raw_wb_sales": StatSpec("wb", ("srid", "nm_id", "chrt_id", "sale_id"), "event_ts"),
    "raw_wb_orders": StatSpec("wb", ("srid", "nm_id", "chrt_id"), "event_ts"),
    "raw_wb_stocks": StatSpec(
        "wb",
        ("nm_id", "chrt_id", "warehouse_id"),
        "snapshot_ts",
        volatile=("run_id", "ingested_at", "snapshot_ts"),
        observed_column="snapshot_ts",
    ),
    "raw_wb_funnel_daily": StatSpec("wb", ("day", "nm_id"), "day"),
    "raw_ozon_postings": StatSpec("ozon", ("posting_number",), "created_at"),
    "raw_ozon_posting_items": StatSpec(
        "ozon", ("posting_number", "ozon_product_id"), "ingested_at"
    ),
    "raw_ozon_stocks": StatSpec(
        "ozon",
        ("ozon_product_id", "warehouse_id"),
        "snapshot_ts",
        volatile=("run_id", "ingested_at", "snapshot_ts"),
        observed_column="snapshot_ts",
    ),
    "raw_ozon_ads_daily": StatSpec("ozon", ("day", "campaign_id"), "day"),
    "raw_ozon_finance_ops": StatSpec("ozon", ("operation_id",), "operation_ts"),
    # finance block: the balance breakdown of a day, report lines, balance snapshots
    "raw_ozon_finance_balance": StatSpec("ozon", ("day",), "day"),
    "raw_wb_sales_report": StatSpec("wb", ("rrd_id",), "day"),
    "raw_marketplace_balance": StatSpec(
        "",
        ("marketplace",),
        "snapshot_ts",
        volatile=("run_id", "ingested_at", "snapshot_ts"),
        observed_column="snapshot_ts",
        marketplace_column="marketplace",
        true_instants=True,
    ),
}

# Entities whose table changed its key: the old keys stay in the archive as history and are
# retired (a deletion commit) so a point-in-time view does not count a row twice.
LEGACY_ENTITY_FILTERS: dict[str, tuple[str, str]] = {
    # srid|nm_id|chrt_id until 0029 added sale_id: a return replaced its sale
    "raw_wb_sales": (
        "length(splitByChar('|', entity_key)) = 3",
        "re-keyed: sale_id joined the key (migration 0029)",
    ),
    # items stored before postings carried the SKU; duplicates of the SKU rows (0029)
    "raw_ozon_posting_items": (
        "endsWith(entity_key, '|0')",
        "removed: duplicate of the item stored under its SKU (migration 0029)",
    ),
}


def _key_part(value: Any) -> str:
    return "" if value is None else str(value)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return None


def _observation(
    spec: StatSpec, row: dict[str, Any], columns: list[str] | None = None
) -> Observation:
    # only stored columns count: a parser adding a helper key must not change the state
    names = columns if columns is not None else list(row)
    document = {
        column: row.get(column)
        for column in names
        if column not in spec.volatile and column != "payload"
    }
    if "payload" in names:
        document["payload"] = load_json_or_text(row["payload"])
    observed = None
    if spec.observed_column:
        observed = _as_datetime(row.get(spec.observed_column))
    if observed is None:
        observed = _as_datetime(row.get("ingested_at"))
    return Observation(
        entity_key="|".join(_key_part(row.get(column)) for column in spec.key),
        document=document,
        observed_at=observed,
    )


def archive_rows(
    client: Any,
    table: str,
    rows: list[dict[str, Any]],
    *,
    run_id: str = "",
    source: str = "ingest",
    columns: list[str] | None = None,
) -> RecordResult | None:
    """Commit the given ``raw_*`` rows; unchanged rows cost a lookup and write nothing."""
    spec = STAT_SPECS.get(table)
    if spec is None or not rows or not history_enabled():
        return None
    by_account: dict[tuple[str, str], list[Observation]] = {}
    for row in rows:
        account_id = str(row.get("account_id") or "default")
        marketplace = (
            str(row.get(spec.marketplace_column) or "")
            if spec.marketplace_column
            else spec.marketplace
        )
        by_account.setdefault((marketplace, account_id), []).append(
            _observation(spec, row, columns)
        )

    store = HistoryStore(client, run_id=run_id or "", source=source)
    total = RecordResult()
    ignore = ignore_patterns(STAT_IGNORE_ENV)
    for (marketplace, account_id), observations in by_account.items():
        part = store.record(
            marketplace=marketplace,
            account_id=account_id,
            repo=table,
            observations=observations,
            ignore=ignore,
        )
        for name in ("seen", "unchanged", "created", "modified", "changes"):
            setattr(total, name, getattr(total, name) + getattr(part, name))
    return total


# -- one-off import of what the raw tables held before the archive existed --


def backfill_done(client: Any, table: str) -> bool:
    result = client.query(
        "SELECT count() FROM sys_watermarks WHERE source = %(source)s AND account_id = %(account)s",
        parameters={
            "source": BACKFILL_MARKER_PREFIX + table,
            "account": BACKFILL_MARKER_ACCOUNT,
        },
    )
    return bool(result.result_rows and result.result_rows[0][0])


def _mark_backfill_done(client: Any, table: str) -> None:
    client.insert(
        table="sys_watermarks",
        data=[[BACKFILL_MARKER_PREFIX + table, BACKFILL_MARKER_ACCOUNT, datetime.now(UTC)]],
        column_names=["source", "account_id", "watermark_ts"],
    )


def _as_ingested(row: dict[str, Any]) -> dict[str, Any]:
    """Give a row read back from ClickHouse the datetimes its collector originally wrote.

    Collectors hand naive datetimes to clickhouse_connect, which reads them as process-local
    time and stores them as UTC; reading converts them back to UTC. Undoing that makes a
    backfilled row hash like the same row ingested live. ``ingested_at`` is the server's own
    ``now()`` (true UTC) and stays as is.
    """
    converted: dict[str, Any] = {}
    for column, value in row.items():
        if isinstance(value, datetime) and column != "ingested_at":
            aware = value if value.tzinfo else value.replace(tzinfo=UTC)
            value = aware.astimezone().replace(tzinfo=None)
        converted[column] = value
    return converted


def _days(first: date, last: date) -> Iterator[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def backfill_table(client: Any, table: str, *, run_id: str) -> dict[str, int]:
    """Archive the current contents of one raw table, day by day (idempotent)."""
    spec = STAT_SPECS[table]
    bounds = client.query(
        f"SELECT min(toDate({spec.time_column})), max(toDate({spec.time_column})) FROM {table}"
    ).result_rows
    totals = {"rows": 0, "commits": 0}
    if not bounds or bounds[0][0] is None or bounds[0][1] is None:
        _mark_backfill_done(client, table)
        return totals
    first, last = bounds[0]
    # 1970-01-01 is what min() yields for an empty table; nothing to import then
    if last < first or last.year < 2000:
        _mark_backfill_done(client, table)
        return totals
    for day in _days(first, last):
        result = client.query(
            f"SELECT * FROM {table} FINAL WHERE toDate({spec.time_column}) = %(day)s",
            parameters={"day": day},
        )
        rows = [row if spec.true_instants else _as_ingested(row) for row in result.named_results()]
        if not rows:
            continue
        archived = archive_rows(client, table, rows, run_id=run_id, source="backfill")
        totals["rows"] += len(rows)
        if archived is not None:
            totals["commits"] += archived.commits
    _mark_backfill_done(client, table)
    return totals


def retire_legacy_entities(client: Any, *, run_id: str) -> dict[str, int]:
    """Deletion commits for the live entities of ``LEGACY_ENTITY_FILTERS`` (idempotent)."""
    retired: dict[str, int] = {}
    store = HistoryStore(client, run_id=run_id, source="maintenance")
    for repo, (condition, message) in LEGACY_ENTITY_FILTERS.items():
        result = client.query(
            "SELECT marketplace, account_id, groupArray(entity_key) FROM hist_refs FINAL"
            f" WHERE repo = %(repo)s AND is_deleted = 0 AND {condition}"
            " GROUP BY marketplace, account_id",
            parameters={"repo": repo},
        )
        for marketplace, account_id, keys in result.result_rows:
            part = store.record(
                marketplace=str(marketplace),
                account_id=str(account_id),
                repo=repo,
                observations=[],
                retire=list(keys),
                retire_message=message,
            )
            retired[repo] = retired.get(repo, 0) + part.deleted
    return retired
