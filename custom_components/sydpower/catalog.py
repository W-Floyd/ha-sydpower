"""
Local product catalog reader for the Sydpower HA integration.

The catalog file is shipped alongside this integration (or copied here by
running ``python apk_analysis/fetch_catalog.py``).  All functions degrade
gracefully when the file is absent.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

_CATALOG_PATH = pathlib.Path(__file__).parent / "product_catalog.json"
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        if _CATALOG_PATH.exists():
            _cache = json.loads(_CATALOG_PATH.read_text())
        else:
            _cache = {}
    return _cache


def get_product_features(product_key: str) -> dict[str, list[dict[str, Any]]]:
    """
    Return ``{"states": [...], "settings": [...]}`` for the given product key.

    Returns an empty dict when the catalog or product is not found.
    """
    catalog = _load()
    product = catalog.get("products", {}).get(product_key)
    if product is None:
        return {}
    product_id = product.get("product_id", "")
    return catalog.get("features", {}).get(product_id, {})
