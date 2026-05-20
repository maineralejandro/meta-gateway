CREATE TABLE IF NOT EXISTS catalog_item_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL REFERENCES catalog_items(key) ON DELETE CASCADE,
    label TEXT NOT NULL,
    price INTEGER NOT NULL,
    slug TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(item_key, slug)
);

CREATE INDEX IF NOT EXISTS idx_catalog_variants_item_key ON catalog_item_variants(item_key);
