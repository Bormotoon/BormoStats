# Architecture

## Pipeline

1. Celery beat triggers collectors (`wb_collect`, `ozon_collect`)
2. Collectors write JSON payload + normalized fields into `raw_*`
3. Transform task writes canonical records into `stg_*`
4. Mart task aggregates into `mrt_*`
5. FastAPI reads marts and serves API
6. Automation engine runs SQL rules and executes actions (Telegram)

## Components

- ClickHouse: analytical warehouse (`mp_analytics`)
- Redis: Celery broker and distributed locks
- Worker: ingestion/transforms/marts/maintenance
- Backend: read/admin API
- Metabase: BI dashboards

## Reliability

- Watermarks (`sys_watermarks`) for incremental collectors
- Redis locks (`lock:{source}:{account_id}`) to prevent parallel same-source runs
- Task run audit (`sys_task_runs`) with status and message

## Project boundaries

System works only with seller's own account data (WB/Ozon APIs).
No competitor/category intelligence is collected.
