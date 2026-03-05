"""Rule-based automation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import clickhouse_connect
import yaml

from automation.actions.base import Action


@dataclass
class RuleAction:
    type: str
    template: str


@dataclass
class Rule:
    name: str
    query: str
    condition: str
    actions: list[RuleAction] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


def _result_to_dicts(result: Any) -> list[dict[str, Any]]:
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]


def _safe_eval_condition(expression: str, row: dict[str, Any], params: dict[str, Any]) -> bool:
    safe_globals = {"__builtins__": {}}
    safe_locals = {
        "row": row,
        "params": params,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "int": int,
        "float": float,
        "len": len,
    }
    return bool(eval(expression, safe_globals, safe_locals))  # noqa: S307 - constrained context


def load_rules(rules_dir: Path) -> list[Rule]:
    rules: list[Rule] = []
    for path in sorted(rules_dir.glob("*.yml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        actions = [
            RuleAction(type=str(action["type"]), template=str(action["template"]))
            for action in raw.get("actions", [])
        ]
        rules.append(
            Rule(
                name=str(raw["name"]),
                query=str(raw["query"]),
                condition=str(raw.get("condition", "True")),
                actions=actions,
                params=dict(raw.get("params", {})),
            )
        )
    return rules


def run_rules(
    client: clickhouse_connect.driver.Client,
    rules_dir: Path,
    actions: dict[str, Action],
) -> dict[str, Any]:
    report: dict[str, Any] = {"rules": [], "triggered": 0}
    for rule in load_rules(rules_dir):
        result = client.query(rule.query)
        rows = _result_to_dicts(result)
        triggered_rows = 0

        for row in rows:
            if not _safe_eval_condition(rule.condition, row=row, params=rule.params):
                continue
            triggered_rows += 1
            report["triggered"] += 1
            for action in rule.actions:
                action_impl = actions.get(action.type)
                if action_impl is None:
                    continue
                message = action.template.format(**row, **rule.params)
                action_impl.execute(rule_name=rule.name, payload=row, message=message)

        report["rules"].append(
            {
                "name": rule.name,
                "rows": len(rows),
                "triggered": triggered_rows,
            }
        )
    return report
