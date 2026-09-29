-- History store, modelled on git: every observed state of a product card or a statistics
-- record is kept forever. Nothing here is ever updated in place or pruned.
--
--   hist_objects  content-addressed blobs (like git blobs): identical content is stored once
--   hist_commits  one commit per observed change of an entity, linked to its parent commit
--   hist_refs     HEAD of every entity (rebuildable from hist_commits)
--   hist_changes  field-level diff of every commit, for "how did this price change" queries
--
-- Commit ids are derived from (entity, parent, object), so a retried write is idempotent.

CREATE TABLE IF NOT EXISTS hist_objects
(
  object_hash String,
  kind LowCardinality(String),
  size UInt32,
  body String CODEC(ZSTD(3)),
  stored_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(stored_at)
ORDER BY (object_hash);

CREATE TABLE IF NOT EXISTS hist_commits
(
  commit_id String,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  repo LowCardinality(String),
  entity_key String,
  parent_id String,
  object_hash String,
  is_deleted UInt8,
  committed_at DateTime,
  run_id String,
  source LowCardinality(String),
  message String,
  changed_paths Array(String) CODEC(ZSTD(3)),
  INDEX idx_committed_at committed_at TYPE minmax GRANULARITY 4
)
ENGINE = ReplacingMergeTree(committed_at)
ORDER BY (marketplace, account_id, repo, entity_key, commit_id);

CREATE TABLE IF NOT EXISTS hist_refs
(
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  repo LowCardinality(String),
  entity_key String,
  head_commit String,
  head_object String,
  is_deleted UInt8,
  commit_count UInt32,
  first_seen_at DateTime,
  updated_at DateTime
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (marketplace, account_id, repo, entity_key);

CREATE TABLE IF NOT EXISTS hist_changes
(
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  repo LowCardinality(String),
  entity_key String,
  path String,
  commit_id String,
  committed_at DateTime,
  op LowCardinality(String),
  old_value String CODEC(ZSTD(3)),
  new_value String CODEC(ZSTD(3)),
  INDEX idx_committed_at committed_at TYPE minmax GRANULARITY 4
)
ENGINE = ReplacingMergeTree(committed_at)
ORDER BY (marketplace, account_id, repo, entity_key, path, commit_id);
