CREATE TABLE IF NOT EXISTS orders (
    phone TEXT PRIMARY KEY,
    items_json TEXT NOT NULL DEFAULT '[]',
    total INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(phone);
