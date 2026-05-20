import re

_ACCENT_MAP = str.maketrans(
    "\u00e1\u00e0\u00e4\u00e9\u00e8\u00eb\u00ed\u00ec\u00ef\u00f3\u00f2\u00f6\u00fa\u00f9\u00fc\u00f1",
    "aaaeeeiiiooouuun",
)


def slugify(text: str) -> str:
    normalized = text.lower().translate(_ACCENT_MAP)
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\s+", "_", normalized.strip())
    return normalized
