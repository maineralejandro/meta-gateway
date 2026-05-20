CREATE TABLE IF NOT EXISTS catalog_options (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    category_scope TEXT NOT NULL DEFAULT '*',
    sort_order INTEGER NOT NULL DEFAULT 0
);
