from __future__ import annotations

from typing import Any

import asyncpg

from db.repositories.base import BaseRepository


class CartRepository(BaseRepository):
    async def save(self, phone: str, items_json: str, total: int) -> None:
        await self._execute(
            """INSERT INTO carts (phone, items_json, total, updated_at)
            VALUES ($1, $2::jsonb, $3, NOW())
            ON CONFLICT (phone) DO UPDATE SET
            items_json=excluded.items_json, total=excluded.total, updated_at=NOW()""",
            phone, items_json, total,
        )

    async def load(self, phone: str) -> tuple[str, int] | None:
        row = await self._fetchone(
            "SELECT items_json, total FROM carts WHERE phone=$1",
            phone,
        )
        if row:
            return row["items_json"], row["total"]
        return None

    async def delete(self, phone: str) -> None:
        await self._execute("DELETE FROM carts WHERE phone=$1", phone)


class CatalogRepository(BaseRepository):
    async def load_items(self) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT key, name, price, category, is_available, sort_order, "
            "description, tags, size, specifications, base_price, subcategory, "
            "image_url FROM catalog_items ORDER BY sort_order"
        )
        return [dict(row) for row in rows]

    async def upsert_item(
        self, key: str, name: str, price: int, category: str = "general",
        is_available: bool = True, sort_order: int = 0,
        description: str = "", tags: str = "[]", size: str = "",
        specifications: str = "",
        subcategory: str = "", base_price: int | None = None,
        image_url: str | None = None,
    ) -> None:
        await self._execute(
            """INSERT INTO catalog_items (key, name, price, category, subcategory, base_price,
            is_available, sort_order, description, tags, size, specifications, image_url, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12, $13, NOW())
            ON CONFLICT (key) DO UPDATE SET
            name=excluded.name, price=excluded.price, category=excluded.category,
            subcategory=excluded.subcategory, base_price=excluded.base_price,
            is_available=excluded.is_available, sort_order=excluded.sort_order,
            description=excluded.description, tags=excluded.tags, size=excluded.size,
            specifications=excluded.specifications, image_url=excluded.image_url, updated_at=NOW()""",
            key, name, price, category, subcategory, base_price,
            is_available, sort_order, description, tags, size, specifications, image_url,
        )


class AppointmentRepository(BaseRepository):
    async def save(self, phone: str, date: str, time: str, service_key: str, status: str = "confirmed") -> int:
        return await self._insert_returning_id(
            """INSERT INTO appointments (phone, date, time, service_key, status, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW()) RETURNING id""",
            phone, date, time, service_key, status,
        )

    async def load(self, phone: str, status: str = "confirmed") -> list[asyncpg.Record]:
        if status:
            return await self._fetchall(
                "SELECT * FROM appointments WHERE phone=$1 AND status=$2 ORDER BY date, time",
                phone, status,
            )
        return await self._fetchall(
            "SELECT * FROM appointments WHERE phone=$1 ORDER BY date, time",
            phone,
        )

    async def cancel(self, phone: str, date: str, time: str) -> None:
        await self._execute(
            "UPDATE appointments SET status='cancelled', updated_at=NOW() WHERE phone=$1 AND date=$2 AND time=$3",
            phone, date, time,
        )


class MembershipRepository(BaseRepository):
    async def save(self, phone: str, plan_key: str, status: str, started_at: str, next_billing: str) -> None:
        await self._execute(
            """INSERT INTO memberships (phone, plan_key, status, started_at, next_billing, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (phone) DO UPDATE SET
            plan_key=excluded.plan_key, status=excluded.status,
            started_at=excluded.started_at, next_billing=excluded.next_billing, updated_at=NOW()""",
            phone, plan_key, status, started_at, next_billing,
        )

    async def load(self, phone: str) -> asyncpg.Record | None:
        return await self._fetchone(
            "SELECT * FROM memberships WHERE phone=$1",
            phone,
        )

    async def cancel(self, phone: str) -> None:
        await self._execute(
            "UPDATE memberships SET status='cancelled', updated_at=NOW() WHERE phone=$1",
            phone,
        )


class PlanRepository(BaseRepository):
    async def load_all(self) -> list[asyncpg.Record]:
        return await self._fetchall(
            "SELECT * FROM plans ORDER BY sort_order, price"
        )

    async def upsert(self, key: str, name: str, price: int, billing_cycle: str = "monthly", features: str = "[]", sort_order: int = 0) -> None:
        await self._execute(
            """INSERT INTO plans (key, name, price, billing_cycle, features, sort_order)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            ON CONFLICT (key) DO UPDATE SET
            name=excluded.name, price=excluded.price,
            billing_cycle=excluded.billing_cycle, features=excluded.features, sort_order=excluded.sort_order""",
            key, name, price, billing_cycle, features, sort_order,
        )


class VariantRepository(BaseRepository):
    async def load_all(self) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT id, item_key, label, price, slug, sort_order "
            "FROM catalog_item_variants ORDER BY item_key, sort_order"
        )
        return [dict(row) for row in rows]

    async def load_for_item(self, item_key: str) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT id, item_key, label, price, slug, sort_order "
            "FROM catalog_item_variants WHERE item_key=$1 ORDER BY sort_order",
            item_key,
        )
        return [dict(row) for row in rows]

    async def upsert(self, item_key: str, label: str, price: int, slug: str, sort_order: int = 0) -> None:
        await self._execute(
            """INSERT INTO catalog_item_variants (item_key, label, price, slug, sort_order)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (item_key, slug) DO UPDATE SET
            label=excluded.label, price=excluded.price, sort_order=excluded.sort_order""",
            item_key, label, price, slug, sort_order,
        )

    async def delete_for_item(self, item_key: str) -> None:
        await self._execute(
            "DELETE FROM catalog_item_variants WHERE item_key=$1", item_key,
        )


class OptionRepository(BaseRepository):
    async def load_all(self) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT key, name, price, category_scope, sort_order "
            "FROM catalog_options ORDER BY sort_order"
        )
        return [dict(row) for row in rows]

    async def load_for_category(self, category: str) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT key, name, price, category_scope, sort_order "
            "FROM catalog_options WHERE category_scope=$1 ORDER BY sort_order",
            category,
        )
        return [dict(row) for row in rows]

    async def upsert(self, key: str, name: str, price: int, category_scope: str = "*", sort_order: int = 0) -> None:
        await self._execute(
            """INSERT INTO catalog_options (key, name, price, category_scope, sort_order)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (key) DO UPDATE SET
            name=excluded.name, price=excluded.price, category_scope=excluded.category_scope, sort_order=excluded.sort_order""",
            key, name, price, category_scope, sort_order,
        )

    async def delete(self, key: str) -> None:
        await self._execute("DELETE FROM catalog_options WHERE key=$1", key)


class PromotionRepository(BaseRepository):
    async def load_all(self) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT key, name, promotion_type, price, valid_days, valid_from, valid_to, "
            "terms, display_text, sort_order FROM promotions ORDER BY sort_order"
        )
        return [dict(row) for row in rows]

    async def upsert(
        self, key: str, name: str, promotion_type: str, price: int | None = None,
        valid_days: str = "[]", valid_from: str = "", valid_to: str = "",
        terms: str = "", display_text: str = "", sort_order: int = 0,
    ) -> None:
        await self._execute(
            """INSERT INTO promotions (key, name, promotion_type, price, valid_days, valid_from, valid_to,
            terms, display_text, sort_order)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)
            ON CONFLICT (key) DO UPDATE SET
            name=excluded.name, promotion_type=excluded.promotion_type, price=excluded.price,
            valid_days=excluded.valid_days, valid_from=excluded.valid_from, valid_to=excluded.valid_to,
            terms=excluded.terms, display_text=excluded.display_text, sort_order=excluded.sort_order""",
            key, name, promotion_type, price, valid_days, valid_from, valid_to, terms, display_text, sort_order,
        )

    async def load_promotion_items(self, promotion_key: str) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT promotion_key, item_key, promotion_price FROM promotion_items WHERE promotion_key=$1",
            promotion_key,
        )
        return [dict(row) for row in rows]

    async def upsert_promotion_item(self, promotion_key: str, item_key: str, promotion_price: int | None = None) -> None:
        await self._execute(
            """INSERT INTO promotion_items (promotion_key, item_key, promotion_price)
            VALUES ($1, $2, $3)
            ON CONFLICT (promotion_key, item_key) DO UPDATE SET promotion_price=excluded.promotion_price""",
            promotion_key, item_key, promotion_price,
        )

    async def delete_promotion_items(self, promotion_key: str) -> None:
        await self._execute("DELETE FROM promotion_items WHERE promotion_key=$1", promotion_key)

    async def delete(self, key: str) -> None:
        await self._execute("DELETE FROM promotion_items WHERE promotion_key=$1", key)
        await self._execute("DELETE FROM promotions WHERE key=$1", key)


class LeadRepository(BaseRepository):
    async def load(self, phone: str) -> asyncpg.Record | None:
        return await self._fetchone(
            "SELECT * FROM leads WHERE phone=$1",
            phone,
        )

    async def upsert(self, phone: str, stage: str, data_json: str) -> None:
        await self._execute(
            """INSERT INTO leads (phone, stage, data_json, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW())
            ON CONFLICT (phone) DO UPDATE SET
            stage=excluded.stage, data_json=excluded.data_json, updated_at=NOW()""",
            phone, stage, data_json,
        )
