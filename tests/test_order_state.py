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
    assert result is None


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
