from typing import Any

from core.capabilities.base import BaseCapability
from core.capabilities.order import (
    OrderCapability,
)


class _CompatAdapter(BaseCapability):
    name = "order"

    def __init__(self) -> None:
        object.__setattr__(self, "_impl", OrderCapability())
        super().__init__(config={})

    _impl: OrderCapability

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") and name != "_impl" and hasattr(self, "_impl") and hasattr(self._impl, name):
            setattr(self._impl, name, value)
        else:
            super().__setattr__(name, value)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") and hasattr(self, "_impl"):
            return getattr(self._impl, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    async def format_for_context(self, phone: str, config: dict[str, Any] | None = None) -> str | None:
        return await self._impl.format_for_context(phone, config or {})

    async def parse_tags(self, phone: str, text: str, config: dict[str, Any] | None = None) -> str:
        return await self._impl.parse_tags(phone, text, config or {})

    async def clear(self, phone: str, config: dict[str, Any] | None = None) -> None:
        return await self._impl.clear(phone, config or {})

    def get_prompt_instructions(self, config: dict[str, Any] | None = None) -> str:
        return self._impl.get_prompt_instructions(config or {})

    async def get_order(self, phone: str) -> dict[str, Any]:
        return await self._impl.get_order(phone)

    async def add_item(self, phone: str, item_key: str, quantity: int = 1) -> None:
        return await self._impl.add_item(phone, item_key, quantity)

    async def remove_item(self, phone: str, item_key: str, quantity: int | None = None) -> None:
        return await self._impl.remove_item(phone, item_key, quantity)

    async def reload_menu_from_db(self) -> None:
        return await self._impl.reload_menu_from_db()

    def get_menu(self) -> dict[str, dict[str, Any]]:
        return self._impl.get_menu()


class OrderState(_CompatAdapter):
    pass


order_state = OrderState()
