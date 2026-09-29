# Migration Policy

Migrations live in `warehouse/migrations/NNNN_name.sql`; every migration after the
baseline (`0005`) must ship a matching `warehouse/migrations/rollbacks/NNNN_name.sql`.
`warehouse/apply_migrations.py` is the only supported way to apply them.

## How the runner protects the schema

| Guard | Behaviour |
|---|---|
| Lock | A ClickHouse DDL lock table (`sys_schema_migrations_lock`) prevents two deploys from migrating at once. Locks older than `--lock-ttl` (30 min) are taken over; `apply_migrations.py unlock` removes a lock left by a crashed run. |
| Journal | Every attempt is recorded in `sys_schema_migrations` as `started` → `applied` / `failed` / `rolled_back` with checksum, duration, error and operator. |
| Checksums | A SHA-256 of each file is stored when it is applied. Editing an applied migration aborts the next run — ship a new migration instead. |
| Synchronous mutations | The runner session uses `mutations_sync = 2`, so `ALTER … UPDATE/DELETE` complete before the version is recorded. |
| Postconditions | After each migration, tables created and columns added by it must exist (temporary tables that are renamed/dropped in the same file are tracked). |
| Manifest | `apply_migrations.py status` lists version, state, rollback presence, destructive flag and checksum; `verify` fails CI when a rollback script is missing. |

## Commands

```bash
make migrate                         # apply pending migrations
make migrate-status                  # journal + manifest
make migrate-verify                  # offline check (CI, make check)
make migrate-rollback TARGET=0020_webhooks   # revert everything after TARGET
python warehouse/apply_migrations.py unlock  # clear a stale lock
```

`rollback` requires an explicit `--target`, refuses to start if any version to revert
has no rollback script, and is refused when `APP_ENV=prod` unless
`--allow-production` is passed (after a backup). **Production fixes are forward
migrations**; rollbacks are for dev/stage and emergencies.

## Writing a migration

- Prefer additive changes: `ADD COLUMN IF NOT EXISTS … DEFAULT …`, new tables.
- Keep old and new code compatible for one release (zero-downtime deploys run the
  migration before the new backend/workers start; the old code must tolerate new
  columns, the new code must tolerate missing data).
- Destructive statements (`DROP`, `DELETE`, `MODIFY COLUMN`) need a recovery plan in
  the release notes; the manifest flags them as destructive.
- Data migrations (`ALTER … UPDATE`) must be idempotent (guard with a `WHERE`).
- Write the rollback script at the same time and test the round trip:
  `apply → rollback --target <previous> → apply`.

## CI

`migration-smoke` starts ClickHouse from the documented template, upgrades from the
previous release schema (`--target 0020_webhooks`) to head, performs a rollback /
re-apply round trip and verifies the schema contract (including that no plaintext API
keys remain). The Docker-based integration tests apply all migrations to a fresh
database on every run.
