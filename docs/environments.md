# Environments

## Model

The stack is operated as three separate environments:

- `dev`: local feature work, self-signed TLS, disposable data, debug logging allowed
- `stage`: production-like validation on isolated credentials, alerts, and ports
- `prod`: business traffic only, least-privilege credentials, no shared secrets with other environments

Each environment must have:

- its own `.env` file or secret bundle
- its own `STACK_NAME`
- its own published ports when environments share a host
- its own ClickHouse/Redis/Metabase volumes and credentials
- its own marketplace tokens and admin API key

## Templates

Example environment templates are provided in the repository root:

- `.env.dev.example`
- `.env.stage.example`
- `.env.prod.example`

Use them as starting points only. Real secrets must stay outside git.

## Secrets separation

- Never reuse marketplace tokens between `stage` and `prod`.
- Never reuse `ADMIN_API_KEY` between environments.
- Use separate ClickHouse app/bootstrap passwords per environment.
- Use separate Telegram destinations so stage alerts cannot page production channels.

Recommended storage:

- local `dev`: uncommitted `.env`
- `stage` / `prod`: secret manager or deployment platform secret store

## Stack names and ports

Default examples intentionally use different stack names and host ports:

| Environment | Stack name | HTTP | HTTPS | ClickHouse | Metabase | Worker metrics | Beat metrics |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | `bormostats-dev` | `18080` | `18443` | `18123` | `13000` | `19101` | `19102` |
| stage | `bormostats-stage` | `28080` | `28443` | `28123` | `23000` | `29101` | `29102` |
| prod | `bormostats-prod` | `38080` | `38443` | `38123` | `33000` | `39101` | `39102` |

If production runs on a dedicated host or behind an external load balancer, you can override the
published ports there, but the example templates keep environments collision-free by default.

## Promotion flow

1. Develop and validate changes in `dev`.
2. Promote the exact same commit to `stage`.
3. Run the full quality gate, bootstrap/migration smoke checks, and release checklist in `stage`.
4. Verify alerts, dashboards, `/ready`, `/metrics`, and one bounded admin smoke action in `stage`.
5. Promote the same commit and pinned image set to `prod` without rebuilding artifacts.
6. If `prod` fails verification, roll back to the previous known-good commit/images and document the incident.

## Running an environment from its own env file

Several stacks can share a host (for example a stopped `dev` next to a running `prod`). Keep each
environment's settings in its own git-ignored file, e.g. `.env.prod.local`, and point every tool
at it:

- `--env-file .env.prod.local` for `docker compose` (variable substitution in the compose file);
- `APP_ENV_FILE=../../.env.prod.local` **inside** that file: the path, relative to
  `infra/docker/`, of the file the backend, worker and beat containers read. Without it they fall
  back to `.env` and start with the other environment's secrets;
- `ENV_FILE=$PWD/.env.prod.local` for `scripts/bootstrap.sh`, `backup.sh`, `restore_check.sh`,
  `run_local.sh` and `make` targets.

```bash
docker compose --project-name bormostats-prod --env-file .env.prod.local \
  -f infra/docker/docker-compose.yml up -d
ENV_FILE="$PWD/.env.prod.local" bash scripts/backup.sh
```

To serve the UI on the local network, set `TLS_SERVER_NAME` to the host's LAN address and
`PUBLIC_BASE_URL` to `https://<address>:<BACKEND_TLS_HOST_PORT>`, then regenerate the certificate
(`scripts/gen_tls_cert.sh` skips an existing one). The proxy publishes HTTP/HTTPS on all
interfaces; ClickHouse, Metabase and the metrics ports stay bound to `127.0.0.1`.
