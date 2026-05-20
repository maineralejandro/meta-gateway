from __future__ import annotations

import asyncpg
import structlog

from core.config import settings

logger = structlog.get_logger()

_pool: asyncpg.Pool | None = None


async def create_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=settings.DB_POOL_MIN,
        max_size=settings.DB_POOL_MAX,
        ssl=None,
    )
    logger.info("pg_pool_created", dsn=settings.DATABASE_URL.split("@")[-1], min=settings.DB_POOL_MIN, max=settings.DB_POOL_MAX)
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        return await create_pool()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("pg_pool_closed")
