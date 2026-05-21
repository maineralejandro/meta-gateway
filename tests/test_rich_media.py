from unittest.mock import AsyncMock, patch

import pytest

from core.capabilities.cart import CartCapability


@pytest.fixture
def cart():
    c = CartCapability()
    c._carts = {}
    c._loaded_phones = set()
    c._catalog = {
        "item_a": {"name": "Producto A", "price": 5000, "image_url": "https://img.example.com/a.jpg", "category": "food"},
        "item_b": {"name": "Producto B", "price": 3000, "category": "drinks"},
        "item_c": {"name": "Producto C", "price": 7000, "image_url": "https://img.example.com/c.jpg", "category": "food"},
    }
    c._options = {}
    c._promotions = []
    c._catalog_search = None
    return c


@pytest.mark.asyncio
async def test_send_product_image_success(cart):
    mock_meta = AsyncMock()
    mock_meta.send_image = AsyncMock(return_value={"messages": [{"id": "wamid_img"}]})

    with patch("core.meta_client.meta_client", mock_meta):
        result = await cart._execute_send_product_image({"item_key": "item_a"}, "56912345678")

    assert result["success"] is True
    assert result["action"] == "send_product_image"
    assert result["image_url"] == "https://img.example.com/a.jpg"
    mock_meta.send_image.assert_called_once()
    call_args = mock_meta.send_image.call_args
    assert call_args[0][1] == "https://img.example.com/a.jpg"


@pytest.mark.asyncio
async def test_send_product_image_no_image(cart):
    result = await cart._execute_send_product_image({"item_key": "item_b"}, "56912345678")

    assert result["success"] is False
    assert "no tiene imagen" in result["error"]


@pytest.mark.asyncio
async def test_send_product_image_not_found(cart):
    result = await cart._execute_send_product_image({"item_key": "nonexistent"}, "56912345678")

    assert result["success"] is False
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_send_product_image_empty_key(cart):
    result = await cart._execute_send_product_image({"item_key": ""}, "56912345678")

    assert result["success"] is False
    assert "item_key is required" in result["error"]


@pytest.mark.asyncio
async def test_send_product_image_meta_error(cart):
    mock_meta = AsyncMock()
    mock_meta.send_image = AsyncMock(return_value={"error": True, "status": 401, "detail": "Unauthorized"})

    with patch("core.meta_client.meta_client", mock_meta):
        result = await cart._execute_send_product_image({"item_key": "item_a"}, "56912345678")

    assert result["success"] is False
    assert "Error enviando imagen" in result["error"]


@pytest.mark.asyncio
async def test_show_category_menu_success(cart):
    from core.capabilities.catalog_search import CatalogSearch

    cs = CatalogSearch(cart._catalog)
    cs.build_index()
    cart._catalog_search = cs

    mock_meta = AsyncMock()
    mock_meta.send_interactive_list = AsyncMock(return_value={"messages": [{"id": "wamid_list"}]})

    with patch("core.meta_client.meta_client", mock_meta):
        result = await cart._execute_show_category_menu("56912345678")

    assert result["success"] is True
    assert result["action"] == "show_category_menu"
    mock_meta.send_interactive_list.assert_called_once()
    call_args = mock_meta.send_interactive_list.call_args
    sections = call_args[0][3] if len(call_args[0]) > 3 else call_args[1].get("sections", [])
    assert len(sections) > 0
    row_ids = [r["id"] for r in sections[0]["rows"]]
    assert any("category_" in rid for rid in row_ids)


@pytest.mark.asyncio
async def test_show_category_menu_meta_error(cart):
    from core.capabilities.catalog_search import CatalogSearch

    cs = CatalogSearch(cart._catalog)
    cs.build_index()
    cart._catalog_search = cs

    mock_meta = AsyncMock()
    mock_meta.send_interactive_list = AsyncMock(return_value={"error": True, "status": 500, "detail": "Internal error"})

    with patch("core.meta_client.meta_client", mock_meta):
        result = await cart._execute_show_category_menu("56912345678")

    assert result["success"] is False
    assert "Error enviando menu" in result["error"]


@pytest.mark.asyncio
async def test_show_category_menu_empty_catalog():
    c = CartCapability()
    c._carts = {}
    c._loaded_phones = set()
    c._catalog = {}
    c._options = {}
    c._promotions = []
    c._catalog_search = None

    result = await c._execute_show_category_menu("56912345678")

    assert result["success"] is False


@pytest.mark.asyncio
async def test_execute_tool_send_product_image(cart):
    mock_meta = AsyncMock()
    mock_meta.send_image = AsyncMock(return_value={"messages": [{"id": "wamid_img"}]})

    with patch("core.meta_client.meta_client", mock_meta):
        result = await cart.execute_tool("send_product_image", {"item_key": "item_a"}, "56912345678", "tc_1", {})

    assert result["success"] is True


@pytest.mark.asyncio
async def test_execute_tool_show_category_menu(cart):
    from core.capabilities.catalog_search import CatalogSearch

    cs = CatalogSearch(cart._catalog)
    cs.build_index()
    cart._catalog_search = cs

    mock_meta = AsyncMock()
    mock_meta.send_interactive_list = AsyncMock(return_value={"messages": [{"id": "wamid_list"}]})

    with patch("core.meta_client.meta_client", mock_meta):
        result = await cart.execute_tool("show_category_menu", {}, "56912345678", "tc_1", {})

    assert result["success"] is True


def test_tool_names_include_new_tools():
    c = CartCapability()
    c._catalog = {"a": {"name": "A", "price": 100, "category": "x"}}
    c._catalog_search = None
    names = c.get_tool_names()
    assert "send_product_image" in names
    assert "show_category_menu" in names


def test_flat_tool_names_include_new_tools():
    c = CartCapability()
    c._catalog = {"a": {"name": "A", "price": 100}}
    c._catalog_search = None
    names = c.get_tool_names()
    assert "send_product_image" in names
    assert "show_category_menu" in names


def test_tool_definitions_include_send_product_image():
    c = CartCapability()
    c._catalog = {"a": {"name": "A", "price": 100}}
    c._catalog_search = None
    defs = c.get_tool_definitions({})
    tool_names = [d["function"]["name"] for d in defs]
    assert "send_product_image" in tool_names
    assert "show_category_menu" in tool_names
