import re
from typing import Any

import structlog
from rank_bm25 import BM25Okapi

logger = structlog.get_logger()

SEARCH_THRESHOLD = 50

_ACCENT_MAP = str.maketrans(
    "áàäéèëíìïóòöúùüñ", "aaaeeeiiiooouuun"
)
_STOPWORDS = frozenset({
    "de", "la", "el", "los", "las", "con", "sin", "por", "para",
    "una", "uno", "unos", "unas", "del", "que", "en", "y", "o",
    "se", "es", "lo", "su", "un", "al", "no", "si", "mi",
})


def tokenize(text: str) -> list[str]:
    normalized = text.lower().translate(_ACCENT_MAP)
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return [t for t in normalized.split() if len(t) > 2 and t not in _STOPWORDS]


def _build_searchable_text(item: dict[str, Any]) -> str:
    parts = [item.get("name", "")]
    cat = item.get("category")
    sub = item.get("subcategory")
    if cat and sub:
        parts.append(f"{cat} {sub}")
    elif cat:
        parts.append(cat)
    if sub:
        parts.append(sub)
    desc = item.get("description")
    if desc:
        parts.append(desc)
    size = item.get("size")
    if size:
        parts.append(size)
    specs = item.get("specifications")
    if specs:
        parts.append(specs)
    tags = item.get("tags")
    if isinstance(tags, list):
        parts.extend(tags)
    return " ".join(filter(None, parts))


class CatalogSearch:
    def __init__(self, catalog: dict[str, dict[str, Any]]) -> None:
        self._catalog = catalog
        self._keys: list[str] = []
        self._docs: list[str] = []
        self._bm25: BM25Okapi | None = None
        self._categories: dict[str, dict[str, Any]] = {}

    @property
    def needs_search(self) -> bool:
        return len(self._catalog) > SEARCH_THRESHOLD

    def build_index(self) -> None:
        self._keys = []
        self._docs = []
        self._categories = {}
        for key, item in sorted(self._catalog.items()):
            self._keys.append(key)
            self._docs.append(_build_searchable_text(item))
            cat = item.get("category", "general")
            if cat not in self._categories:
                self._categories[cat] = {
                    "key": cat,
                    "display_name": cat.replace("_", " ").title(),
                    "item_count": 0,
                    "min_price": float("inf"),
                }
            self._categories[cat]["item_count"] += 1
            price = item.get("price", 0)
            if price < self._categories[cat]["min_price"]:
                self._categories[cat]["min_price"] = price
        for cat_data in self._categories.values():
            if cat_data["min_price"] == float("inf"):
                cat_data["min_price"] = 0
        tokenized = [tokenize(doc) for doc in self._docs]
        self._bm25 = BM25Okapi(tokenized)
        logger.info("catalog_search_index_built", items=len(self._keys), categories=len(self._categories))

    def search(self, query: str, top_k: int = 5, min_score: float = 0.01) -> list[dict[str, Any]]:
        if not self._bm25:
            return []
        tokenized_query = tokenize(query)
        if not tokenized_query:
            return []
        scores = self._bm25.get_scores(tokenized_query)
        scored = [(i, s) for i, s in enumerate(scores) if s > min_score]
        scored.sort(key=lambda x: x[1], reverse=True)
        top_indices = [idx for idx, _ in scored[:top_k]]
        results = []
        for idx in top_indices:
            key = self._keys[idx]
            item = self._catalog[key]
            result: dict[str, Any] = {
                "item_key": key,
                "name": item.get("name", key),
                "price": item.get("price", 0),
            }
            for field in ("category", "subcategory", "description", "size", "specifications"):
                if field in item:
                    result[field] = item[field]
            if "tags" in item:
                result["tags"] = item["tags"]
            results.append(result)
        return results

    def get_categories(self) -> list[dict[str, Any]]:
        return sorted(self._categories.values(), key=lambda c: c["display_name"])

    def get_items_by_category(self, category: str) -> list[dict[str, Any]]:
        results = []
        for key in self._keys:
            item = self._catalog[key]
            if item.get("category", "general") == category:
                result: dict[str, Any] = {
                    "item_key": key,
                    "name": item.get("name", key),
                    "price": item.get("price", 0),
                }
                for field in ("subcategory", "description", "size", "specifications"):
                    if field in item:
                        result[field] = item[field]
                if "tags" in item:
                    result["tags"] = item["tags"]
                results.append(result)
        return results
