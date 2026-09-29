# Authentication, roles and tenancy

## Principals

| Principal | Key | Scope |
|---|---|---|
| Platform admin | `ADMIN_API_KEY` | ops endpoints (`/admin`, `/organizations`, `/costs`, `/ai`), any organization via `X-Organization-Id` (default `default`) |
| User | `bsk_<key_id>_<secret>` issued per user | exactly one organization (from the user record) and the user's membership role |
| Anonymous | none | only when `PUBLIC_READ_API=true` (dev): read-only analytics of the `default` organization |

Every request resolves to an `AuthContext` (`principal_id`, `organization_id`, `role`,
`scopes`, `auth_method`). Services receive the organization from this context only;
request bodies and query parameters cannot select a tenant.

## Roles and scopes

| Role | Satisfies | Scopes |
|---|---|---|
| owner | owner, admin, manager, analyst, viewer | read:analytics, write:catalog, write:settings, manage:users, execute:marketplace |
| admin | admin, manager, analyst, viewer | same as owner |
| manager | manager, analyst, viewer | read:analytics, write:catalog |
| analyst | analyst, viewer | read:analytics |
| viewer | viewer | read:analytics |

The policy is an explicit table (`app.core.auth.ROLE_GRANTS`), not the enum order.
A user without a membership row in its organization gets **403**.

## User API keys

- Created with `POST /api/v1/users` (optionally `api_key_ttl_days`) and
  `POST /api/v1/users/{id}/rotate-key`; the plaintext key is returned once.
- Stored as `api_key_id` + salted scrypt hash (`N=2^14, r=8, p=1`). Legacy plaintext keys
  were converted by migration `0021` to SHA-256 digests and are upgraded to scrypt on
  first use.
- `POST /users/{id}/revoke-key` revokes one key, `POST /users/revoke-all-keys` all keys
  of the organization. Revocations apply within `AUTH_CACHE_TTL_SECONDS` (30 s) on every
  API process.
- `sys_api_key_usage` records the last use per key (throttled to one write per 5 min).

## Master key hygiene

- Compared in constant time; restrict it with `ADMIN_ALLOWED_NETWORKS` (the proxy
  overwrites `X-Forwarded-For` and uvicorn runs with `--proxy-headers`).
- Do not use it in the web UI day-to-day; create personal user keys instead.

## Audit

All `POST/PUT/PATCH/DELETE` requests under `/api/` are written to `sys_audit_log`
(actor, organization, route, path parameters, status code, `X-Request-ID`).
Admin actions additionally keep their detailed payload in `details_json`.
