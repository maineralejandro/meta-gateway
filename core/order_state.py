import json
import re
from typing import Any

import structlog

logger = structlog.get_logger()

MENU_ITEMS = {
    "completo_normal": {"name": "Completo Normal (carne)", "price": 3700},
    "completo_gigante": {"name": "Completo Gigante (carne)", "price": 4800},
    "completo_italiano": {"name": "Completo Italiano", "price": 3700},
    "completo_vienesa": {"name": "Completo Vienesa", "price": 3200},
    "completo_vienesa_gigante": {"name": "Vienesa Gigante Italiana", "price": 3400},
    "completo_vienesa_vegano": {"name": "Completo Vienesa Vegano", "price": 4000},
    "completo_vienesa_vegano_gigante": {"name": "Vienesa Vegana Gigante", "price": 4800},
    "as_normal": {"name": "AS Normal", "price": 3700},
    "as_gigante": {"name": "AS Gigante", "price": 4800},
    "chorrillana": {"name": "Chorrillana", "price": 8900},
    "salchipapas_individual": {"name": "Salchipapas Individual", "price": 2800},
    "salchipapas_mediana": {"name": "Salchipapas Mediana", "price": 5100},
    "papas_individual": {"name": "Papas Fritas Individual", "price": 2100},
    "papas_mediana": {"name": "Papas Fritas Mediana", "price": 3700},
    "coca_lata": {"name": "Coca Cola lata", "price": 1500},
    "coca_1_5l": {"name": "Coca Cola 1.5 Lts", "price": 3000},
    "sprite_lata": {"name": "Sprite lata", "price": 1500},
    "fanta_lata": {"name": "Fanta lata", "price": 1500},
    "agua": {"name": "Agua mineral", "price": 1200},
}

ORDER_TAG_RE = re.compile(r"\[ORDER_ADD:([a-z_0-9]+):(\d+)\]")
ORDER_CLEAR_RE = re.compile(r"\[ORDER_CLEAR\]")
ORDER_REMOVE_RE = re.compile(r"\[ORDER_REMOVE:([a-z_0-9]+)(?::(\d+))?\]")


class OrderState:
    def __init__(self) -> None:
        self._orders: dict[str, dict[str, Any]] = {}
        self._loaded_phones: set[str] = set()

    async def _ensure_loaded(self, phone: str) -> None:
        if phone in self._loaded_phones:
            return
        try:
            from db.database import get_db
            db = await get_db()
            row = await db.load_order(phone)
            if row:
                items_json, total = row
                try:
                    items = json.loads(items_json)
                    self._orders[phone] = {"items": items, "total": total}
                except (json.JSONDecodeError, TypeError):
                    logger.warning("order_load_corrupt", phone=phone)
        except Exception:
            pass
        self._loaded_phones.add(phone)

    async def _persist(self, phone: str) -> None:
        try:
            from db.database import get_db
            db = await get_db()
            order = self._orders.get(phone)
            if order and order["items"]:
                await db.save_order(phone, json.dumps(order["items"]), order["total"])
            else:
                await db.delete_order(phone)
        except Exception:
            pass

    async def get_order(self, phone: str) -> dict[str, Any]:
        await self._ensure_loaded(phone)
        return self._orders.get(phone, {"items": [], "total": 0})

    async def add_item(self, phone: str, item_key: str, quantity: int = 1) -> None:
        await self._ensure_loaded(phone)
        if phone not in self._orders:
            self._orders[phone] = {"items": [], "total": 0}
        order = self._orders[phone]
        menu_item = MENU_ITEMS.get(item_key)
        if not menu_item:
            logger.warning("order_add_unknown_item", phone=phone, key=item_key)
            return
        for existing in order["items"]:
            if existing["key"] == item_key:
                existing["quantity"] += quantity
                break
        else:
            order["items"].append({
                "key": item_key,
                "name": menu_item["name"],
                "price": menu_item["price"],
                "quantity": quantity,
            })
        self._recalc_total(phone)
        await self._persist(phone)
        logger.info("order_item_added", phone=phone, key=item_key, qty=quantity)

    async def remove_item(self, phone: str, item_key: str, quantity: int | None = None) -> None:
        await self._ensure_loaded(phone)
        order = self._orders.get(phone)
        if not order:
            return
        for i, existing in enumerate(order["items"]):
            if existing["key"] == item_key:
                if quantity is None or existing["quantity"] <= quantity:
                    order["items"].pop(i)
                else:
                    existing["quantity"] -= quantity
                break
        self._recalc_total(phone)
        await self._persist(phone)

    async def clear(self, phone: str) -> None:
        self._orders.pop(phone, None)
        self._loaded_phones.discard(phone)
        try:
            from db.database import get_db
            db = await get_db()
            await db.delete_order(phone)
        except Exception:
            pass

    def _recalc_total(self, phone: str) -> None:
        order = self._orders.get(phone)
        if not order:
            return
        order["total"] = sum(item["price"] * item["quantity"] for item in order["items"])

    async def format_for_context(self, phone: str) -> str | None:
        await self._ensure_loaded(phone)
        order = self._orders.get(phone)
        if not order or not order["items"]:
            return None
        lines = ["Pedido actual del cliente:"]
        for item in order["items"]:
            subtotal = item["price"] * item["quantity"]
            lines.append(
                f"- {item['quantity']}x {item['name']} (${item['price']:,} c/u) = ${subtotal:,}"
            )
        lines.append(f"Total: ${order['total']:,}")
        return "\n".join(lines)

    async def parse_tags(self, phone: str, text: str) -> str:
        for match in ORDER_TAG_RE.finditer(text):
            key, qty = match.group(1), int(match.group(2))
            await self.add_item(phone, key, qty)

        for match in ORDER_REMOVE_RE.finditer(text):
            key = match.group(1)
            qty_str = match.group(2)
            remove_qty: int | None = int(qty_str) if qty_str is not None else None
            await self.remove_item(phone, key, remove_qty)

        if ORDER_CLEAR_RE.search(text):
            await self.clear(phone)

        cleaned = ORDER_TAG_RE.sub("", text)
        cleaned = ORDER_REMOVE_RE.sub("", cleaned)
        cleaned = ORDER_CLEAR_RE.sub("", cleaned)
        return cleaned.strip()


order_state = OrderState()
