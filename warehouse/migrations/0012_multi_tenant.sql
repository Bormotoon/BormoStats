-- Multi-tenant: Organizations, org members, and account scoping

CREATE TABLE IF NOT EXISTS dim_organization
(
  organization_id String,
  name String,
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id);

CREATE TABLE IF NOT EXISTS dim_organization_member
(
  organization_id LowCardinality(String),
  user_id LowCardinality(String),
  role Enum8('owner' = 1, 'admin' = 2, 'manager' = 3, 'analyst' = 4, 'viewer' = 5),
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id, user_id);

ALTER TABLE dim_account ADD COLUMN IF NOT EXISTS organization_id LowCardinality(String) DEFAULT 'default';

ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS organization_id LowCardinality(String) DEFAULT 'default';

INSERT INTO dim_organization (organization_id, name)
SELECT *
FROM (
  SELECT 'default' AS organization_id, 'Default Organization' AS name
)
WHERE NOT EXISTS (
  SELECT 1 FROM dim_organization FINAL WHERE organization_id = 'default'
);
