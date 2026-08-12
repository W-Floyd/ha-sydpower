"""
Sensor platform for Sydpower BLE devices.

Sensors are defined from registers verified against real hardware — see
docs/register-map-v0.md — rather than derived from the product catalog.

The catalog is authoritative for Modbus parameters (slave address, register
count, protocol version) but its feature indices are not register numbers on
this hardware: a child entry's ``input_index`` is a sub-index within its parent.
The light's children are ``1``, ``2`` and ``3`` — register 27's *values* for
on/SOS/flashing — and the USB children are ``3, 4, 6, 7`` while the measured
port-power registers are 30, 31 and 35. Reading those as register numbers, from
both banks, and averaging non-zero results produced readings like 32,893 W
(``0xFFFF`` from a holding sentinel averaged with an input value).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity


@dataclass(frozen=True, kw_only=True)
class SydpowerSensorDescription(SensorEntityDescription):
    """Describes a sensor backed by one input register."""

    register: int
    # Raw register value is divided by this to reach the reported unit.
    divisor: float = 1.0


SENSOR_DESCRIPTIONS: tuple[SydpowerSensorDescription, ...] = (
    SydpowerSensorDescription(
        key="battery",
        name="Battery",
        register=56,
        divisor=10,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="remaining_time",
        name="Remaining time",
        register=59,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="ac_frequency",
        name="AC frequency",
        register=22,
        divisor=100,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="ac_voltage",
        name="AC voltage",
        register=18,
        divisor=10,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="light_power",
        name="Light power",
        register=15,
        divisor=10,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="usb_a1_power",
        name="USB-A port 1 power",
        register=30,
        divisor=10,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="usb_a2_power",
        name="USB-A port 2 power",
        register=31,
        divisor=10,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="usb_c_power",
        name="USB-C port power",
        register=35,
        divisor=10,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

# Deliberately not exposed:
#   input 6, 20, 39 — a reproducible relationship to each other, but the
#     quantity and scale are unresolved; absolute values shifted between
#     sessions under identical output state.
#   input 21 — tracks register 18 about 0.3 V lower; whether the pair is AC
#     input versus output is unresolved, so only one is published.
#   input 42 — a bitfield, not a wattage, despite its plausible magnitude.


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower sensors from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SydpowerSensor(coordinator, entry, desc) for desc in SENSOR_DESCRIPTIONS
    )


class SydpowerSensor(SydpowerEntity, SensorEntity):
    """A sensor reading one input register, scaled to its reported unit."""

    entity_description: SydpowerSensorDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._input(self.entity_description.register) is not None
        )

    @property
    def native_value(self) -> float | int | None:
        value = self._input(self.entity_description.register)
        if value is None:
            return None
        divisor = self.entity_description.divisor
        if divisor == 1:
            return value
        return round(value / divisor, 2)
