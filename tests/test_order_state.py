import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.capabilities.order import DEFAULT_MENU_ITEMS, MENU_ITEMS, ORDER_TAG_RE, _load_menu_from_file
from core.order_state import OrderState


@pytest.fixture
def os_instance():
    inst = OrderState()
    inst._persist = AsyncMock()
    inst._ensure_loaded = AsyncMock()
    return inst


def test_menu_items_has_expected_keys():
    assert "completo_normal" in MENU_ITEMS
    assert "coca_lata" in MENU_ITEMS
    assert "agua" in MENU_ITEMS


def test_order_tag_re_matches():
    m = ORDER_TAG_RE.search("text [ORDER_ADD:completo_normal:2] more")
    assert m is not None
    assert m.group(1) == "completo_normal"
    assert m.group(2) == "2"


@pytest.mark.asyncio
async def test_add_item(os_instance):
    await os_instance.add_item("56911111111", "completo_normal", 2)
    order = await os_instance.get_order("56911111111")
    assert len(order["items"]) == 1
    assert order["items"][0]["quantity"] == 2
    assert order["total"] == 7400


@pytest.mark.asyncio
async def test_add_item_stacked(os_instance):
    await os_instance.add_item("56911111111", "completo_normal", 1)
    await os_instance.add_item("56911111111", "completo_normal", 2)
    order = await os_instance.get_order("56911111111")
    assert len(order["items"]) == 1
    assert order["items"][0]["quantity"] == 3


@pytest.mark.asyncio
async def test_add_item_unknown_key(os_instance):
    await os_instance.add_item("56911111111", "nonexistent", 1)
    order = await os_instance.get_order("56911111111")
    assert order["items"] == []


@pytest.mark.asyncio
async def test_remove_item_partial(os_instance):
    await os_instance.add_item("56911111111", "completo_normal", 3)
    await os_instance.remove_item("56911111111", "completo_normal", 1)
    order = await os_instance.get_order("56911111111")
    assert order["items"][0]["quantity"] == 2


@pytest.mark.asyncio
async def test_remove_item_full(os_instance):
    await os_instance.add_item("56911111111", "completo_normal", 1)
    await os_instance.remove_item("56911111111", "completo_normal")
    order = await os_instance.get_order("56911111111")
    assert order["items"] == []


@pytest.mark.asyncio
async def test_clear(os_instance):
    await os_instance.add_item("56911111111", "completo_normal", 1)
    with patch("db.database.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.delete_order = AsyncMock()
        mock_get_db.return_value = mock_db
        await os_instance.clear("56911111111")
    order = await os_instance.get_order("56911111111")
    assert order["items"] == []


@pytest.mark.asyncio
async def test_format_for_context(os_instance):
    await os_instance.add_item("56911111111", "completo_normal", 2)
    result = await os_instance.format_for_context("56911111111")
    assert result is not None
    assert "completo_normal" in result or "Completo" in result
    assert "$7,400" in result


@pytest.mark.asyncio
async def test_format_for_context_empty(os_instance):
    result = await os_instance.format_for_context("56999999999")
    assert result is not None
    assert "Menu disponible" in result


@pytest.mark.asyncio
async def test_parse_tags(os_instance):
    text = "Tu pedido [ORDER_ADD:completo_normal:1] está listo [ORDER_ADD:coca_lata:2]"
    cleaned = await os_instance.parse_tags("56911111111", text)
    assert "[ORDER_ADD" not in cleaned
    order = await os_instance.get_order("56911111111")
    assert len(order["items"]) == 2


@pytest.mark.asyncio
async def test_parse_tags_clear(os_instance):
    await os_instance.add_item("56911111111", "completo_normal", 1)
    with patch("db.database.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.delete_order = AsyncMock()
        mock_get_db.return_value = mock_db
        cleaned = await os_instance.parse_tags("56911111111", "Vamos [ORDER_CLEAR]")
    assert "[ORDER_CLEAR]" not in cleaned
    order = await os_instance.get_order("56911111111")
    assert order["items"] == []


@pytest.mark.asyncio
async def test_ensure_loaded_logs_error_on_db_failure():
    inst = OrderState()
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
         patch("core.capabilities.order.logger") as mock_logger:
        await inst._ensure_loaded("56911111111")
        mock_logger.error.assert_called_once_with(
            "order_load_error", phone="56911111111", error="db down"
        )
        assert "56911111111" in inst._loaded_phones


@pytest.mark.asyncio
async def test_persist_logs_error_on_db_failure():
    inst = OrderState()
    inst._orders["56911111111"] = {"items": [{"key": "completo_normal", "name": "Completo Normal (carne)", "price": 3700, "quantity": 1}], "total": 3700}
    inst._loaded_phones.add("56911111111")
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
         patch("core.capabilities.order.logger") as mock_logger:
        await inst._persist("56911111111")
        mock_logger.error.assert_called_once_with(
            "order_persist_error", phone="56911111111", error="db down"
        )
        assert "56911111111" not in inst._orders
        assert "56911111111" not in inst._loaded_phones


@pytest.mark.asyncio
async def test_clear_logs_error_on_db_failure():
    inst = OrderState()
    inst._orders["56911111111"] = {"items": [{"key": "completo_normal", "name": "Completo Normal (carne)", "price": 3700, "quantity": 1}], "total": 3700}
    inst._loaded_phones.add("56911111111")
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
         patch("core.capabilities.order.logger") as mock_logger:
        await inst.clear("56911111111")
    mock_logger.error.assert_called_once_with(
        "order_clear_error", phone="56911111111", error="db down"
    )
    assert "56911111111" not in inst._orders
    assert "56911111111" not in inst._loaded_phones


@pytest.mark.asyncio
async def test_ensure_loaded_corrupt_json():
    inst = OrderState()
    mock_db = MagicMock()
    mock_db.load_order = AsyncMock(return_value=("not json", 1000))
    with patch("db.database.get_db", return_value=mock_db):
        await inst._ensure_loaded("56922222222")
    order = inst._orders.get("56922222222")
    assert order is None


@pytest.mark.asyncio
async def test_get_order_default(os_instance):
    order = await os_instance.get_order("56999999999")
    assert order == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_clear_prevents_resurrection():
    inst = OrderState()
    mock_db = MagicMock()
    mock_db.load_order = AsyncMock(return_value=('[{"key":"completo_normal","name":"Completo Normal (carne)","price":3700,"quantity":1}]', 3700))
    mock_db.delete_order = AsyncMock()
    with patch("db.database.get_db", return_value=mock_db):
        await inst._ensure_loaded("56933333333")
        assert "56933333333" in inst._orders
        await inst.clear("56933333333")
    assert "56933333333" not in inst._orders
    assert "56933333333" not in inst._loaded_phones


@pytest.mark.asyncio
async def test_persist_failure_invalidates_cache():
    inst = OrderState()
    inst._orders["56944444444"] = {"items": [{"key": "completo_normal", "name": "Completo Normal (carne)", "price": 3700, "quantity": 1}], "total": 3700}
    inst._loaded_phones.add("56944444444")
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
         patch("core.capabilities.order.logger"):
        await inst._persist("56944444444")
    assert "56944444444" not in inst._orders
    assert "56944444444" not in inst._loaded_phones


def test_default_menu_items_has_all_keys():
    expected_keys = [
        "completo_normal", "completo_gigante", "completo_italiano", "completo_vienesa",
        "completo_vienesa_gigante", "completo_vienesa_vegano", "completo_vienesa_vegano_gigante",
        "as_normal", "as_gigante", "chorrillana", "salchipapas_individual", "salchipapas_mediana",
        "papas_individual", "papas_mediana", "coca_lata", "coca_1_5l", "sprite_lata", "fanta_lata", "agua",
    ]
    for key in expected_keys:
        assert key in DEFAULT_MENU_ITEMS, f"Missing key: {key}"


def test_get_menu_returns_copy():
    inst = OrderState()
    menu = inst.get_menu()
    assert menu == inst._menu
    menu["new_item"] = {"name": "test", "price": 999}
    assert "new_item" not in inst._menu


def test_load_menu_from_file_returns_default_on_missing_file():
    with patch("core.capabilities.order.MENU_CONFIG_PATH", "/nonexistent/path/menu.json"):
        result = _load_menu_from_file()
        assert result == DEFAULT_MENU_ITEMS


def test_load_menu_from_file_returns_default_on_invalid_json():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{invalid json")
        tmp_path = f.name
    with patch("core.capabilities.order.MENU_CONFIG_PATH", tmp_path):
        result = _load_menu_from_file()
        assert result == DEFAULT_MENU_ITEMS


def test_load_menu_from_file_parses_valid_json():
    data = '{"test_item": {"name": "Test Item", "price": 1000}}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(data)
        tmp_path = f.name
    with patch("core.capabilities.order.MENU_CONFIG_PATH", tmp_path):
        result = _load_menu_from_file()
        assert "test_item" in result
        assert result["test_item"]["name"] == "Test Item"
        assert result["test_item"]["price"] == 1000


def test_load_menu_from_file_skips_items_missing_fields():
    data = '{"good": {"name": "Good", "price": 500}, "bad": {"name": "No Price"}}'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(data)
        tmp_path = f.name
    with patch("core.capabilities.order.MENU_CONFIG_PATH", tmp_path):
        result = _load_menu_from_file()
        assert "good" in result
        assert "bad" not in result


@pytest.mark.asyncio
async def test_reload_menu_from_db():
    inst = OrderState()
    mock_db = MagicMock()
    mock_db.load_menu_items = AsyncMock(return_value=[
        {"key": "db_item", "name": "DB Item", "price": 2000, "category": "test", "is_available": 1, "sort_order": 1},
        {"key": "unavailable_item", "name": "Unavailable", "price": 9999, "category": "test", "is_available": 0, "sort_order": 2},
    ])
    with patch("db.database.get_db", return_value=mock_db):
        await inst.reload_menu_from_db()
    assert "db_item" in inst._menu
    assert "unavailable_item" not in inst._menu
    assert inst._menu["db_item"]["name"] == "DB Item"


@pytest.mark.asyncio
async def test_reload_menu_from_db_error_keeps_existing():
    inst = OrderState()
    original_count = len(inst._menu)
    with patch("db.database.get_db", side_effect=RuntimeError("db down")), \
         patch("core.capabilities.order.logger"):
        await inst.reload_menu_from_db()
    assert len(inst._menu) == original_count


def test_get_tool_definitions():
    inst = OrderState()
    defs = inst.get_tool_definitions({})
    assert len(defs) == 4
    names = [d["function"]["name"] for d in defs]
    assert "order_add" in names
    assert "order_remove" in names
    assert "order_clear" in names
    assert "order_get_menu" in names


def test_get_tool_names():
    inst = OrderState()
    names = inst.get_tool_names()
    assert names == {"order_add", "order_remove", "order_clear", "order_get_menu"}


@pytest.mark.asyncio
async def test_execute_add(os_instance):
    result = await os_instance.execute_tool("order_add", {"item_key": "completo_normal", "qty": 2}, "+56910000001", "tc1", {})
    assert result["success"] is True
    assert result["action"] == "item_added"
    assert result["order_state"]["items"][0]["key"] == "completo_normal"
    assert result["order_state"]["items"][0]["qty"] == 2
    assert "order_summary" in result


@pytest.mark.asyncio
async def test_execute_add_invalid_item(os_instance):
    result = await os_instance.execute_tool("order_add", {"item_key": "nonexistent_item", "qty": 1}, "+56910000001", "tc2", {})
    assert result["success"] is False
    assert "valid_keys" in result
    assert "instruction" in result


@pytest.mark.asyncio
async def test_execute_add_invalid_qty(os_instance):
    result = await os_instance.execute_tool("order_add", {"item_key": "completo_normal", "qty": 0}, "+56910000001", "tc3", {})
    assert result["success"] is False
    assert "qty" in result["error"]


@pytest.mark.asyncio
async def test_execute_remove(os_instance):
    await os_instance.add_item("+56910000001", "completo_normal", 2)
    result = await os_instance.execute_tool("order_remove", {"item_key": "completo_normal", "qty": 1}, "+56910000001", "tc4", {})
    assert result["success"] is True
    assert result["action"] == "item_removed"


@pytest.mark.asyncio
async def test_execute_clear(os_instance):
    await os_instance.add_item("+56910000001", "completo_normal", 2)
    result = await os_instance.execute_tool("order_clear", {}, "+56910000001", "tc5", {})
    assert result["success"] is True
    assert result["action"] == "order_cleared"
    assert result["order_state"]["total"] == 0


@pytest.mark.asyncio
async def test_execute_get_menu(os_instance):
    result = await os_instance.execute_tool("order_get_menu", {}, "+56910000001", "tc6", {})
    assert result["success"] is True
    assert result["action"] == "get_menu"
    assert len(result["menu"]) > 0


@pytest.mark.asyncio
async def test_execute_unknown_tool(os_instance):
    result = await os_instance.execute_tool("unknown_tool", {}, "+56910000001", "tc7", {})
    assert result["success"] is False
    assert "Unknown tool" in result["error"]


def test_parallel_safe_and_sequential_tools():
    inst = OrderState()
    assert {"order_get_menu", "order_search_item", "order_get_categories"} == inst.PARALLEL_SAFE_TOOLS
    assert {"order_add", "order_remove", "order_clear"} == inst.SEQUENTIAL_TOOLS


def test_tool_definitions_dynamic_from_runtime_menu():
    inst = OrderState()
    inst._menu = {"custom_item": {"name": "Custom Item", "price": 9999}}
    defs = inst.get_tool_definitions({})
    add_def = next(d for d in defs if d["function"]["name"] == "order_add")
    item_key_prop = add_def["function"]["parameters"]["properties"]["item_key"]
    assert item_key_prop.get("enum") == ["custom_item"]


def test_tool_definitions_item_key_has_enum():
    inst = OrderState()
    defs = inst.get_tool_definitions({})
    for tool_name in ("order_add", "order_remove"):
        tool_def = next(d for d in defs if d["function"]["name"] == tool_name)
        item_key_prop = tool_def["function"]["parameters"]["properties"]["item_key"]
        assert "enum" in item_key_prop
        assert set(item_key_prop["enum"]) == set(inst._menu.keys())


def test_tool_definitions_no_claves_in_description():
    inst = OrderState()
    defs = inst.get_tool_definitions({})
    for tool_name in ("order_add", "order_remove"):
        tool_def = next(d for d in defs if d["function"]["name"] == tool_name)
        assert "Claves validas" not in tool_def["function"]["description"]


def test_load_menu_accepts_optional_fields():
    import json
    import os
    import tempfile
    enriched = {
        "test_item": {
            "name": "Test Item",
            "price": 5000,
            "category": "test_cat",
            "description": "A test description",
            "tags": ["vegano", "economico"],
            "size": "grande",
            "conditions": "solo viernes",
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(enriched, f)
        tmp = f.name
    try:
        import core.capabilities.order as mod
        orig = mod.MENU_CONFIG_PATH
        mod.MENU_CONFIG_PATH = tmp
        result = mod._load_menu_from_file()
        mod.MENU_CONFIG_PATH = orig
        assert "test_item" in result
        assert result["test_item"]["category"] == "test_cat"
        assert result["test_item"]["description"] == "A test description"
        assert result["test_item"]["tags"] == ["vegano", "economico"]
        assert result["test_item"]["size"] == "grande"
        assert result["test_item"]["conditions"] == "solo viernes"
    finally:
        os.unlink(tmp)


def test_load_menu_backward_compat_flat():
    import json
    import os
    import tempfile
    flat = {"simple_item": {"name": "Simple", "price": 1000}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(flat, f)
        tmp = f.name
    try:
        import core.capabilities.order as mod
        orig = mod.MENU_CONFIG_PATH
        mod.MENU_CONFIG_PATH = tmp
        result = mod._load_menu_from_file()
        mod.MENU_CONFIG_PATH = orig
        assert "simple_item" in result
        assert result["simple_item"]["name"] == "Simple"
        assert result["simple_item"]["price"] == 1000
        assert "category" not in result["simple_item"]
    finally:
        os.unlink(tmp)


LARGE_MENU = {f"item_{i:03d}": {"name": f"Item {i}", "price": 1000 + i, "category": f"cat_{i % 5}"} for i in range(60)}
LARGE_MENU["choro_beatles_chica"] = {"name": "Chorrillana Beatles Chica", "price": 17900, "category": "chorrillanas", "description": "Papas, carne, longaniza, queso"}
LARGE_MENU["mojito_tradicional"] = {"name": "Mojito Tradicional", "price": 4900, "category": "mojitos", "description": "Ron Blanco, Limon, Menta, Goma, Soda"}


class TestDualModeFlat:
    def test_flat_mode_under_threshold(self):
        inst = OrderState()
        assert not inst.needs_search

    def test_flat_tool_definitions_have_enum(self):
        inst = OrderState()
        defs = inst.get_tool_definitions({})
        names = {d["function"]["name"] for d in defs}
        assert names == {"order_add", "order_remove", "order_clear", "order_get_menu"}
        add_def = next(d for d in defs if d["function"]["name"] == "order_add")
        assert "enum" in add_def["function"]["parameters"]["properties"]["item_key"]

    def test_flat_tool_names(self):
        inst = OrderState()
        assert inst.get_tool_names() == {"order_add", "order_remove", "order_clear", "order_get_menu"}

    def test_flat_format_for_context_has_full_menu(self):
        inst = OrderState()
        inst._ensure_loaded = AsyncMock()
        ctx = __import__("asyncio").run(inst.format_for_context("+5691", {}))
        assert "Menu disponible" in ctx

    def test_flat_get_menu_returns_all_items(self):
        inst = OrderState()
        result = __import__("asyncio").run(inst.execute_tool("order_get_menu", {}, "+5691", "tc", {}))
        assert result["success"] is True
        assert len(result["menu"]) == len(inst._menu)

    @pytest.mark.asyncio
    async def test_flat_add_invalid_key_shows_valid_keys(self):
        inst = OrderState()
        inst._ensure_loaded = AsyncMock()
        result = await inst.execute_tool("order_add", {"item_key": "zzz_fake", "qty": 1}, "+5691", "tc", {})
        assert result["success"] is False
        assert "valid_keys" in result


class TestDualModeSearch:
    def _make_search_instance(self):
        inst = OrderState()
        inst._menu = dict(LARGE_MENU)
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
        assert "order_search_item" in names
        assert "order_get_categories" in names
        assert "order_get_menu" in names
        assert "order_add" in names
        assert "order_remove" in names
        assert "order_clear" in names
        add_def = next(d for d in defs if d["function"]["name"] == "order_add")
        assert "enum" not in add_def["function"]["parameters"]["properties"]["item_key"]

    def test_search_tool_names(self):
        inst = self._make_search_instance()
        names = inst.get_tool_names()
        assert "order_search_item" in names
        assert "order_get_categories" in names
        assert names - {"order_search_item", "order_get_categories"} == {"order_add", "order_remove", "order_clear", "order_get_menu"}

    def test_search_add_description_has_never_invent_key(self):
        inst = self._make_search_instance()
        defs = inst.get_tool_definitions({})
        add_def = next(d for d in defs if d["function"]["name"] == "order_add")
        desc = add_def["function"]["description"]
        assert "NUNCA inventes" in desc or "NUNCA" in desc

    def test_search_format_for_context_no_full_menu(self):
        inst = self._make_search_instance()
        ctx = __import__("asyncio").run(inst.format_for_context("+5691", {}))
        assert "Menu grande" in ctx
        assert "order_search_item" in ctx

    @pytest.mark.asyncio
    async def test_execute_search_item(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("order_search_item", {"query": "chorrillana beatles"}, "+5691", "tc", {})
        assert result["success"] is True
        assert result["action"] == "search_item"
        assert len(result["results"]) > 0
        assert result["results"][0]["item_key"] == "choro_beatles_chica"

    @pytest.mark.asyncio
    async def test_execute_search_item_empty_query(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("order_search_item", {"query": ""}, "+5691", "tc", {})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_get_categories(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("order_get_categories", {}, "+5691", "tc", {})
        assert result["success"] is True
        assert result["action"] == "get_categories"
        assert len(result["categories"]) > 0
        cat_keys = {c["key"] for c in result["categories"]}
        assert "chorrillanas" in cat_keys

    @pytest.mark.asyncio
    async def test_execute_get_menu_with_category(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("order_get_menu", {"category": "chorrillanas"}, "+5691", "tc", {})
        assert result["success"] is True
        assert result.get("category") == "chorrillanas"
        assert len(result["menu"]) > 0

    @pytest.mark.asyncio
    async def test_execute_get_menu_no_category_returns_sample(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("order_get_menu", {}, "+5691", "tc", {})
        assert result["success"] is True
        assert "categories" in result
        assert len(result["menu"]) <= 30

    @pytest.mark.asyncio
    async def test_search_add_invalid_key_no_valid_keys_list(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("order_add", {"item_key": "zzz_fake", "qty": 1}, "+5691", "tc", {})
        assert result["success"] is False
        assert "valid_keys" not in result
        assert "order_search_item" in result["instruction"]

    @pytest.mark.asyncio
    async def test_search_add_valid_key(self):
        inst = self._make_search_instance()
        result = await inst.execute_tool("order_add", {"item_key": "choro_beatles_chica", "qty": 1}, "+5691", "tc", {})
        assert result["success"] is True
        assert result["action"] == "item_added"

    def test_search_index_lazy_init(self):
        inst = self._make_search_instance()
        assert inst._menu_search is None
        search = inst._search
        assert search is not None
        search2 = inst._search
        assert search2 is search

    def test_rebuild_search_resets_index(self):
        inst = self._make_search_instance()
        _ = inst._search
        assert inst._menu_search is not None
        inst._rebuild_search()
        assert inst._menu_search is None
