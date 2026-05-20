from __future__ import annotations

from typing import Any

import asyncpg

from db.engine import get_pool


class BaseRepository:
    def __init__(self, get_pool_fn: Any = get_pool) -> None:
        self._get_pool = get_pool_fn

    async def _execute(self, query: str, *args: Any) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(query, *args)

    async def _fetchone(self, query: str, *args: Any) -> asyncpg.Record | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def _fetchall(self, query: str, *args: Any) -> list[asyncpg.Record]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)  # type: ignore[no-any-return]

    async def _execute_and_commit(self, query: str, *args: Any) -> None:
        await self._execute(query, *args)

    async def _insert_returning_id(self, query: str, *args: Any) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            if row is None:
                raise RuntimeError("INSERT RETURNING id returned no row")
            return row["id"]  # type: ignore[no-any-return]

    async def _execute_transaction(self, operations: list[tuple[str, tuple[Any, ...]]]) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn, conn.transaction():
            for query, args in operations:
                await conn.execute(query, *args)
