# Ozon analytics customization: review draft

This contribution collects local changes originally developed against `282a1e0`
and reapplies them to upstream `60c79bf`. It is a review draft, not a claim that
the changes are production ready. The original project's authorship is retained.

## Changes

- Add article economics with SKU advertising attribution, separate unattributed
  expenses, configurable columns, ABC classifications and spreadsheet export.
- Add an Ozon funnel with seller-provided spreadsheet imports, event-day finance,
  posting cohorts, advertising classifications and historical stock metrics.
- Add realization, CIS buyout, advertising SKU report and campaign metadata
  collectors. Persist report jobs to reuse pending UUIDs and refresh revisions.
- Extend monthly P&L and add daily P&L, dated external expenses, tax estimates
  and realization-based reconciliation. Avoid subtracting Ozon advertising twice
  when it is already included in financial accruals.
- Add a date-range picker, balance/stock snapshots as of a selected date and
  stock cost valuation.
- Preserve the original independent collection timers, incremental watermarks,
  nightly backfills, transform/mart cadence and freshness thresholds. New CIS,
  realization and SKU advertising sources use separate daily timers at 05:00,
  05:10 and 05:55 in the configured Celery timezone. The daily orchestrator and
  its Redis checkpoints have been removed.
- Allow startup with one complete marketplace credential pair. Include optional
  Windows launch/stop helpers and a localhost Compose override.

Local financial examples, credentials, operational exports and a one-off script
with a machine-specific credentials path are excluded. The optional fallback
product-image mapping is empty; normal images still come from the catalogue.

## Settings and migration

Apply migrations 0039 through 0045 using the existing migration runner before
starting the updated services. These add realization, advertising SKU reports,
report jobs, CIS buyouts, funnel imports, campaign metadata and expense dates.
Use rebuilt backend/worker images and rebuilt frontend assets. The optional
local Compose override uses bind mounts; it is not a replacement for a clean
image build.

The realization tax feature defaults to disabled. Its rule is configurable and
must be validated for each deployment; it is not a universal accounting policy:

```dotenv
PNL_REALIZATION_TAX_ENABLED=false
PNL_TAX_RATE_PCT=8
PNL_TAX_ORGANIZATION_ID=default
PNL_TAX_ACCOUNT_ID=default
```

When enabled, monthly realization provides the confirmed base where coverage is
complete; otherwise buyer-price sales net of returns provide an estimate.
Daily allocations preserve the monthly total after rounding. Dated expenses
belong to their exact day; legacy monthly expenses are allocated across calendar
days. Organization-wide external expenses remain included when filtering a
single account and are explicitly described as such.

The original intraday collection, maintenance, marketplace automation, reviews
and backfill schedules remain. Celery again defaults to Europe/Warsaw unless TZ
is set. Mart freshness is two hours; watermark alerts use six hours.

## Areas requiring maintainer review

- Missing COGS can produce numeric profit with a warning in daily P&L, whereas
  article economics uses unknown values. CIS missing-cost propagation needs
  equivalent coverage.
- Dashboard profit availability and the label "after tax" need to distinguish
  missing source data and a disabled tax configuration.
- Monthly margin percentages need reconciliation after financing/CIS adjustments.
- Article tax status needs reconciliation after replacing its amount with the
  daily P&L total, especially for incomplete monthly balance coverage.
- Validate account/organization isolation when the same SKU occurs in multiple
  accounts, and reconcile the account scope of the tax settings.
- Confirm whether every `loans_and_factoring` entry should be excluded from
  operating expenses; principal and financing fees may need separate treatment.
- New frontend unit-test files need wiring into CI; the older dashboardProfit
  helper tests do not cover the current daily-API dashboard implementation.
- Validate imported reports, pagination, role permissions, corrected reports,
  late returns, concurrency and recovery of individual collection tasks.

## Validation and rollback

Schedule restoration on 2026-11-02: 130 focused worker, Celery configuration and
rebuild tests passed in both checkouts under Python 3.14. Tests used pytest 9.1.1
with unrelated plugin autoload disabled. Prometheus rule tests and the local
frontend production build passed. Full integration CI remains outstanding.

See the PR description for checks actually run. Full CI, strict typing, lint,
browser tests and clean Docker builds remain necessary before merge. The
rollback for migration 0044, missing in the local prototype, is included here.

To disable only tax calculation, set PNL_REALIZATION_TAX_ENABLED=false and
recreate the relevant services. To revert the broader behavior, deploy the prior
application version. SQL rollback scripts remove new tables
or columns and can destroy collected/imported data; disabling the application
feature does not require dropping those tables. Back up data before schema
rollback and use the migration runner rather than executing scripts ad hoc.
