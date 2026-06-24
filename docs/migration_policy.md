# Migration Policy

## Forward-only rule

- schema migrations are forward-only
- do not edit an already applied migration
- do not add down-migration files
- fixes must be shipped as a new migration

## Dry-run validation

Every schema change must pass:

1. local review of the new SQL file
2. local `warehouse/apply_migrations.py` test on a disposable ClickHouse instance when the change is risky
3. the `migration-smoke` CI job against a clean database
4. post-migration schema verification for key tables

Current dry-run path:

- copy `.env.example` to `.env`
- point bootstrap variables to a disposable ClickHouse instance
- run `python warehouse/apply_migrations.py`
- verify key tables and `sys_schema_migrations`

## Failure mitigation

If a migration fails in `stage` or `prod`:

1. stop the rollout
2. identify the last successfully applied migration version
3. do not hand-edit existing migration files
4. fix the issue with:
   - a new corrective migration, or
   - an operational mitigation documented in release notes / incident notes
5. rerun migration smoke before the next rollout attempt

## Migration review checklist

- Does the migration preserve forward-only semantics?
- Does it avoid destructive changes without an explicit recovery plan?
- Is the target table/database name correct?
- Does the release need a bounded backfill after the migration?
- Has migration smoke been rerun on a clean database?
- Are rollback/mitigation notes captured in release notes?
