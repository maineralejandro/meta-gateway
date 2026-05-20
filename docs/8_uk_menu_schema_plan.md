# UK Menu Schema Migration Plan

## Summary

Extend the menu system to support UK Bar y Restaurant's complex menu (~250+ items with variants, modifiers, promos). Design principle: **write-normalized, read-flat** — the admin edits normalized data in the dashboard; `reload_menu_from_db()` expands variants into a flat dict that the LLM consumes via BM25 search and tool results.

## Design Decisions

### 1. Variant keys use slugified labels, NOT autoincrement IDs

Autoincrement IDs are unstable across environments and re-seeds. Persistent orders in `orders.items_json` would break.

```
flat_key = f"{item_key}_{slugify(variant_label)}"
# "chorr_beatles_trad_chica", "sand_deep_purple_churrasco"
```

### 2. Promos need `promo_items` join table

Happy Intenso is a curated list of specific items with promo-specific prices — not a whole category. `included_categories` alone doesn't express this. But the LLM never does the JOIN: `format_active_promos()` precomputes text injected into system_prompt.

### 3. No `order_get_modifiers` tool

Pizza toppings are the only modifier case in the entire menu. Inject as text in system_prompt or `format_for_context`. The LLM can add them to orders by including `modifier_keys` in `order_add`.

### 4. Categories: `category` + `subcategory` columns, not `parent_id` tree

Two levels suffice. BM25 indexes the path "cocteles sour premium" as concatenated text. No recursive tree needed.

### 5. `menu_modifiers` is a flat table (no `modifier_groups`)

Modifier groups are a UI pattern (Uber Eats checkboxes). For a chatbot, a flat table with `applies_to` is enough.

### 6. Seed data via parsing script, not manual entry

~350-400 rows with variants. A Python script parses the raw menu text and generates SQL INSERTs.

## Schema

### ALTER `menu_items`

```sql
ALTER TABLE menu_items ADD COLUMN base_price INTEGER;
ALTER TABLE menu_items ADD COLUMN subcategory TEXT NOT NULL DEFAULT '';
-- When variants exist: base_price = NULL, price unused at runtime
-- When no variants: base_price = the single price (backward compat)
```

### New table: `menu_item_variants`

```sql
CREATE TABLE menu_item_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL REFERENCES menu_items(key) ON DELETE CASCADE,
    label TEXT NOT NULL,           -- "Chica (1-2 pers.)", "Churrasco"
    price INTEGER NOT NULL,       -- 17900
    slug TEXT NOT NULL,           -- "chica", "churrasco" — stable key component
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(item_key, slug)        -- guarantees flat_key stability
);
```

### New table: `menu_modifiers`

```sql
CREATE TABLE menu_modifiers (
    key TEXT PRIMARY KEY,          -- "agreg_camarones"
    name TEXT NOT NULL,            -- "Camarones / Jamón Serrano / Salmón"
    price INTEGER NOT NULL,       -- 5900
    applies_to TEXT NOT NULL,      -- "pizzas" (category or item_key)
    sort_order INTEGER NOT NULL DEFAULT 0
);
```

### New table: `promos`

```sql
CREATE TABLE promos (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    promo_type TEXT NOT NULL,      -- "2x1", "fixed_price", "bundle"
    price INTEGER,                 -- NULL for 2x1, 7000 for "2x$7.000"
    valid_days TEXT NOT NULL DEFAULT '[]',  -- JSON [1,2,3] (1=Mon)
    valid_from TEXT NOT NULL DEFAULT '',     -- "17:00"
    valid_to TEXT NOT NULL DEFAULT '',       -- "18:30"
    conditions TEXT NOT NULL DEFAULT '',
    display_text TEXT NOT NULL DEFAULT '',   -- pre-formatted for system prompt
    sort_order INTEGER NOT NULL DEFAULT 0
);
```

### New table: `promo_items`

```sql
CREATE TABLE promo_items (
    promo_key TEXT NOT NULL REFERENCES promos(key) ON DELETE CASCADE,
    item_key TEXT NOT NULL REFERENCES menu_items(key) ON DELETE CASCADE,
    promo_price INTEGER,           -- NULL = use normal price, 4500 = promo price
    PRIMARY KEY (promo_key, item_key)
);
```

## Runtime Flow

### `reload_menu_from_db()` — expand variants into flat dict

```python
async def reload_menu_from_db(self) -> None:
    items = await db.load_menu_items()
    variants = await db.load_menu_variants()
    modifiers = await db.load_menu_modifiers()
    
    flat_menu = {}
    for item in items:
        item_variants = [v for v in variants if v["item_key"] == item["key"]]
        if item_variants:
            for v in item_variants:
                flat_key = f"{item['key']}_{v['slug']}"
                flat_menu[flat_key] = {
                    "name": f"{item['name']} - {v['label']}",
                    "price": v["price"],
                    "category": item["category"],
                    "subcategory": item["subcategory"],
                    "description": item["description"],
                    "tags": item.get("tags", []),
                    "conditions": item.get("conditions", ""),
                    "base_item_key": item["key"],  # for grouping
                }
        else:
            flat_menu[item["key"]] = {
                "name": item["name"],
                "price": item.get("base_price") or item.get("price", 0),
                "category": item["category"],
                "subcategory": item["subcategory"],
                "description": item["description"],
                "tags": item.get("tags", []),
                "conditions": item.get("conditions", ""),
            }
    
    self._menu = flat_menu
    self._modifiers = {m["key"]: m for m in modifiers}
    self._rebuild_search()
```

### `format_for_context()` — inject promos + modifiers

```python
async def format_for_context(self, phone, config):
    lines = []
    if self.needs_search:
        lines.append("Menu grande: usa order_search_item para buscar productos o order_get_categories para ver categorias.")
    else:
        # flat mode (unlikely with UK menu, but backward compat)
        ...
    
    # Active promos
    active = self._get_active_promos()
    if active:
        lines.append("")
        lines.append("PROMOCIONES ACTIVAS AHORA:")
        for promo in active:
            lines.append(f"- {promo['display_text']}")
    
    # Modifiers relevant to current order categories
    order = self._orders.get(phone)
    if order and order["items"]:
        lines.append("")
        lines.append("Pedido actual del cliente:")
        ...
    else:
        lines.append("")
        lines.append("Pedido actual del cliente: vacio")
    
    return "\n".join(lines)
```

### `add_item()` — accept modifier_keys

```python
async def add_item(self, phone, item_key, quantity=1, modifier_keys=None):
    # ... existing logic ...
    modifier_total = 0
    applied_modifiers = []
    if modifier_keys:
        for mk in modifier_keys:
            mod = self._modifiers.get(mk)
            if mod:
                modifier_total += mod["price"]
                applied_modifiers.append({"key": mk, "name": mod["name"], "price": mod["price"]})
    
    order["items"].append({
        "key": item_key,
        "name": menu_item["name"],
        "price": menu_item["price"] + modifier_total,
        "quantity": quantity,
        "modifiers": applied_modifiers,  # track for display
    })
```

### `MenuSearch.build_index()` — category path in BM25 text

```python
def _build_searchable_text(item):
    parts = [item.get("name", "")]
    
    cat = item.get("category", "")
    sub = item.get("subcategory", "")
    if cat and sub:
        parts.append(f"{cat} {sub}")  # "cocteles sour"
    elif cat:
        parts.append(cat)
    
    desc = item.get("description")
    if desc:
        parts.append(desc)
    # ... rest unchanged
```

## Execution Order

| Step | What | Files |
|------|------|-------|
| 1 | Migrations: 019-023 (alter menu_items, create variants/modifiers/promos/promo_items) | `db/migrations/019-023*.sql` |
| 1.5 | Parsing script: UK menu text → SQL seed | `scripts/parse_uk_menu.py` |
| 2 | Repositories + database.py delegates | `db/repositories/business.py`, `db/database.py` |
| 3 | slugify() + rewrite reload_menu_from_db (variant expansion) | `core/capabilities/order.py` |
| 4 | MenuSearch: category path in BM25 index | `core/capabilities/menu_search.py` |
| 5 | format_for_context: inject active promos + modifiers | `core/capabilities/order.py` |
| 6 | add_item: accept modifier_keys, sum modifier prices | `core/capabilities/order.py` |
| 7 | Update tool definitions: order_add with modifier_keys | `core/capabilities/order.py` |
| 8 | Update tests + new tests | `tests/` |
| 9 | Dashboard MenuEditor.tsx (future, not in this iteration) | Dashboard |

## Backward Compatibility

- Existing `menu_items` with single price: `base_price` set, no variants → works as before
- `config/menu.json` fallback: continues to load flat items without variants
- `orders.items_json` format: adds optional `modifiers` field, backward compat with existing orders
- `price` column kept (NOT NULL constraint) — becomes "display price" or fallback when `base_price` is NULL
- Tests using Chilean food truck menu continue to pass (no variants in that dataset)
