# BormoStats

Production-oriented self-hosted marketplace analytics for Wildberries and Ozon seller accounts.

The repository is organized as a thin root wrapper around the main application package in [`marketplace-analytics/`](./marketplace-analytics). That package contains the backend API, Celery workers, collectors, ClickHouse migrations, dashboards, automation rules, and infrastructure manifests.

## Highlights

- FastAPI backend with a built-in web UI and admin control plane
- ClickHouse warehouse with raw, staging, and mart layers
- Celery workers for WB/Ozon ingestion, transforms, marts, and maintenance tasks
- Docker Compose stack with reverse proxy, health checks, resource limits, and pinned images
- Integration tests, performance smoke checks, vulnerability scans, SBOM generation, and GitHub Actions CI
- Operational documentation for release management, disaster recovery, credential rotation, observability, and troubleshooting

## Repository Layout

```text
.
|-- .github/                    GitHub Actions and repository templates
|-- marketplace-analytics/      Main application package
|   |-- automation/
|   |-- backend/
|   |-- collectors/
|   |-- common/
|   |-- dashboards/
|   |-- docs/
|   |-- infra/
|   |-- scripts/
|   |-- tests/
|   |-- warehouse/
|   `-- workers/
|-- CONTRIBUTING.md
|-- SECURITY.md
|-- CODE_OF_CONDUCT.md
`-- Makefile
```

## Quick Start

1. Create an environment file:

```bash
cd marketplace-analytics
cp .env.example .env
```

2. Fill in real credentials before bootstrap.
   Required values include:
   - `BOOTSTRAP_CH_ADMIN_USER`
   - `BOOTSTRAP_CH_ADMIN_PASSWORD`
   - `CH_USER`
   - `CH_PASSWORD`
   - `ADMIN_API_KEY`
   - `WB_TOKEN_STATISTICS`
   - `WB_TOKEN_ANALYTICS`
   - `OZON_CLIENT_ID`
   - `OZON_API_KEY`

3. Return to the repository root and bootstrap the stack:

```bash
cd ..
make bootstrap
```

4. Open the application:
   - UI: `https://localhost:18443/ui/`
   - Health: `http://localhost:18080/health`
   - Ready: `https://localhost:18443/ready`

The application README in [`marketplace-analytics/README.md`](./marketplace-analytics/README.md) contains the full runtime guide, API surface, environment model, and operational guardrails.

## Developer Workflow

Common commands from the repository root:

```bash
make lint
make typecheck
make test
make check
make perf-smoke
```

Equivalent project-local commands are available inside [`marketplace-analytics/Makefile`](./marketplace-analytics/Makefile).

## Documentation

- Runtime and deployment guide: [`marketplace-analytics/README.md`](./marketplace-analytics/README.md)
- Documentation index: [`marketplace-analytics/docs/README.md`](./marketplace-analytics/docs/README.md)
- Contribution guide: [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- Security policy: [`SECURITY.md`](./SECURITY.md)
- Code of conduct: [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)

## GitHub Readiness Notes

- GitHub issue templates and a pull request template are included under [`.github/`](./.github).
- Dependabot configuration is included in [`.github/dependabot.yml`](./.github/dependabot.yml).
- CI is defined in [`.github/workflows/ci.yml`](./.github/workflows/ci.yml).

## License

This repository is licensed under the GNU General Public License v3.0.
See [`LICENSE`](./LICENSE) for the full text.
