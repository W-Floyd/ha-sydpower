"""
Product catalog loader.

Maps the BLE advertisement key ``<SERVICE_UUID>_<DEVICE_NAME>`` to per-device
Modbus parameters (address, register count, protocol version). All functions
degrade gracefully when the catalog file is absent — callers receive ``None`` and
fall back to the defaults in ``constants.py``.

``product_catalog.json`` is generated from the BrightEMS application by
``analysis/extract_catalog.py``, which unpacks the XAPK, beautifies the uni-app
bundle and normalises what it finds into ``products``, ``categories``,
``settings``, ``states``, ``faults`` and ``firmware_gates``.

``input_index`` and ``holding_index`` are both meaningful, contrary to an earlier
reading of this file that treated them as unusable sub-indexes:

* ``holding_index`` is a real holding-register number. Verified against hardware
  for all four controls and all seven settings of the test device.
* ``input_index`` is a **bit position in the combined 32-bit state word** — input
  register 42 as the low half and 41 as the high half, see ``state_word`` — not
  an input-register number. Read as register numbers these produced wildly wrong
  values, which is what the earlier reading was reacting to. As bit positions all
  17 states of the test device validated.

Labels are English in the generated file; the app ships French and Chinese
strings for some products, which ``fault_messages.py`` overrides on read.
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


def preload() -> None:
    """
    Read and cache the catalog now, so later lookups touch no disk.

    Every accessor loads the file on first use, which is fine for a script but not
    for an asyncio application: Home Assistant detects the read inside its event
    loop and warns. Calling this once from an executor thread — before anything
    that queries the catalog — leaves the rest of the accessors pure cache reads.
    """
    _load()


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


# Register holding the panel firmware version. The app's own constant is
# `Panel_Version`, though it posts the same register to its backend as
# `DC_version`.
PANEL_VERSION_REGISTER = 50

# The app combines two input registers into one 32-bit state word: the first
# supplies bits 0-15 and the second bits 16-31. A state's catalog `input_index`
# is a bit position in that word, not a register number — which is why 25, 26, 27
# and 28 are the USB, DC, AC and light outputs, being bits 9 to 12 of register 41.
STATE_WORD_REGISTERS = (42, 41)


def state_word(input_registers: list[int]) -> int | None:
    """Combine the two state registers into the app's 32-bit status word."""
    low, high = STATE_WORD_REGISTERS
    if max(low, high) >= len(input_registers):
        return None
    return input_registers[low] | (input_registers[high] << 16)


def get_product_states(product_key: str) -> list[dict]:
    """
    Return a product's state definitions, resolved from the shared table.

    Each entry has a ``function_name`` and an ``input_index`` giving its bit in
    :func:`state_word`. Entries with a ``parent_id`` are ports or modes belonging
    to the output named by that parent.
    """
    catalog = _load()
    product = catalog.get("products", {}).get(product_key)
    if product is None:
        return []
    definitions = catalog.get("states", [])
    return [
        definitions[i]
        for i in product.get("state_indexes", [])
        if 0 <= i < len(definitions)
    ]


def gated_setting_options(
    setting: dict,
    product_name: str,
    panel_version_raw: int | None,
) -> list[int]:
    """
    Return a setting's options with any firmware-gated ones removed.

    Some product and panel-version combinations cannot honour every option the
    catalog lists, and the app hides those. For the AC no-load standby timer it
    drops the zero ("never turn off") option when the device's product name and
    panel version match a rule in the gate table:

        if rule.product_name == product_name
           and 10 * float(rule.panel_version) == panel_version_low:
               options = [o for o in options if o > 0]

    ``panel_version_raw`` is the raw value of the panel version register; only its
    low byte is compared, and the app reads it as tenths, so 29 means 2.9.

    Without a gate table — it needs an authenticated fetch — this returns the
    options unchanged.
    """
    options = list(setting.get("data_list") or [])
    rules = _load().get("firmware_gates", {}).get("ac_standby_time") or []
    if not rules or panel_version_raw is None:
        return options

    low = panel_version_raw & 0xFF
    for rule in rules:
        try:
            version = float(rule.get("panel_version"))
        except (TypeError, ValueError):
            continue
        if rule.get("product_name") == product_name and round(10 * version) == low:
            return [o for o in options if o > 0]
    return options


def get_output_children(product_key: str, control_register: int) -> list[tuple[int, str]]:
    """
    Return ``(input_index, name)`` for the children of the output controlled by
    *control_register*, sorted by index.

    What the index *means* depends on the output, and the caller must know which:

    * For most outputs the children are ports and the index is a bit in
      :func:`state_word` — the six USB ports of register 24, for instance.
    * For the light the children are its modes, and the index is the value written
      to its control register: 1, 2 and 3 for steady, SOS and flashing. These
      collide numerically with the USB port bits, which is exactly why the
      distinction cannot be inferred from the catalog alone.

    Returns an empty list when the catalog does not describe the product or the
    register names no output.
    """
    states = get_product_states(product_key)
    parent = next(
        (
            s
            for s in states
            if s.get("holding_index") == control_register and not s.get("parent_id")
        ),
        None,
    )
    if parent is None:
        return []
    children = [
        (s["input_index"], s.get("function_name") or f"Child {s['input_index']}")
        for s in states
        if s.get("parent_id") == parent.get("id") and s.get("input_index") is not None
    ]
    return sorted(children)


def get_faults() -> list[dict]:
    """
    Return the fault group definitions: name, input registers, and named bits.

    Registers are in the **input** bank. The numbers overlap the firmware version
    registers at holding 47-50, which are a different address space entirely.
    """
    return _load().get("faults", [])


def fault_value(registers: list[int], input_registers: list[int]) -> int | None:
    """
    Combine a fault group's registers into one bitfield.

    A single register supplies bits 0-15. Two registers are combined the way the
    app does it: the *second* register provides the low 16 bits and the first the
    high 16, so a 32-bit group's bit 17 is bit 1 of its first register.
    """
    if not registers or any(r >= len(input_registers) for r in registers):
        return None
    if len(registers) == 1:
        return input_registers[registers[0]]
    if len(registers) == 2:
        return input_registers[registers[1]] | (input_registers[registers[0]] << 16)
    return None


def active_faults(input_registers: list[int]) -> list[str]:
    """
    Return the messages for every named fault bit currently set.

    Messages the backend leaves untranslated are replaced with English wording;
    see ``fault_messages.py``.
    """
    from .fault_messages import translate_fault

    messages: list[str] = []
    for group in get_faults():
        value = fault_value(group.get("registers") or [], input_registers)
        if value is None:
            continue
        for bit, message in sorted(
            group.get("bits", {}).items(), key=lambda kv: int(kv[0])
        ):
            if message and value >> int(bit) & 1:
                messages.append(translate_fault(message))
    return messages


def list_product_keys() -> list[str]:
    """Return all known product keys from the catalog."""
    return list(_load().get("products", {}).keys())
