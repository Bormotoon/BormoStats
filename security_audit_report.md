# BormoStats — Total Security Audit & Hardening Report

**Date:** 2026-11-04  
**Auditor:** Senior Security & Full-Stack Agent  
**Scope:** Backend (FastAPI), Workers (Celery), Database Queries (ClickHouse), Frontend (React/Vite), Authentication & RBAC, Secret & URL Handling.

---

## 1. Executive Summary

A comprehensive security audit of BormoStats was conducted across all architectural layers. The review identified 5 primary areas requiring defensive hardening:
1. **HTTP Defensive Headers & CORS:** Lack of standard defensive headers (`nosniff`, `SAMEORIGIN`, `strict-origin-when-cross-origin`, `Permissions-Policy`, `Content-Security-Policy`), and hardcoded empty CORS origin config missing `Authorization` preflight header.
2. **Session Revocation & Auth Cache Coherence:** User password change and admin credential resets did not purge cached permissions or terminate orphaned active sessions. In addition, organization member updates/removals did not invalidate the in-memory auth cache.
3. **Database Scoping & Path Traversal:** The Ozon funnel import query lacked explicit `marketplace = 'ozon'` filtering, risking row leakage when accounts across marketplaces shared IDs like `'default'`. The SQL query loader lacked path traversal bounds checking.
4. **Spreadsheet Formula Injection:** CSV export generation streamed raw text fields into CSV files without escaping formula trigger characters (`=`, `+`, `-`, `@`, `\t`, `\r`), posing code/formula execution risks in Excel and LibreOffice Calc.
5. **Frontend Image URL Sanitization:** Table and card image renderers accepted unvalidated image URLs without protocol whitelisting, permitting unsafe schemes.

All 5 issues have been fixed, verified with dedicated unit tests, and committed atomically. All 7 project verification gates remain 100% green.

---

## 2. Discovered Vulnerabilities & Mitigations

### 2.1 HTTP Defensive Headers & Configurable CORS
- **Issue:** Missing standard defensive headers allowed potential clickjacking, MIME sniffing, and token leakage in `Referer`. Additionally, CORS allowed origins were hardcoded empty without `Authorization` in `allow_headers`.
- **Mitigation:**
  - Added `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Permissions-Policy` to `ObservabilityMiddleware` for all responses.
  - Added strict `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` for all `/api/` endpoints.
  - Enforced `Strict-Transport-Security: max-age=31536000; includeSubDomains` in strict environments.
  - Introduced `CORS_ORIGINS` setting in `Settings` and included `Authorization` header in CORS allowed headers.
- **Commit:** `7bee38b` (`fix(security): add HTTP security headers and configurable CORS origins`)

### 2.2 Auth Cache Invalidation & Session Termination
- **Issue:** Changing user passwords or resetting them via admin API did not terminate existing sessions or clear the fast principal cache (`_CACHE`), allowing revoked credentials to continue authenticating for up to 30 seconds. In addition, removing or updating an organization member did not flush cached roles.
- **Mitigation:**
  - Added `revoke_all_for_user` and `revoke_other_sessions` methods to `SessionService`.
  - On user password change: revoked all other active sessions for that user and purged auth cache.
  - On admin password reset: revoked all active sessions for the user and purged auth cache.
  - In `organizations.py`: called `invalidate_auth_cache()` on `update_member`, `remove_member`, and `delete_organization`.
- **Commit:** `188298b` (`fix(security): invalidate auth cache and revoke sessions on credential/member changes`)

### 2.3 ClickHouse Tenant Isolation & SQL Loader Traversal Defense
- **Issue:** In `_query_funnel_analytics`, the Ozon branch queried `raw_ozon_funnel_import` without filtering `marketplace = 'ozon'`, allowing cross-marketplace row leakage for accounts with identical names (e.g. `'default'`). In `sql_loader.py`, query names were concatenated directly without boundary resolution checking.
- **Mitigation:**
  - Added `AND marketplace = 'ozon'` to the Ozon analytics query in `funnel.py`.
  - Added path canonicalization (`resolve()`) and `target.is_relative_to(base)` validation in `sql_loader.py` to prevent directory traversal attacks.
- **Commit:** `cc700ec` (`fix(security): prevent path traversal in sql loader and enforce marketplace filter in funnel`)

### 2.4 CSV Spreadsheet Formula Injection
- **Issue:** Product names, titles, and SKUs beginning with `=`, `+`, `-`, `@`, `\t`, or `\r` were written directly to CSV export files without neutralization. Opening these files in spreadsheet software could execute DDE formulas.
- **Mitigation:**
  - Added `sanitize_csv_cell` in `workers/app/tasks/exports.py` that prefixes formula triggers with a leading single quote (`'`), while preserving valid numbers (e.g. `-123.45` or `+42`).
  - Applied cell sanitization to both headers and rows streamed to disk.
- **Commit:** `c5f3cf8` (`fix(security): prevent formula injection in CSV export generation`)

### 2.5 Frontend URL & Image Sanitization
- **Issue:** `DataTable.jsx`, `Reviews.jsx`, and `Pricing.jsx` rendered `image_url` strings directly in `<img src={...} />` tags without scheme validation.
- **Mitigation:**
  - Created `isSafeImageUrl(url)` utility in `formats.js` strictly allowing `https://`, `http://`, or `data:image/` URIs and rejecting `javascript:` or other schemes.
  - Updated `CellValue` in `DataTable.jsx`, as well as image views in `Reviews.jsx` and `Pricing.jsx`.
- **Commit:** `b13bff0` (`fix(security): sanitize image URLs to prevent script injection in UI`)

---

## 3. Verification Gates Results

| Gate | Tool / Command | Result |
|---|---|---|
| Gate 1 | `ruff check .` | Passed (0 errors) |
| Gate 2 | `ruff format --check .` | Passed (312 files formatted) |
| Gate 3 | `mypy backend workers collectors automation warehouse scripts common` | Passed (0 issues in 187 source files) |
| Gate 4 | `python warehouse/apply_migrations.py verify` | Passed (`migration manifest OK`) |
| Gate 5 | `PYTHONPATH=backend:workers:. pytest -q tests/unit` | Passed (all 670+ tests passing) |
| Gate 6 | `PYTHONPATH=workers:backend:. pytest -q tests/worker_suite` | Passed (all worker tests passing) |
| Gate 7 | `cd frontend && npm test && npm run build` | Passed (17 node tests passing, Vite production build successful) |

---

## 4. Commit Summary

1. `7bee38b`: `fix(security): add HTTP security headers and configurable CORS origins`
2. `188298b`: `fix(security): invalidate auth cache and revoke sessions on credential/member changes`
3. `cc700ec`: `fix(security): prevent path traversal in sql loader and enforce marketplace filter in funnel`
4. `c5f3cf8`: `fix(security): prevent formula injection in CSV export generation`
5. `b13bff0`: `fix(security): sanitize image URLs to prevent script injection in UI`
6. `ccbb975`: `docs(security): add comprehensive total security audit report`

