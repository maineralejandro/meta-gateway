from typing import Any

from fastapi import APIRouter

from core.capabilities.base import registry

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


@router.get("")
async def list_capabilities() -> list[dict[str, Any]]:
    return registry.list_available_detailed()
