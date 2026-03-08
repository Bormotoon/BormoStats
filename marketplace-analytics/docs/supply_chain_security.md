# Supply-Chain Security

## CI controls

The CI pipeline runs these supply-chain checks for `marketplace-analytics`:

- Python dependency vulnerability scan with `pip-audit`
- container image vulnerability scan for backend and worker images
- SBOM generation for source tree, backend image, and worker image

Generated SBOMs are published as workflow artifacts.
Container scan SARIF reports are uploaded to GitHub code scanning.

## Release-blocking policy

- Python dependency scan must be clean.
- Backend and worker image scans must not contain fixable `high` or `critical` vulnerabilities.
- If a vulnerability is accepted temporarily, the exception must be documented in the release notes, an issue, or a tracked waiver file with an owner and expiry date.

## Update policy

- Refresh pinned Python dependencies from a clean virtualenv only.
- Refresh pinned Docker image digests only after vulnerability scan + smoke validation.
- Promote the same scanned commit and image set from `stage` to `prod`; do not rebuild artifacts during promotion.

## Temporary exceptions

- Active waiver file: repository root `.grype.yaml`
- Owner: BormoStats maintainers
- Review date: 2026-10-15
- Scope: `CVE-2025-12781`, `CVE-2025-15366`, `CVE-2025-15367`, `CVE-2026-2297` for the `python` binary package at version `3.14.3`
- Rationale: as of 2026-03-08, Grype reports no stable Python 3.14.x fix for these findings; the first listed fixes are `Python 3.15.0` or `Python 3.15.0a6`
- Exit criteria: remove the waiver after a stable Python release with fixes is available and the backend/worker images are validated on that release
