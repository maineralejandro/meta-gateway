ALTER TABLE catalog_items ADD COLUMN base_price INTEGER;
ALTER TABLE catalog_items ADD COLUMN subcategory TEXT NOT NULL DEFAULT '';
