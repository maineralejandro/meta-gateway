from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import aiosqlite


class BaseRepository:
    def __init__(self, get_conn: Any) -> None:
        self._get_conn = get_conn

    async def _execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        conn = await self._get_conn()
        await conn.execute(query, params)

    async def _fetchone(self, query: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        conn = await self._get_conn()
        cursor = await conn.execute(query, params)
        return cast("aiosqlite.Row | None", await cursor.fetchone())

    async def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        conn = await self._get_conn()
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return list(rows)

    async def _commit(self) -> None:
        conn = await self._get_conn()
        await conn.commit()

    async def _execute_and_commit(self, query: str, params: tuple[Any, ...] = ()) -> None:
        await self._execute(query, params)
        await self._commit()

    async def _insert_returning_id(self, query: str, params: tuple[Any, ...]) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(query, params)
        await conn.commit()
        assert cursor.lastrowid is not None
        return cast(int, cursor.lastrowid)

    async def _execute_transaction(self, operations: list[tuple[str, tuple[Any, ...]]]) -> None:
        conn = await self._get_conn()
        try:
            await conn.execute("BEGIN")
            for query, params in operations:
                await conn.execute(query, params)
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise
