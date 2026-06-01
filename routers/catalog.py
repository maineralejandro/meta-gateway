import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.database import Database, get_db

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


class VariantCreate(BaseModel):
    label: str
    price: int
    slug: str | None = None
    sort_order: int = 0


class VariantUpdate(BaseModel):
    label: str | None = None
    price: int | None = None
    slug: str | None = None
    sort_order: int | None = None


class VariantResponse(BaseModel):
    id: int
    item_key: str
    label: str
    price: int
    slug: str
    sort_order: int


class CatalogItemCreate(BaseModel):
    key: str
    name: str
    price: int
    category: str = "general"
    subcategory: str = ""
    description: str = ""
    tags: list[str] = []
    size: str = ""
    specifications: str = ""
    is_available: bool = True
    sort_order: int = 0
    base_price: int | None = None
    image_url: str | None = None
    variants: list[VariantCreate] = []


class CatalogItemUpdate(BaseModel):
    name: str | None = None
    price: int | None = None
    category: str | None = None
    subcategory: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    size: str | None = None
    specifications: str | None = None
    is_available: bool | None = None
    sort_order: int | None = None
    base_price: int | None = None
    image_url: str | None = None


class CatalogItemResponse(BaseModel):
    key: str
    name: str
    price: int
    category: str
    subcategory: str
    description: str
    tags: list[str] | str
    size: str
    specifications: str
    is_available: bool
    sort_order: int
    base_price: int | None
    image_url: str | None
    variants: list[VariantResponse] = []


class OptionCreate(BaseModel):
    key: str
    name: str
    price: int
    category_scope: str = "*"
    sort_order: int = 0


class OptionUpdate(BaseModel):
    name: str | None = None
    price: int | None = None
    category_scope: str | None = None
    sort_order: int | None = None


class OptionResponse(BaseModel):
    key: str
    name: str
    price: int
    category_scope: str
    sort_order: int


class PromotionItemCreate(BaseModel):
    item_key: str
    promotion_price: int | None = None


class PromotionItemResponse(BaseModel):
    promotion_key: str
    item_key: str
    promotion_price: int | None


class PromotionCreate(BaseModel):
    key: str
    name: str
    promotion_type: str = "fixed_price"
    price: int | None = None
    valid_days: list[str] = []
    valid_from: str = ""
    valid_to: str = ""
    terms: str = ""
    display_text: str = ""
    sort_order: int = 0
    items: list[PromotionItemCreate] = []


class PromotionUpdate(BaseModel):
    name: str | None = None
    promotion_type: str | None = None
    price: int | None = None
    valid_days: list[str] | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    terms: str | None = None
    display_text: str | None = None
    sort_order: int | None = None
    items: list[PromotionItemCreate] | None = None


class PromotionResponse(BaseModel):
    key: str
    name: str
    promotion_type: str
    price: int | None
    valid_days: list[str] | str
    valid_from: str
    valid_to: str
    terms: str
    display_text: str
    sort_order: int
    items: list[PromotionItemResponse] = []


class BulkImportRequest(BaseModel):
    data: dict[str, Any]
    clear: bool = False


async def _reload_catalog() -> None:
    from core.capabilities.base import registry
    from core.container import container

    if container.cart_capability is not None:
        await container.cart_capability.reload_catalog_from_db()
    registry.invalidate()


def _parse_tags(tags: Any) -> list[str]:
    if isinstance(tags, list):
        return list(tags)
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            return list(parsed) if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _parse_valid_days(vd: Any) -> list[str]:
    if isinstance(vd, list):
        return list(vd)
    if isinstance(vd, str):
        try:
            parsed = json.loads(vd)
            return list(parsed) if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


@router.get("/items", response_model=list[CatalogItemResponse])
async def list_items(db: Database = Depends(get_db)) -> Any:
    items = await db.load_catalog_items()
    all_variants = await db.load_catalog_variants()
    variants_by_key: dict[str, list[dict[str, Any]]] = {}
    for v in all_variants:
        variants_by_key.setdefault(v["item_key"], []).append(v)
    result = []
    for item in items:
        item_variants = variants_by_key.get(item["key"], [])
        result.append({
            **item,
            "tags": _parse_tags(item.get("tags", [])),
            "variants": [
                {
                    "id": v["id"],
                    "item_key": v["item_key"],
                    "label": v["label"],
                    "price": v["price"],
                    "slug": v["slug"],
                    "sort_order": v["sort_order"],
                }
                for v in item_variants
            ],
        })
    return result


@router.get("/items/{key}", response_model=CatalogItemResponse)
async def get_item(key: str, db: Database = Depends(get_db)) -> Any:
    items = await db.load_catalog_items()
    item = next((i for i in items if i["key"] == key), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    variants = await db.load_catalog_variants_for_item(key)
    return {
        **item,
        "tags": _parse_tags(item.get("tags", [])),
        "variants": [
            {
                "id": v["id"],
                "item_key": v["item_key"],
                "label": v["label"],
                "price": v["price"],
                "slug": v["slug"],
                "sort_order": v["sort_order"],
            }
            for v in variants
        ],
    }


@router.post("/items", response_model=CatalogItemResponse)
async def create_item(item_in: CatalogItemCreate, db: Database = Depends(get_db)) -> Any:
    from core.utils import slugify

    tags_json = json.dumps(item_in.tags)
    await db.upsert_catalog_item(
        key=item_in.key,
        name=item_in.name,
        price=item_in.price,
        category=item_in.category,
        is_available=item_in.is_available,
        sort_order=item_in.sort_order,
        description=item_in.description,
        tags=tags_json,
        size=item_in.size,
        specifications=item_in.specifications,
        subcategory=item_in.subcategory,
        base_price=item_in.base_price,
        image_url=item_in.image_url,
    )
    for v_idx, variant in enumerate(item_in.variants):
        v_slug = variant.slug or slugify(variant.label)
        await db.upsert_catalog_variant(item_in.key, variant.label, variant.price, v_slug, v_idx)
    await _reload_catalog()
    return await get_item(item_in.key, db)


@router.put("/items/{key}", response_model=CatalogItemResponse)
async def update_item(key: str, item_in: CatalogItemUpdate, db: Database = Depends(get_db)) -> Any:
    existing = await db.load_catalog_item(key)
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")

    update_fields = item_in.model_dump(exclude_unset=True)
    if not update_fields:
        return await get_item(key, db)

    new_name = update_fields.get("name", existing["name"])
    new_price = update_fields.get("price", existing["price"])
    new_category = update_fields.get("category", existing["category"])
    new_subcategory = update_fields.get("subcategory", existing.get("subcategory", ""))
    new_description = update_fields.get("description", existing.get("description", ""))
    new_tags = update_fields.get("tags", _parse_tags(existing.get("tags", [])))
    new_size = update_fields.get("size", existing.get("size", ""))
    new_specifications = update_fields.get("specifications", existing.get("specifications", ""))
    new_is_available = update_fields.get("is_available", existing.get("is_available", True))
    new_sort_order = update_fields.get("sort_order", existing.get("sort_order", 0))
    new_base_price = update_fields.get("base_price", existing.get("base_price"))
    new_image_url = update_fields.get("image_url", existing.get("image_url"))

    tags_json = json.dumps(new_tags) if isinstance(new_tags, list) else new_tags

    await db.upsert_catalog_item(
        key=key,
        name=new_name,
        price=new_price,
        category=new_category,
        is_available=new_is_available,
        sort_order=new_sort_order,
        description=new_description,
        tags=tags_json,
        size=new_size,
        specifications=new_specifications,
        subcategory=new_subcategory,
        base_price=new_base_price,
        image_url=new_image_url,
    )
    await _reload_catalog()
    return await get_item(key, db)


@router.delete("/items/{key}")
async def delete_item(key: str, db: Database = Depends(get_db)) -> dict[str, str]:
    existing = await db.load_catalog_item(key)
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete_catalog_item(key)
    await _reload_catalog()
    return {"status": "ok"}


@router.post("/items/{key}/variants", response_model=VariantResponse)
async def add_variant(key: str, variant_in: VariantCreate, db: Database = Depends(get_db)) -> Any:
    from core.utils import slugify

    existing = await db.load_catalog_item(key)
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")
    v_slug = variant_in.slug or slugify(variant_in.label)
    await db.upsert_catalog_variant(key, variant_in.label, variant_in.price, v_slug, variant_in.sort_order)
    await _reload_catalog()
    variants = await db.load_catalog_variants_for_item(key)
    for v in variants:
        if v["slug"] == v_slug:
            return v
    raise HTTPException(status_code=500, detail="Variant creation failed")


@router.put("/items/{key}/variants/{slug}", response_model=VariantResponse)
async def update_variant(key: str, slug: str, variant_in: VariantUpdate, db: Database = Depends(get_db)) -> Any:
    variants = await db.load_catalog_variants_for_item(key)
    existing = next((v for v in variants if v["slug"] == slug), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Variant not found")

    new_label = variant_in.label if variant_in.label is not None else existing["label"]
    new_price = variant_in.price if variant_in.price is not None else existing["price"]
    new_slug = variant_in.slug if variant_in.slug is not None else existing["slug"]
    new_sort = variant_in.sort_order if variant_in.sort_order is not None else existing["sort_order"]

    await db.upsert_catalog_variant(key, new_label, new_price, new_slug, new_sort)
    await _reload_catalog()
    updated_variants = await db.load_catalog_variants_for_item(key)
    for v in updated_variants:
        if v["slug"] == new_slug:
            return v
    raise HTTPException(status_code=404, detail="Updated variant not found")


@router.delete("/items/{key}/variants/{slug}")
async def delete_variant(key: str, slug: str, db: Database = Depends(get_db)) -> dict[str, str]:
    variants = await db.load_catalog_variants_for_item(key)
    existing = next((v for v in variants if v["slug"] == slug), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Variant not found")
    await db.execute(
        "DELETE FROM catalog_item_variants WHERE item_key=$1 AND slug=$2",
        key, slug,
    )
    await _reload_catalog()
    return {"status": "ok"}


@router.get("/options", response_model=list[OptionResponse])
async def list_options(db: Database = Depends(get_db)) -> Any:
    return await db.load_catalog_options()


@router.post("/options", response_model=OptionResponse)
async def create_option(opt_in: OptionCreate, db: Database = Depends(get_db)) -> Any:
    await db.upsert_catalog_option(opt_in.key, opt_in.name, opt_in.price, opt_in.category_scope, opt_in.sort_order)
    return {"key": opt_in.key, "name": opt_in.name, "price": opt_in.price, "category_scope": opt_in.category_scope, "sort_order": opt_in.sort_order}


@router.put("/options/{key}", response_model=OptionResponse)
async def update_option(key: str, opt_in: OptionUpdate, db: Database = Depends(get_db)) -> Any:
    options = await db.load_catalog_options()
    existing = next((o for o in options if o["key"] == key), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Option not found")

    new_name = opt_in.name if opt_in.name is not None else existing["name"]
    new_price = opt_in.price if opt_in.price is not None else existing["price"]
    new_scope = opt_in.category_scope if opt_in.category_scope is not None else existing["category_scope"]
    new_sort = opt_in.sort_order if opt_in.sort_order is not None else existing["sort_order"]

    await db.upsert_catalog_option(key, new_name, new_price, new_scope, new_sort)
    return {"key": key, "name": new_name, "price": new_price, "category_scope": new_scope, "sort_order": new_sort}


@router.delete("/options/{key}")
async def delete_option(key: str, db: Database = Depends(get_db)) -> dict[str, str]:
    options = await db.load_catalog_options()
    if not any(o["key"] == key for o in options):
        raise HTTPException(status_code=404, detail="Option not found")
    await db.delete_catalog_option(key)
    return {"status": "ok"}


@router.get("/promotions", response_model=list[PromotionResponse])
async def list_promotions(db: Database = Depends(get_db)) -> Any:
    promos = await db.load_promotions()
    result = []
    for p in promos:
        p_items = await db.load_promotion_items(p["key"])
        result.append({
            **p,
            "valid_days": _parse_valid_days(p.get("valid_days", [])),
            "items": [
                {
                    "promotion_key": pi["promotion_key"],
                    "item_key": pi["item_key"],
                    "promotion_price": pi.get("promotion_price"),
                }
                for pi in p_items
            ],
        })
    return result


@router.post("/promotions", response_model=PromotionResponse)
async def create_promotion(promo_in: PromotionCreate, db: Database = Depends(get_db)) -> Any:
    valid_days_json = json.dumps(promo_in.valid_days)
    await db.upsert_promotion(
        key=promo_in.key,
        name=promo_in.name,
        promotion_type=promo_in.promotion_type,
        price=promo_in.price,
        valid_days=valid_days_json,
        valid_from=promo_in.valid_from,
        valid_to=promo_in.valid_to,
        terms=promo_in.terms,
        display_text=promo_in.display_text,
        sort_order=promo_in.sort_order,
    )
    if promo_in.items:
        await db.delete_promotion_items(promo_in.key)
        for pi in promo_in.items:
            await db.upsert_promotion_item(promo_in.key, pi.item_key, pi.promotion_price)
    await _reload_catalog()
    promos = await db.load_promotions()
    created = next((p for p in promos if p["key"] == promo_in.key), None)
    if not created:
        raise HTTPException(status_code=500, detail="Promotion creation failed")
    p_items = await db.load_promotion_items(promo_in.key)
    return {
        **created,
        "valid_days": _parse_valid_days(created.get("valid_days", [])),
        "items": [
            {"promotion_key": pi["promotion_key"], "item_key": pi["item_key"], "promotion_price": pi.get("promotion_price")}
            for pi in p_items
        ],
    }


@router.put("/promotions/{key}", response_model=PromotionResponse)
async def update_promotion(key: str, promo_in: PromotionUpdate, db: Database = Depends(get_db)) -> Any:
    promos = await db.load_promotions()
    existing = next((p for p in promos if p["key"] == key), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Promotion not found")

    update_fields = promo_in.model_dump(exclude_unset=True)
    if not update_fields:
        return await _promotion_response(key, db)

    new_name = update_fields.get("name", existing["name"])
    new_type = update_fields.get("promotion_type", existing["promotion_type"])
    new_price = update_fields.get("price", existing.get("price"))
    new_valid_days = update_fields.get("valid_days", _parse_valid_days(existing.get("valid_days", [])))
    new_valid_from = update_fields.get("valid_from", existing.get("valid_from", ""))
    new_valid_to = update_fields.get("valid_to", existing.get("valid_to", ""))
    new_terms = update_fields.get("terms", existing.get("terms", ""))
    new_display = update_fields.get("display_text", existing.get("display_text", ""))
    new_sort = update_fields.get("sort_order", existing.get("sort_order", 0))

    valid_days_json = json.dumps(new_valid_days) if isinstance(new_valid_days, list) else new_valid_days

    await db.upsert_promotion(
        key=key,
        name=new_name,
        promotion_type=new_type,
        price=new_price,
        valid_days=valid_days_json,
        valid_from=new_valid_from,
        valid_to=new_valid_to,
        terms=new_terms,
        display_text=new_display,
        sort_order=new_sort,
    )

    if "items" in update_fields and update_fields["items"] is not None:
        await db.delete_promotion_items(key)
        for pi in update_fields["items"]:
            await db.upsert_promotion_item(key, pi["item_key"], pi.get("promotion_price"))

    await _reload_catalog()
    return await _promotion_response(key, db)


@router.delete("/promotions/{key}")
async def delete_promotion(key: str, db: Database = Depends(get_db)) -> dict[str, str]:
    promos = await db.load_promotions()
    if not any(p["key"] == key for p in promos):
        raise HTTPException(status_code=404, detail="Promotion not found")
    await db.delete_promotion(key)
    await _reload_catalog()
    return {"status": "ok"}


async def _promotion_response(key: str, db: Database) -> dict[str, Any]:
    promos = await db.load_promotions()
    promo = next((p for p in promos if p["key"] == key), None)
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    p_items = await db.load_promotion_items(key)
    return {
        **promo,
        "valid_days": _parse_valid_days(promo.get("valid_days", [])),
        "items": [
            {"promotion_key": pi["promotion_key"], "item_key": pi["item_key"], "promotion_price": pi.get("promotion_price")}
            for pi in p_items
        ],
    }


@router.post("/bulk-import")
async def bulk_import(req: BulkImportRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
    from core.utils import slugify

    data = req.data
    if req.clear:
        await db.execute("DELETE FROM promotion_items")
        await db.execute("DELETE FROM promotions")
        await db.execute("DELETE FROM catalog_options")
        await db.execute("DELETE FROM catalog_item_variants")
        await db.execute("DELETE FROM catalog_items")

    item_count = 0
    variant_count = 0
    option_count = 0
    promo_count = 0

    if "catalog_items" in data:
        for item_data in data["catalog_items"]:
            i_key = item_data.get("key", "")
            if not i_key:
                continue
            i_name = item_data.get("name", "")
            i_category = item_data.get("category", "general")
            i_subcategory = item_data.get("subcategory", "")
            i_description = item_data.get("description", "")
            i_specifications = item_data.get("specifications", "")
            i_tags = item_data.get("tags", [])
            i_tags_json = json.dumps(i_tags) if isinstance(i_tags, list) else item_data.get("tags", "[]")
            i_is_available = item_data.get("is_available", True)
            i_size = item_data.get("size", "")
            i_image_url = item_data.get("image_url")

            variants = item_data.get("variants", [])
            if variants:
                i_base_price = None
                i_price_val = 0
            else:
                i_base_price = item_data.get("price", 0)
                i_price_val = i_base_price or 0

            await db.upsert_catalog_item(
                key=i_key,
                name=i_name,
                price=i_price_val,
                category=i_category,
                is_available=i_is_available,
                sort_order=item_count,
                description=i_description,
                tags=i_tags_json,
                size=i_size,
                specifications=i_specifications,
                subcategory=i_subcategory,
                base_price=i_base_price,
                image_url=i_image_url,
            )
            for v_idx, variant in enumerate(variants):
                v_label = variant.get("label", "")
                v_price = int(variant.get("price", 0))
                v_slug = variant.get("slug") or slugify(v_label)
                await db.upsert_catalog_variant(i_key, v_label, v_price, v_slug, v_idx)
                variant_count += 1
            item_count += 1
    else:
        for i_key, item in data.items():
            if isinstance(item, dict) and "name" in item and "price" in item:
                i_tags = item.get("tags", [])
                i_tags_json = json.dumps(i_tags) if isinstance(i_tags, list) else item.get("tags", "[]")
                await db.upsert_catalog_item(
                    key=i_key,
                    name=item["name"],
                    price=int(item["price"]),
                    category=item.get("category", "general"),
                    is_available=True,
                    sort_order=item_count,
                    description=item.get("description", ""),
                    tags=i_tags_json,
                    size=item.get("size", ""),
                    specifications=item.get("specifications", ""),
                    subcategory=item.get("subcategory", ""),
                )
                item_count += 1

    for opt_data in data.get("options", []):
        await db.upsert_catalog_option(
            opt_data["key"], opt_data["name"], opt_data["price"],
            opt_data.get("category_scope", "*"), opt_data.get("sort_order", 0),
        )
        option_count += 1

    for promo_data in data.get("promotions", []):
        p_key = promo_data.get("key", "")
        if not p_key:
            continue
        p_valid_days = json.dumps(promo_data.get("valid_days", []))
        await db.upsert_promotion(
            key=p_key,
            name=promo_data.get("name", ""),
            promotion_type=promo_data.get("promotion_type", "fixed_price"),
            price=promo_data.get("price"),
            valid_days=p_valid_days,
            valid_from=promo_data.get("valid_from", ""),
            valid_to=promo_data.get("valid_to", ""),
            terms=promo_data.get("terms", ""),
            display_text=promo_data.get("display_text", ""),
            sort_order=promo_data.get("sort_order", 0),
        )
        for pi in promo_data.get("items", []):
            await db.upsert_promotion_item(p_key, pi["item_key"], pi.get("promotion_price"))
        promo_count += 1

    await _reload_catalog()
    return {
        "status": "ok",
        "items": item_count,
        "variants": variant_count,
        "options": option_count,
        "promotions": promo_count,
    }


@router.post("/reload")
async def reload_catalog() -> dict[str, Any]:
    from core.container import container

    cart_cap = container.cart_capability
    await cart_cap.reload_catalog_from_db()
    from core.capabilities.base import registry
    registry.invalidate()
    return {
        "status": "ok",
        "catalog_items": len(cart_cap._catalog),
        "needs_search": cart_cap.needs_search,
    }
