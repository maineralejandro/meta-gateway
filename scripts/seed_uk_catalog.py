import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.utils import slugify


async def seed_uk_catalog(json_path: str, *, clear: bool = False) -> int:
    from db.database import get_db, init_db
    await init_db()
    db = await get_db()

    with open(json_path) as f:
        data = json.load(f)

    if clear:
        await db.execute("DELETE FROM promotion_items")
        await db.execute("DELETE FROM promotions")
        await db.execute("DELETE FROM catalog_options")
        await db.execute("DELETE FROM catalog_item_variants")
        await db.execute("DELETE FROM catalog_items")
        print("Cleared existing catalog data")

    sort = 0

    for item_data in data.get("catalog_items", []):
        key = item_data["key"]
        name = item_data["name"]
        category = item_data.get("category", "general")
        subcategory = item_data.get("subcategory", "")
        description = item_data.get("description", "")
        specifications = item_data.get("specifications", "")
        tags = item_data.get("tags", [])
        tags_json = json.dumps(tags) if isinstance(tags, list) else item_data.get("tags", "[]")
        is_available = item_data.get("is_available", True)

        variants = item_data.get("variants", [])
        if variants:
            base_price = None
            price = 0
        else:
            base_price = item_data.get("price", 0)
            price = base_price or 0

        await db.upsert_catalog_item(
            key=key,
            name=name,
            price=price,
            category=category,
            is_available=is_available,
            sort_order=sort,
            description=description,
            tags=tags_json,
            size="",
            specifications=specifications,
            subcategory=subcategory,
            base_price=base_price,
        )

        for v_idx, variant in enumerate(variants):
            label = variant["label"]
            v_price = variant["price"]
            slug = slugify(label)
            await db.upsert_catalog_variant(key, label, v_price, slug, v_idx)

        sort += 1

    for opt_data in data.get("options", []):
        key = opt_data["key"]
        name = opt_data["name"]
        price = opt_data["price"]
        category_scope = opt_data.get("category_scope", "")
        opt_sort = opt_data.get("sort_order", 0)
        await db.upsert_catalog_option(key, name, price, category_scope, opt_sort)

    for promo_data in data.get("promotions", []):
        key = promo_data["key"]
        name = promo_data["name"]
        promotion_type = promo_data.get("promotion_type", "fixed_price")
        price = promo_data.get("price")
        valid_days = json.dumps(promo_data.get("valid_days", []))
        valid_from = promo_data.get("valid_from", "")
        valid_to = promo_data.get("valid_to", "")
        terms = promo_data.get("terms", "")
        display_text = promo_data.get("display_text", "")
        promo_sort = promo_data.get("sort_order", 0)

        await db.upsert_promotion(
            key=key, name=name, promotion_type=promotion_type, price=price,
            valid_days=valid_days, valid_from=valid_from, valid_to=valid_to,
            terms=terms, display_text=display_text, sort_order=promo_sort,
        )

        for pi in promo_data.get("items", []):
            item_key = pi["item_key"]
            promotion_price = pi.get("promotion_price")
            await db.upsert_promotion_item(key, item_key, promotion_price)

    item_count = sort
    variant_count = len(await db.load_catalog_variants())
    opt_count = len(await db.load_catalog_options())
    all_promos = await db.load_promotions()
    promo_count = len(all_promos)

    print(f"Seeded: {item_count} items, {variant_count} variants, {opt_count} options, {promo_count} promotions")
    await db.close()
    return item_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed catalog from structured JSON into DB")
    parser.add_argument("json_path", help="Path to catalog JSON file")
    parser.add_argument("--clear", action="store_true", help="Clear existing catalog data before seeding")
    args = parser.parse_args()

    count = asyncio.run(seed_uk_catalog(args.json_path, clear=args.clear))
    print(f"Done. {count} base items in DB.")

    count = asyncio.run(seed_uk_catalog(args.json_path, clear=args.clear))
    print(f"Done. {count} base items in DB.")


if __name__ == "__main__":
    main()
