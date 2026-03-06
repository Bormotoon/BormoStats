"""Rule-based automation engine."""

from __future__ import annotations

import ast
import operator
from collections.abc import Mapping
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


class UnsafeExpressionError(ValueError):
    """Raised when rule expression contains unsupported or unsafe syntax."""


_ALLOWED_CALLS: dict[str, Any] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "int": int,
    "float": float,
    "len": len,
    "bool": bool,
    "str": str,
}

_ALLOWED_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

_ALLOWED_COMPARE_OPS: dict[type[ast.cmpop], Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
    ast.Is: lambda left, right: left is right,
    ast.IsNot: lambda left, right: left is not right,
}


def _result_to_dicts(result: Any) -> list[dict[str, Any]]:
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]


def _eval_expr(node: ast.AST, names: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_expr(node.body, names)

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        raise UnsafeExpressionError(f"unknown symbol: {node.id}")

    if isinstance(node, ast.List):
        return [_eval_expr(item, names) for item in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_eval_expr(item, names) for item in node.elts)

    if isinstance(node, ast.Set):
        return {_eval_expr(item, names) for item in node.elts}

    if isinstance(node, ast.Dict):
        result: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                raise UnsafeExpressionError("dict unpacking is not allowed")
            result[_eval_expr(key, names)] = _eval_expr(value, names)
        return result

    if isinstance(node, ast.Subscript):
        target = _eval_expr(node.value, names)
        index = _eval_expr(node.slice, names)
        return target[index]

    if isinstance(node, ast.BinOp):
        op = _ALLOWED_BIN_OPS.get(type(node.op))
        if op is None:
            raise UnsafeExpressionError(f"operator not allowed: {type(node.op).__name__}")
        return op(_eval_expr(node.left, names), _eval_expr(node.right, names))

    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_UNARY_OPS.get(type(node.op))
        if op is None:
            raise UnsafeExpressionError(f"unary operator not allowed: {type(node.op).__name__}")
        return op(_eval_expr(node.operand, names))

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(bool(_eval_expr(value, names)) for value in node.values)
        if isinstance(node.op, ast.Or):
            return any(bool(_eval_expr(value, names)) for value in node.values)
        raise UnsafeExpressionError(f"boolean operator not allowed: {type(node.op).__name__}")

    if isinstance(node, ast.Compare):
        left = _eval_expr(node.left, names)
        for op_node, comparator in zip(node.ops, node.comparators, strict=True):
            op = _ALLOWED_COMPARE_OPS.get(type(op_node))
            if op is None:
                raise UnsafeExpressionError(f"comparator not allowed: {type(op_node).__name__}")
            right = _eval_expr(comparator, names)
            if not op(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.IfExp):
        branch = node.body if bool(_eval_expr(node.test, names)) else node.orelse
        return _eval_expr(branch, names)

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            fn = _ALLOWED_CALLS.get(node.func.id)
            if fn is None:
                raise UnsafeExpressionError(f"function not allowed: {node.func.id}")
            args = [_eval_expr(arg, names) for arg in node.args]
            kwargs = {
                kw.arg: _eval_expr(kw.value, names) for kw in node.keywords if kw.arg is not None
            }
            return fn(*args, **kwargs)

        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            target = _eval_expr(node.func.value, names)
            if not isinstance(target, dict):
                raise UnsafeExpressionError("only dict.get is allowed for attribute calls")
            args = [_eval_expr(arg, names) for arg in node.args]
            kwargs = {
                kw.arg: _eval_expr(kw.value, names) for kw in node.keywords if kw.arg is not None
            }
            return target.get(*args, **kwargs)

        raise UnsafeExpressionError("call target is not allowed")

    raise UnsafeExpressionError(f"syntax not allowed: {type(node).__name__}")


def _safe_eval_condition(expression: str, row: dict[str, Any], params: dict[str, Any]) -> bool:
    parsed = ast.parse(expression, mode="eval")
    return bool(_eval_expr(parsed, {"row": row, "params": params}))


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
    actions: Mapping[str, Action],
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
