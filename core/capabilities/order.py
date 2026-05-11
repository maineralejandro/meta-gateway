import contextlib
import json
import re
from pathlib import Path
from typing import Any, ClassVar

import structlog

from core.capabilities.base import BaseCapability
from core.capabilities.menu_search import SEARCH_THRESHOLD, MenuSearch

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
                entry: dict[str, Any] = {"name": item["name"], "price": int(item["price"])}
                for field in ("category", "description", "size", "protein", "conditions"):
                    if item.get(field):
                        entry[field] = item[field]
                if "tags" in item and isinstance(item["tags"], list):
                    entry["tags"] = item["tags"]
                validated[key] = entry
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

_FLAT_TOOLS: ClassVar[set[str]] = {"order_add", "order_remove", "order_clear", "order_get_menu"}
_SEARCH_TOOLS: ClassVar[set[str]] = {
    "order_add", "order_remove", "order_clear",
    "order_search_item", "order_get_categories", "order_get_menu",
}

_SEARCH_ADD_DESCRIPTION = (
    "Llama esta funcion UNICAMENTE cuando el cliente haya confirmado "
    "explicitamente que quiere agregar un producto a su pedido. "
    "NO la llames si el cliente solo pregunta por precio o disponibilidad. "
    "Ejemplos de cuando llamarla: 'quiero 2 completos', 'agregame una bebida', "
    "'si, eso quiero', 'uno de cada uno' (llama una vez por cada producto mencionado). "
    "Ejemplos de cuando NO llamarla: 'tienen completos?', 'cuanto cuesta?'. "
    "Correferencia: si el cliente dice 'uno de cada uno', 'eso mismo', 'lo mismo', "
    "'todos esos', resuelve a que productos se refiere por el contexto de la conversacion "
    "y llama esta funcion por cada uno con su item_key y qty=1. "
    "IMPORTANTE: el item_key DEBE venir exactamente de los resultados de order_search_item "
    "o order_get_menu. NUNCA inventes ni adivines un item_key."
)


class OrderCapability(BaseCapability):
    name = "order"
    description = "Order management with menu items and cart tracking"
    tag_patterns: ClassVar[dict[str, re.Pattern[str]]] = {
        "ORDER_ADD": ORDER_TAG_RE,
        "ORDER_REMOVE": ORDER_REMOVE_RE,
        "ORDER_CLEAR": ORDER_CLEAR_RE,
    }
    PARALLEL_SAFE_TOOLS: ClassVar[set[str]] = {"order_get_menu", "order_search_item", "order_get_categories"}
    SEQUENTIAL_TOOLS: ClassVar[set[str]] = {"order_add", "order_remove", "order_clear"}

    _BASE_ADD_DESCRIPTION = (
        "Llama esta funcion UNICAMENTE cuando el cliente haya confirmado "
        "explicitamente que quiere agregar un producto a su pedido. "
        "NO la llames si el cliente solo pregunta por precio o disponibilidad. "
        "Ejemplos de cuando llamarla: 'quiero 2 completos', 'agregame una bebida', "
        "'si, eso quiero', 'uno de cada uno' (llama una vez por cada producto mencionado). "
        "Ejemplos de cuando NO llamarla: 'tienen completos?', 'cuanto cuesta?'. "
        "Correferencia: si el cliente dice 'uno de cada uno', 'eso mismo', 'lo mismo', "
        "'todos esos', resuelve a que productos se refiere por el contexto de la conversacion "
        "y llama esta funcion por cada uno con su item_key y qty=1."
    )
    _BASE_REMOVE_DESCRIPTION = (
        "Llama esta funcion cuando el cliente quiera quitar o reducir "
        "un producto de su pedido actual. Solo funciona con productos "
        "que ya estan en el pedido."
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._orders: dict[str, dict[str, Any]] = {}
        self._loaded_phones: set[str] = set()
        self._menu: dict[str, dict[str, Any]] = MENU_ITEMS
        self._menu_search: MenuSearch | None = None

    async def on_resolve(self) -> None:
        await self.reload_menu_from_db()

    @property
    def _search(self) -> MenuSearch:
        if self._menu_search is None:
            self._menu_search = MenuSearch(self._menu)
            self._menu_search.build_index()
        return self._menu_search

    @property
    def needs_search(self) -> bool:
        return len(self._menu) > SEARCH_THRESHOLD

    def get_menu(self) -> dict[str, dict[str, Any]]:
        return dict(self._menu)

    def _rebuild_search(self) -> None:
        self._menu_search = None

    async def reload_menu_from_db(self) -> None:
        try:
            from db.database import get_db
            db = await get_db()
            rows = await db.load_menu_items()
            if rows:
                loaded: dict[str, dict[str, Any]] = {}
                for row in rows:
                    if row["is_available"]:
                        entry: dict[str, Any] = {"name": row["name"], "price": row["price"]}
                        for field in ("category", "description", "size", "protein", "conditions"):
                            val = row.get(field)
                            if val:
                                entry[field] = val
                        tags_raw = row.get("tags")
                        if tags_raw:
                            if isinstance(tags_raw, str):
                                with contextlib.suppress(json.JSONDecodeError, TypeError):
                                    entry["tags"] = json.loads(tags_raw)
                            elif isinstance(tags_raw, list):
                                entry["tags"] = tags_raw
                        loaded[row["key"]] = entry
                if loaded:
                    self._menu = loaded
                    self._rebuild_search()
                    logger.info("menu_reloaded_from_db", item_count=len(self._menu))
                    return
            logger.info("menu_db_empty_using_file", path=str(MENU_CONFIG_PATH))
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

    def _order_state_dict(self, phone: str) -> dict[str, Any]:
        order = self._orders.get(phone, {"items": [], "total": 0})
        return {
            "items": [
                {"key": i["key"], "name": i["name"], "qty": i["quantity"], "price": i["price"]}
                for i in order.get("items", [])
            ],
            "total": order.get("total", 0),
        }

    def _order_summary(self, phone: str) -> str:
        order = self._orders.get(phone)
        if not order or not order.get("items"):
            return "Pedido vacio"
        parts = []
        for item in order["items"]:
            subtotal = item["price"] * item["quantity"]
            parts.append(f"{item['quantity']}x {item['name']} (${item['price']:,} c/u) = ${subtotal:,}")
        parts.append(f"Total: ${order['total']:,}")
        return " | ".join(parts)

    def get_tool_definitions(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        if self.needs_search:
            return self._search_mode_definitions()
        return self._flat_mode_definitions()

    def _flat_mode_definitions(self) -> list[dict[str, Any]]:
        valid_keys = sorted(self._menu.keys())
        item_key_prop: dict[str, Any] = {
            "type": "string",
            "description": "Clave canonica del item del menu",
        }
        if valid_keys:
            item_key_prop["enum"] = valid_keys
        return [
            {
                "type": "function",
                "function": {
                    "name": "order_add",
                    "description": self._BASE_ADD_DESCRIPTION,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_key": item_key_prop,
                            "qty": {"type": "integer", "description": "Cantidad a agregar", "minimum": 1},
                        },
                        "required": ["item_key", "qty"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "order_remove",
                    "description": self._BASE_REMOVE_DESCRIPTION,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_key": item_key_prop,
                            "qty": {"type": "integer", "description": "Cantidad a quitar. Si se omite, quita todo."},
                        },
                        "required": ["item_key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "order_clear",
                    "description": (
                        "Llama esta funcion cuando el cliente quiera cancelar o vaciar "
                        "su pedido completo. Ejemplos: 'cancela todo', 'limpia mi pedido', "
                        "'borra el pedido', 'vacia el carrito', 'quiero empezar de nuevo'. "
                        "NO la uses si el cliente solo quiere quitar un item (usa order_remove). "
                        "NO pidas confirmacion si la intencion del cliente es clara."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "order_get_menu",
                    "description": "Obtener el menu disponible con nombres, claves y precios. Usar cuando el cliente pregunta por productos o precios.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def _search_mode_definitions(self) -> list[dict[str, Any]]:
        item_key_prop: dict[str, Any] = {
            "type": "string",
            "description": (
                "Clave canonica del item. DEBE ser obtenida de order_search_item "
                "o order_get_menu. NUNCA inventes un valor."
            ),
        }
        return [
            {
                "type": "function",
                "function": {
                    "name": "order_search_item",
                    "description": (
                        "Busca items del menu por nombre o descripcion. "
                        "Usa esta herramienta ANTES de order_add para encontrar el item_key exacto. "
                        "Ejemplos: 'chorrillana beatles', 'mojito tradicional', 'pizza pollo'. "
                        "Devuelve hasta 5 resultados con item_key, nombre, precio y descripcion."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Termino de busqueda (nombre, ingrediente, categoria)"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "order_get_categories",
                    "description": (
                        "Obtiene las categorias del menu con cantidad de items y precio minimo. "
                        "Usa esta herramienta cuando el cliente pregunte que tipos de productos hay "
                        "o quiera explorar el menu por categorias."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "order_get_menu",
                    "description": (
                        "Obtiene items del menu. Si se especifica categoria, devuelve solo esa categoria. "
                        "Si no, devuelve hasta 30 items de las categorias mas populares. "
                        "Usa order_get_categories primero para ver las categorias disponibles."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "description": "Categoria especifica (de order_get_categories). Omitir para menu general.",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "order_add",
                    "description": _SEARCH_ADD_DESCRIPTION,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_key": item_key_prop,
                            "qty": {"type": "integer", "description": "Cantidad a agregar", "minimum": 1},
                        },
                        "required": ["item_key", "qty"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "order_remove",
                    "description": self._BASE_REMOVE_DESCRIPTION,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_key": item_key_prop,
                            "qty": {"type": "integer", "description": "Cantidad a quitar. Si se omite, quita todo."},
                        },
                        "required": ["item_key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "order_clear",
                    "description": (
                        "Llama esta funcion cuando el cliente quiera cancelar o vaciar "
                        "su pedido completo. Ejemplos: 'cancela todo', 'limpia mi pedido', "
                        "'borra el pedido', 'vacia el carrito', 'quiero empezar de nuevo'. "
                        "NO la uses si el cliente solo quiere quitar un item (usa order_remove). "
                        "NO pidas confirmacion si la intencion del cliente es clara."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def get_tool_names(self) -> set[str]:
        return _SEARCH_TOOLS if self.needs_search else _FLAT_TOOLS

    async def execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        phone: str,
        tool_call_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        if name == "order_add":
            return await self._execute_add(args, phone)
        if name == "order_remove":
            return await self._execute_remove(args, phone)
        if name == "order_clear":
            return await self._execute_clear(phone)
        if name == "order_get_menu":
            return self._execute_get_menu(args)
        if name == "order_search_item":
            return self._execute_search_item(args)
        if name == "order_get_categories":
            return self._execute_get_categories()
        return {"success": False, "error": f"Unknown tool: {name}"}

    async def _execute_add(self, args: dict[str, Any], phone: str) -> dict[str, Any]:
        item_key = args.get("item_key", "")
        qty = args.get("qty", 1)
        try:
            qty = int(qty)
        except (ValueError, TypeError):
            return {"success": False, "error": f"qty must be a positive integer, got {qty!r}", "instruction": "Provide a valid quantity >= 1."}
        if qty < 1:
            return {"success": False, "error": f"qty must be >= 1, got {qty}", "instruction": "Provide a valid quantity >= 1."}
        if item_key not in self._menu:
            instruction = (
                "Usa order_search_item para encontrar el item_key correcto. "
                "NUNCA inventes un item_key."
            ) if self.needs_search else "Usa una de las claves validas listadas arriba."
            result: dict[str, Any] = {
                "success": False,
                "error": f"item_key '{item_key}' not found",
                "instruction": instruction,
            }
            if not self.needs_search:
                result["valid_keys"] = sorted(self._menu.keys())
            return result
        await self.add_item(phone, item_key, qty)
        return {
            "success": True,
            "action": "item_added",
            "item": item_key,
            "qty_added": qty,
            "order_state": self._order_state_dict(phone),
            "order_summary": self._order_summary(phone),
        }

    async def _execute_remove(self, args: dict[str, Any], phone: str) -> dict[str, Any]:
        item_key = args.get("item_key", "")
        qty = args.get("qty")
        if item_key not in self._menu:
            return {
                "success": False,
                "error": f"item_key '{item_key}' not found",
                "valid_keys": sorted(self._menu.keys()),
                "instruction": "Usa una de las claves validas listadas arriba.",
            }
        remove_qty: int | None = None
        if qty is not None:
            try:
                remove_qty = int(qty)
                if remove_qty < 1:
                    remove_qty = None
            except (ValueError, TypeError):
                remove_qty = None
        await self.remove_item(phone, item_key, remove_qty)
        return {
            "success": True,
            "action": "item_removed",
            "item": item_key,
            "qty_removed": remove_qty,
            "order_state": self._order_state_dict(phone),
            "order_summary": self._order_summary(phone),
        }

    async def _execute_clear(self, phone: str) -> dict[str, Any]:
        await self.clear(phone, {})
        return {
            "success": True,
            "action": "order_cleared",
            "order_state": {"items": [], "total": 0},
            "order_summary": "Pedido vacio",
        }

    def _execute_get_menu(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        if args is None:
            args = {}
        category = args.get("category")
        if self.needs_search and category:
            items = self._search.get_items_by_category(category)
            return {"success": True, "action": "get_menu", "category": category, "menu": items}
        if self.needs_search:
            categories = self._search.get_categories()
            items: list[dict[str, Any]] = []
            for cat in categories[:5]:
                items.extend(self._search.get_items_by_category(cat["key"])[:6])
            return {"success": True, "action": "get_menu", "menu": items[:30], "categories": categories}
        flat_items = []
        for key, info in sorted(self._menu.items()):
            flat_items.append({"key": key, "name": info["name"], "price": info["price"]})
        return {"success": True, "action": "get_menu", "menu": flat_items}

    def _execute_search_item(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query", "")
        if not query:
            return {"success": False, "error": "query is required", "instruction": "Proporciona un termino de busqueda."}
        results = self._search.search(query)
        return {"success": True, "action": "search_item", "query": query, "results": results}

    def _execute_get_categories(self) -> dict[str, Any]:
        categories = self._search.get_categories()
        return {"success": True, "action": "get_categories", "categories": categories}

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
        lines: list[str] = []
        if self.needs_search:
            lines.append("Menu grande: usa order_search_item para buscar productos o order_get_categories para ver categorias.")
        else:
            menu_lines = ["Menu disponible (usa estas claves exactas en item_key):"]
            for key, info in sorted(self._menu.items()):
                menu_lines.append(f"- {key}: {info['name']} (${info['price']:,})")
            lines.append("\n".join(menu_lines))
        order = self._orders.get(phone)
        if order and order["items"]:
            lines.append("")
            lines.append("Pedido actual del cliente:")
            for item in order["items"]:
                subtotal = item["price"] * item["quantity"]
                lines.append(
                    f"- {item['quantity']}x {item['name']} (${item['price']:,} c/u) = ${subtotal:,}"
                )
            lines.append(f"Total: ${order['total']:,}")
        elif not self.needs_search:
            lines.append("")
            lines.append("Pedido actual del cliente: vacio")
        else:
            lines.append("")
            lines.append("Pedido actual del cliente: vacio")
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
