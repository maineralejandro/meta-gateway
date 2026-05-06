import json
import re
from pathlib import Path
from typing import Any, ClassVar

import structlog

from core.capabilities.base import BaseCapability

logger = structlog.get_logger()

MENU_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "menu.json"

DEFAULT_MENU_ITEMS: dict[str, dict[str, Any]] = {
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


def _load_menu_from_file() -> dict[str, dict[str, Any]]:
    try:
        with open(MENU_CONFIG_PATH) as f:
            data = json.load(f)
        validated: dict[str, dict[str, Any]] = {}
        for key, item in data.items():
            if "name" in item and "price" in item:
                validated[key] = {"name": item["name"], "price": int(item["price"])}
        if validated:
            return validated
        logger.warning("menu_json_empty", path=str(MENU_CONFIG_PATH))
    except FileNotFoundError:
        logger.info("menu_json_not_found", path=str(MENU_CONFIG_PATH))
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("menu_json_parse_error", path=str(MENU_CONFIG_PATH), error=str(e))
    return DEFAULT_MENU_ITEMS


MENU_ITEMS: dict[str, dict[str, Any]] = _load_menu_from_file()

ORDER_TAG_RE = re.compile(r"\[ORDER_ADD:([a-z_0-9]+):(\d+)\]")
ORDER_CLEAR_RE = re.compile(r"\[ORDER_CLEAR\]")
ORDER_REMOVE_RE = re.compile(r"\[ORDER_REMOVE:([a-z_0-9]+)(?::(\d+))?\]")


class OrderCapability(BaseCapability):
    name = "order"
    description = "Order management with menu items and cart tracking"
    tag_patterns: ClassVar[dict[str, re.Pattern[str]]] = {
        "ORDER_ADD": ORDER_TAG_RE,
        "ORDER_REMOVE": ORDER_REMOVE_RE,
        "ORDER_CLEAR": ORDER_CLEAR_RE,
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._orders: dict[str, dict[str, Any]] = {}
        self._loaded_phones: set[str] = set()
        self._menu: dict[str, dict[str, Any]] = MENU_ITEMS

    def get_menu(self) -> dict[str, dict[str, Any]]:
        return dict(self._menu)

    async def reload_menu_from_db(self) -> None:
        try:
            from db.database import get_db
            db = await get_db()
            rows = await db.load_menu_items()
            if rows:
                self._menu = {}
                for row in rows:
                    if row["is_available"]:
                        self._menu[row["key"]] = {"name": row["name"], "price": row["price"]}
                logger.info("menu_reloaded_from_db", item_count=len(self._menu))
        except Exception as e:
            logger.error("menu_reload_error", error=str(e))

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
        except Exception as e:
            logger.error("order_load_error", phone=phone, error=str(e))
        self._loaded_phones.add(phone)

    async def _persist(self, phone: str) -> None:
        order = self._orders.get(phone)
        try:
            from db.database import get_db
            db = await get_db()
            if order and order["items"]:
                await db.save_order(phone, json.dumps(order["items"]), order["total"])
            else:
                await db.delete_order(phone)
        except Exception as e:
            logger.error("order_persist_error", phone=phone, error=str(e))
            self._orders.pop(phone, None)
            self._loaded_phones.discard(phone)

    async def get_order(self, phone: str) -> dict[str, Any]:
        await self._ensure_loaded(phone)
        return self._orders.get(phone, {"items": [], "total": 0})

    async def add_item(self, phone: str, item_key: str, quantity: int = 1) -> None:
        await self._ensure_loaded(phone)
        if phone not in self._orders:
            self._orders[phone] = {"items": [], "total": 0}
        order = self._orders[phone]
        menu_item = self._menu.get(item_key)
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

    def _recalc_total(self, phone: str) -> None:
        order = self._orders.get(phone)
        if not order:
            return
        order["total"] = sum(item["price"] * item["quantity"] for item in order["items"])

    async def format_for_context(self, phone: str, config: dict[str, Any]) -> str | None:
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

    async def parse_tags(self, phone: str, text: str, config: dict[str, Any]) -> str:
        for match in ORDER_TAG_RE.finditer(text):
            key, qty = match.group(1), int(match.group(2))
            await self.add_item(phone, key, qty)

        for match in ORDER_REMOVE_RE.finditer(text):
            key = match.group(1)
            qty_str = match.group(2)
            remove_qty: int | None = int(qty_str) if qty_str is not None else None
            await self.remove_item(phone, key, remove_qty)

        if ORDER_CLEAR_RE.search(text):
            await self.clear(phone, config)

        cleaned = ORDER_TAG_RE.sub("", text)
        cleaned = ORDER_REMOVE_RE.sub("", cleaned)
        cleaned = ORDER_CLEAR_RE.sub("", cleaned)
        return cleaned.strip()

    async def clear(self, phone: str, config: dict[str, Any]) -> None:
        try:
            from db.database import get_db
            db = await get_db()
            await db.delete_order(phone)
        except Exception as e:
            logger.error("order_clear_error", phone=phone, error=str(e))
            return
        self._orders.pop(phone, None)
        self._loaded_phones.discard(phone)

    def get_prompt_instructions(self, config: dict[str, Any]) -> str:
        items_list = ", ".join(self._menu.keys())
        return (
            "GESTIÓN DE PEDIDOS (OBLIGATORIO):\n"
            "Cuando el cliente agregue un item al pedido, incluye al final de tu respuesta"
            " un tag oculto con el formato: [ORDER_ADD:clave:cantidad]\n"
            f"Claves válidas: {items_list}\n\n"
            "Ejemplos:\n"
            '- "3 vienesas gigantes italianas" → [ORDER_ADD:completo_vienesa_gigante:3]\n'
            '- "2 papas fritas medianas" → [ORDER_ADD:papas_mediana:2]\n'
            '- "una coca cola de 1.5 litros" → [ORDER_ADD:coca_1_5l:1]\n\n'
            "Si el cliente quita un item: [ORDER_REMOVE:clave] o [ORDER_REMOVE:clave:cantidad]\n"
            "Si el cliente quiere empezar de cero: [ORDER_CLEAR]\n\n"
            "Los tags NO son visibles para el cliente. Escríbelos SIEMPRE al final de tu"
            " respuesta cuando agregues items.\n\n"
            "IMPORTANTE: Solo incluye tags [ORDER_ADD], [ORDER_REMOVE] o [ORDER_CLEAR]"
            " cuando el cliente haya explícitamente agregado, quitado o limpiado items."
            " NUNCA incluyas estos tags en saludos, despedidas o respuestas donde no se"
            " modifique el pedido."
        )
