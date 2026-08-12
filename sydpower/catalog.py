"""
Product catalog loader.

Maps the BLE advertisement key ``<SERVICE_UUID>_<DEVICE_NAME>`` to per-device
Modbus parameters (address, register count, protocol version). All functions
degrade gracefully when the catalog file is absent — callers receive ``None`` and
fall back to the defaults in ``constants.py``.

``product_catalog.json`` was scraped from the BrightEMS application and carries
only the ``products`` and ``categories`` sections. The original also held a
438 KB ``features`` section, dropped because nothing reads it and its contents
actively mislead: a feature's child ``input_index`` is a sub-index within its
parent, **not** a register number, and reading those as registers produced
wildly wrong sensor values. Its labels are also French. The unabridged file is
kept at ``reference/product_catalog.full.json`` in the repository, outside this
package, because no tooling to regenerate it survives here.
"""

from __future__ import annotations

import json
import pathlib
from typing import TypedDict

_CATALOG_PATH = pathlib.Path(__file__).parent / "product_catalog.json"

# Cached catalog so the file is only read once per process.
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        if _CATALOG_PATH.exists():
            _cache = json.loads(_CATALOG_PATH.read_text())
        else:
            _cache = {}
    return _cache


def invalidate_cache() -> None:
    """Force the next call to re-read the catalog file from disk."""
    global _cache
    _cache = None


class DeviceParams(TypedDict):
    modbus_address: int
    modbus_count: int
    protocol_version: int


def get_device_params(product_key: str) -> DeviceParams | None:
    """
    Return Modbus parameters for a device identified by its *product key*.

    The product key is ``"<SERVICE_UUID>_<DEVICE_NAME>"`` — the same format
    used by the BrightEMS app's ``productMap``.

    Returns ``None`` when the catalog is unavailable or the key is not found.
    """
    catalog = _load()
    product = catalog.get("products", {}).get(product_key)
    if product is None:
        return None

    # modbus_address / modbus_count may be stored directly on the product
    # (added by the updated fetch_catalog.py) or resolved via the category.
    if "modbus_address" in product and "modbus_count" in product:
        return DeviceParams(
            modbus_address=product["modbus_address"],
            modbus_count=product["modbus_count"],
            protocol_version=product.get("protocol_version", 1),
        )

    # Fallback: resolve through category entry.
    category_id = product.get("category_id", "")
    category = catalog.get("categories", {}).get(category_id, {})
    return DeviceParams(
        modbus_address=category.get("modbus_address", 18),
        modbus_count=category.get("modbus_count", 85),
        protocol_version=product.get("protocol_version", 1),
    )


def get_product_model(product_key: str) -> str | None:
    """
    Return the OEM model code for a product key, e.g. ``"P210-A0E01"``.

    Returns ``None`` when the catalog or the key is unavailable. Note the catalog
    has no consumer brand: its largest group is the manufacturer's white-label
    bucket, and resellers such as AFERIY or FOSSiBOT do not appear at all, so the
    model code is the only identity worth reporting.
    """
    product = _load().get("products", {}).get(product_key)
    if product is None:
        return None
    model = product.get("model")
    return model.strip() if isinstance(model, str) and model.strip() else None


def get_product_settings(product_key: str) -> list[dict]:
    """
    Return the writable setting definitions for a product, resolved from the
    shared definition table.

    Each entry carries ``holding_index``, ``data_list`` and optionally ``units``.
    ``units`` is overloaded exactly as the app treats it: when it has as many
    entries as ``data_list`` they are per-option labels, otherwise entry 0 is a
    shared unit.

    The register value is *not* always the option value — see
    ``SETTING_ENCODINGS`` in ``constants.py``.
    """
    catalog = _load()
    product = catalog.get("products", {}).get(product_key)
    if product is None:
        return []
    definitions = catalog.get("settings", [])
    return [
        definitions[i]
        for i in product.get("setting_indexes", [])
        if 0 <= i < len(definitions)
    ]


def list_product_keys() -> list[str]:
    """Return all known product keys from the catalog."""
    return list(_load().get("products", {}).keys())
