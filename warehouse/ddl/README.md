# DDL Notes

Schema is managed by SQL migrations in `warehouse/migrations`.

- `0001_init.sql` — system tables, dimensions, raw layer
- `0002_stg.sql` — canonical staging layer
- `0003_marts.sql` — aggregate marts + KPI views

Apply migrations with:

```bash
python3 warehouse/apply_migrations.py
```
