import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

async def seed_menu(json_path: str, *, clear: bool = False) -> int:
    from db.database import get_db, init_db
    await init_db()
    db = await get_db()

    with open(json_path) as f:
        data = json.load(f)

    if clear:
        conn = await db._get_conn()
        await conn.execute("DELETE FROM menu_items")
        await conn.commit()
        print("Cleared existing menu items")

    count = 0
    for key, item in data.items():
        if "name" not in item or "price" not in item:
            print(f"  SKIP {key}: missing name or price")
            continue
        category = item.get("category", "general")
        description = item.get("description", "")
        tags = item.get("tags", [])
        tags_json = json.dumps(tags) if isinstance(tags, list) else item.get("tags", "[]")
        size = item.get("size", "")
        protein = item.get("protein", "")
        conditions = item.get("conditions", "")
        sort_order = count
        await db.upsert_menu_item(
            key=key,
            name=item["name"],
            price=int(item["price"]),
            category=category,
            is_available=True,
            sort_order=sort_order,
            description=description,
            tags=tags_json,
            size=size,
            protein=protein,
            conditions=conditions,
        )
        count += 1

    print(f"Seeded {count} items from {json_path}")
    await db.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed menu items from JSON into DB")
    parser.add_argument("json_path", help="Path to menu JSON file (e.g. config/menu_uk_bar.json)")
    parser.add_argument("--clear", action="store_true", help="Clear existing items before seeding")
    parser.add_argument("--db-path", default=None, help="Override DB path")
    args = parser.parse_args()

    if args.db_path:
        import os
        os.environ["DB_DIR"] = str(Path(args.db_path).parent)
        import core.config as cfg
        cfg.settings.DB_PATH = args.db_path

    count = asyncio.run(seed_menu(args.json_path, clear=args.clear))
    print(f"Done. {count} items in DB.")


if __name__ == "__main__":
    main()
