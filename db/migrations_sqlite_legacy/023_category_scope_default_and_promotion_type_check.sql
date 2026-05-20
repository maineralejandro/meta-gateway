-- Migration 023: Fix category_scope default, add promotion_type CHECK
-- catalog_options: DEFAULT empty changed to DEFAULT star (star means all categories)
-- promotions: add CHECK constraint on promotion_type
-- Strategy: create temp tables, copy data, drop originals, recreate with correct schema, copy back, drop temps

CREATE TABLE IF NOT EXISTS catalog_options_new (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    category_scope TEXT NOT NULL DEFAULT '*',
    sort_order INTEGER NOT NULL DEFAULT 0
);

INSERT INTO catalog_options_new (key, name, price, category_scope, sort_order)
    SELECT key, name, price,
           CASE WHEN category_scope = '' THEN '*' ELSE category_scope END,
           sort_order
    FROM catalog_options;

DROP TABLE catalog_options;

CREATE TABLE catalog_options (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    category_scope TEXT NOT NULL DEFAULT '*',
    sort_order INTEGER NOT NULL DEFAULT 0
);

INSERT INTO catalog_options SELECT * FROM catalog_options_new;

DROP TABLE catalog_options_new;

CREATE TABLE IF NOT EXISTS promotions_new (
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

INSERT INTO promotions_new (key, name, promotion_type, price, valid_days, valid_from, valid_to, terms, display_text, sort_order)
    SELECT key, name, promotion_type, price, valid_days, valid_from, valid_to, terms, display_text, sort_order
    FROM promotions;

CREATE TABLE IF NOT EXISTS promotion_items_new (
    promotion_key TEXT NOT NULL,
    item_key TEXT NOT NULL,
    promotion_price INTEGER,
    PRIMARY KEY (promotion_key, item_key)
);

INSERT INTO promotion_items_new (promotion_key, item_key, promotion_price)
    SELECT promotion_key, item_key, promotion_price
    FROM promotion_items;

DROP TABLE promotion_items;

DROP TABLE promotions;

CREATE TABLE promotions (
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

INSERT INTO promotions SELECT * FROM promotions_new;

DROP TABLE promotions_new;

CREATE TABLE promotion_items (
    promotion_key TEXT NOT NULL,
    item_key TEXT NOT NULL,
    promotion_price INTEGER,
    PRIMARY KEY (promotion_key, item_key)
);

INSERT INTO promotion_items SELECT * FROM promotion_items_new;

DROP TABLE promotion_items_new;

CREATE INDEX IF NOT EXISTS idx_promotion_items_promo ON promotion_items(promotion_key);

CREATE INDEX IF NOT EXISTS idx_promotion_items_item ON promotion_items(item_key);
