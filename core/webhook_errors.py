import asyncio
import json

import asyncpg

from core.errors import InfraError, PersistError


def webhook_status_for_error(exc: Exception) -> int:
    if isinstance(exc, InfraError):
        return 503
    if isinstance(exc, PersistError):
        return 200
    if isinstance(exc, (ValueError, KeyError, json.JSONDecodeError)):
        return 200
    if isinstance(exc, asyncpg.PostgresConnectionError):
        return 503
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return 503
    if isinstance(exc, asyncpg.PostgresError):
        return 503
    if isinstance(exc, ConnectionError):
        return 503
    return 500
