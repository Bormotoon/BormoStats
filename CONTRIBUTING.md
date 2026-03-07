# Contributing

## Scope

This repository is optimized for a production-grade self-hosted analytics stack.
Contributions should improve correctness, security, maintainability, observability, or operator experience without weakening the existing runtime guardrails.

## Before You Start

- Open an issue before large feature work or architectural changes.
- Keep changes focused. Avoid mixing unrelated refactors, docs churn, and behavior changes in one pull request.
- Do not commit secrets, local `.env` files, credentials, or generated caches.

## Local Setup

```bash
cd marketplace-analytics
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
```

Fill `.env` with safe local values before running stack-level commands.

## Required Checks

Run these before opening a pull request:

```bash
make lint
./.venv/bin/black --check .
make typecheck
make test
./.venv/bin/python scripts/perf_smoke.py
```

If you touch supply-chain, Docker, or infrastructure files, also validate:

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml config -q
```

## Pull Request Expectations

- Describe the user-visible or operator-visible change.
- Explain risks, migrations, and rollback considerations when relevant.
- Update docs together with code.
- Add or adjust tests for new behavior.
- Keep backward compatibility explicit. If you break it, call it out.
- By submitting a contribution, you agree that it is provided under the repository license.

## Style

- Python: Ruff, Black, MyPy strict mode, pinned dependencies.
- Docs: concise, operationally useful, and kept in sync with the actual code.
- Commits: clear, imperative subject lines.

## Security

- Never post secrets in issues, PRs, logs, screenshots, or fixtures.
- For vulnerabilities, follow [`SECURITY.md`](./SECURITY.md) instead of opening a public issue.
