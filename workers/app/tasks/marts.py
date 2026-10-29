"""Tasks for building analytics marts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.sql.loader import load_sql
from app.utils.celery_helpers import shared_task
from app.utils.locking import LockNotAcquiredError
from app.utils.rebuilds import LOGGER as REBUILD_LOGGER
from app.utils.rebuilds import rebuild_task_scope
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context
from clickhouse_connect.driver import Client

from common.query_cache import bump_generation

_MARTS_DIR = Path(__file__).resolve().parents[1] / "sql" / "marts"


def _load(name: str) -> str:
    return load_sql(_MARTS_DIR, name)


# business days are Moscow days, as in the marketplaces' reports
MOSCOW_TODAY = "toDate(now(), 'Europe/Moscow')"
SYNC_MUTATION = {"mutations_sync": 2}


def _window_delete(table_name: str, day_column: str) -> str:
    return f"ALTER TABLE {table_name} DELETE WHERE {day_column} >= {MOSCOW_TODAY} - %(days)s"


MART_REBUILD_TABLES = (
    ("mrt_sales_daily", "day"),
    ("mrt_stock_daily", "day"),
    ("mrt_funnel_daily", "day"),
    ("mrt_profit_daily", "day"),
    ("mrt_ad_performance_daily", "day"),
    ("mrt_finance_daily", "day"),
)


def _build_price_current(client: Client) -> None:
    """Replace the price breakdown snapshot: insert the new build, then drop older builds.

    Readers never see an empty table; until the delete finishes they may see both builds,
    which ``FINAL`` collapses to the newer one.
    """
    built_at = datetime.now(UTC).replace(microsecond=0)
    client.command(_load("mrt_price_current.sql"), parameters={"built_at": built_at})
    client.command(
        "ALTER TABLE mrt_price_current DELETE WHERE built_at < {built_at:DateTime}",
        parameters={"built_at": built_at},
        settings=SYNC_MUTATION,
    )


def _run_marts(days: int, task_name: str) -> dict[str, str | int]:
    run_id, started_at = new_run_context()
    client = get_ch_client()
    redis_client = get_redis_client()

    try:
        with rebuild_task_scope(
            redis_client=redis_client,
            task_lock_source=task_name.rsplit(".", maxsplit=1)[-1],
        ):
            ads_days = max(days, 60)
            # a separate SET is lost between HTTP requests (no session), so every delete
            # carries the setting itself and finishes before the rows are re-inserted
            for table_name, day_column in MART_REBUILD_TABLES:
                client.command(
                    _window_delete(table_name, day_column),
                    parameters={
                        "days": ads_days if table_name == "mrt_ad_performance_daily" else days
                    },
                    settings=SYNC_MUTATION,
                )
            client.command(
                _window_delete("mrt_ads_daily", "day"),
                parameters={"days": ads_days},
                settings=SYNC_MUTATION,
            )
            client.command(_load("mrt_sales_daily.sql"), parameters={"days": days})
            client.command(_load("mrt_stock_daily.sql"), parameters={"days": days})
            client.command(_load("mrt_funnel_daily.sql"), parameters={"days": days})
            client.command(_load("mrt_ads_daily.sql"), parameters={"days": ads_days})
            client.command(_load("mrt_profit_daily.sql"), parameters={"days": days})
            client.command(
                f"ALTER TABLE mrt_supply_planning_daily DELETE WHERE day = {MOSCOW_TODAY}",
                settings=SYNC_MUTATION,
            )
            client.command(_load("mrt_supply_planning_daily.sql"))
            client.command(_load("mrt_ad_performance_daily.sql"), parameters={"days": ads_days})
            client.command(_load("mrt_finance_daily_ozon.sql"), parameters={"days": days})
            client.command(_load("mrt_finance_daily_wb.sql"), parameters={"days": days})
            # the P&L is monthly: every month the window touches is rebuilt whole
            client.command(
                "ALTER TABLE mrt_pnl_monthly DELETE"
                f" WHERE month >= toStartOfMonth({MOSCOW_TODAY} - %(days)s)",
                parameters={"days": days},
                settings=SYNC_MUTATION,
            )
            client.command(_load("mrt_pnl_monthly.sql"), parameters={"days": days})
            client.command(_load("mrt_pnl_monthly_expenses.sql"), parameters={"days": days})
            # a snapshot of today's classes, read by the ABC/XYZ page and the insights; earlier
            # days are the class history and cannot be rebuilt, so only today is replaced
            client.command(
                f"ALTER TABLE mrt_abc_xyz_analysis DELETE WHERE day = {MOSCOW_TODAY}",
                settings=SYNC_MUTATION,
            )
            client.command(_load("mrt_abc_xyz_daily.sql"))
            _build_price_current(client)
        # The API caches mart reads; drop them now that fresh rows are in place.
        bump_generation(redis_client)
        log_task_run(
            client,
            task_name,
            run_id,
            started_at,
            "success",
            0,
            f"marts built for {days} days",
        )
        return {"run_id": run_id, "status": "success", "days": days}
    except LockNotAcquiredError as exc:
        REBUILD_LOGGER.warning(
            "rebuild_launch_skipped task_name=%s reason=lock_conflict error=%s",
            task_name,
            str(exc),
        )
        log_task_run(
            client,
            task_name,
            run_id,
            started_at,
            "skipped",
            0,
            "marts skipped: conflicting rebuild lock",
            meta={"reason": "lock_not_acquired", "conflict": True},
        )
        return {"run_id": run_id, "status": "skipped", "reason": "lock_not_acquired"}
    except Exception as exc:
        log_task_run(client, task_name, run_id, started_at, "failed", 0, str(exc))
        raise


@shared_task(name="tasks.marts.build_marts_recent")
def build_marts_recent() -> dict[str, str | int]:
    return _run_marts(days=14, task_name="tasks.marts.build_marts_recent")


@shared_task(name="tasks.marts.build_marts_backfill_days")
def build_marts_backfill_days(days: int = 14) -> dict[str, str | int]:
    safe_days = max(1, min(days, 730))
    return _run_marts(days=safe_days, task_name="tasks.marts.build_marts_backfill_days")
