"""Every hand-written query must run against the migrated schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
RULE_FILES = sorted((ROOT_DIR / "automation" / "rules").glob("*.yml"))


@pytest.mark.parametrize("rule_file", RULE_FILES, ids=lambda p: p.stem)
def test_automation_rule_queries_run(integration_runtime: Any, rule_file: Path) -> None:
    rule = yaml.safe_load(rule_file.read_text(encoding="utf-8"))
    client = integration_runtime.ch_client()
    try:
        client.query(rule["query"], parameters=rule.get("params") or {})
    finally:
        client.close()


def test_insights_trigger_queries_run(integration_runtime: Any) -> None:
    from app.tasks.insights import BAD_ADS_SQL, STAGNANT_SQL, TURNOVER_SQL

    client = integration_runtime.ch_client()
    try:
        for sql in (TURNOVER_SQL, STAGNANT_SQL, BAD_ADS_SQL):
            client.query(sql, parameters={"oid": "default"})
    finally:
        client.close()


def test_worker_rule_queries_run(integration_runtime: Any) -> None:
    from app.tasks import bidder, repricer
    from app.utils.data_quality import collect_data_quality_metrics

    client = integration_runtime.ch_client()
    try:
        assert bidder.fetch_active_rules(client) == []
        assert repricer.fetch_active_rules(client) == []
        metrics = collect_data_quality_metrics(client)
        assert all(missing == 0 for missing in metrics.schema_missing.values())
    finally:
        client.close()


@pytest.mark.parametrize(
    "dataset", ["sales_daily", "stocks_current", "funnel_daily", "ads_daily", "kpis"]
)
def test_export_writes_csv_for_each_dataset(
    integration_runtime: Any, tmp_path: Path, dataset: str
) -> None:
    from app.tasks.exports import build_query_parameters, write_csv

    from common.exports import DATASETS, QUERIES_DIR

    client = integration_runtime.ch_client()
    try:
        target = tmp_path / f"{dataset}.csv"
        rows = write_csv(
            client,
            (QUERIES_DIR / DATASETS[dataset]).read_text(encoding="utf-8"),
            build_query_parameters(dataset, "default", {}),
            target,
        )
    finally:
        client.close()
    header = target.read_text(encoding="utf-8-sig").splitlines()[0]
    assert rows >= 0 and "marketplace" in header


def test_freshness_summary_on_empty_marts(integration_runtime: Any) -> None:
    from app.services.freshness_service import FreshnessService

    client = integration_runtime.ch_client()
    try:
        summary = FreshnessService(client, "default").summary()
    finally:
        client.close()
    assert {m["table"] for m in summary["marts"]} >= {"mrt_sales_daily"}
    assert all(m["updated_at"] is None or m["updated_at"].year > 2000 for m in summary["marts"])
