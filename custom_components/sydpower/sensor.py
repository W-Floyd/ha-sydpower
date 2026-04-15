"""Sensor platform for Sydpower BLE devices."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
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


def _is_parent_sensor_state(state: dict) -> bool:
    """
    Determine if a state's children represent modes of a single entity
    (should be combined) rather than separate output ports.

    Returns True for 'Lampe LED' type sensors where children are modes.
    Returns False for 'Sortie DC' type sensors where children are separate ports.
    """
    function_name = state.get("function_name", "")

    # Sortie DC type sensors - children are separate output ports
    # These should be separate sensors
    if function_name.startswith("Sortie"):
        return False

    # Default: treat as separate sensors
    return True


def _build_descriptions(
    product_key: str,
    modbus_count: int,
) -> list[SensorEntityDescription]:
    """
    Build sensor descriptions from catalog state features.

    Handles both combined and separate children:
    - Lampe LED: children represent modes, combined into single sensor
    - Sortie DC: children represent separate ports, separate sensors
    """
    features = get_product_features(product_key)
    states = features.get("states", [])
    descriptions: list[SensorEntityDescription] = []

    for state in states:
        name: str = state.get("function_name", "Unknown")
        # Prefer the live input register; fall back to the holding register.
        input_idx: int | None = state.get("input_index")
        holding_idx: int | None = state.get("holding_index")

        # Determine if this is a combined state or separate children
        is_combined = _is_parent_sensor_state(state)

        # Find the primary index for the parent state
        if input_idx is not None and input_idx < modbus_count:
            parent_idx = input_idx
        elif holding_idx is not None and holding_idx < modbus_count:
            parent_idx = holding_idx
        else:
            continue

        child_indices = []

        # Collect child indices for combined states
        if is_combined:
            for child in state.get("children", []):
                child_input_idx: int | None = child.get("input_index")
                if child_input_idx is not None and child_input_idx < modbus_count:
                    child_indices.append(child_input_idx)

            # Create a single sensor description that reads all relevant indices
            if child_indices:
                # Get the lowest index for the main register
                child_idx = min(child_indices)
                child_uid = f"{product_key}_{state['id']}"
                descriptions.append(
                    SydpowerSensorDescription(
                        key=child_uid,
                        name=name,
                        register_indices=[child_idx, *child_indices],
                        state_class=SensorStateClass.MEASUREMENT,
                        device_class=SensorDeviceClass.POWER,
                        unit_of_measurement=UnitOfPower.WATT,
                    )
                )
        else:
            # Create a main sensor for the parent state
            parent_uid = f"{product_key}_{state['id']}"
            descriptions.append(
                SydpowerSensorDescription(
                    key=parent_uid,
                    name=name,
                    register_indices=[parent_idx],
                    state_class=SensorStateClass.MEASUREMENT,
                    device_class=SensorDeviceClass.POWER,
                    unit_of_measurement=UnitOfPower.WATT,
                )
            )

            # Create separate sensors for each child (output ports)
            for child in state.get("children", []):
                child_name: str = child.get("function_name", "Unknown")
                child_idx: int | None = child.get("input_index")
                if child_idx is None or child_idx >= modbus_count:
                    continue

                child_uid = f"{product_key}_{child['id']}"
                descriptions.append(
                    SydpowerSensorDescription(
                        key=child_uid,
                        name=f"{name} - {child_name}",
                        register_indices=[child_idx],
                        state_class=SensorStateClass.MEASUREMENT,
                        device_class=SensorDeviceClass.POWER,
                        unit_of_measurement=UnitOfPower.WATT,
                    )
                )

    return descriptions


@dataclass(frozen=True, kw_only=True)
class SydpowerSensorDescription(SensorEntityDescription):
    """Describes a single Sydpower sensor backed by register indices."""

    register_indices: list[int]  # 0-based indices into the register list


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower sensors from a config entry."""
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
        SydpowerSensor(coordinator, entry, desc) for desc in descriptions
    )


class SydpowerSensor(PassiveBluetoothCoordinatorEntity, SensorEntity):
    """A sensor reading multiple register indices from the Sydpower coordinator."""

    entity_description: SydpowerSensorDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerSensorDescription,
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
    def native_value(self) -> float | None:
        data: SydpowerData | None = self.coordinator.data
        if data is None:
            return None

        # Collect values from all relevant indices
        combined_value: float | None = None

        for reg_type in [_INPUT, _HOLDING]:
            registers = data.input if reg_type == _INPUT else data.holding
            for idx in self.entity_description.register_indices:
                if idx >= len(registers):
                    continue
                val = registers[idx]
                if isinstance(val, (int, float)) and val != 0:
                    # Use the first non-zero value found, or average if multiple
                    if combined_value is None:
                        combined_value = float(val)
                    else:
                        # Average multiple non-zero values
                        combined_value = (combined_value + float(val)) / 2

        return round(combined_value, 2) if combined_value is not None else None
