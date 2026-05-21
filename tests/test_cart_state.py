from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.cart_state import CartState

_TEST_CATALOG = {
    "item_a": {"name": "Item A (regular)", "price": 3700},
    "item_b": {"name": "Item B (large)", "price": 4800},
    "item_c": {"name": "Item C Special", "price": 3700},
    "item_d": {"name": "Item D Basic", "price": 3200},
    "item_e": {"name": "Item E Large Special", "price": 3400},
    "item_f": {"name": "Item F Alt", "price": 4000},
    "item_g": {"name": "Item G Alt Large", "price": 4800},
    "item_h": {"name": "Item H Regular", "price": 3700},
    "item_i": {"name": "Item I Large", "price": 4800},
    "item_j": {"name": "Plato J", "price": 8900},
    "item_k": {"name": "Acompanamiento K Individual", "price": 2800},
    "item_l": {"name": "Acompanamiento L Mediano", "price": 5100},
    "item_m": {"name": "Acompanamiento M Individual", "price": 2100},
    "item_n": {"name": "Acompanamiento N Mediano", "price": 3700},
    "item_o": {"name": "Bebida O lata", "price": 1500},
    "item_p": {"name": "Bebida P 1.5 Lts", "price": 3000},
    "item_q": {"name": "Bebida Q lata", "price": 1500},
    "item_r": {"name": "Bebida R lata", "price": 1500},
    "item_s": {"name": "Bebida S mineral", "price": 1200},
}


@pytest.fixture
def os_instance():
    inst = CartState()
    inst._catalog = dict(_TEST_CATALOG)
    inst._persist = AsyncMock()
    inst._ensure_loaded = AsyncMock()
    return inst


@pytest.mark.asyncio
async def test_add_item(os_instance):
    await os_instance.add_item("56911111111", "item_a", 2)
    cart = await os_instance.get_cart("56911111111")
    assert len(cart["items"]) == 1
    assert cart["items"][0]["quantity"] == 2
    assert cart["total"] == 7400


@pytest.mark.asyncio
async def test_add_item_stacked(os_instance):
    await os_instance.add_item("56911111111", "item_a", 1)
    await os_instance.add_item("56911111111", "item_a", 2)
    cart = await os_instance.get_cart("56911111111")
    assert len(cart["items"]) == 1
    assert cart["items"][0]["quantity"] == 3


@pytest.mark.asyncio
async def test_add_item_unknown_key(os_instance):
    await os_instance.add_item("56911111111", "nonexistent", 1)
    cart = await os_instance.get_cart("56911111111")
    assert cart["items"] == []


@pytest.mark.asyncio
async def test_remove_item_partial(os_instance):
    await os_instance.add_item("56911111111", "item_a", 3)
    await os_instance.remove_item("56911111111", "item_a", 1)
    cart = await os_instance.get_cart("56911111111")
    assert cart["items"][0]["quantity"] == 2


@pytest.mark.asyncio
async def test_remove_item_full(os_instance):
    await os_instance.add_item("56911111111", "item_a", 1)
    await os_instance.remove_item("56911111111", "item_a")
    cart = await os_instance.get_cart("56911111111")
    assert cart["items"] == []


@pytest.mark.asyncio
async def test_clear(os_instance):
    await os_instance.add_item("56911111111", "item_a", 1)
    with patch("db.database.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.carts = MagicMock()
        mock_db.carts.delete = AsyncMock()
        mock_get_db.return_value = mock_db
        await os_instance.clear("56911111111")
    cart = await os_instance.get_cart("56911111111")
    assert cart["items"] == []


@pytest.mark.asyncio
async def test_format_for_context(os_instance):
    await os_instance.add_item("56911111111", "item_a", 2)
    result = await os_instance.format_for_context("56911111111")
    assert result is not None
    assert "item_a" in result or "Item A" in result
    assert "$7,400" in result


@pytest.mark.asyncio
async def test_format_for_context_empty(os_instance):
    result = await os_instance.format_for_context("56999999999")
    assert result is not None
    assert "Catalogo disponible" in result


@pytest.mark.asyncio
async def test_ensure_loaded_logs_error_on_db_failure():
    inst = CartState()
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
            patch("core.capabilities.cart.logger") as mock_logger:
        await inst._ensure_loaded("56911111111")
        mock_logger.error.assert_called_once_with(
            "cart_load_error", phone="56911111111", error="db down"
        )
        assert "56911111111" in inst._loaded_phones


@pytest.mark.asyncio
async def test_persist_logs_error_on_db_failure():
    inst = CartState()
    inst._carts["56911111111"] = {"items": [{"key": "item_a", "name": "Item A (regular)", "price": 3700, "quantity": 1}], "total": 3700}
    inst._loaded_phones.add("56911111111")
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
            patch("core.capabilities.cart.logger") as mock_logger:
        await inst._persist("56911111111")
    mock_logger.error.assert_called_once_with(
        "cart_persist_error", phone="56911111111", error="db down"
    )
    assert "56911111111" in inst._carts
    assert inst._carts["56911111111"]["total"] == 3700


@pytest.mark.asyncio
async def test_clear_logs_error_on_db_failure():
    inst = CartState()
    inst._carts["56911111111"] = {"items": [{"key": "item_a", "name": "Item A (regular)", "price": 3700, "quantity": 1}], "total": 3700}
    inst._loaded_phones.add("56911111111")
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
            patch("core.capabilities.cart.logger") as mock_logger:
        await inst.clear("56911111111")
    mock_logger.error.assert_called_once_with(
        "cart_clear_error", phone="56911111111", error="db down"
    )
    assert "56911111111" not in inst._carts
    assert "56911111111" in inst._loaded_phones


@pytest.mark.asyncio
async def test_ensure_loaded_corrupt_json():
    inst = CartState()
    mock_db = MagicMock()
    mock_db.carts = MagicMock()
    mock_db.carts.load = AsyncMock(return_value=("not json", 1000))
    with patch("db.database.get_db", return_value=mock_db):
        await inst._ensure_loaded("56922222222")
    cart = inst._carts.get("56922222222")
    assert cart is None


@pytest.mark.asyncio
async def test_get_cart_default(os_instance):
    cart = await os_instance.get_cart("56999999999")
    assert cart == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_clear_prevents_resurrection():
    inst = CartState()
    mock_db = MagicMock()
    mock_db.carts = MagicMock()
    mock_db.carts.load = AsyncMock(return_value=('[{"key":"item_a","name":"Item A (regular)","price":3700,"quantity":1}]', 3700))
    mock_db.carts.delete = AsyncMock()
    with patch("db.database.get_db", return_value=mock_db):
        await inst._ensure_loaded("56933333333")
        assert "56933333333" in inst._carts
        await inst.clear("56933333333")
        assert "56933333333" not in inst._carts
        assert "56933333333" not in inst._loaded_phones


@pytest.mark.asyncio
async def test_persist_failure_invalidates_cache():
    inst = CartState()
    inst._carts["56944444444"] = {"items": [{"key": "item_a", "name": "Item A (regular)", "price": 3700, "quantity": 1}], "total": 3700}
    inst._loaded_phones.add("56944444444")
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
         patch("core.capabilities.cart.logger"):
        await inst._persist("56944444444")
    assert "56944444444" in inst._carts
    assert inst._carts["56944444444"]["total"] == 3700


def test_get_catalog_returns_copy():
    inst = CartState()
    catalog = inst.get_catalog()
    assert catalog == inst._catalog
    catalog["new_item"] = {"name": "test", "price": 999}
    assert "new_item" not in inst._catalog


@pytest.mark.asyncio
async def test_reload_catalog_from_db():
    inst = CartState()
    mock_db = MagicMock()
    mock_db.load_catalog_items = AsyncMock(return_value=[
        {"key": "db_item", "name": "DB Item", "price": 2000, "base_price": 2000, "category": "test", "subcategory": "sub_test", "is_available": 1, "sort_order": 1},
        {"key": "unavailable_item", "name": "Unavailable", "price": 9999, "base_price": 9999, "category": "test", "subcategory": "", "is_available": 0, "sort_order": 2},
    ])
    mock_db.load_catalog_variants = AsyncMock(return_value=[])
    mock_db.load_catalog_options = AsyncMock(return_value=[])
    mock_db.load_promotions = AsyncMock(return_value=[])
    with patch("db.database.get_db", return_value=mock_db):
        await inst.reload_catalog_from_db()
        assert "db_item" in inst._catalog
        assert "unavailable_item" not in inst._catalog
        assert inst._catalog["db_item"]["name"] == "DB Item"
        assert inst._catalog["db_item"]["subcategory"] == "sub_test"


@pytest.mark.asyncio
async def test_reload_catalog_from_db_error_keeps_existing():
    inst = CartState()
    original_count = len(inst._catalog)
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
            patch("core.capabilities.cart.logger"):
        await inst.reload_catalog_from_db()
        assert len(inst._catalog) == original_count


def test_get_tool_definitions():
    inst = CartState()
    defs = inst.get_tool_definitions({})
    assert len(defs) == 6
    names = [d["function"]["name"] for d in defs]
    assert "cart_add" in names
    assert "cart_remove" in names
    assert "cart_clear" in names
    assert "catalog_list" in names
    assert "send_product_image" in names
    assert "show_category_menu" in names


def test_get_tool_names():
    inst = CartState()
    names = inst.get_tool_names()
    assert names == {"cart_add", "cart_remove", "cart_clear", "catalog_list", "send_product_image", "show_category_menu"}


@pytest.mark.asyncio
async def test_execute_add(os_instance):
    result = await os_instance.execute_tool("cart_add", {"item_key": "item_a", "qty": 2}, "+56910000001", "tc1", {})
    assert result["success"] is True
    assert result["action"] == "item_added"
    assert result["cart_state"]["items"][0]["key"] == "item_a"
    assert result["cart_state"]["items"][0]["qty"] == 2
    assert "cart_summary" in result


@pytest.mark.asyncio
async def test_execute_add_invalid_item(os_instance):
    result = await os_instance.execute_tool("cart_add", {"item_key": "nonexistent_item", "qty": 1}, "+56910000001", "tc2", {})
    assert result["success"] is False
    assert "valid_keys" in result
    assert "instruction" in result


@pytest.mark.asyncio
async def test_execute_add_invalid_qty(os_instance):
    result = await os_instance.execute_tool("cart_add", {"item_key": "item_a", "qty": 0}, "+56910000001", "tc3", {})
    assert result["success"] is False
    assert "qty" in result["error"]


@pytest.mark.asyncio
async def test_execute_remove(os_instance):
    await os_instance.add_item("+56910000001", "item_a", 2)
    result = await os_instance.execute_tool("cart_remove", {"item_key": "item_a", "qty": 1}, "+56910000001", "tc4", {})
    assert result["success"] is True
    assert result["action"] == "item_removed"


@pytest.mark.asyncio
async def test_execute_clear(os_instance):
    await os_instance.add_item("+56910000001", "item_a", 2)
    result = await os_instance.execute_tool("cart_clear", {}, "+56910000001", "tc5", {})
    assert result["success"] is True
    assert result["action"] == "cart_cleared"
    assert result["cart_state"]["total"] == 0


@pytest.mark.asyncio
async def test_execute_catalog_list(os_instance):
    result = await os_instance.execute_tool("catalog_list", {}, "+56910000001", "tc6", {})
    assert result["success"] is True
    assert result["action"] == "catalog_list"
    assert len(result["catalog"]) > 0


@pytest.mark.asyncio
async def test_execute_unknown_tool(os_instance):
    result = await os_instance.execute_tool("unknown_tool", {}, "+56910000001", "tc7", {})
    assert result["success"] is False
    assert "Unknown tool" in result["error"]


def test_parallel_safe_and_sequential_tools():
    inst = CartState()
    assert {"catalog_list", "catalog_search", "catalog_categories", "send_product_image", "show_category_menu"} == inst.PARALLEL_SAFE_TOOLS
    assert {"cart_add", "cart_remove", "cart_clear"} == inst.SEQUENTIAL_TOOLS


def test_tool_definitions_dynamic_from_runtime_catalog():
    inst = CartState()
    inst._catalog = {"custom_item": {"name": "Custom Item", "price": 9999}}
    inst._rebuild_search()
    defs = inst.get_tool_definitions({})
    add_def = next(d for d in defs if d["function"]["name"] == "cart_add")
    item_key_prop = add_def["function"]["parameters"]["properties"]["item_key"]
    assert item_key_prop.get("enum") == ["custom_item"]


def test_tool_definitions_item_key_has_enum():
    inst = CartState()
    inst._catalog = dict(_TEST_CATALOG)
    defs = inst.get_tool_definitions({})
    for tool_name in ("cart_add", "cart_remove"):
        tool_def = next(d for d in defs if d["function"]["name"] == tool_name)
        item_key_prop = tool_def["function"]["parameters"]["properties"]["item_key"]
        assert "enum" in item_key_prop
        assert set(item_key_prop["enum"]) == set(inst._catalog.keys())


def test_tool_definitions_no_claves_in_description():
    inst = CartState()
    defs = inst.get_tool_definitions({})
    for tool_name in ("cart_add", "cart_remove"):
        tool_def = next(d for d in defs if d["function"]["name"] == tool_name)
        assert "Claves validas" not in tool_def["function"]["description"]


LARGE_CATALOG = {f"item_{i:03d}": {"name": f"Item {i}", "price": 1000 + i, "category": f"cat_{i % 5}"} for i in range(60)}
LARGE_CATALOG["item_beatles_chica"] = {"name": "Plato Beatles Chica", "price": 17900, "category": "cat_c", "description": "Ingredientes principales del plato"}
LARGE_CATALOG["item_mojito_tradicional"] = {"name": "Mojito Tradicional", "price": 4900, "category": "cocteles", "description": "Ron Blanco, Limon, Menta, Goma, Soda"}


class TestDualModeFlat:
    def test_flat_mode_under_threshold(self):
        inst = CartState()
        inst._catalog = dict(_TEST_CATALOG)
        assert not inst.needs_search

    def test_flat_tool_definitions_have_enum(self):
        inst = CartState()
        inst._catalog = dict(_TEST_CATALOG)
        defs = inst.get_tool_definitions({})
        names = {d["function"]["name"] for d in defs}
        assert names == {"cart_add", "cart_remove", "cart_clear", "catalog_list", "send_product_image", "show_category_menu"}
        add_def = next(d for d in defs if d["function"]["name"] == "cart_add")
        assert "enum" in add_def["function"]["parameters"]["properties"]["item_key"]

    def test_flat_tool_names(self):
        inst = CartState()
        inst._catalog = dict(_TEST_CATALOG)
        assert inst.get_tool_names() == {"cart_add", "cart_remove", "cart_clear", "catalog_list", "send_product_image", "show_category_menu"}

    def test_flat_format_for_context_has_full_catalog(self):
        inst = CartState()
        inst._catalog = dict(_TEST_CATALOG)
        inst._ensure_loaded = AsyncMock()
        ctx = __import__("asyncio").run(inst.format_for_context("+5691", {}))
        assert "Catalogo disponible" in ctx

    def test_flat_get_catalog_returns_all_items(self):
        inst = CartState()
        inst._catalog = dict(_TEST_CATALOG)
        result = __import__("asyncio").run(inst.execute_tool("catalog_list", {}, "+5691", "tc", {}))
        assert result["success"] is True
        assert len(result["catalog"]) == len(inst._catalog)

    @pytest.mark.asyncio
    async def test_flat_add_invalid_key_shows_valid_keys(self):
        inst = CartState()
        inst._ensure_loaded = AsyncMock()
        result = await inst.execute_tool("cart_add", {"item_key": "zzz_fake", "qty": 1}, "+5691", "tc", {})
        assert result["success"] is False
        assert "valid_keys" in result


class TestDualModeSearch:
    def _make_search_instance(self):
        inst = CartState()
        inst._catalog = dict(LARGE_CATALOG)
        inst._rebuild_search()
        inst._ensure_loaded = AsyncMock()
        return inst

    def test_search_mode_over_threshold(self):
        inst = self._make_search_instance()
        assert inst.needs_search

    def test_search_tool_definitions_no_enum(self):
        inst = self._make_search_instance()
        defs = inst.get_tool_definitions({})
        names = {d["function"]["name"] for d in defs}
        assert "catalog_search" in names
        assert "catalog_categories" in names
        assert "catalog_list" in names
        assert "cart_add" in names
        assert "cart_remove" in names
        assert "cart_clear" in names
        add_def = next(d for d in defs if d["function"]["name"] == "cart_add")
        assert "enum" not in add_def["function"]["parameters"]["properties"]["item_key"]

    def test_search_tool_names(self):
        inst = self._make_search_instance()
        names = inst.get_tool_names()
        assert "catalog_search" in names
        assert "catalog_categories" in names
        assert names - {"catalog_search", "catalog_categories"} == {"cart_add", "cart_remove", "cart_clear", "catalog_list", "send_product_image", "show_category_menu"}

    def test_search_add_description_has_never_invent_key(self):
        inst = self._make_search_instance()
        defs = inst.get_tool_definitions({})
        add_def = next(d for d in defs if d["function"]["name"] == "cart_add")
        desc = add_def["function"]["description"]
        assert "NUNCA inventes" in desc or "NUNCA" in desc

    def test_search_format_for_context_no_full_catalog(self):
        inst = self._make_search_instance()
        ctx = __import__("asyncio").run(inst.format_for_context("+5691", {}))
        assert "Catalogo grande" in ctx
        assert "catalog_search" in ctx

    @pytest.mark.asyncio
    async def test_execute_catalog_search(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("catalog_search", {"query": "beatles"}, "+5691", "tc", {})
        assert result["success"] is True
        assert result["action"] == "catalog_search"
        assert len(result["results"]) > 0
        assert result["results"][0]["item_key"] == "item_beatles_chica"

    @pytest.mark.asyncio
    async def test_execute_catalog_search_empty_query(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("catalog_search", {"query": ""}, "+5691", "tc", {})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_catalog_categories(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("catalog_categories", {}, "+5691", "tc", {})
        assert result["success"] is True
        assert result["action"] == "catalog_categories"
        assert len(result["categories"]) > 0
        cat_keys = {c["key"] for c in result["categories"]}
        assert "cat_c" in cat_keys

    @pytest.mark.asyncio
    async def test_execute_catalog_list_with_category(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("catalog_list", {"category": "cat_c"}, "+5691", "tc", {})
        assert result["success"] is True
        assert result.get("category") == "cat_c"
        assert len(result["catalog"]) > 0

    @pytest.mark.asyncio
    async def test_execute_catalog_list_no_category_returns_sample(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("catalog_list", {}, "+5691", "tc", {})
        assert result["success"] is True
        assert "categories" in result
        assert len(result["catalog"]) <= 30

    @pytest.mark.asyncio
    async def test_search_add_invalid_key_no_valid_keys_list(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("cart_add", {"item_key": "zzz_fake", "qty": 1}, "+5691", "tc", {})
        assert result["success"] is False
        assert "valid_keys" not in result
        assert "catalog_search" in result["instruction"]

    @pytest.mark.asyncio
    async def test_search_add_valid_key(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("cart_add", {"item_key": "item_beatles_chica", "qty": 1}, "+5691", "tc", {})
        assert result["success"] is True
        assert result["action"] == "item_added"

    def test_search_index_lazy_init(self):
        inst = self._make_search_instance()
        assert inst._catalog_search is None
        search = inst._search
        assert search is not None
        search2 = inst._search
        assert search2 is search

    def test_rebuild_search_resets_index(self):
        inst = self._make_search_instance()
        _ = inst._search
        assert inst._catalog_search is not None
        inst._rebuild_search()
        assert inst._catalog_search is None


LARGE_CATALOG_WITH_SUBCATEGORY = {
    **{f"item_{i:03d}": {"name": f"Item {i}", "price": 1000 + i, "category": f"cat_{i % 5}", "subcategory": f"sub_{i % 3}"} for i in range(60)},
    "item_margherita_individual": {"name": "Pizza Margherita - Individual", "price": 7900, "category": "cat_pizzas", "subcategory": "individuales", "description": "Salsa tomate, mozzarella, albahaca"},
    "item_margherita_familiar": {"name": "Pizza Margherita - Familiar", "price": 14900, "category": "cat_pizzas", "subcategory": "familiares", "description": "Salsa tomate, mozzarella, albahaca"},
}


class TestVariantExpansion:
    @pytest.mark.asyncio
    async def test_reload_catalog_from_db_with_variants(self):
        inst = CartState()
        mock_db = MagicMock()
        mock_db.load_catalog_items = AsyncMock(return_value=[
            {"key": "item_margherita", "name": "Pizza Margherita", "price": 0, "base_price": None, "category": "cat_pizzas", "subcategory": "", "is_available": 1, "sort_order": 1},
        ])
        mock_db.load_catalog_variants = AsyncMock(return_value=[
            {"item_key": "item_margherita", "slug": "individual", "label": "Individual", "price": 7900},
            {"item_key": "item_margherita", "slug": "familiar", "label": "Familiar", "price": 14900},
        ])
        mock_db.load_catalog_options = AsyncMock(return_value=[])
        mock_db.load_promotions = AsyncMock(return_value=[])
        with patch("db.database.get_db", return_value=mock_db):
            await inst.reload_catalog_from_db()
            assert "item_margherita" not in inst._catalog
            assert "item_margherita_individual" in inst._catalog
            assert "item_margherita_familiar" in inst._catalog
            assert inst._catalog["item_margherita_individual"]["price"] == 7900
            assert inst._catalog["item_margherita_familiar"]["price"] == 14900
            assert inst._catalog["item_margherita_individual"]["name"] == "Pizza Margherita - Individual"

    @pytest.mark.asyncio
    async def test_reload_catalog_from_db_no_variants_uses_base_price(self):
        inst = CartState()
        mock_db = MagicMock()
        mock_db.load_catalog_items = AsyncMock(return_value=[
            {"key": "simple_drink", "name": "Simple Drink", "price": 2000, "base_price": 2000, "category": "cat_e", "subcategory": "", "is_available": 1, "sort_order": 1},
        ])
        mock_db.load_catalog_variants = AsyncMock(return_value=[])
        mock_db.load_catalog_options = AsyncMock(return_value=[])
        mock_db.load_promotions = AsyncMock(return_value=[])
        with patch("db.database.get_db", return_value=mock_db):
            await inst.reload_catalog_from_db()
            assert "simple_drink" in inst._catalog
            assert inst._catalog["simple_drink"]["price"] == 2000
            assert "base_item_key" not in inst._catalog["simple_drink"]

    @pytest.mark.asyncio
    async def test_variant_item_has_base_item_key(self):
        inst = CartState()
        mock_db = MagicMock()
        mock_db.load_catalog_items = AsyncMock(return_value=[
            {"key": "item_margherita", "name": "Pizza Margherita", "price": 0, "base_price": None, "category": "cat_pizzas", "subcategory": "", "is_available": 1, "sort_order": 1},
        ])
        mock_db.load_catalog_variants = AsyncMock(return_value=[
            {"item_key": "item_margherita", "slug": "individual", "label": "Individual", "price": 7900},
        ])
        mock_db.load_catalog_options = AsyncMock(return_value=[])
        mock_db.load_promotions = AsyncMock(return_value=[])
        with patch("db.database.get_db", return_value=mock_db):
            await inst.reload_catalog_from_db()
            assert inst._catalog["item_margherita_individual"]["base_item_key"] == "item_margherita"


class TestPromoActivation:
    @pytest.mark.asyncio
    async def test_reload_catalog_from_db_with_promotions(self):
        inst = CartState()
        mock_db = MagicMock()
        mock_db.load_catalog_items = AsyncMock(return_value=[
            {"key": "item1", "name": "Item 1", "price": 5000, "base_price": 5000, "category": "test", "subcategory": "", "is_available": 1, "sort_order": 1},
        ])
        mock_db.load_catalog_variants = AsyncMock(return_value=[])
        mock_db.load_catalog_options = AsyncMock(return_value=[])
        mock_db.load_promotions = AsyncMock(return_value=[
            {"key": "happy_intenso", "name": "Happy Intenso", "display_text": "2x1 Intenso", "valid_days": "[1,2,3,4,5]", "valid_from": "17:00", "valid_to": "20:00"},
        ])
        mock_db.load_promotion_items = AsyncMock(return_value=[
            {"promo_key": "happy_intenso", "item_key": "item1", "promo_price": 3000},
        ])
        with patch("db.database.get_db", return_value=mock_db):
            await inst.reload_catalog_from_db()
            assert len(inst._promotions) == 1
            assert inst._promotions[0]["key"] == "happy_intenso"
            assert len(inst._promotions[0]["items"]) == 1

    def test_get_active_promotions_filters_by_day(self):
        from unittest.mock import patch as mock_patch
        inst = CartState()
        inst._promotions = [
            {"key": "weekday_promo", "valid_days": [1, 2, 3, 4, 5], "valid_from": "", "valid_to": ""},
            {"key": "weekend_promo", "valid_days": [6, 7], "valid_from": "", "valid_to": ""},
        ]
        with mock_patch("core.capabilities.cart.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.isoweekday.return_value = 3
            mock_now.strftime.return_value = "12:00"
            mock_dt.now.return_value = mock_now
            active = inst._get_active_promotions()
            promo_keys = [p["key"] for p in active]
            assert "weekday_promo" in promo_keys
            assert "weekend_promo" not in promo_keys

    def test_get_active_promotions_filters_by_time(self):
        from unittest.mock import patch as mock_patch
        inst = CartState()
        inst._promotions = [
            {"key": "happy_hour", "valid_days": [], "valid_from": "17:00", "valid_to": "20:00"},
        ]
        with mock_patch("core.capabilities.cart.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.isoweekday.return_value = 3
            mock_now.strftime.return_value = "18:00"
            mock_dt.now.return_value = mock_now
            active = inst._get_active_promotions()
            assert len(active) == 1
        with mock_patch("core.capabilities.cart.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.isoweekday.return_value = 3
            mock_now.strftime.return_value = "21:00"
            mock_dt.now.return_value = mock_now
            active = inst._get_active_promotions()
            assert len(active) == 0

    def test_format_promotions_text(self):
        inst = CartState()
        promotions = [
            {"display_text": "2x1 Cervezas de 17:00 a 20:00"},
            {"display_text": "Happy Intenso desde $3.000"},
        ]
        text = inst._format_promotions_text(promotions)
        assert "2x1 Cervezas" in text
        assert "Happy Intenso" in text


class TestOptionPricing:
    @pytest.mark.asyncio
    async def test_add_item_with_options(self):
        inst = CartState()
        inst._catalog["item_margherita_individual"] = {"name": "Pizza Margherita - Individual", "price": 7900, "category": "cat_pizzas"}
        inst._options = {
            "extra_queso": {"key": "extra_queso", "name": "Extra Queso", "price": 1000, "category_scope": "cat_pizzas"},
            "pepperoni": {"key": "pepperoni", "name": "Pepperoni", "price": 1500, "category_scope": "cat_pizzas"},
        }
        inst._ensure_loaded = AsyncMock()
        inst._persist = AsyncMock()
        await inst.add_item("+5691", "item_margherita_individual", 1, modifier_keys=["extra_queso", "pepperoni"])
        cart = await inst.get_cart("+5691")
        assert len(cart["items"]) == 1
        assert cart["items"][0]["price"] == 10400
        assert cart["items"][0]["modifiers"][0]["name"] == "Extra Queso"
        assert cart["items"][0]["modifiers"][1]["name"] == "Pepperoni"
        assert cart["items"][0]["base_price"] == 7900
        assert cart["items"][0]["modifier_total"] == 2500

    @pytest.mark.asyncio
    async def test_add_item_same_key_diff_modifiers_separate_lines(self):
        inst = CartState()
        inst._catalog["item_margherita_individual"] = {"name": "Pizza Margherita - Individual", "price": 7900, "category": "cat_pizzas"}
        inst._options = {
            "extra_queso": {"key": "extra_queso", "name": "Extra Queso", "price": 1000, "category_scope": "cat_pizzas"},
        }
        inst._ensure_loaded = AsyncMock()
        inst._persist = AsyncMock()
        await inst.add_item("+5691", "item_margherita_individual", 1, modifier_keys=[])
        await inst.add_item("+5691", "item_margherita_individual", 1, modifier_keys=["extra_queso"])
        cart = await inst.get_cart("+5691")
        assert len(cart["items"]) == 2

    @pytest.mark.asyncio
    async def test_add_item_same_key_same_price_stacks(self):
        inst = CartState()
        inst._catalog["item_margherita_individual"] = {"name": "Pizza Margherita - Individual", "price": 7900, "category": "cat_pizzas"}
        inst._options = {}
        inst._ensure_loaded = AsyncMock()
        inst._persist = AsyncMock()
        await inst.add_item("+5691", "item_margherita_individual", 1)
        await inst.add_item("+5691", "item_margherita_individual", 2)
        cart = await inst.get_cart("+5691")
        assert len(cart["items"]) == 1
        assert cart["items"][0]["quantity"] == 3

    def test_format_options_text(self):
        inst = CartState()
        inst._options = {
            "extra_queso": {"key": "extra_queso", "name": "Extra Queso", "price": 1000, "category_scope": "cat_pizzas"},
            "pepperoni": {"key": "pepperoni", "name": "Pepperoni", "price": 1500, "category_scope": "cat_pizzas"},
            "extra_hielo": {"key": "extra_hielo", "name": "Extra Hielo", "price": 500, "category_scope": "cat_e"},
        }
        text = inst._format_options_text("cat_pizzas")
        assert "Extra Queso" in text
        assert "Pepperoni" in text
        assert "Extra Hielo" not in text

    @pytest.mark.asyncio
    async def test_format_for_context_includes_options(self):
        inst = CartState()
        inst._catalog["item_margherita_individual"] = {"name": "Pizza Margherita - Individual", "price": 7900, "category": "cat_pizzas"}
        inst._options = {
            "extra_queso": {"key": "extra_queso", "name": "Extra Queso", "price": 1000, "category_scope": "cat_pizzas"},
        }
        inst._ensure_loaded = AsyncMock()
        inst._persist = AsyncMock()
        await inst.add_item("+5691", "item_margherita_individual", 1, modifier_keys=["extra_queso"])
        ctx = await inst.format_for_context("+5691", {})
        assert "Extra Queso" in ctx


class TestSubcategorySearch:
    def _make_search_instance(self):
        inst = CartState()
        inst._catalog = dict(LARGE_CATALOG_WITH_SUBCATEGORY)
        inst._rebuild_search()
        inst._ensure_loaded = AsyncMock()
        return inst

    @pytest.mark.asyncio
    async def test_search_includes_subcategory_in_results(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("catalog_search", {"query": "pizza margherita individual"}, "+5691", "tc", {})
        assert result["success"] is True
        assert any("subcategory" in r for r in result["results"])

    @pytest.mark.asyncio
    async def test_search_by_subcategory(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("catalog_search", {"query": "individuales pizza"}, "+5691", "tc", {})
        assert result["success"] is True
        assert len(result["results"]) > 0

    @pytest.mark.asyncio
    async def test_catalog_list_by_category_includes_subcategory(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("catalog_list", {"category": "cat_pizzas"}, "+5691", "tc", {})
        assert result["success"] is True
        assert any("subcategory" in item for item in result["catalog"])


class TestSlugify:
    def test_slugify_simple(self):
        from core.utils import slugify
        assert slugify("Individual") == "individual"

    def test_slugify_accents(self):
        from core.utils import slugify
        assert slugify("Família") == "familia"

    def test_slugify_spaces(self):
        from core.utils import slugify
        assert slugify("Extra Grande") == "extra_grande"

    def test_slugify_special_chars(self):
        from core.utils import slugify
        assert slugify("1/2 Litro") == "12_litro"
