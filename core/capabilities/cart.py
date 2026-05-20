import contextlib
import json
from datetime import datetime
from typing import Any, ClassVar

import structlog

from core.capabilities.base import BaseCapability
from core.capabilities.catalog_search import SEARCH_THRESHOLD, CatalogSearch
from core.utils import slugify

logger = structlog.get_logger()


_FLAT_TOOLS: set[str] = {"cart_add", "cart_remove", "cart_clear", "catalog_list"}
_SEARCH_TOOLS: set[str] = {
    "cart_add", "cart_remove", "cart_clear",
    "catalog_search", "catalog_categories", "catalog_list",
}

_SEARCH_ADD_DESCRIPTION = (
    "Llama esta funcion UNICAMENTE cuando el cliente haya confirmado "
    "explicitamente que quiere agregar un producto a su carrito. "
    "NO la llames si el cliente solo pregunta por precio o disponibilidad. "
    "Ejemplos de cuando llamarla: 'quiero 2 del item_a', 'agregame un item_b', "
    "'si, eso quiero', 'uno de cada uno' (llama una vez por cada producto mencionado). "
    "Ejemplos de cuando NO llamarla: 'tienen item_a?', 'cuanto cuesta?'. "
    "Correferencia: si el cliente dice 'uno de cada uno', 'eso mismo', 'lo mismo', "
    "'todos esos', resuelve a que productos se refiere por el contexto de la conversacion "
    "y llama esta funcion por cada uno con su item_key y qty=1. "
    "IMPORTANTE: el item_key DEBE venir exactamente de los resultados de catalog_search "
    "o catalog_list. NUNCA inventes ni adivines un item_key."
)


class CartCapability(BaseCapability):
    name = "cart"
    description = "Cart management with catalog items and cart tracking"
    PARALLEL_SAFE_TOOLS: ClassVar[set[str]] = {"catalog_list", "catalog_search", "catalog_categories"}
    SEQUENTIAL_TOOLS: ClassVar[set[str]] = {"cart_add", "cart_remove", "cart_clear"}

    _BASE_ADD_DESCRIPTION = (
        "Llama esta funcion UNICAMENTE cuando el cliente haya confirmado "
        "explicitamente que quiere agregar un producto a su carrito. "
        "NO la llames si el cliente solo pregunta por precio o disponibilidad. "
        "Ejemplos de cuando llamarla: 'quiero 2 del item_a', 'agregame un item_b', "
        "'si, eso quiero', 'uno de cada uno' (llama una vez por cada producto mencionado). "
        "Ejemplos de cuando NO llamarla: 'tienen item_a?', 'cuanto cuesta?'. "
        "Correferencia: si el cliente dice 'uno de cada uno', 'eso mismo', 'lo mismo', "
        "'todos esos', resuelve a que productos se refiere por el contexto de la conversacion "
        "y llama esta funcion por cada uno con su item_key y qty=1."
    )
    _BASE_REMOVE_DESCRIPTION = (
        "Llama esta funcion cuando el cliente quiera quitar o reducir "
        "un producto de su carrito actual. Solo funciona con productos "
        "que ya estan en el carrito."
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._carts: dict[str, dict[str, Any]] = {}
        self._loaded_phones: set[str] = set()
        self._catalog: dict[str, dict[str, Any]] = {}
        self._options: dict[str, dict[str, Any]] = {}
        self._promotions: list[dict[str, Any]] = []
        self._catalog_search: CatalogSearch | None = None

    async def on_resolve(self) -> None:
        await self.reload_catalog_from_db()

    @property
    def _search(self) -> CatalogSearch:
        if self._catalog_search is None:
            self._catalog_search = CatalogSearch(self._catalog)
            self._catalog_search.build_index()
        return self._catalog_search

    @property
    def needs_search(self) -> bool:
        return len(self._catalog) > SEARCH_THRESHOLD

    def get_catalog(self) -> dict[str, dict[str, Any]]:
        return dict(self._catalog)

    def _rebuild_search(self) -> None:
        self._catalog_search = None

    async def reload_catalog_from_db(self) -> None:
        try:
            from db.database import get_db
            db = await get_db()
            rows = await db.load_catalog_items()
            if not rows:
                logger.warning("catalog_db_empty")
                self._catalog = {}
                self._options = {}
                self._promotions = []
                self._rebuild_search()
                return

            variants = await db.load_catalog_variants()
            variants_by_item: dict[str, list[dict[str, Any]]] = {}
            for v in variants:
                variants_by_item.setdefault(v["item_key"], []).append(v)

            loaded: dict[str, dict[str, Any]] = {}
            for row in rows:
                if not row["is_available"]:
                    continue
                key = row["key"]
                item_variants = variants_by_item.get(key, [])

                common_fields: dict[str, Any] = {}
                for field in ("description", "size", "specifications"):
                    val = row.get(field)
                    if val:
                        common_fields[field] = val
                tags_raw = row.get("tags")
                if tags_raw:
                    if isinstance(tags_raw, str):
                        with contextlib.suppress(json.JSONDecodeError, TypeError):
                            common_fields["tags"] = json.loads(tags_raw)
                    elif isinstance(tags_raw, list):
                        common_fields["tags"] = tags_raw
                category = row.get("category", "general") or "general"
                subcategory = row.get("subcategory", "") or ""
                common_fields["category"] = category
                common_fields["subcategory"] = subcategory

                if item_variants:
                    for v in item_variants:
                        v_slug = v.get("slug") or slugify(v["label"])
                        flat_key = f"{key}_{v_slug}"
                        entry: dict[str, Any] = {
                            "name": f"{row['name']} - {v['label']}",
                            "price": v["price"],
                            **common_fields,
                            "base_item_key": key,
                        }
                        loaded[flat_key] = entry
                else:
                    price = row.get("base_price") or row.get("price", 0)
                    entry = {
                        "name": row["name"],
                        "price": price,
                        **common_fields,
                    }
                    loaded[key] = entry

            if loaded:
                self._catalog = loaded
                self._rebuild_search()

            opt_rows = await db.load_catalog_options()
            self._options = {m["key"]: m for m in opt_rows}

            promo_rows = await db.load_promotions()
            self._promotions = []
            for p in promo_rows:
                promo_data = dict(p)
                promo_items = await db.load_promotion_items(p["key"])
                promo_data["items"] = [dict(pi) for pi in promo_items]
                valid_days = p.get("valid_days", "[]")
                if isinstance(valid_days, str):
                    with contextlib.suppress(json.JSONDecodeError, TypeError):
                        promo_data["valid_days"] = json.loads(valid_days)
                self._promotions.append(promo_data)

            logger.info(
                "catalog_reloaded_from_db",
                item_count=len(self._catalog),
                option_count=len(self._options),
                promotion_count=len(self._promotions),
            )
        except Exception as e:
            logger.error("catalog_reload_error", error=str(e))

    def _get_active_promotions(self) -> list[dict[str, Any]]:
        now = datetime.now()
        dow = now.isoweekday()
        t = now.strftime("%H:%M")
        active = []
        for promo in self._promotions:
            valid_days = promo.get("valid_days", [])
            if not isinstance(valid_days, list):
                continue
            if valid_days and dow not in valid_days:
                continue
            vf = promo.get("valid_from", "")
            vt = promo.get("valid_to", "")
            if vf and vt and not (vf <= t <= vt):
                continue
            active.append(promo)
        return active

    def _format_promotions_text(self, promos: list[dict[str, Any]]) -> str:
        lines = []
        for promo in promos:
            dt = promo.get("display_text", "")
            if dt:
                lines.append(f"- {dt}")
        return "\n".join(lines)

    def _format_options_text(self, category: str) -> str:
        mods = [m for m in self._options.values() if m.get("category_scope") == category]
        if not mods:
            return ""
        parts = []
        for m in mods:
            parts.append(f"{m['name']} ${m['price']:,}")
        return f"Opciones disponibles para {category}: {', '.join(parts)}"

    async def _ensure_loaded(self, phone: str) -> None:
        if phone in self._loaded_phones:
            return
        try:
            from db.database import get_db
            db = await get_db()
            row = await db.carts.load(phone)
            if row:
                items_json, total = row
                try:
                    items = json.loads(items_json)
                    self._carts[phone] = {"items": items, "total": total}
                except (json.JSONDecodeError, TypeError):
                    logger.warning("cart_load_corrupt", phone=phone)
        except Exception as e:
            logger.error("cart_load_error", phone=phone, error=str(e))
            self._loaded_phones.add(phone)

    async def _persist(self, phone: str) -> None:
        cart = self._carts.get(phone)
        try:
            from db.database import get_db
            db = await get_db()
            if cart and cart["items"]:
                await db.carts.save(phone, json.dumps(cart["items"]), cart["total"])
            else:
                await db.carts.delete(phone)
        except Exception as e:
            logger.error("cart_persist_error", phone=phone, error=str(e))
            self._carts.pop(phone, None)
            self._loaded_phones.discard(phone)

    async def get_cart(self, phone: str) -> dict[str, Any]:
        await self._ensure_loaded(phone)
        return self._carts.get(phone, {"items": [], "total": 0})

    def _cart_state_dict(self, phone: str) -> dict[str, Any]:
        cart = self._carts.get(phone, {"items": [], "total": 0})
        return {
            "items": [
                {"key": i["key"], "name": i["name"], "qty": i["quantity"], "price": i["price"]}
                for i in cart.get("items", [])
            ],
            "total": cart.get("total", 0),
        }

    def _cart_summary(self, phone: str) -> str:
        cart = self._carts.get(phone)
        if not cart or not cart.get("items"):
            return "Carrito vacio"
        parts = []
        for item in cart["items"]:
            subtotal = item["price"] * item["quantity"]
            parts.append(f"{item['quantity']}x {item['name']} (${item['price']:,} c/u) = ${subtotal:,}")
        parts.append(f"Total: ${cart['total']:,}")
        return " | ".join(parts)

    def get_tool_definitions(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        if self.needs_search:
            return self._search_mode_definitions()
        return self._flat_mode_definitions()

    def _flat_mode_definitions(self) -> list[dict[str, Any]]:
        valid_keys = sorted(self._catalog.keys())
        item_key_prop: dict[str, Any] = {
            "type": "string",
            "description": "Clave canonica del item del catalogo",
        }
        if valid_keys:
            item_key_prop["enum"] = valid_keys
        return [
            {
                "type": "function",
                "function": {
                    "name": "cart_add",
                    "description": self._BASE_ADD_DESCRIPTION,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_key": item_key_prop,
                            "qty": {"type": "integer", "description": "Cantidad a agregar", "minimum": 1},
                            "modifier_keys": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Claves de opciones/adicionales (ej: accesorios para esta categoria). Opcional.",
                            },
                        },
                        "required": ["item_key", "qty"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cart_remove",
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
                    "name": "cart_clear",
            "description": (
                "Llama esta funcion cuando el cliente quiera cancelar o vaciar "
                "su carrito completo. Ejemplos: 'cancela todo', 'limpia mi carrito', "
                "'borra el carrito', 'vacia el carrito', 'quiero empezar de nuevo'. "
                "NO la uses si el cliente solo quiere quitar un item (usa cart_remove). "
                "NO pidas confirmacion si la intencion del cliente es clara."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "catalog_list",
                    "description": "Obtener el catalogo disponible con nombres, claves y precios. Usar cuando el cliente pregunta por productos o precios.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def _search_mode_definitions(self) -> list[dict[str, Any]]:
        item_key_prop: dict[str, Any] = {
            "type": "string",
            "description": (
                "Clave canonica del item. DEBE ser obtenida de catalog_search "
                "o catalog_list. NUNCA inventes un valor."
            ),
        }
        return [
            {
                "type": "function",
                "function": {
                    "name": "catalog_search",
                    "description": (
                        "Busca items del catalogo por nombre o descripcion. "
                        "Usa esta herramienta ANTES de cart_add para encontrar el item_key exacto. "
                        "Ejemplos: 'producto A', 'categoria B', 'servicio C'. "
                        "Devuelve hasta 5 resultados con item_key, nombre, precio y descripcion."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Termino de busqueda (nombre, atributo, categoria)"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "catalog_categories",
                    "description": (
                        "Obtiene las categorias del catalogo con cantidad de items y precio minimo. "
                        "Usa esta herramienta cuando el cliente pregunte que tipos de productos hay "
                        "o quiera explorar el catalogo por categorias."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "catalog_list",
                    "description": (
                        "Obtiene items del catalogo. Si se especifica categoria, devuelve solo esa categoria. "
                        "Si no, devuelve hasta 30 items de las categorias mas populares. "
                        "Usa catalog_categories primero para ver las categorias disponibles."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "description": "Categoria especifica (de catalog_categories). Omitir para catalogo general.",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cart_add",
                    "description": _SEARCH_ADD_DESCRIPTION,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_key": item_key_prop,
                            "qty": {"type": "integer", "description": "Cantidad a agregar", "minimum": 1},
                            "modifier_keys": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Claves de opciones/adicionales (ej: accesorios para esta categoria). Opcional.",
                            },
                        },
                        "required": ["item_key", "qty"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cart_remove",
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
            "name": "cart_clear",
            "description": (
                "Llama esta funcion cuando el cliente quiera cancelar o vaciar "
                "su carrito completo. Ejemplos: 'cancela todo', 'limpia mi carrito', "
                "'borra el carrito', 'vacia el carrito', 'quiero empezar de nuevo'. "
                "NO la uses si el cliente solo quiere quitar un item (usa cart_remove). "
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
        if name == "cart_add":
            return await self._execute_add(args, phone)
        if name == "cart_remove":
            return await self._execute_remove(args, phone)
        if name == "cart_clear":
            return await self._execute_clear(phone)
        if name == "catalog_list":
            return self._execute_catalog_list(args)
        if name == "catalog_search":
            return self._execute_catalog_search(args)
        if name == "catalog_categories":
            return self._execute_catalog_categories()
        return {"success": False, "error": f"Unknown tool: {name}"}

    async def _execute_add(self, args: dict[str, Any], phone: str) -> dict[str, Any]:
        item_key = args.get("item_key", "")
        qty = args.get("qty", 1)
        modifier_keys = args.get("modifier_keys")
        try:
            qty = int(qty)
        except (ValueError, TypeError):
            return {"success": False, "error": f"qty must be a positive integer, got {qty!r}", "instruction": "Provide a valid quantity >= 1."}
        if qty < 1:
            return {"success": False, "error": f"qty must be >= 1, got {qty}", "instruction": "Provide a valid quantity >= 1."}
        if item_key not in self._catalog:
            instruction = (
                "Usa catalog_search para encontrar el item_key correcto. "
                "NUNCA inventes un item_key."
            ) if self.needs_search else "Usa una de las claves validas listadas arriba."
            result: dict[str, Any] = {
                "success": False,
                "error": f"item_key '{item_key}' not found",
                "instruction": instruction,
            }
            if not self.needs_search:
                result["valid_keys"] = sorted(self._catalog.keys())
            return result
        await self.add_item(phone, item_key, qty, modifier_keys=modifier_keys)
        resp: dict[str, Any] = {
            "success": True,
            "action": "item_added",
            "item": item_key,
            "qty_added": qty,
            "cart_state": self._cart_state_dict(phone),
            "cart_summary": self._cart_summary(phone),
        }
        if modifier_keys:
            resp["modifier_keys"] = modifier_keys
        return resp

    async def _execute_remove(self, args: dict[str, Any], phone: str) -> dict[str, Any]:
        item_key = args.get("item_key", "")
        qty = args.get("qty")
        if item_key not in self._catalog:
            return {
                "success": False,
                "error": f"item_key '{item_key}' not found",
                "valid_keys": sorted(self._catalog.keys()),
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
            "cart_state": self._cart_state_dict(phone),
            "cart_summary": self._cart_summary(phone),
        }

    async def _execute_clear(self, phone: str) -> dict[str, Any]:
        await self.clear(phone, {})
        return {
            "success": True,
            "action": "cart_cleared",
            "cart_state": {"items": [], "total": 0},
            "cart_summary": "Carrito vacio",
        }

    def _execute_catalog_list(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        if args is None:
            args = {}
        category = args.get("category")
        if self.needs_search and category:
            items = self._search.get_items_by_category(category)
            return {"success": True, "action": "catalog_list", "category": category, "catalog": items}
        if self.needs_search:
            categories = self._search.get_categories()
            sample_items: list[dict[str, Any]] = []
            for cat in categories[:5]:
                sample_items.extend(self._search.get_items_by_category(cat["key"])[:6])
            return {"success": True, "action": "catalog_list", "catalog": sample_items[:30], "categories": categories}
        flat_items = []
        for key, info in sorted(self._catalog.items()):
            flat_items.append({"key": key, "name": info["name"], "price": info["price"]})
        return {"success": True, "action": "catalog_list", "catalog": flat_items}

    def _execute_catalog_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query", "")
        if not query:
            return {"success": False, "error": "query is required", "instruction": "Proporciona un termino de busqueda."}
        results = self._search.search(query)
        return {"success": True, "action": "catalog_search", "query": query, "results": results}

    def _execute_catalog_categories(self) -> dict[str, Any]:
        categories = self._search.get_categories()
        return {"success": True, "action": "catalog_categories", "categories": categories}

    async def add_item(
        self,
        phone: str,
        item_key: str,
        quantity: int = 1,
        modifier_keys: list[str] | None = None,
    ) -> None:
        await self._ensure_loaded(phone)
        if phone not in self._carts:
            self._carts[phone] = {"items": [], "total": 0}
        cart = self._carts[phone]
        catalog_item = self._catalog.get(item_key)
        if not catalog_item:
            logger.warning("cart_add_unknown_item", phone=phone, key=item_key)
            return

        modifier_total = 0
        applied_modifiers: list[dict[str, Any]] = []
        if modifier_keys:
            for mk in modifier_keys:
                mod = self._options.get(mk)
                if mod:
                    modifier_total += mod["price"]
                    applied_modifiers.append({"key": mk, "name": mod["name"], "price": mod["price"]})

        unit_price = catalog_item["price"] + modifier_total

        for existing in cart["items"]:
            if existing["key"] == item_key and existing.get("price") == unit_price:
                existing["quantity"] += quantity
                break
        else:
            item_data: dict[str, Any] = {
                "key": item_key,
                "name": catalog_item["name"],
                "price": unit_price,
                "quantity": quantity,
            }
            if applied_modifiers:
                item_data["modifiers"] = applied_modifiers
                item_data["base_price"] = catalog_item["price"]
                item_data["modifier_total"] = modifier_total
            cart["items"].append(item_data)

        self._recalc_total(phone)
        await self._persist(phone)
        logger.info("cart_item_added", phone=phone, key=item_key, qty=quantity, modifiers=len(applied_modifiers))

    async def remove_item(self, phone: str, item_key: str, quantity: int | None = None) -> None:
        await self._ensure_loaded(phone)
        cart = self._carts.get(phone)
        if not cart:
            return
        for i, existing in enumerate(cart["items"]):
            if existing["key"] == item_key:
                if quantity is None or existing["quantity"] <= quantity:
                    cart["items"].pop(i)
                else:
                    existing["quantity"] -= quantity
                break
        self._recalc_total(phone)
        await self._persist(phone)

    def _recalc_total(self, phone: str) -> None:
        cart = self._carts.get(phone)
        if not cart:
            return
        cart["total"] = sum(item["price"] * item["quantity"] for item in cart["items"])

    async def format_for_context(self, phone: str, config: dict[str, Any] | None = None) -> str | None:
        await self._ensure_loaded(phone)
        if not self._catalog:
            return None
        lines: list[str] = []
        if self.needs_search:
            lines.append("Catalogo grande: usa catalog_search para buscar productos o catalog_categories para ver categorias.")
        else:
            cat_lines = ["Catalogo disponible (usa estas claves exactas en item_key):"]
            for key, info in sorted(self._catalog.items()):
                cat_lines.append(f"- {key}: {info['name']} (${info['price']:,})")
            lines.append("\n".join(cat_lines))

        active_promos = self._get_active_promotions()
        if active_promos:
            lines.append("")
            lines.append("PROMOCIONES ACTIVAS AHORA:")
            lines.append(self._format_promotions_text(active_promos))

        all_opt_categories: set[str] = set()
        cart = self._carts.get(phone)
        if cart and cart["items"]:
            for item in cart["items"]:
                catalog_entry = self._catalog.get(item["key"])
                if catalog_entry:
                    cat = catalog_entry.get("category", "")
                    if cat:
                        all_opt_categories.add(cat)

        if not all_opt_categories and self._options:
            cats_in_opts: set[str] = set()
            for m in self._options.values():
                at = m.get("category_scope", "")
                if at:
                    cats_in_opts.add(at)
            if len(cats_in_opts) <= 2:
                all_opt_categories = cats_in_opts

        for cat in sorted(all_opt_categories):
            opt_text = self._format_options_text(cat)
            if opt_text:
                lines.append("")
                lines.append(opt_text)

        if cart and cart["items"]:
            lines.append("")
            lines.append("Carrito actual del cliente:")
            for item in cart["items"]:
                subtotal = item["price"] * item["quantity"]
                name = item["name"]
                if item.get("modifiers"):
                    mod_names = ", ".join(m["name"] for m in item["modifiers"])
                    name = f"{name} (+{mod_names})"
                lines.append(
                    f"- {item['quantity']}x {name} (${item['price']:,} c/u) = ${subtotal:,}"
                )
            lines.append(f"Total: ${cart['total']:,}")
        else:
            lines.append("")
            lines.append("Carrito actual del cliente: vacio")
        return "\n".join(lines)

    async def clear(self, phone: str, config: dict[str, Any] | None = None) -> None:
        try:
            from db.database import get_db
            db = await get_db()
            await db.carts.delete(phone)
        except Exception as e:
            logger.error("cart_clear_error", phone=phone, error=str(e))
        self._carts.pop(phone, None)
        self._loaded_phones.discard(phone)
