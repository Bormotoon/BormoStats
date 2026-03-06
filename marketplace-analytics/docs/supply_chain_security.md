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
- If a vulnerability is accepted temporarily, the exception must be documented in the release notes or an issue with an owner and expiry date.

## Update policy

- Refresh pinned Python dependencies from a clean virtualenv only.
- Refresh pinned Docker image digests only after vulnerability scan + smoke validation.
- Promote the same scanned commit and image set from `stage` to `prod`; do not rebuild artifacts during promotion.
