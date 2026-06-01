from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

AUTH_HEADERS = {"Authorization": "Bearer test_dashboard_token"}

_mock_db = MagicMock()


@pytest.fixture
def client():
    from db.database import get_db
    from main import app

    _mock_db.load_catalog_items = AsyncMock(return_value=[])
    _mock_db.load_catalog_variants = AsyncMock(return_value=[])
    _mock_db.load_catalog_variants_for_item = AsyncMock(return_value=[])
    _mock_db.load_catalog_options = AsyncMock(return_value=[])
    _mock_db.load_promotions = AsyncMock(return_value=[])
    _mock_db.load_promotion_items = AsyncMock(return_value=[])
    _mock_db.load_catalog_item = AsyncMock(return_value=None)
    _mock_db.upsert_catalog_item = AsyncMock()
    _mock_db.upsert_catalog_variant = AsyncMock()
    _mock_db.upsert_catalog_option = AsyncMock()
    _mock_db.upsert_promotion = AsyncMock()
    _mock_db.upsert_promotion_item = AsyncMock()
    _mock_db.delete_catalog_item = AsyncMock()
    _mock_db.delete_catalog_option = AsyncMock()
    _mock_db.delete_promotion_items = AsyncMock()
    _mock_db.delete_promotion = AsyncMock()
    _mock_db.execute = AsyncMock()
    _mock_db.execute_transaction = AsyncMock()

    app.dependency_overrides[get_db] = lambda: _mock_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _item(key="test_item", name="Test Item", price=1000, category="general"):
    return {
        "key": key, "name": name, "price": price, "category": category,
        "subcategory": "", "description": "", "tags": [], "size": "",
        "specifications": "", "is_available": True, "sort_order": 0,
        "base_price": None, "image_url": None,
    }


def test_list_items_empty(client):
    _mock_db.load_catalog_items.return_value = []
    _mock_db.load_catalog_variants.return_value = []
    response = client.get("/api/catalog/items", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_list_items_with_data(client):
    _mock_db.load_catalog_items.return_value = [_item()]
    _mock_db.load_catalog_variants.return_value = []
    response = client.get("/api/catalog/items", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["key"] == "test_item"


def test_get_item(client):
    _mock_db.load_catalog_items.return_value = [_item()]
    _mock_db.load_catalog_variants_for_item.return_value = []
    response = client.get("/api/catalog/items/test_item", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["key"] == "test_item"


def test_get_item_404(client):
    _mock_db.load_catalog_items.return_value = []
    response = client.get("/api/catalog/items/nonexistent", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_create_item(client):
    created_item = _item(key="new_item", name="New Item", price=5000, category="food")
    _mock_db.load_catalog_items.return_value = [created_item]
    _mock_db.load_catalog_variants_for_item.return_value = []
    response = client.post(
        "/api/catalog/items",
        json={"key": "new_item", "name": "New Item", "price": 5000, "category": "food"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key"] == "new_item"
    _mock_db.upsert_catalog_item.assert_called_once()


def test_create_item_with_variants(client):
    _mock_db.load_catalog_items.return_value = [_item(key="burger")]
    _mock_db.load_catalog_variants_for_item.return_value = [
        {"id": 1, "item_key": "burger", "label": "Simple", "price": 3000, "slug": "simple", "sort_order": 0},
    ]
    response = client.post(
        "/api/catalog/items",
        json={
            "key": "burger",
            "name": "Hamburguesa",
            "price": 0,
            "category": "food",
            "variants": [{"label": "Simple", "price": 3000}],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    _mock_db.upsert_catalog_item.assert_called_once()
    _mock_db.upsert_catalog_variant.assert_called_once()


def test_update_item(client):
    _mock_db.load_catalog_item.return_value = _item()
    _mock_db.load_catalog_items.return_value = [_item(key="test_item", name="Updated Item")]
    _mock_db.load_catalog_variants_for_item.return_value = []
    response = client.put(
        "/api/catalog/items/test_item",
        json={"name": "Updated Item"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Item"


def test_update_item_404(client):
    _mock_db.load_catalog_item.return_value = None
    response = client.put(
        "/api/catalog/items/nonexistent",
        json={"name": "X"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


def test_delete_item(client):
    _mock_db.load_catalog_item.return_value = _item()
    response = client.delete("/api/catalog/items/test_item", headers=AUTH_HEADERS)
    assert response.status_code == 200
    _mock_db.delete_catalog_item.assert_called_once()


def test_delete_item_404(client):
    _mock_db.load_catalog_item.return_value = None
    response = client.delete("/api/catalog/items/nonexistent", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_add_variant(client):
    _mock_db.load_catalog_item.return_value = _item()
    _mock_db.load_catalog_variants_for_item.return_value = [
        {"id": 1, "item_key": "test_item", "label": "Grande", "price": 2000, "slug": "grande", "sort_order": 0},
    ]
    response = client.post(
        "/api/catalog/items/test_item/variants",
        json={"label": "Grande", "price": 2000},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["slug"] == "grande"


def test_delete_variant(client):
    _mock_db.load_catalog_variants_for_item.return_value = [
        {"id": 1, "item_key": "test_item", "label": "Grande", "price": 2000, "slug": "grande", "sort_order": 0},
    ]
    response = client.delete("/api/catalog/items/test_item/variants/grande", headers=AUTH_HEADERS)
    assert response.status_code == 200


def test_list_options_empty(client):
    _mock_db.load_catalog_options.return_value = []
    response = client.get("/api/catalog/options", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_create_option(client):
    response = client.post(
        "/api/catalog/options",
        json={"key": "extra_queso", "name": "Extra Queso", "price": 500},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["key"] == "extra_queso"


def test_update_option(client):
    _mock_db.load_catalog_options.return_value = [
        {"key": "extra_queso", "name": "Extra Queso", "price": 500, "category_scope": "*", "sort_order": 0},
    ]
    response = client.put(
        "/api/catalog/options/extra_queso",
        json={"price": 700},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["price"] == 700


def test_delete_option(client):
    _mock_db.load_catalog_options.return_value = [
        {"key": "extra_queso", "name": "Extra Queso", "price": 500, "category_scope": "*", "sort_order": 0},
    ]
    response = client.delete("/api/catalog/options/extra_queso", headers=AUTH_HEADERS)
    assert response.status_code == 200


def test_list_promotions_empty(client):
    _mock_db.load_promotions.return_value = []
    response = client.get("/api/catalog/promotions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_create_promotion(client):
    _mock_db.load_promotions.return_value = [
        {"key": "combo1", "name": "Combo 1", "promotion_type": "fixed_price", "price": 5000,
         "valid_days": "[]", "valid_from": "", "valid_to": "", "terms": "",
         "display_text": "Combo 1", "sort_order": 0},
    ]
    _mock_db.load_promotion_items.return_value = []
    response = client.post(
        "/api/catalog/promotions",
        json={"key": "combo1", "name": "Combo 1", "promotion_type": "fixed_price", "price": 5000},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["key"] == "combo1"


def test_delete_promotion(client):
    _mock_db.load_promotions.return_value = [
        {"key": "combo1", "name": "Combo 1", "promotion_type": "fixed_price", "price": 5000,
         "valid_days": "[]", "valid_from": "", "valid_to": "", "terms": "",
         "display_text": "", "sort_order": 0},
    ]
    response = client.delete("/api/catalog/promotions/combo1", headers=AUTH_HEADERS)
    assert response.status_code == 200


def test_bulk_import(client):
    response = client.post(
        "/api/catalog/bulk-import",
        json={
            "data": {
                "catalog_items": [
                    {"key": "item_a", "name": "Item A", "price": 1000, "category": "food"},
                    {"key": "item_b", "name": "Item B", "price": 2000, "category": "drink"},
                ],
            },
            "clear": False,
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == 2


def test_reload(client):
    mock_cart = MagicMock()
    mock_cart._catalog = {"item_a": {}}
    mock_cart.needs_search = True
    mock_cart.reload_catalog_from_db = AsyncMock()

    with patch("core.container.container.cart_capability", mock_cart):
        response = client.post("/api/catalog/reload", headers=AUTH_HEADERS)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
