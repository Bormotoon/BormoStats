from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from automation.engine import _safe_eval_condition, run_rules


@dataclass
class FakeResult:
    column_names: list[str]
    result_rows: list[tuple[Any, ...]]


@dataclass
class FakeClient:
    rows: list[tuple[Any, ...]]

    def query(self, _: str) -> FakeResult:
        return FakeResult(column_names=["product_id", "stock_end"], result_rows=self.rows)


@dataclass
class FakeAction:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, rule_name: str, payload: dict[str, Any], message: str) -> None:
        self.calls.append({"rule_name": rule_name, "payload": payload, "message": message})


def test_run_rules_triggers_action(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "low_stock.yml").write_text(
        "\n".join(
            [
                "name: low_stock_test",
                "query: |",
                "  SELECT product_id, stock_end FROM mrt_stock_daily",
                "condition: row.get(\"stock_end\", 0) < params.get(\"threshold\", 5)",
                "params:",
                "  threshold: 5",
                "actions:",
                "  - type: telegram",
                "    template: \"Low stock {product_id}: {stock_end}\"",
            ]
        ),
        encoding="utf-8",
    )

    fake_client = FakeClient(rows=[("sku-1", 2), ("sku-2", 10)])
    fake_action = FakeAction()

    report = run_rules(client=fake_client, rules_dir=rules_dir, actions={"telegram": fake_action})
    assert report["triggered"] == 1
    assert len(fake_action.calls) == 1
    assert fake_action.calls[0]["rule_name"] == "low_stock_test"
    assert "sku-1" in fake_action.calls[0]["message"]


def test_safe_eval_rejects_unsafe_expression() -> None:
    with pytest.raises(ValueError):
        _safe_eval_condition('__import__("os").system("echo hacked")', row={}, params={})
