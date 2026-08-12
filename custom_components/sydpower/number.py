"""Number platform for Sydpower BLE devices."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    REG_THRESHOLD_CHARGE,
    REG_THRESHOLD_DISCHARGE,
    THRESHOLD_SCALE,
)
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity


@dataclass(frozen=True, kw_only=True)
class SydpowerNumberDescription(NumberEntityDescription):
    """Describes a number backed by a single holding register."""

    register: int


# The min/max here constrain the UI. They deliberately mirror the ranges in the
# library's WRITABLE_HOLDING_REGISTERS, which is the real enforcement point — a
# value arriving from a service call or template is validated there regardless of
# what this platform advertises.
NUMBER_DESCRIPTIONS: tuple[SydpowerNumberDescription, ...] = (
    SydpowerNumberDescription(
        key="threshold_charge",
        name="Charge threshold",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=10.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        register=REG_THRESHOLD_CHARGE,
    ),
    SydpowerNumberDescription(
        key="threshold_discharge",
        name="Discharge threshold",
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
    """Set up Sydpower number entities from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SydpowerNumber(coordinator, entry, desc) for desc in NUMBER_DESCRIPTIONS
    )


class SydpowerNumber(SydpowerEntity, NumberEntity):
    """A charge or discharge threshold, stored on the device in permille."""

    entity_description: SydpowerNumberDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerNumberDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self._holding(
            self.entity_description.register
        ) is not None

    @property
    def native_value(self) -> float | None:
        value = self._holding(self.entity_description.register)
        return None if value is None else value / THRESHOLD_SCALE

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_register(
            self.entity_description.register, round(value * THRESHOLD_SCALE)
        )
