"""
Binary sensor platform for Sydpower BLE devices.

Output and port states are built from the product catalog. A state's catalog
``input_index`` is not a register: it is a bit position in the 32-bit word the app
assembles from two input registers, the first supplying bits 0-15 and the second
bits 16-31. That is why indices 25, 26, 27 and 28 are the USB, DC, AC and light
outputs — they are bits 9 to 12 of register 41. Verified against hardware for
every parent and every port on this device.

Because the catalog also describes each output's individual ports, this yields
per-port sensors rather than only the four outputs, and works for any product in
the catalog. Products the catalog does not describe fall back to the four
hardcoded bits.

These report the device's own view of what is live, which is not always the same
as the control register a switch writes: the light's control register holds a mode
value while its state bit simply reports whether it is lit.

A state that carries a control register is marked diagnostic, since a control
writes that register and is therefore the primary entity for it. That is read from
the catalog: only parent states carry one, so the field's presence is the signal
and no list of registers has to be maintained alongside. Such a sensor is still
worth having, because it reads the state word rather than the control register and
so confirms independently that a write took effect. Children have no register,
nothing writes them, and they are the only view of which port is live — so they
stay primary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from sydpower.catalog import (
    active_faults,
    fault_value,
    get_faults,
    get_product_states,
    state_word,
)

from .const import (
    CONF_PRODUCT_KEY,
    DOMAIN,
    REG_LIGHT_CONTROL,
    STATE_AC_BIT,
    STATE_DC_BIT,
    STATE_LIGHT_BIT,
    STATE_USB_BIT,
)
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity

_LOGGER = logging.getLogger(__name__)

# Register 41 occupies the word's high half, so its bit 9 is word bit 25.
_HIGH_HALF = 16

# Stable keys for the four outputs, so entity ids survive these becoming
# catalog-derived rather than hardcoded.
STABLE_KEYS: dict[int, tuple[str, BinarySensorDeviceClass]] = {
    _HIGH_HALF + STATE_USB_BIT.bit_length() - 1: ("usb_active", BinarySensorDeviceClass.POWER),
    _HIGH_HALF + STATE_DC_BIT.bit_length() - 1: ("dc_active", BinarySensorDeviceClass.POWER),
    _HIGH_HALF + STATE_AC_BIT.bit_length() - 1: ("ac_active", BinarySensorDeviceClass.POWER),
    _HIGH_HALF + STATE_LIGHT_BIT.bit_length() - 1: ("light_active", BinarySensorDeviceClass.LIGHT),
}


@dataclass(frozen=True, kw_only=True)
class SydpowerBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor backed by one bit of the state word."""

    bit: int


def _describe(
    bit: int, name: str, *, diagnostic: bool = False
) -> SydpowerBinarySensorDescription:
    key, device_class = STABLE_KEYS.get(
        bit, (f"state_{bit}", BinarySensorDeviceClass.POWER)
    )
    return SydpowerBinarySensorDescription(
        key=key,
        name=name,
        bit=bit,
        device_class=device_class,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
    )


def _catalog_descriptions(product_key: str) -> list[SydpowerBinarySensorDescription]:
    """Build a description per catalog state, ports included."""
    states = get_product_states(product_key)
    if not states:
        return []

    by_id = {s["id"]: s for s in states if s.get("id")}
    descriptions: list[SydpowerBinarySensorDescription] = []
    seen: set[int] = set()

    for state in states:
        bit = state.get("input_index")
        if bit is None:
            continue

        parent = by_id.get(state.get("parent_id", ""))
        if parent is not None and parent.get("holding_index") == REG_LIGHT_CONTROL:
            # The light's children are its modes, and their indices are register
            # values rather than word bits — they collide with USB port bits.
            continue
        if bit in seen:
            _LOGGER.debug(
                "Skipping duplicate state bit %d (%s)", bit, state.get("function_name")
            )
            continue
        seen.add(bit)

        name = state.get("function_name") or f"Bit {bit}"
        if parent is not None:
            name = f"{parent.get('function_name', '')} {name}".strip()
        # A state carrying a control register is something a control writes, so
        # its sensor is diagnostic and the control is the primary entity. Children
        # have no register of their own, nothing writes them, and they are the only
        # view of which port is live — so they stay primary. Read from the catalog
        # rather than a list of registers kept in step by hand.
        diagnostic = "holding_index" in state
        descriptions.append(_describe(bit, name, diagnostic=diagnostic))

    return _number_duplicates(descriptions)


def _number_duplicates(
    descriptions: list[SydpowerBinarySensorDescription],
) -> list[SydpowerBinarySensorDescription]:
    """
    Number repeated names, e.g. three "PD 20W" ports become "PD 20W 1..3".

    Several ports of the same kind share a name in the catalog. Left alone, Home
    Assistant would disambiguate the entity ids with _2 and _3 suffixes while the
    friendly names stayed identical, which is worse than numbering them.
    """
    counts: dict[str, int] = {}
    for description in descriptions:
        counts[description.name] = counts.get(description.name, 0) + 1

    running: dict[str, int] = {}
    result: list[SydpowerBinarySensorDescription] = []
    for description in descriptions:
        name = description.name
        if counts[name] > 1:
            running[name] = running.get(name, 0) + 1
            name = f"{name} {running[name]}"
        result.append(
            SydpowerBinarySensorDescription(
                key=description.key,
                name=name,
                bit=description.bit,
                device_class=description.device_class,
                entity_category=description.entity_category,
            )
        )
    return result


def _fallback_descriptions() -> list[SydpowerBinarySensorDescription]:
    """
    The four outputs, for products the catalog does not describe.

    All four mirror a control, so all four are diagnostic.
    """
    return [
        _describe(_HIGH_HALF + STATE_USB_BIT.bit_length() - 1, "USB output", diagnostic=True),
        _describe(_HIGH_HALF + STATE_DC_BIT.bit_length() - 1, "DC output", diagnostic=True),
        _describe(_HIGH_HALF + STATE_AC_BIT.bit_length() - 1, "AC output", diagnostic=True),
        _describe(_HIGH_HALF + STATE_LIGHT_BIT.bit_length() - 1, "Light", diagnostic=True),
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower binary sensors from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    product_key = entry.data.get(CONF_PRODUCT_KEY) or ""

    descriptions = _catalog_descriptions(product_key)
    if descriptions:
        _LOGGER.debug("Built %d state sensor(s) from the catalog", len(descriptions))
    else:
        descriptions = _fallback_descriptions()
        _LOGGER.debug("No catalog states for %r; using the four outputs", product_key)

    entities: list[BinarySensorEntity] = [
        SydpowerBinarySensor(coordinator, entry, desc) for desc in descriptions
    ]
    entities.append(SydpowerConnectivitySensor(coordinator, entry))
    if get_faults():
        entities.append(SydpowerProblemSensor(coordinator, entry))
    async_add_entities(entities)


class SydpowerBinarySensor(SydpowerEntity, BinarySensorEntity):
    """A binary sensor reading one bit of the combined state word."""

    entity_description: SydpowerBinarySensorDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    def _word(self) -> int | None:
        data = self.coordinator.data
        return None if data is None else state_word(data.input)

    @property
    def available(self) -> bool:
        return super().available and self._word() is not None

    @property
    def is_on(self) -> bool | None:
        word = self._word()
        return None if word is None else bool(word >> self.entity_description.bit & 1)


class SydpowerConnectivitySensor(SydpowerEntity, BinarySensorEntity):
    """
    Whether the last poll reached the device.

    This integration opens a connection per poll rather than holding one open, so
    there is no persistent link to report. What matters is reachability, which is
    what ``last_update_success`` records.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Connected"

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "connected")

    @property
    def available(self) -> bool:
        """
        Always available, so it can report being disconnected.

        This must override the property rather than set ``_attr_available``:
        ``CoordinatorEntity.available`` returns ``last_update_success and
        super().available``, so the attribute alone would leave this entity
        unavailable exactly when it has something worth saying.
        """
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class SydpowerProblemSensor(SydpowerEntity, BinarySensorEntity):
    """
    On when the device reports any fault.

    The catalog defines five fault groups over input-bank registers, decoded bit
    by bit — 42 named bits in total. Exposing each as its own entity would bury
    the device in mostly-inactive sensors, so this reports whether anything is
    wrong and lists the active messages as attributes.

    Only *named* bits count. Some bits are set on a perfectly healthy device
    (registers 47 and 48 read 0x3000 and 0x4000 here) and carry no fault message;
    the app ignores those, and so does this.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Problem"

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "problem")

    def _messages(self) -> list[str] | None:
        data = self.coordinator.data
        if data is None:
            return None
        return active_faults(data.input)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def is_on(self) -> bool | None:
        messages = self._messages()
        return None if messages is None else bool(messages)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """List the active faults, plus each group's raw value for debugging."""
        messages = self._messages() or []
        attributes: dict[str, object] = {"active_faults": messages}

        data = self.coordinator.data
        if data is not None:
            raw = {}
            for group in get_faults():
                value = fault_value(group.get("registers") or [], data.input)
                if value is not None:
                    raw[group["name"]] = f"0x{value:08X}"
            attributes["raw"] = raw
        return attributes
