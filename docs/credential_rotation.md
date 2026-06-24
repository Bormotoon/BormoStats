# Credential Rotation and Least Privilege

## Marketplace tokens

### Wildberries

- credentials:
  - `WB_TOKEN_STATISTICS`
  - `WB_TOKEN_ANALYTICS`
- rotation trigger:
  - scheduled rotation before expiry
  - suspected leak
  - scope review after role changes
- rotation procedure:
  1. issue a new token in the marketplace cabinet
  2. update the target environment secret store / `.env`
  3. run `make check-tokens`
  4. verify worker task runs recover
  5. revoke the old token

### Ozon

- credentials:
  - `OZON_CLIENT_ID`
  - `OZON_API_KEY`
  - optional `OZON_PERF_API_KEY`
- rotation procedure:
  1. issue replacement credentials in Ozon
  2. update the environment secret store / `.env`
  3. run `make check-tokens`
  4. verify postings/finance/ads tasks
  5. revoke the old credentials

## Admin API key

- credential: `ADMIN_API_KEY`
- generate with:

```bash
openssl rand -hex 32
```

- rotation procedure:
  1. generate a new key
  2. update the environment secret store / `.env`
  3. redeploy backend/proxy
  4. verify admin endpoints with the new key
  5. remove the old key from any operator tooling

## ClickHouse and Redis credentials

### ClickHouse

- roles:
  - bootstrap admin: used for provisioning and migrations
  - app user: used by backend/workers
  - optional read-only user: used by Metabase
- least-privilege rule:
  - day-to-day services must not use the bootstrap admin
  - Metabase must use the read-only user when enabled
- rotation procedure:
  1. create a new password or replacement user
  2. update secrets for the target environment
  3. redeploy services that use the credential
  4. verify `/ready`, queries, and Metabase connectivity
  5. revoke the old credential

### Redis

- current model:
  - no host-published port
  - private Docker network only
  - access limited by network topology, not by a Redis password
- least-privilege review result:
  - acceptable for the current single-host private-network deployment model
  - not sufficient for a shared-host or multi-tenant deployment
- if the deployment model expands, add Redis ACLs / password auth before exposing the host to less-trusted workloads

## Least-privilege review summary

- backend admin surface is restricted to typed whitelist endpoints
- admin key is memory-only in the web UI
- ClickHouse app access uses a dedicated non-bootstrap user
- worker and beat are isolated from the public network
- Redis relies on private-network isolation; keep it unpublished and reassess before any topology expansion
