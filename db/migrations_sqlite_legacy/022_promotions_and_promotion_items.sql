CREATE TABLE IF NOT EXISTS promotions (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    promotion_type TEXT NOT NULL CHECK(promotion_type IN ('fixed_price', 'percentage', 'bogo', 'bundle', 'flat_discount', 'other')) DEFAULT 'fixed_price',
    price INTEGER,
    valid_days TEXT NOT NULL DEFAULT '[]',
    valid_from TEXT NOT NULL DEFAULT '',
    valid_to TEXT NOT NULL DEFAULT '',
    terms TEXT NOT NULL DEFAULT '',
    display_text TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS promotion_items (
    promotion_key TEXT NOT NULL REFERENCES promotions(key) ON DELETE CASCADE,
    item_key TEXT NOT NULL REFERENCES catalog_items(key) ON DELETE CASCADE,
    promotion_price INTEGER,
    PRIMARY KEY (promotion_key, item_key)
);

CREATE INDEX IF NOT EXISTS idx_promotion_items_promo ON promotion_items(promotion_key);
CREATE INDEX IF NOT EXISTS idx_promotion_items_item ON promotion_items(item_key);
