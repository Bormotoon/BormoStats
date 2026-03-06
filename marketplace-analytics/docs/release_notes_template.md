# Release Notes Template

## Release

- Version:
- Date:
- Commit:
- Environment:

## Summary

- 

## User-facing changes

- 

## Schema / data impact

- migrations included:
- backfill required:
- data quality or observability changes:

## Operational changes

- env changes:
- dashboard / alert changes:
- infrastructure changes:

## Verification

- `ruff check .`
- `black --check .`
- `mypy backend workers collectors automation warehouse scripts`
- `pytest -q`
- migration smoke:
- backup / restore status:
- perf smoke:

## Rollback notes

- previous known-good version:
- rollback trigger:
- bounded requeue needed after rollback:

## Known issues / follow-ups

- 
