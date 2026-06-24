"""Transform tasks from raw to stg."""

from __future__ import annotations

from pathlib import Path

from app.sql.loader import load_sql
from app.utils.celery_helpers import shared_task
from app.utils.locking import LockNotAcquiredError
from app.utils.rebuilds import LOGGER as REBUILD_LOGGER
from app.utils.rebuilds import rebuild_task_scope
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context

_TRANSFORMS_DIR = Path(__file__).resolve().parents[1] / "sql" / "transforms"


def _load(name: str) -> str:
    return load_sql(_TRANSFORMS_DIR, name)


STG_REBUILD_TABLES = (
    ("stg_sales", "day"),
    ("stg_orders", "day"),
    ("stg_stocks", "day"),
    ("stg_funnel_daily", "day"),
)

STG_LONG_REBUILD_TABLES = (
    ("stg_ads_daily", "day"),
    ("stg_finance_ops", "day"),
)


def _run_transform(days: int, task_name: str) -> dict[str, int | str]:
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
            for table_name, day_column in STG_REBUILD_TABLES:
                client.command(
                    f"ALTER TABLE {table_name} DELETE WHERE {day_column} >= today() - %(days)s",
                    parameters={"days": days},
                )
            for table_name, day_column in STG_LONG_REBUILD_TABLES:
                client.command(
                    f"ALTER TABLE {table_name} DELETE WHERE {day_column} >= today() - %(days)s",
                    parameters={"days": ads_days},
                )

            client.command(_load("wb_sales_to_stg.sql"), parameters={"days": days})
            client.command(_load("wb_orders_to_stg.sql"), parameters={"days": days})
            client.command(_load("wb_stocks_to_stg.sql"), parameters={"days": days})
            client.command(_load("wb_funnel_to_stg.sql"), parameters={"days": days})
            client.command(_load("ozon_sales_to_stg.sql"), parameters={"days": days})
            client.command(_load("ozon_orders_to_stg.sql"), parameters={"days": days})
            client.command(_load("ozon_stocks_to_stg.sql"), parameters={"days": days})
            client.command(_load("ozon_ads_to_stg.sql"), parameters={"days": ads_days})
            client.command(_load("ozon_finance_to_stg.sql"), parameters={"days": ads_days})
            client.command(_load("sync_dim_product_wb.sql"), parameters={"days": max(days, 30)})
            client.command(_load("sync_dim_product_ozon.sql"), parameters={"days": max(days, 30)})
        log_task_run(
            client,
            task_name,
            run_id,
            started_at,
            "success",
            0,
            f"transform done for {days} days",
        )
        return {"status": "success", "days": days, "run_id": run_id}
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
            "transform skipped: conflicting rebuild lock",
            meta={"reason": "lock_not_acquired", "conflict": True},
        )
        return {"status": "skipped", "reason": "lock_not_acquired", "run_id": run_id}
    except Exception as exc:
        log_task_run(client, task_name, run_id, started_at, "failed", 0, str(exc))
        raise


@shared_task(name="tasks.transforms.transform_all_recent")
def transform_all_recent() -> dict[str, int | str]:
    return _run_transform(days=14, task_name="tasks.transforms.transform_all_recent")


@shared_task(name="tasks.transforms.transform_backfill_days")
def transform_backfill_days(days: int = 14) -> dict[str, int | str]:
    safe_days = max(1, min(days, 365))
    return _run_transform(days=safe_days, task_name="tasks.transforms.transform_backfill_days")
