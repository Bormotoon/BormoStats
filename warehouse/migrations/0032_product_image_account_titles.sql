-- Product photo for tables that list goods (a thumbnail of the card's first photo).
ALTER TABLE dim_product ADD COLUMN IF NOT EXISTS image_url Nullable(String);

-- The seeded accounts were titled "WB default" / "Ozon default"; with one cabinet per
-- marketplace the marketplace name is the title. Renamed titles stay as they are.
ALTER TABLE dim_account UPDATE title = 'WB'
WHERE marketplace = 'wb' AND account_id = 'default' AND title = 'WB default'
  SETTINGS mutations_sync = 2;
ALTER TABLE dim_account UPDATE title = 'Ozon'
WHERE marketplace = 'ozon' AND account_id = 'default' AND title = 'Ozon default'
  SETTINGS mutations_sync = 2;
