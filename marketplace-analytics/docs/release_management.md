# Release Management

## Versioning policy

Use Semantic Versioning for operator-visible releases:

- `MAJOR`: incompatible operational or API changes
- `MINOR`: backward-compatible features, new runbooks, new capabilities
- `PATCH`: backward-compatible fixes, dependency refreshes, security fixes, doc-only corrections that matter operationally

Recommended release tag format:

- `vMAJOR.MINOR.PATCH`
- example: `v1.4.2`

## Promotion rule

- build and validate once
- promote the same commit and pinned image set from `stage` to `prod`
- do not rebuild images during promotion

## Release notes

Use `docs/release_notes_template.md` for every release candidate and production release.

Minimum required sections:

- summary of user-visible changes
- schema/data migration impact
- operational changes
- rollback notes
- follow-ups / known issues

## Rollback procedure

1. Identify the last known-good release tag and image set.
2. Stop the current rollout and redeploy the previous pinned artifacts.
3. Re-run:
   - `GET /health`
   - `GET /ready`
   - backend/worker/beat `/metrics`
   - `/api/v1/admin/watermarks`
4. Requeue any missed bounded ingestion windows after recovery.
5. Record the failure mode in release notes or an incident doc before the next rollout attempt.

## Production deploy checklist

Use `docs/release_checklist.md` as the required production deploy checklist.
