CREATE TABLE IF NOT EXISTS menu_items (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    is_available INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO menu_items (key, name, price, category, sort_order) VALUES
    ('completo_normal', 'Completo Normal (carne)', 3700, 'completos', 1),
    ('completo_gigante', 'Completo Gigante (carne)', 4800, 'completos', 2),
    ('completo_italiano', 'Completo Italiano', 3700, 'completos', 3),
    ('completo_vienesa', 'Completo Vienesa', 3200, 'completos', 4),
    ('completo_vienesa_gigante', 'Vienesa Gigante Italiana', 3400, 'completos', 5),
    ('completo_vienesa_vegano', 'Completo Vienesa Vegano', 4000, 'completos', 6),
    ('completo_vienesa_vegano_gigante', 'Vienesa Vegana Gigante', 4800, 'completos', 7),
    ('as_normal', 'AS Normal', 3700, 'anticuchos', 8),
    ('as_gigante', 'AS Gigante', 4800, 'anticuchos', 9),
    ('chorrillana', 'Chorrillana', 8900, 'platos', 10),
    ('salchipapas_individual', 'Salchipapas Individual', 2800, 'platos', 11),
    ('salchipapas_mediana', 'Salchipapas Mediana', 5100, 'platos', 12),
    ('papas_individual', 'Papas Fritas Individual', 2100, 'acompanamientos', 13),
    ('papas_mediana', 'Papas Fritas Mediana', 3700, 'acompanamientos', 14),
    ('coca_lata', 'Coca Cola lata', 1500, 'bebidas', 15),
    ('coca_1_5l', 'Coca Cola 1.5 Lts', 3000, 'bebidas', 16),
    ('sprite_lata', 'Sprite lata', 1500, 'bebidas', 17),
    ('fanta_lata', 'Fanta lata', 1500, 'bebidas', 18),
    ('agua', 'Agua mineral', 1200, 'bebidas', 19);
