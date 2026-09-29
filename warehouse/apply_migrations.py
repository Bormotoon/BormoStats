#!/usr/bin/env python3
"""Apply, verify and roll back ClickHouse SQL migrations.

Commands::

    apply_migrations.py [apply] [--target VERSION]
    apply_migrations.py status
    apply_migrations.py verify
    apply_migrations.py rollback --target VERSION [--allow-production]
    apply_migrations.py unlock

Safety model:

* a ClickHouse DDL lock (``CREATE TABLE`` fails if the lock table exists) keeps two
  deploys from migrating concurrently; stale locks expire after ``--lock-ttl``;
* every attempt is journaled in ``sys_schema_migrations`` as ``started`` →
  ``applied``/``failed`` (or ``rolled_back``) with the file checksum;
* an applied migration whose file changed afterwards aborts the run — ship a new
  forward migration instead of editing history;
* mutations run with ``mutations_sync = 2`` so ``ALTER … UPDATE/DELETE`` finish
  before the version is recorded;
* after each migration, created tables and added columns are verified to exist;
* rollbacks require an explicit target, a rollback file for every version being
  reverted, and are refused in production unless ``--allow-production`` is given
  (production fixes should normally be forward migrations).
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import logging
import os
import re
import socket
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import clickhouse_connect

LOGGER = logging.getLogger("warehouse.migrations")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
JOURNAL_TABLE = "sys_schema_migrations"
LOCK_TABLE = "sys_schema_migrations_lock"
DEFAULT_LOCK_TTL_SECONDS = 1800
PRODUCTION_ENVS = frozenset({"prod", "production"})
_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([A-Za-z_][A-Za-z0-9_]*)`?", re.IGNORECASE
)
_ADD_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"`?([A-Za-z_][A-Za-z0-9_]*)`?",
    re.IGNORECASE,
)
_DROP_TABLE_RE = re.compile(
    r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?`?([A-Za-z_][A-Za-z0-9_]*)`?", re.IGNORECASE
)
_RENAME_RE = re.compile(
    r"`?([A-Za-z_][A-Za-z0-9_]*)`?\s+TO\s+`?([A-Za-z_][A-Za-z0-9_]*)`?", re.IGNORECASE
)
_DESTRUCTIVE_RE = re.compile(
    r"\b(DROP\s+(TABLE|COLUMN|DATABASE|VIEW)|TRUNCATE|DELETE\s+WHERE|MODIFY\s+COLUMN)\b",
    re.IGNORECASE,
)


class MigrationError(RuntimeError):
    """Raised when migrations cannot be applied safely."""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    checksum: str
    rollback_path: Path | None
    destructive: bool

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class JournalEntry:
    version: str
    status: str
    checksum: str


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def split_sql_statements(sql: str) -> Iterable[str]:
    statements: list[str] = []
    buffer: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    previous = ""

    for char in sql:
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                buffer.append(char)
            previous = char
            continue
        if char == "-" and previous == "-" and not in_single and not in_double:
            buffer.pop()
            in_line_comment = True
            previous = ""
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double

        if char == ";" and not in_single and not in_double:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer.clear()
            previous = char
            continue

        buffer.append(char)
        previous = char

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)

    return statements


def checksum_sql(sql: str) -> str:
    normalized = sql.replace("\r\n", "\n").strip() + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _require_identifier(label: str, value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid {label} identifier: {value}")
    return value


def _database_name() -> str:
    return _require_identifier("CH_DB", os.getenv("CH_DB", "mp_analytics"))


def _quoted_identifier(value: str) -> str:
    return f"`{value}`"


def _qualified_table(database: str, table: str) -> str:
    return f"{_quoted_identifier(database)}.{_quoted_identifier(table)}"


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def _rollbacks_dir() -> Path:
    return _migrations_dir() / "rollbacks"


def discover_migrations(migrations_dir: Path | None = None) -> list[Migration]:
    """Build the migration manifest: version, checksum, rollback presence, destructive flag."""
    base = migrations_dir or _migrations_dir()
    rollbacks = base / "rollbacks"
    manifest: list[Migration] = []
    for path in sorted(p for p in base.glob("*.sql") if p.is_file()):
        sql = path.read_text(encoding="utf-8")
        rollback_path = rollbacks / path.name
        manifest.append(
            Migration(
                version=path.stem,
                path=path,
                checksum=checksum_sql(sql),
                rollback_path=rollback_path if rollback_path.is_file() else None,
                destructive=bool(_DESTRUCTIVE_RE.search(sql)),
            )
        )
    return manifest


def expected_objects(sql: str) -> tuple[set[str], set[tuple[str, str]]]:
    """Tables and columns that must exist once a migration has run (postconditions).

    Statements are replayed in order so temporary tables that are later renamed or
    dropped within the same migration are tracked correctly.
    """
    tables: set[str] = set()
    columns: set[tuple[str, str]] = set()
    for statement in split_sql_statements(sql):
        upper = statement.lstrip().upper()
        if upper.startswith("CREATE"):
            tables.update(_CREATE_TABLE_RE.findall(statement))
        elif upper.startswith("DROP TABLE"):
            match = _DROP_TABLE_RE.match(statement.strip())
            if match:
                tables.discard(match.group(1))
        elif upper.startswith("RENAME TABLE"):
            for source, target in _RENAME_RE.findall(statement):
                if source in tables:
                    tables.discard(source)
                tables.add(target)
        columns.update(_ADD_COLUMN_RE.findall(statement))
    return tables, columns


def _client() -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=os.getenv("CH_HOST", "localhost"),
        port=int(os.getenv("CH_PORT", "8123")),
        username=os.getenv("CH_USER", "default"),
        password=os.getenv("CH_PASSWORD", ""),
        database=_database_name(),
        settings={"mutations_sync": 2},
    )


def ensure_sys_table(client: clickhouse_connect.driver.Client, database: str) -> None:
    client.command(f"CREATE DATABASE IF NOT EXISTS {_quoted_identifier(database)}")
    journal = _qualified_table(database, JOURNAL_TABLE)
    client.command(
        f"""
        CREATE TABLE IF NOT EXISTS {journal}
        (
          version String,
          applied_at DateTime DEFAULT now()
        )
        ENGINE = MergeTree
        ORDER BY (version)
        """
    )
    for column, definition in (
        ("checksum", "String DEFAULT ''"),
        ("status", "LowCardinality(String) DEFAULT 'applied'"),
        # Monotonic ordering key; legacy rows (before journaling) read as 0.
        ("seq", "UInt64 DEFAULT 0"),
        ("duration_ms", "UInt32 DEFAULT 0"),
        ("error", "String DEFAULT ''"),
        ("applied_by", "String DEFAULT ''"),
    ):
        client.command(f"ALTER TABLE {journal} ADD COLUMN IF NOT EXISTS {column} {definition}")


def load_journal(
    client: clickhouse_connect.driver.Client, database: str
) -> dict[str, JournalEntry]:
    """Latest journal state per version (legacy rows count as ``applied``)."""
    rows = client.query(
        "SELECT version, argMax(status, seq), argMax(checksum, seq)"
        f" FROM {_qualified_table(database, JOURNAL_TABLE)} GROUP BY version"
    ).result_rows
    return {
        str(version): JournalEntry(version=str(version), status=str(status), checksum=str(cs))
        for version, status, cs in rows
    }


def load_applied_versions(client: clickhouse_connect.driver.Client, database: str) -> set[str]:
    return {v for v, entry in load_journal(client, database).items() if entry.status == "applied"}


def _record(
    client: clickhouse_connect.driver.Client,
    database: str,
    migration: Migration,
    status: str,
    *,
    duration_ms: int = 0,
    error: str = "",
) -> None:
    client.command(
        f"INSERT INTO {_qualified_table(database, JOURNAL_TABLE)}"
        " (version, checksum, status, seq, duration_ms, error, applied_by)"
        " VALUES ({version:String}, {checksum:String}, {status:String}, {seq:UInt64},"
        " {duration_ms:UInt32}, {error:String}, {applied_by:String})",
        parameters={
            "seq": time.time_ns(),
            "version": migration.version,
            "checksum": migration.checksum,
            "status": status,
            "duration_ms": duration_ms,
            "error": error[:2000],
            "applied_by": _actor(),
        },
    )


def _actor() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    return f"{user}@{socket.gethostname()}:{os.getpid()}"


# -- Locking -----------------------------------------------------------------------------


def acquire_lock(
    client: clickhouse_connect.driver.Client,
    database: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> None:
    lock_table = _qualified_table(database, LOCK_TABLE)
    for attempt in range(2):
        try:
            client.command(
                f"CREATE TABLE {lock_table} (holder String, acquired_at DateTime DEFAULT now())"
                " ENGINE = Memory"
            )
            client.command(
                f"INSERT INTO {lock_table} (holder) VALUES ({{holder:String}})",
                parameters={"holder": _actor()},
            )
            return
        except Exception as exc:
            if "already exists" not in str(exc).lower() and "TABLE_ALREADY_EXISTS" not in str(exc):
                raise
            age = _lock_age_seconds(client, database)
            if attempt == 0 and age is not None and age > ttl_seconds:
                LOGGER.warning("stale migration lock (age=%ss); taking it over", age)
                release_lock(client, database)
                continue
            raise MigrationError(
                f"another migration run holds the lock ({LOCK_TABLE}, age={age}s);"
                " wait for it or run `apply_migrations.py unlock` if it crashed"
            ) from exc
    raise MigrationError("could not acquire migration lock")


def _lock_age_seconds(client: clickhouse_connect.driver.Client, database: str) -> int | None:
    rows = client.query(
        "SELECT dateDiff('second', metadata_modification_time, now()) FROM system.tables"
        " WHERE database = {db:String} AND name = {name:String}",
        parameters={"db": database, "name": LOCK_TABLE},
    ).result_rows
    return int(rows[0][0]) if rows else None


def release_lock(client: clickhouse_connect.driver.Client, database: str) -> None:
    client.command(f"DROP TABLE IF EXISTS {_qualified_table(database, LOCK_TABLE)}")


# -- Postconditions ------------------------------------------------------------------------


def verify_postconditions(
    client: clickhouse_connect.driver.Client, database: str, migration: Migration
) -> None:
    tables, columns = expected_objects(migration.sql)
    if tables:
        existing = {
            str(row[0])
            for row in client.query(
                "SELECT name FROM system.tables WHERE database = {db:String}",
                parameters={"db": database},
            ).result_rows
        }
        missing = sorted(tables - existing)
        if missing:
            raise MigrationError(f"{migration.version}: tables missing after apply: {missing}")
    if columns:
        existing_columns = {
            (str(row[0]), str(row[1]))
            for row in client.query(
                "SELECT table, name FROM system.columns WHERE database = {db:String}",
                parameters={"db": database},
            ).result_rows
        }
        missing_columns = sorted(columns - existing_columns)
        if missing_columns:
            raise MigrationError(
                f"{migration.version}: columns missing after apply: {missing_columns}"
            )


# -- Commands --------------------------------------------------------------------------------


def _check_history(manifest: list[Migration], journal: dict[str, JournalEntry]) -> None:
    by_version = {m.version: m for m in manifest}
    problems: list[str] = []
    for version, entry in journal.items():
        if entry.status != "applied":
            continue
        migration = by_version.get(version)
        if migration is None:
            problems.append(f"{version}: applied in the database but missing on disk")
        elif entry.checksum and entry.checksum != migration.checksum:
            problems.append(
                f"{version}: file changed after it was applied"
                f" (db={entry.checksum[:12]}, file={migration.checksum[:12]})"
            )
    if problems:
        raise MigrationError(
            "migration history does not match the files; write a new forward migration"
            " instead of editing applied ones:\n  " + "\n  ".join(problems)
        )


def apply_migrations(
    target_version: str | None = None,
    *,
    lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> list[str]:
    configure_logging()
    database = _database_name()
    client = _client()
    applied_now: list[str] = []

    try:
        ensure_sys_table(client, database)
        acquire_lock(client, database, lock_ttl_seconds)
        try:
            manifest = discover_migrations()
            journal = load_journal(client, database)
            _check_history(manifest, journal)
            LOGGER.info("migrations_found=%s", len(manifest))

            for migration in manifest:
                entry = journal.get(migration.version)
                if entry is not None and entry.status == "applied":
                    if not entry.checksum:
                        # Legacy row without checksum: record a baseline once.
                        _record(client, database, migration, "applied")
                    LOGGER.info("skip version=%s reason=already_applied", migration.version)
                    continue

                if target_version is not None and migration.version > target_version:
                    LOGGER.info(
                        "stop version=%s reason=target_reached(%s)",
                        migration.version,
                        target_version,
                    )
                    break

                _apply_one(client, database, migration)
                applied_now.append(migration.version)
        finally:
            release_lock(client, database)
    finally:
        client.close()
    return applied_now


def _apply_one(
    client: clickhouse_connect.driver.Client, database: str, migration: Migration
) -> None:
    started_at = time.perf_counter()
    _record(client, database, migration, "started")
    try:
        for statement in split_sql_statements(migration.sql):
            client.command(statement)
        verify_postconditions(client, database, migration)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _record(client, database, migration, "failed", duration_ms=duration_ms, error=str(exc))
        LOGGER.exception("failed version=%s duration_ms=%s", migration.version, duration_ms)
        raise
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    _record(client, database, migration, "applied", duration_ms=duration_ms)
    LOGGER.info("applied version=%s duration_ms=%s", migration.version, duration_ms)


def rollback_migrations(
    target_version: str,
    *,
    allow_production: bool = False,
    lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> list[str]:
    configure_logging()
    if not target_version:
        raise MigrationError("rollback requires an explicit --target version")
    if os.getenv("APP_ENV", "").strip().casefold() in PRODUCTION_ENVS and not allow_production:
        raise MigrationError(
            "refusing to roll back in production; ship a forward-fix migration or pass"
            " --allow-production after taking a backup"
        )

    database = _database_name()
    client = _client()
    rolled_back: list[str] = []
    try:
        ensure_sys_table(client, database)
        acquire_lock(client, database, lock_ttl_seconds)
        try:
            manifest = discover_migrations()
            journal = load_journal(client, database)
            _check_history(manifest, journal)
            to_revert = [
                m
                for m in reversed(manifest)
                if m.version > target_version
                and journal.get(m.version) is not None
                and journal[m.version].status == "applied"
            ]
            missing = [m.version for m in to_revert if m.rollback_path is None]
            if missing:
                raise MigrationError(f"no rollback script for: {', '.join(missing)}")

            for migration in to_revert:
                assert migration.rollback_path is not None
                started_at = time.perf_counter()
                sql = migration.rollback_path.read_text(encoding="utf-8")
                for statement in split_sql_statements(sql):
                    client.command(statement)
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _record(client, database, migration, "rolled_back", duration_ms=duration_ms)
                rolled_back.append(migration.version)
                LOGGER.info("rolled_back version=%s duration_ms=%s", migration.version, duration_ms)
        finally:
            release_lock(client, database)
    finally:
        client.close()
    return rolled_back


def verify_manifest(manifest: list[Migration], rollback_required_from: str = "0005") -> list[str]:
    """Offline checks for CI: every migration after the baseline has a rollback script."""
    return [
        f"{m.version}: missing rollbacks/{m.path.name}"
        for m in manifest
        if m.version >= rollback_required_from and m.rollback_path is None
    ]


def print_status() -> None:
    database = _database_name()
    client = _client()
    try:
        ensure_sys_table(client, database)
        journal = load_journal(client, database)
    finally:
        client.close()
    print(f"{'version':<32} {'state':<12} {'rollback':<9} {'destructive':<12} checksum")
    for migration in discover_migrations():
        entry = journal.get(migration.version)
        state = entry.status if entry else "pending"
        drift = (
            " (CHANGED)"
            if entry and entry.checksum and entry.checksum != migration.checksum
            else ""
        )
        print(
            f"{migration.version:<32} {state:<12} "
            f"{'yes' if migration.rollback_path else 'no':<9} "
            f"{'yes' if migration.destructive else 'no':<12} "
            f"{migration.checksum[:12]}{drift}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage ClickHouse schema migrations")
    parser.add_argument(
        "command",
        nargs="?",
        default="apply",
        choices=("apply", "rollback", "status", "verify", "unlock"),
    )
    parser.add_argument("--target", default=None, metavar="VERSION")
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--lock-ttl", type=int, default=DEFAULT_LOCK_TTL_SECONDS)
    parser.add_argument(
        "--rollback",
        nargs="?",
        const="",
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.rollback is not None:
        print(
            "--rollback is no longer supported; use `apply_migrations.py rollback --target V`",
            file=sys.stderr,
        )
        return 2
    try:
        if args.command == "apply":
            apply_migrations(target_version=args.target, lock_ttl_seconds=args.lock_ttl)
        elif args.command == "rollback":
            rollback_migrations(
                args.target or "",
                allow_production=args.allow_production,
                lock_ttl_seconds=args.lock_ttl,
            )
        elif args.command == "status":
            print_status()
        elif args.command == "verify":
            problems = verify_manifest(discover_migrations())
            for problem in problems:
                print(problem, file=sys.stderr)
            if problems:
                return 1
            print("migration manifest OK")
        elif args.command == "unlock":
            client = _client()
            try:
                release_lock(client, _database_name())
            finally:
                client.close()
            print("migration lock released")
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
