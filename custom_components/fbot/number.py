"""Number platform for the Fbot integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    REG_THRESHOLD_CHARGE,
    REG_THRESHOLD_DISCHARGE,
    KEY_THRESHOLD_CHARGE,
    KEY_THRESHOLD_DISCHARGE,
)
from .coordinator import FbotCoordinator


@dataclass(frozen=True, kw_only=True)
class FbotNumberEntityDescription(NumberEntityDescription):
    """Extends NumberEntityDescription with Fbot-specific fields."""
    data_key: str
    register: int
    # Values are stored in permille on the device; multiply by 10 before writing.
    scale: float = 10.0


NUMBER_DESCRIPTIONS: tuple[FbotNumberEntityDescription, ...] = (
    FbotNumberEntityDescription(
        key="threshold_charge",
        data_key=KEY_THRESHOLD_CHARGE,
        name="Charge Threshold",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=10.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        register=REG_THRESHOLD_CHARGE,
    ),
    FbotNumberEntityDescription(
        key="threshold_discharge",
        data_key=KEY_THRESHOLD_DISCHARGE,
        name="Discharge Threshold",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0.0,
        native_max_value=50.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        register=REG_THRESHOLD_DISCHARGE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FbotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        FbotNumber(coordinator, description) for description in NUMBER_DESCRIPTIONS
    )


class FbotNumber(CoordinatorEntity[FbotCoordinator], NumberEntity):
    """A number entity for adjustable Fbot thresholds."""

    _attr_has_entity_name = True
    entity_description: FbotNumberEntityDescription

    def __init__(
        self,
        coordinator: FbotCoordinator,
        description: FbotNumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name="Fbot Battery Station",
            manufacturer="Fbot",
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.entity_description.data_key in (self.coordinator.data or {})
        )

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get(self.entity_description.data_key)

    async def async_set_native_value(self, value: float) -> None:
        # Device stores values in permille (e.g. 80% → register value 800)
        reg_value = int(value * self.entity_description.scale)
        await self.coordinator.async_send_command(
            self.entity_description.register, reg_value
        )
