"""Persistence of the git-like history store (``hist_*`` tables).

``HistoryStore.record`` takes the current state of a batch of entities and commits only
what differs from each entity's HEAD, so re-reading an unchanged catalogue costs one
lookup and writes nothing. Write order is objects, changes, commits, refs: a crash leaves
HEAD behind the commits, and the retry recomputes the same deterministic commit ids.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.utils.metrics import observe_rows

from common.history import (
    DELETED_DOCUMENT,
    Change,
    canonicalize,
    commit_id,
    diff_documents,
    dump,
    object_hash,
    strip_ignored,
)

LOGGER = logging.getLogger(__name__)

LOOKUP_CHUNK = 2000
INSERT_CHUNK = 20000
# a listing that would delete more than this share of the known catalogue is treated as
# a broken response (partial page, revoked scope), not as sellers removing everything
MAX_TOMBSTONE_SHARE = 0.5
MIN_ENTITIES_FOR_TOMBSTONE_GUARD = 10

OBJECT_COLUMNS = ["object_hash", "kind", "size", "body"]
COMMIT_COLUMNS = [
    "commit_id",
    "marketplace",
    "account_id",
    "repo",
    "entity_key",
    "parent_id",
    "object_hash",
    "is_deleted",
    "committed_at",
    "run_id",
    "source",
    "message",
    "changed_paths",
]
REF_COLUMNS = [
    "marketplace",
    "account_id",
    "repo",
    "entity_key",
    "head_commit",
    "head_object",
    "is_deleted",
    "commit_count",
    "first_seen_at",
    "updated_at",
]
CHANGE_COLUMNS = [
    "marketplace",
    "account_id",
    "repo",
    "entity_key",
    "path",
    "commit_id",
    "committed_at",
    "op",
    "old_value",
    "new_value",
]


def history_enabled() -> bool:
    return os.getenv("HISTORY_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def ignore_patterns(env_name: str) -> tuple[str, ...]:
    raw = os.getenv(env_name, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _utc(value: datetime | None) -> datetime:
    """Timezone-aware UTC, second precision.

    clickhouse_connect reads a naive datetime as the *process-local* time (workers run with
    TZ=Europe/Warsaw), so history tables are always written with aware values.
    """
    moment = value or datetime.now(UTC)
    moment = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    return moment.replace(microsecond=0)


def _chunks[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


@dataclass(frozen=True)
class Observation:
    entity_key: str
    document: Any
    observed_at: datetime | None = None


@dataclass
class RecordResult:
    seen: int = 0
    unchanged: int = 0
    created: int = 0
    modified: int = 0
    deleted: int = 0
    restored: int = 0
    changes: int = 0
    skipped_tombstones: int = 0
    guard_triggered: bool = False

    @property
    def commits(self) -> int:
        return self.created + self.modified + self.deleted + self.restored

    def as_meta(self) -> dict[str, int | bool]:
        return {
            "seen": self.seen,
            "unchanged": self.unchanged,
            "created": self.created,
            "modified": self.modified,
            "deleted": self.deleted,
            "restored": self.restored,
            "changes": self.changes,
            "tombstones_skipped": self.skipped_tombstones,
            "tombstone_guard": self.guard_triggered,
        }


@dataclass
class _Head:
    commit_id: str
    object_hash: str
    is_deleted: bool
    commit_count: int
    first_seen_at: datetime


@dataclass
class _Pending:
    entity_key: str
    document: Any
    text: str
    obj: str
    observed_at: datetime
    deleted: bool = False


@dataclass
class HistoryStore:
    client: Any
    run_id: str
    source: str
    kind_by_repo: dict[str, str] = field(default_factory=dict)

    # -- reads --

    def _heads(
        self, marketplace: str, account_id: str, repo: str, keys: Sequence[str]
    ) -> dict[str, _Head]:
        heads: dict[str, _Head] = {}
        for chunk in _chunks(list(keys), LOOKUP_CHUNK):
            result = self.client.query(
                "SELECT entity_key, head_commit, head_object, is_deleted, commit_count,"
                " first_seen_at FROM hist_refs FINAL"
                " WHERE marketplace = %(marketplace)s AND account_id = %(account_id)s"
                " AND repo = %(repo)s AND entity_key IN %(keys)s",
                parameters={
                    "marketplace": marketplace,
                    "account_id": account_id,
                    "repo": repo,
                    "keys": list(chunk),
                },
            )
            for key, head_commit, head_object, deleted, count, first_seen in result.result_rows:
                heads[key] = _Head(
                    head_commit, head_object, bool(deleted), int(count), _utc(first_seen)
                )
        return heads

    def live_keys(self, marketplace: str, account_id: str, repo: str) -> list[str]:
        result = self.client.query(
            "SELECT entity_key FROM hist_refs FINAL"
            " WHERE marketplace = %(marketplace)s AND account_id = %(account_id)s"
            " AND repo = %(repo)s AND is_deleted = 0",
            parameters={"marketplace": marketplace, "account_id": account_id, "repo": repo},
        )
        return [row[0] for row in result.result_rows]

    def _bodies(self, hashes: Sequence[str]) -> dict[str, str]:
        bodies: dict[str, str] = {}
        for chunk in _chunks(list(dict.fromkeys(hashes)), LOOKUP_CHUNK):
            result = self.client.query(
                "SELECT object_hash, body FROM hist_objects WHERE object_hash IN %(hashes)s",
                parameters={"hashes": list(chunk)},
            )
            for digest, body in result.result_rows:
                bodies[digest] = body
        return bodies

    def _missing_objects(self, hashes: Sequence[str]) -> set[str]:
        present: set[str] = set()
        unique = list(dict.fromkeys(hashes))
        for chunk in _chunks(unique, LOOKUP_CHUNK):
            result = self.client.query(
                "SELECT object_hash FROM hist_objects WHERE object_hash IN %(hashes)s",
                parameters={"hashes": list(chunk)},
            )
            present.update(row[0] for row in result.result_rows)
        return set(unique) - present

    # -- writes --

    def record(
        self,
        *,
        marketplace: str,
        account_id: str,
        repo: str,
        observations: Iterable[Observation],
        ignore: Iterable[str] = (),
        tombstone_missing: bool = False,
        carry: Iterable[str] = (),
        retire: Iterable[str] = (),
        retire_message: str = "",
    ) -> RecordResult:
        """Commit every observation that differs from its entity's HEAD.

        ``tombstone_missing`` is only valid when ``observations`` is the complete
        catalogue: live entities absent from it get a deletion commit. ``carry`` names
        top-level document sections that are copied from HEAD when an observation lacks
        them, so a section whose source failed this run does not read as a removal.
        ``retire`` lists existing entities to close with a deletion commit carrying
        ``retire_message`` (e.g. rows re-keyed by a migration).
        """
        result = RecordResult()
        ignore_list = tuple(ignore)
        carry_sections = tuple(carry)
        kind = self.kind_by_repo.get(repo, repo)

        observed = list(observations)
        heads = self._heads(marketplace, account_id, repo, [o.entity_key for o in observed])
        # objects of the current HEADs, loaded once for carrying sections and for diffs
        bodies: dict[str, str] = {}
        if carry_sections:
            bodies = self._bodies(
                [head.object_hash for head in heads.values() if not head.is_deleted]
            )

        pending: list[_Pending] = []
        for observation in observed:
            raw_document = canonicalize(observation.document)
            head = heads.get(observation.entity_key)
            if carry_sections and head is not None and not head.is_deleted:
                previous = _loads(bodies[head.object_hash]) if head.object_hash in bodies else {}
                if isinstance(raw_document, dict) and isinstance(previous, dict):
                    for section in carry_sections:
                        if section not in raw_document and section in previous:
                            raw_document[section] = previous[section]
            document = strip_ignored(raw_document, ignore_list)
            text = dump(document)
            pending.append(
                _Pending(
                    entity_key=observation.entity_key,
                    document=document,
                    text=text,
                    obj=object_hash(document),
                    observed_at=_utc(observation.observed_at),
                )
            )
        result.seen = len(pending)

        if tombstone_missing:
            seen_keys = {item.entity_key for item in pending}
            missing = [
                key for key in self.live_keys(marketplace, account_id, repo) if key not in seen_keys
            ]
            known = len(missing) + len(seen_keys)
            if (
                known >= MIN_ENTITIES_FOR_TOMBSTONE_GUARD
                and len(missing) / known > MAX_TOMBSTONE_SHARE
            ):
                result.guard_triggered = True
                result.skipped_tombstones = len(missing)
                LOGGER.warning(
                    "history tombstones skipped: %s of %s %s entities vanished at once",
                    len(missing),
                    known,
                    repo,
                )
            else:
                now = _utc(None)
                heads.update(self._heads(marketplace, account_id, repo, missing))
                for key in missing:
                    pending.append(
                        _Pending(
                            entity_key=key,
                            document=DELETED_DOCUMENT,
                            text=dump(DELETED_DOCUMENT),
                            obj=object_hash(DELETED_DOCUMENT),
                            observed_at=now,
                            deleted=True,
                        )
                    )

        retire_keys = list(dict.fromkeys(retire))
        retired: set[str] = set()
        if retire_keys:
            heads.update(self._heads(marketplace, account_id, repo, retire_keys))
            now = _utc(None)
            for key in retire_keys:
                if key not in heads:
                    continue
                retired.add(key)
                pending.append(
                    _Pending(
                        entity_key=key,
                        document=DELETED_DOCUMENT,
                        text=dump(DELETED_DOCUMENT),
                        obj=object_hash(DELETED_DOCUMENT),
                        observed_at=now,
                        deleted=True,
                    )
                )

        if not pending:
            return result

        # first pass: which observations change anything. Repeated keys in one batch are
        # compared against the previous occurrence, not against the stale HEAD.
        state: dict[str, tuple[str, bool]] = {
            key: (head.object_hash, head.is_deleted) for key, head in heads.items()
        }
        planned: list[_Pending] = []
        for item in pending:
            current = state.get(item.entity_key)
            if current == (item.obj, item.deleted):
                result.unchanged += 1
                continue
            planned.append(item)
            state[item.entity_key] = (item.obj, item.deleted)

        if not planned:
            return result

        bodies.update(
            self._bodies(
                [
                    head.object_hash
                    for key in {item.entity_key for item in planned}
                    if (head := heads.get(key)) is not None
                    and not head.is_deleted
                    and head.object_hash not in bodies
                ]
            )
        )
        local_bodies: dict[str, str] = {item.obj: item.text for item in planned}

        objects: dict[str, tuple[str, str, int, str]] = {}
        commits: list[list[Any]] = []
        change_rows: list[list[Any]] = []
        refs: dict[str, list[Any]] = {}
        chain: dict[str, _Head] = {}
        now = _utc(None)

        for item in planned:
            head = chain.get(item.entity_key) or heads.get(item.entity_key)
            parent_id = head.commit_id if head else ""
            cid = commit_id(
                marketplace=marketplace,
                account_id=account_id,
                repo=repo,
                entity_key=item.entity_key,
                parent_id=parent_id,
                obj=item.obj,
            )
            changed: list[Change] = []
            if item.deleted:
                message = (
                    retire_message
                    if item.entity_key in retired and retire_message
                    else "deleted: no longer returned by the marketplace"
                )
                changed_paths = ["$"]
                result.deleted += 1
            elif head is None:
                message = "initial"
                changed_paths = []
                result.created += 1
            elif head.is_deleted:
                message = "restored: returned by the marketplace again"
                changed_paths = ["$"]
                result.restored += 1
            else:
                old_text = local_bodies.get(head.object_hash) or bodies.get(head.object_hash)
                if old_text is None:
                    # the parent object is missing (damaged store): record the commit anyway
                    LOGGER.warning("history object %s missing for %s", head.object_hash, repo)
                    changed_paths = ["$"]
                else:
                    changed = diff_documents(_loads(old_text), item.document)
                    changed_paths = [change.path for change in changed]
                    if not changed_paths:
                        # only the order of id-matched list items differs (Ozon returns
                        # complex attributes in a different order on every call): no change
                        result.unchanged += 1
                        continue
                message = f"changed {len(changed_paths)} field(s)"
                result.modified += 1
            local_bodies[item.obj] = item.text

            objects[item.obj] = (item.obj, kind, len(item.text.encode("utf-8")), item.text)
            commits.append(
                [
                    cid,
                    marketplace,
                    account_id,
                    repo,
                    item.entity_key,
                    parent_id,
                    item.obj,
                    1 if item.deleted else 0,
                    item.observed_at,
                    self.run_id,
                    self.source,
                    message,
                    changed_paths,
                ]
            )
            for change in changed:
                change_rows.append(
                    [
                        marketplace,
                        account_id,
                        repo,
                        item.entity_key,
                        change.path,
                        cid,
                        item.observed_at,
                        change.op,
                        change.old,
                        change.new,
                    ]
                )
            new_head = _Head(
                commit_id=cid,
                object_hash=item.obj,
                is_deleted=item.deleted,
                commit_count=(head.commit_count if head else 0) + 1,
                first_seen_at=head.first_seen_at if head else item.observed_at,
            )
            chain[item.entity_key] = new_head
            refs[item.entity_key] = [
                marketplace,
                account_id,
                repo,
                item.entity_key,
                cid,
                item.obj,
                1 if item.deleted else 0,
                new_head.commit_count,
                new_head.first_seen_at,
                now,
            ]

        result.changes = len(change_rows)

        absent = self._missing_objects(list(objects))
        object_rows = [list(objects[digest]) for digest in objects if digest in absent]

        self._insert("hist_objects", OBJECT_COLUMNS, object_rows)
        self._insert("hist_changes", CHANGE_COLUMNS, change_rows)
        self._insert("hist_commits", COMMIT_COLUMNS, commits)
        self._insert("hist_refs", REF_COLUMNS, list(refs.values()))
        return result

    def _insert(self, table: str, columns: list[str], rows: list[list[Any]]) -> None:
        for chunk in _chunks(rows, INSERT_CHUNK):
            self.client.insert(table=table, data=list(chunk), column_names=columns)
        observe_rows(table=table, rows=len(rows))


def _loads(text: str) -> Any:
    return json.loads(text)
