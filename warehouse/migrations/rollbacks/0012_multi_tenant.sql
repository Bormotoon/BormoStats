DROP TABLE IF EXISTS dim_organization_member;
DROP TABLE IF EXISTS dim_organization;
ALTER TABLE dim_account DROP COLUMN IF EXISTS organization_id;
ALTER TABLE dim_user DROP COLUMN IF EXISTS organization_id;
