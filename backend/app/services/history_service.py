"""Read side of the git-like history store (``hist_*`` tables).

Every query is limited to the accounts of one organization (``account_scope_sql``).
Commits are immutable, so nothing here is cached.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import clickhouse_connect
from app.db.ch import query_dicts

from common.tenancy_sql import account_scope_sql

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_FAR_FUTURE = datetime(2106, 1, 1, tzinfo=UTC)

_SCOPE = account_scope_sql()
_FILTERS = (
    "({marketplace:String} = '' OR marketplace = {marketplace:String})"
    " AND ({account_id:String} = '' OR account_id = {account_id:String})"
    " AND repo = {repo:String}"
    " AND ({entity_key:String} = '' OR entity_key = {entity_key:String})"
    " AND committed_at >= {since:DateTime} AND committed_at <= {until:DateTime}"
)


def _utc(value: datetime | None, default: datetime) -> datetime:
    """Aware UTC for query parameters: clickhouse_connect reads a naive datetime as the
    process-local time, which would shift every bound by the server's TZ offset."""
    if value is None:
        return default
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _json_or_raw(text: str) -> Any:
    if text == "":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


class HistoryService:
    def __init__(self, client: clickhouse_connect.driver.Client, organization_id: str) -> None:
        self.client = client
        self.organization_id = organization_id

    def _query(self, sql: str, **parameters: Any) -> list[dict[str, Any]]:
        return query_dicts(
            self.client, sql, {"organization_id": self.organization_id, **parameters}
        )

    def _filters(
        self,
        *,
        repo: str,
        marketplace: str,
        account_id: str,
        entity_key: str,
        since: datetime | None,
        until: datetime | None,
    ) -> dict[str, Any]:
        return {
            "repo": repo,
            "marketplace": marketplace,
            "account_id": account_id,
            "entity_key": entity_key,
            "since": _utc(since, _EPOCH),
            "until": _utc(until, _FAR_FUTURE),
        }

    def repos(self) -> list[dict[str, Any]]:
        """Entities and commits per repo (``product`` and one repo per archived raw table)."""
        return self._query(
            f"""
            SELECT
              marketplace,
              repo,
              count() AS entities,
              countIf(is_deleted = 1) AS deleted_entities,
              sum(commit_count) AS commits,
              min(first_seen_at) AS first_seen_at,
              max(updated_at) AS last_commit_at
            FROM hist_refs FINAL
            WHERE {_SCOPE}
            GROUP BY marketplace, repo
            ORDER BY marketplace, repo
            """
        )

    def commits(
        self,
        *,
        repo: str,
        marketplace: str,
        account_id: str,
        entity_key: str,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """``git log``: newest commit first; a retried write is listed once."""
        return self._query(
            f"""
            SELECT commit_id, marketplace, account_id, repo, entity_key, parent_id, object_hash,
                   is_deleted, committed_at, run_id, source, message, changed_paths
            FROM hist_commits
            WHERE {_SCOPE} AND {_FILTERS}
            ORDER BY committed_at DESC, commit_id
            LIMIT 1 BY commit_id
            LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
            """,
            limit=limit,
            offset=offset,
            **self._filters(
                repo=repo,
                marketplace=marketplace,
                account_id=account_id,
                entity_key=entity_key,
                since=since,
                until=until,
            ),
        )

    def commit(self, commit_id: str) -> dict[str, Any] | None:
        """``git show``: the commit, the document it recorded and its field changes."""
        rows = self._query(
            f"""
            SELECT commit_id, marketplace, account_id, repo, entity_key, parent_id, object_hash,
                   is_deleted, committed_at, run_id, source, message, changed_paths
            FROM hist_commits
            WHERE {_SCOPE} AND commit_id = {{commit_id:String}}
            LIMIT 1
            """,
            commit_id=commit_id,
        )
        if not rows:
            return None
        commit = rows[0]
        commit["document"] = self._document(commit["object_hash"])
        changes = self._query(
            f"""
            SELECT path, op, old_value, new_value
            FROM hist_changes
            WHERE {_SCOPE} AND commit_id = {{commit_id:String}}
            ORDER BY path
            LIMIT 1 BY path
            """,
            commit_id=commit_id,
        )
        commit["changes"] = [self._decode_change(change) for change in changes]
        return commit

    def snapshot(
        self,
        *,
        repo: str,
        marketplace: str,
        account_id: str,
        entity_key: str,
        at: datetime | None,
    ) -> dict[str, Any] | None:
        """``git checkout``: the entity as it was at ``at`` (default: now)."""
        rows = self._query(
            f"""
            SELECT commit_id, account_id, object_hash, is_deleted, committed_at, message
            FROM hist_commits
            WHERE {_SCOPE}
              AND marketplace = {{marketplace:String}}
              AND ({{account_id:String}} = '' OR account_id = {{account_id:String}})
              AND repo = {{repo:String}} AND entity_key = {{entity_key:String}}
              AND committed_at <= {{at:DateTime}}
            ORDER BY committed_at DESC, commit_id
            LIMIT 1
            """,
            repo=repo,
            marketplace=marketplace,
            account_id=account_id,
            entity_key=entity_key,
            at=_utc(at, _FAR_FUTURE),
        )
        if not rows:
            return None
        head = rows[0]
        return {
            "repo": repo,
            "marketplace": marketplace,
            "entity_key": entity_key,
            "commit_id": head["commit_id"],
            "account_id": head["account_id"],
            "committed_at": head["committed_at"],
            "message": head["message"],
            "is_deleted": bool(head["is_deleted"]),
            "document": None if head["is_deleted"] else self._document(head["object_hash"]),
        }

    def changes(
        self,
        *,
        repo: str,
        marketplace: str,
        account_id: str,
        entity_key: str,
        path_prefix: str,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Field history, newest first: e.g. every change of ``price.sizes`` of one product."""
        rows = self._query(
            f"""
            SELECT marketplace, account_id, repo, entity_key, path, commit_id, committed_at,
                   op, old_value, new_value
            FROM hist_changes
            WHERE {_SCOPE} AND {_FILTERS}
              AND ({{path_prefix:String}} = '' OR startsWith(path, {{path_prefix:String}}))
            ORDER BY committed_at DESC, entity_key, path
            LIMIT 1 BY commit_id, path
            LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
            """,
            path_prefix=path_prefix,
            limit=limit,
            offset=offset,
            **self._filters(
                repo=repo,
                marketplace=marketplace,
                account_id=account_id,
                entity_key=entity_key,
                since=since,
                until=until,
            ),
        )
        return [self._decode_change(row) for row in rows]

    # -- helpers --

    def _document(self, object_hash: str) -> Any:
        rows = self.client.query(
            "SELECT body FROM hist_objects WHERE object_hash = {object_hash:String} LIMIT 1",
            parameters={"object_hash": object_hash},
        ).result_rows
        return _json_or_raw(rows[0][0]) if rows else None

    @staticmethod
    def _decode_change(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "old_value": _json_or_raw(row["old_value"]),
            "new_value": _json_or_raw(row["new_value"]),
        }
