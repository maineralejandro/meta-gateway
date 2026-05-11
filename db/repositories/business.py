from __future__ import annotations

from typing import Any

import aiosqlite

from db.repositories.base import BaseRepository


class OrderRepository(BaseRepository):
    async def save(self, phone: str, items_json: str, total: int) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO orders (phone, items_json, total, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
            items_json=excluded.items_json, total=excluded.total, updated_at=CURRENT_TIMESTAMP""",
            (phone, items_json, total),
        )
        await conn.commit()

    async def load(self, phone: str) -> tuple[str, int] | None:
        row = await self._fetchone(
            "SELECT items_json, total FROM orders WHERE phone=?",
            (phone,),
        )
        if row:
            return row["items_json"], row["total"]
        return None

    async def delete(self, phone: str) -> None:
        await self._execute_and_commit("DELETE FROM orders WHERE phone=?", (phone,))


class MenuRepository(BaseRepository):
    async def load_items(self) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT key, name, price, category, is_available, sort_order, "
            "description, tags, size, protein, conditions "
            "FROM menu_items ORDER BY sort_order"
        )
        return [dict(row) for row in rows]

    async def upsert_item(
        self, key: str, name: str, price: int, category: str = "general",
        is_available: bool = True, sort_order: int = 0,
        description: str = "", tags: str = "[]", size: str = "",
        protein: str = "", conditions: str = "",
    ) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO menu_items (key, name, price, category, is_available, sort_order,
               description, tags, size, protein, conditions, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                name=excluded.name, price=excluded.price, category=excluded.category,
                is_available=excluded.is_available, sort_order=excluded.sort_order,
                description=excluded.description, tags=excluded.tags, size=excluded.size,
                protein=excluded.protein, conditions=excluded.conditions,
                updated_at=CURRENT_TIMESTAMP""",
            (key, name, price, category, int(is_available), sort_order,
             description, tags, size, protein, conditions),
        )
        await conn.commit()


class AppointmentRepository(BaseRepository):
    async def save(self, phone: str, date: str, time: str, service_key: str, status: str = "confirmed") -> int:
        return await self._insert_returning_id(
            """INSERT INTO appointments (phone, date, time, service_key, status, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (phone, date, time, service_key, status),
        )

    async def load(self, phone: str, status: str = "confirmed") -> list[aiosqlite.Row]:
        if status:
            return await self._fetchall(
                "SELECT * FROM appointments WHERE phone=? AND status=? ORDER BY date, time",
                (phone, status),
            )
        return await self._fetchall(
            "SELECT * FROM appointments WHERE phone=? ORDER BY date, time",
            (phone,),
        )

    async def cancel(self, phone: str, date: str, time: str) -> None:
        await self._execute_and_commit(
            "UPDATE appointments SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE phone=? AND date=? AND time=?",
            (phone, date, time),
        )


class MembershipRepository(BaseRepository):
    async def save(self, phone: str, plan_key: str, status: str, started_at: str, next_billing: str) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO memberships (phone, plan_key, status, started_at, next_billing, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
            plan_key=excluded.plan_key, status=excluded.status,
            started_at=excluded.started_at, next_billing=excluded.next_billing, updated_at=CURRENT_TIMESTAMP""",
            (phone, plan_key, status, started_at, next_billing),
        )
        await conn.commit()

    async def load(self, phone: str) -> aiosqlite.Row | None:
        return await self._fetchone(
            "SELECT * FROM memberships WHERE phone=?",
            (phone,),
        )

    async def cancel(self, phone: str) -> None:
        await self._execute_and_commit(
            "UPDATE memberships SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE phone=?",
            (phone,),
        )


class PlanRepository(BaseRepository):
    async def load_all(self) -> list[aiosqlite.Row]:
        return await self._fetchall(
            "SELECT * FROM plans ORDER BY sort_order, price"
        )

    async def upsert(self, key: str, name: str, price: int, billing_cycle: str = "monthly", features: str = "[]", sort_order: int = 0) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO plans (key, name, price, billing_cycle, features, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
            name=excluded.name, price=excluded.price,
            billing_cycle=excluded.billing_cycle, features=excluded.features, sort_order=excluded.sort_order""",
            (key, name, price, billing_cycle, features, sort_order),
        )
        await conn.commit()


class LeadRepository(BaseRepository):
    async def load(self, phone: str) -> aiosqlite.Row | None:
        return await self._fetchone(
            "SELECT * FROM leads WHERE phone=?",
            (phone,),
        )

    async def upsert(self, phone: str, stage: str, data_json: str) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO leads (phone, stage, data_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
            stage=excluded.stage, data_json=excluded.data_json, updated_at=CURRENT_TIMESTAMP""",
            (phone, stage, data_json),
        )
        await conn.commit()
