"""Number platform for Sydpower BLE devices."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from sydpower.constants import WRITABLE_HOLDING_REGISTERS

from .const import (
    DOMAIN,
    REG_MAX_CHARGE_CURRENT,
    REG_MAX_CHARGE_CURRENT_CEILING,
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
        # The app's slider is min 600, max 1000, step 10 in permille.
        native_min_value=60.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        register=REG_THRESHOLD_CHARGE,
    ),
    SydpowerNumberDescription(
        key="threshold_discharge",
        name="Discharge threshold",
        native_unit_of_measurement=PERCENTAGE,
        # The app's slider is min 0, max 500, step 10 in permille.
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
    entities: list[NumberEntity] = [
        SydpowerNumber(coordinator, entry, desc) for desc in NUMBER_DESCRIPTIONS
    ]
    if REG_MAX_CHARGE_CURRENT in WRITABLE_HOLDING_REGISTERS:
        entities.append(SydpowerChargingCurrent(coordinator, entry))
    async_add_entities(entities)


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


class SydpowerChargingCurrent(SydpowerEntity, NumberEntity):
    """
    Maximum charging current, whose ceiling the device declares.

    The app offers 1 up to the value in holding 17 and writes the choice to holding
    20, so the upper bound is read from the device rather than fixed here. The
    allowlist still applies as a backstop, and the lower of the two is used.

    The name is left unqualified, as the app's own label is. Its page is titled AC
    charging settings, but 20 A at 110 V would exceed the 1100 W charge-power
    ceiling, so it may in fact govern the DC/PV input.
    """

    _attr_name = "Maximum charging current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_min_value = 1
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "max_charge_current")

    @property
    def available(self) -> bool:
        """Needs both its own register and the ceiling the device declares."""
        return (
            super().available
            and self._holding(REG_MAX_CHARGE_CURRENT) is not None
            and bool(self._holding(REG_MAX_CHARGE_CURRENT_CEILING))
        )

    @property
    def native_max_value(self) -> float:
        declared = self._holding(REG_MAX_CHARGE_CURRENT_CEILING) or 0
        permitted = WRITABLE_HOLDING_REGISTERS[REG_MAX_CHARGE_CURRENT][1]
        # Whichever is lower: the device should never be offered more than it
        # declares, and never more than the guard would accept.
        return float(min(declared, permitted)) or 1.0

    @property
    def native_value(self) -> float | None:
        value = self._holding(REG_MAX_CHARGE_CURRENT)
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_register(
            REG_MAX_CHARGE_CURRENT, round(value)
        )
