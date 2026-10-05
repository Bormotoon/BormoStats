# History store

A local, append-only history of everything the collectors see, modelled on git. Nothing in it is
updated in place or pruned, so a price, a characteristic, a photo, a posting status or a metric
that the marketplace later changes or deletes stays queryable.

It lives in the same ClickHouse database as the rest of the warehouse (migration `0028_history`),
so it is covered by `make backup` and tenant-scoped through `dim_account` like every other table.

## Model

| git | table | holds |
|---|---|---|
| blob | `hist_objects` | canonical JSON of one state, keyed by the SHA-256 of that JSON. Identical states of any entity are stored once. |
| commit | `hist_commits` | one row per observed change of an entity: parent commit, object, time, run, message, `changed_paths`. |
| ref (`HEAD`) | `hist_refs` | current commit of every entity; rebuildable from `hist_commits`. |
| `git log -p` | `hist_changes` | one row per changed field of a commit with old and new value (`add` / `change` / `remove`). |

An entity is `(marketplace, account_id, repo, entity_key)`. A **repo** groups entities of one kind:

- `product`: one entity per card (WB `nmID`, Ozon `product_id`). The document has sections:
  WB `card` (Content API) and `price` (Prices API); Ozon `info`, `attributes` and `price`.
  Characteristics, descriptions, photo/video URLs, dimensions, prices, discounts, statuses,
  commissions: all of it is in the document, so all of it is tracked.
- one repo per `raw_*` table (`raw_wb_sales`, `raw_ozon_postings`, …). The entity is the row's
  logical key (e.g. `posting_number`); every ingested *version* becomes a commit. The raw table
  keeps only the latest version (`ReplacingMergeTree`) and is pruned, the archive keeps all of them.

Rules that keep the store small and honest:

- A commit is written only when the object hash differs from HEAD and the field diff finds a
  change: a list of id-matched items that only came back in another order (Ozon's complex
  attributes do on every call) is not a commit. Re-reading an unchanged
  catalogue writes nothing. Volatile columns (`run_id`, `ingested_at`, and `snapshot_ts` of stock
  snapshots) are not part of the state, so a stock row is committed when the quantity changes, not
  every 30 minutes.
- Commit ids derive from entity, parent and object, so a retried write is idempotent. Write order is
  objects, changes, commits, refs; a crash leaves `HEAD` behind and the retry repeats the same commits.
- Field paths look like `price.sizes[sizeID=123].discountedPrice`. List items with an `id`-like key
  are matched by it, so reordering characteristics is not a change. Lists of scalars (photo URLs)
  are one value.
- **Deletions are commits.** When a complete catalogue listing no longer contains a product, it gets
  a tombstone commit (`is_deleted = 1`); if it returns, a `restored` commit. Nothing is tombstoned
  when the listing is empty or when more than half of ≥ 10 known products vanish at once (treated as a
  broken response; logged and counted in `tombstone_guard`).
- A section whose source could not be read this run (prices token without access: 401/403) is carried
  over from HEAD instead of being recorded as removed. Other errors, including 404/405 for a switched-off
  method, fail the task.

## Collection

| Task | Schedule | Needs |
|---|---|---|
| `tasks.history.wb_catalog_snapshot` | hourly `:12` | `WB_TOKEN_CONTENT` (category "Content"); prices additionally need `WB_TOKEN_PRICES` |
| `tasks.history.ozon_catalog_snapshot` | hourly `:27` | `OZON_CLIENT_ID` / `OZON_API_KEY` |
| `tasks.history.backfill_raw_archive` | daily 01:30 | imports the raw tables' current contents once per table (a table added later, e.g. the finance tables, is imported on the next run), then retires entities whose key changed (below) |
| every collector | on each insert | `insert_rows` archives what it writes; no extra API calls |

`prune_old_raw` (02:00) skips a raw table until its one-off import is done, so pruning can never delete
the only copy of a row. `HISTORY_ENABLED=false` switches the archive and this guard off.

Marketplace endpoints used (constants in `collectors/*/endpoints.py`): WB `POST /content/v2/get/cards/list`,
`GET /api/v2/list/goods/filter`; Ozon `POST /v3/product/list`, `/v3/product/info/list`,
`/v4/product/info/attributes`, `/v5/product/info/prices`.

### What is archived

Every raw table of the seller's own data: sales, returns and orders (WB), stocks (both), the WB
funnel, Ozon postings and their items, Ozon ads, Ozon accruals, the finance block
(`raw_ozon_finance_balance`, `raw_wb_sales_report`, `raw_marketplace_balance` — balance snapshots
are one entity per marketplace, committed when the balance changes), and the product catalogues
of both marketplaces (cards, attributes, prices, price indexes). An integration test fails when
a non-empty raw table has no history repo.

### Re-keyed tables

When a migration changes a table's key, the entities under the old key would live on next to
the new ones. `LEGACY_ENTITY_FILTERS` lists them; the daily import gives each a deletion commit
with the reason ("re-keyed: sale_id joined the key (migration 0029)"), so a point-in-time view
shows the old entities before that moment and the new ones after it.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `HISTORY_ENABLED` | `true` | Archive collector output and guard pruning. Catalogue tasks are skipped when `false`. |
| `WB_TOKEN_CONTENT` | — | WB Content API token; without it the WB catalogue task is skipped. |
| `HISTORY_PRODUCT_IGNORE_PATHS` | — | Comma-separated `fnmatch` paths dropped from product documents before hashing (e.g. `*.updatedAt`) for fields that change on every read. Dropped fields are not stored. |
| `HISTORY_STAT_IGNORE_PATHS` | — | Same, for archived statistics rows (e.g. `payload.some_counter`). |

## API

All endpoints are read-only, tenant-scoped, and need the same access as the analytics endpoints.

| Endpoint | git equivalent | Notes |
|---|---|---|
| `GET /api/v1/history/repos` | `git count-objects` | entities, deleted entities and commits per repo |
| `GET /api/v1/history/commits` | `git log` | `repo` (default `product`), `marketplace`, `account_id`, `entity_key`, `since`, `until`, `limit`, `offset` |
| `GET /api/v1/history/commits/{commit_id}` | `git show` | the document as recorded and the fields it changed |
| `GET /api/v1/history/snapshot` | `git checkout <time>` | `marketplace`, `entity_key`, `at` (default now); 404 when the entity did not exist yet |
| `GET /api/v1/history/state` | `git checkout <time>` of a whole repo | `repo`, `marketplace`, `account_id`, `at` (default now), `limit`, `offset`: every entity alive at `at` with its document. The UI page "История" shows it for any dataset and moment. |
| `GET /api/v1/history/changes` | `git log -p -- <path>` | `path_prefix` (e.g. `price`, `card.title`), same filters as `commits` |

Examples:

```bash
# every price change of WB card 12345678
curl -H "X-API-Key: $KEY" \
  "$API/api/v1/history/changes?marketplace=wb&entity_key=12345678&path_prefix=price"

# the card as it was on 1 September
curl -H "X-API-Key: $KEY" \
  "$API/api/v1/history/snapshot?marketplace=wb&entity_key=12345678&at=2026-09-01T00:00:00Z"

# every status a posting went through
curl -H "X-API-Key: $KEY" \
  "$API/api/v1/history/commits?repo=raw_ozon_postings&marketplace=ozon&entity_key=0123-4567-1"
```

Timestamps without an offset are read as UTC.

## Limits and operating notes

- Media are tracked as URLs. The image files themselves are not downloaded, so a photo replaced under
  the same URL is not detected.
- `GET /history/repos` reads every ref of the tenant (`FINAL`); it is a status call, not a dashboard query.
- History tables are never pruned. Size grows with the number of *changes*: budget for it
  (`SELECT repo, count() FROM hist_commits GROUP BY repo`). Bodies and diffs are ZSTD-compressed.
- The rollback of `0028_history` drops all four tables. It exists for dev/stage; in production, restore from backup instead.
- Only the seller's own accounts are archived. Competitor tables (`raw_competitor_*`) are not pruned and are not part of this store.
