"""Git-like history primitives: canonical documents, content hashes, field diffs, commits.

A *document* is the JSON-serialisable state of one entity (a product card, a statistics
row). ``object_hash`` is the SHA-256 of its canonical form, so identical states share one
stored object no matter which entity or run produced them. A *commit* links an entity's
new object to its parent commit; ``diff_documents`` describes what changed between two
documents field by field. Persistence lives in the workers (``app.utils.history_store``),
reading lives in the backend (``app.services.history_service``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fnmatch import fnmatchcase
from typing import Any
from uuid import UUID

PRODUCT_REPO = "product"
DELETED_DOCUMENT: dict[str, Any] = {"_deleted": True}

# list items are matched by the first of these keys they all carry, so a reordered
# characteristics list is not reported as a rewrite of every element
IDENTITY_KEYS = ("id", "chrtID", "chrt_id", "nmID", "attribute_id", "sku", "vendorCode", "key")


def canonicalize(value: Any) -> Any:
    """Reduce ``value`` to plain JSON types with a stable representation."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        # NaN/inf are not valid JSON and would make hashes unstable across runs
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        # ClickHouse DateTime has second precision; keep live and re-read rows identical
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): canonicalize(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        items = sorted(value, key=repr) if isinstance(value, set | frozenset) else value
        return [canonicalize(item) for item in items]
    raise TypeError(f"cannot store {type(value).__name__} in a history document")


def dump(value: Any) -> str:
    """Canonical JSON text: sorted keys, no whitespace, UTF-8 friendly."""
    return json.dumps(
        canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def object_hash(document: Any) -> str:
    return hashlib.sha256(dump(document).encode("utf-8")).hexdigest()


def commit_id(
    *, marketplace: str, account_id: str, repo: str, entity_key: str, parent_id: str, obj: str
) -> str:
    """Deterministic, so a retried write produces the very same commit."""
    material = "\0".join((marketplace, account_id, repo, entity_key, parent_id, obj))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def load_json_or_text(text: Any) -> Any:
    """Parse the ``payload`` column back into a document; keep unparsable text as is."""
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except ValueError:
        return text


def strip_ignored(document: Any, patterns: Iterable[str]) -> Any:
    """Drop paths matching any fnmatch pattern (operator-declared noise) from a document."""
    compiled = [pattern for pattern in patterns if pattern]
    if not compiled:
        return document

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, Mapping):
            kept: dict[str, Any] = {}
            for key, item in node.items():
                child = f"{path}.{key}" if path else str(key)
                if any(fnmatchcase(child, pattern) for pattern in compiled):
                    continue
                kept[str(key)] = walk(item, child)
            return kept
        if isinstance(node, list):
            return [walk(item, f"{path}[{index}]") for index, item in enumerate(node)]
        return node

    return walk(document, "")


@dataclass(frozen=True)
class Change:
    path: str
    op: str  # add | change | remove
    old: str  # canonical JSON of the previous value, "" when absent
    new: str  # canonical JSON of the new value, "" when absent


def _identity_key(items: list[Any]) -> str | None:
    if not items or not all(isinstance(item, Mapping) for item in items):
        return None
    for key in IDENTITY_KEYS:
        values = [item.get(key) for item in items]
        if all(isinstance(v, str | int) and not isinstance(v, bool) for v in values) and len(
            set(values)
        ) == len(values):
            return key
    return None


def _diff(old: Any, new: Any, path: str, out: list[Change]) -> None:
    if old == new:
        return
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            child = f"{path}.{key}" if path else key
            if key not in old:
                out.append(Change(child, "add", "", dump(new[key])))
            elif key not in new:
                out.append(Change(child, "remove", dump(old[key]), ""))
            else:
                _diff(old[key], new[key], child, out)
        return
    if isinstance(old, list) and isinstance(new, list):
        identity = _identity_key(old) if old else None
        if identity is not None and _identity_key(new) == identity:
            old_by = {item[identity]: item for item in old}
            new_by = {item[identity]: item for item in new}
            for ident in sorted(old_by.keys() | new_by.keys(), key=str):
                child = f"{path}[{identity}={ident}]"
                if ident not in old_by:
                    out.append(Change(child, "add", "", dump(new_by[ident])))
                elif ident not in new_by:
                    out.append(Change(child, "remove", dump(old_by[ident]), ""))
                else:
                    _diff(old_by[ident], new_by[ident], child, out)
            return
        if all(isinstance(item, dict) for item in old + new):
            for index in range(max(len(old), len(new))):
                child = f"{path}[{index}]"
                if index >= len(old):
                    out.append(Change(child, "add", "", dump(new[index])))
                elif index >= len(new):
                    out.append(Change(child, "remove", dump(old[index]), ""))
                else:
                    _diff(old[index], new[index], child, out)
            return
        # lists of scalars (photo urls, tags) are one value: report the list as a whole
        out.append(Change(path, "change", dump(old), dump(new)))
        return
    out.append(Change(path, "change", dump(old), dump(new)))


def diff_documents(old: Any, new: Any) -> list[Change]:
    """Field-level differences between two canonical documents, sorted by path."""
    changes: list[Change] = []
    _diff(canonicalize(old), canonicalize(new), "", changes)
    return sorted(changes, key=lambda change: change.path)
