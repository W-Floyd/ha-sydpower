"""Binary sensor platform for Sydpower BLE devices."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import get_product_features
from .const import (
    CONF_ADDRESS,
    CONF_MODBUS_COUNT,
    CONF_NAME,
    CONF_PRODUCT_KEY,
    DOMAIN,
)
from .coordinator import SydpowerCoordinator, SydpowerData

_LOGGER = logging.getLogger(__name__)

# Register bank identifiers used in SensorDescription
_HOLDING = "holding"
_INPUT = "input"


@dataclass(frozen=True, kw_only=True)
class SydpowerBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a single Sydpower binary sensor backed by a register bit."""

    register_type: str   # _HOLDING or _INPUT
    register_index: int  # 0-based index into the register list


def _build_descriptions(
    product_key: str,
    modbus_count: int,
) -> list[SydpowerBinarySensorDescription]:
    """Build sensor descriptions from catalog state features."""
    features = get_product_features(product_key)
    states = features.get("states", [])
    descriptions: list[SydpowerBinarySensorDescription] = []

    for state in states:
        name: str = state.get("function_name", "Unknown")
        # Prefer the live input register; fall back to the holding register.
        input_idx: int | None = state.get("input_index")
        holding_idx: int | None = state.get("holding_index")

        if input_idx is not None and input_idx < modbus_count:
            reg_type, reg_idx = _INPUT, input_idx
        elif holding_idx is not None and holding_idx < modbus_count:
            reg_type, reg_idx = _HOLDING, holding_idx
        else:
            continue

        uid = f"{product_key}_{state['id']}"
        descriptions.append(
            SydpowerBinarySensorDescription(
                key=uid,
                name=name,
                register_type=reg_type,
                register_index=reg_idx,
                device_class=BinarySensorDeviceClass.POWER,
            )
        )

        # Child states (individual port / channel statuses)
        for child in state.get("children", []):
            child_name: str = child.get("function_name", "Unknown")
            child_idx: int | None = child.get("input_index")
            if child_idx is None or child_idx >= modbus_count:
                continue
            child_uid = f"{product_key}_{child['id']}"
            descriptions.append(
                SydpowerBinarySensorDescription(
                    key=child_uid,
                    name=f"{name} – {child_name}",
                    register_type=_INPUT,
                    register_index=child_idx,
                    device_class=BinarySensorDeviceClass.POWER,
                )
            )

    return descriptions


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower binary sensors from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]

    product_key: str = entry.data.get(CONF_PRODUCT_KEY, "")
    modbus_count: int = entry.data.get(CONF_MODBUS_COUNT, 85)
    descriptions = _build_descriptions(product_key, modbus_count)

    if not descriptions:
        _LOGGER.warning(
            "No sensor descriptions found for product key %r; "
            "run fetch_catalog.py and restart to populate sensors.",
            product_key,
        )

    async_add_entities(
        SydpowerBinarySensor(coordinator, entry, desc) for desc in descriptions
    )


class SydpowerBinarySensor(PassiveBluetoothCoordinatorEntity, BinarySensorEntity):
    """A binary sensor reading one register index from the Sydpower coordinator."""

    entity_description: SydpowerBinarySensorDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = description.key
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_ADDRESS])},
            name=entry.data[CONF_NAME],
            manufacturer="Sydpower / BrightEMS",
        )

    @property
    def is_on(self) -> bool | None:
        data: SydpowerData | None = self.coordinator.data
        if data is None:
            return None
        registers = (
            data.input
            if self.entity_description.register_type == _INPUT
            else data.holding
        )
        idx = self.entity_description.register_index
        if idx >= len(registers):
            return None
        return registers[idx] != 0
