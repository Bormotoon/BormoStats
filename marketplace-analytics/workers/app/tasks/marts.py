"""Tasks for building analytics marts."""

from __future__ import annotations

from pathlib import Path

from app.sql.loader import load_sql
from app.utils.celery_helpers import shared_task
from app.utils.locking import LockNotAcquiredError
from app.utils.rebuilds import LOGGER as REBUILD_LOGGER
from app.utils.rebuilds import rebuild_task_scope
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context

_MARTS_DIR = Path(__file__).resolve().parents[1] / "sql" / "marts"


def _load(name: str) -> str:
    return load_sql(_MARTS_DIR, name)


MART_REBUILD_TABLES = (
    ("mrt_sales_daily", "day"),
    ("mrt_stock_daily", "day"),
    ("mrt_funnel_daily", "day"),
    ("mrt_profit_daily", "day"),
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
            client.command("SET mutations_sync = 1")
            for table_name, day_column in MART_REBUILD_TABLES:
                client.command(
                    f"ALTER TABLE {table_name} DELETE WHERE {day_column} >= today() - %(days)s",
                    parameters={"days": days},
                )
            client.command(
                "ALTER TABLE mrt_ads_daily DELETE WHERE day >= today() - %(days)s",
                parameters={"days": ads_days},
            )

            client.command(_load("mrt_sales_daily.sql"), parameters={"days": days})
            client.command(_load("mrt_stock_daily.sql"), parameters={"days": days})
            client.command(_load("mrt_funnel_daily.sql"), parameters={"days": days})
            client.command(_load("mrt_ads_daily.sql"), parameters={"days": ads_days})
            client.command(_load("mrt_profit_daily.sql"), parameters={"days": days})
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
    safe_days = max(1, min(days, 365))
    return _run_marts(days=safe_days, task_name="tasks.marts.build_marts_backfill_days")
