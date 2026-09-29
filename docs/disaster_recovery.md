# Disaster Recovery

## Backup targets

### ClickHouse

- primary asset: Docker volume `${STACK_NAME}_ch_data`
- strategy: archive the volume on a schedule and before schema-risky releases
- format: compressed tarball stored outside the Docker host
- restore target: clean ClickHouse data volume on a replacement host or fresh stack

Example backup command:

```bash
docker run --rm \
  -v ${STACK_NAME}_ch_data:/source:ro \
  -v "$(pwd)/backups:/backup" \
  busybox:1.36.1 \
  sh -c 'cd /source && tar czf /backup/clickhouse-$(date +%Y%m%dT%H%M%S).tar.gz .'
```

### Metabase

- primary asset: Docker volume `${STACK_NAME}_metabase_data`
- strategy: archive the volume daily and before Metabase upgrades
- restore target: clean Metabase data volume on a replacement host or fresh stack

Example backup command:

```bash
docker run --rm \
  -v ${STACK_NAME}_metabase_data:/source:ro \
  -v "$(pwd)/backups:/backup" \
  busybox:1.36.1 \
  sh -c 'cd /source && tar czf /backup/metabase-$(date +%Y%m%dT%H%M%S).tar.gz .'
```

### Env files and secrets

- primary assets:
  - `.env` contents for each environment
  - marketplace tokens
  - `ADMIN_API_KEY`
  - ClickHouse bootstrap/app credentials
  - Telegram secrets
- strategy:
  - `dev`: local uncommitted `.env` plus password-manager copy for critical credentials
  - `stage` / `prod`: secret manager is the source of truth
  - keep one encrypted off-host export for disaster recovery
- restore target: new host or recovered stack with fresh `.env`/secret injection

## Restore procedure

1. Provision a clean host or clean Docker volumes.
2. Restore secrets first so bootstrap and services can authenticate.
3. Restore ClickHouse volume backup into the target `${STACK_NAME}_ch_data` volume.
4. Restore Metabase volume backup into the target `${STACK_NAME}_metabase_data` volume.
5. Start the stack with `make bootstrap` or the equivalent compose flow.
6. Verify:
   - `GET /health`
   - `GET /ready`
   - `/api/v1/admin/watermarks`
   - `/api/v1/admin/task-runs`
   - Metabase UI opens and saved dashboards are present

Example restore command for a clean target volume:

```bash
docker run --rm \
  -v ${STACK_NAME}_ch_data:/target \
  -v "$(pwd)/backups:/backup:ro" \
  busybox:1.36.1 \
  sh -c 'cd /target && tar xzf /backup/clickhouse-YYYYMMDDTHHMMSS.tar.gz'
```

Use the same pattern for `${STACK_NAME}_metabase_data`.

## RPO / RTO

| Asset | Target RPO | Target RTO | Notes |
| --- | --- | --- | --- |
| ClickHouse data volume | 24h, plus pre-release manual backup | 2h | Lower RPO requires more frequent backup automation |
| Metabase data volume | 24h | 30m | Metabase metadata is much smaller than warehouse data |
| Env/secrets | 1h after any credential change | 1h | Secret manager export must be refreshed after rotations |

## Restore drill

Validated on March 6, 2026 with a clean-volume restore drill:

1. create temporary source volume
2. write sample data into it
3. archive it with the same `busybox:1.36.1` tar pattern used above
4. restore into a fresh target volume
5. verify the restored sample file matches

Result: restore drill passed on a clean destination volume and the sample payload was recovered intact.

## Automated backups and restore drills

`make backup` (`scripts/backup.sh`) creates a timestamped archive in `BACKUP_DIR` with:

- ClickHouse: native `BACKUP DATABASE … TO File('/var/lib/clickhouse/backups/…')`
  (allowed by `infra/docker/clickhouse/config.d/backups.xml`); the script copies the backup
  out of the container and removes the temporary copy;
- Redis: an RDB snapshot (`SAVE`) — queues and locks only, no business data;
- Metabase: the application database volume.

Archives get a `.sha256` file, are GPG-encrypted when `BACKUP_GPG_RECIPIENT` is set and
are pruned after `BACKUP_RETENTION_DAYS`. Schedule it daily (cron/systemd timer) and copy
the archives off the host.

`make restore-check` (`scripts/restore_check.sh`) is the restore drill: it verifies the
checksum, restores the newest backup into `<CH_DB>_restore_check`, compares row counts
of key tables with production and drops the scratch database. Run it at least monthly
and after ClickHouse upgrades; record the result in the release notes.
