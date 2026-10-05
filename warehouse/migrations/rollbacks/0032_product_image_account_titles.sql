ALTER TABLE dim_product DROP COLUMN IF EXISTS image_url;
ALTER TABLE dim_account UPDATE title = 'WB default'
WHERE marketplace = 'wb' AND account_id = 'default' AND title = 'WB'
  SETTINGS mutations_sync = 2;
ALTER TABLE dim_account UPDATE title = 'Ozon default'
WHERE marketplace = 'ozon' AND account_id = 'default' AND title = 'Ozon'
  SETTINGS mutations_sync = 2;
