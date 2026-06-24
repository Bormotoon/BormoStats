-- PIM (Product Information Management) — brands, categories, product enrichment

CREATE TABLE IF NOT EXISTS dim_brand
(
  brand_id String,
  organization_id LowCardinality(String),
  name String,
  description String DEFAULT '',
  logo_url String DEFAULT '',
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id, brand_id);

CREATE TABLE IF NOT EXISTS dim_category
(
  category_id String,
  organization_id LowCardinality(String),
  name String,
  parent_id Nullable(String),
  path String DEFAULT '',
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id, category_id);

CREATE TABLE IF NOT EXISTS dim_product_pim
(
  organization_id LowCardinality(String),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  title String DEFAULT '',
  description String DEFAULT '',
  seo_keywords String DEFAULT '',
  brand_id Nullable(String),
  category_id Nullable(String),
  images Array(String) DEFAULT [],
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id, marketplace, account_id, product_id);
