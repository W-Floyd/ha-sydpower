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
    EntityCategory,
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


# Firmware versions, from the holding bank. The app posts exactly these four
# registers to its backend under these names (app-service.js, the MCU_version
# comparison), and reads a component version as the register's low byte divided
# by ten — so 29 is v2.9. It also gates some setting options on the DC value, so
# these are worth surfacing rather than hiding.
FIRMWARE_REGISTERS: tuple[tuple[str, str, int], ...] = (
    ("ac_version", "AC firmware", 47),
    ("bms_version", "BMS firmware", 48),
    ("pv_version", "PV firmware", 49),
    ("dc_version", "DC firmware", 50),
)


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
        key="input_power",
        name="Input power",
        register=6,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="output_power",
        name="Output power",
        register=39,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="charge_power",
        name="Charge power",
        register=3,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        # Unverified: has read 0 in every sample, consistent with nothing
        # connected to the DC/solar input. The register number comes from the
        # earlier ESP-FBot integration, whose other power indices proved correct
        # on this device.
        key="dc_input_power",
        name="DC input power",
        register=4,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="time_to_full",
        name="Time to full",
        register=58,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
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

# Power and duration registers are raw units — watts and minutes, no divisor.
# Confirmed against the device's own display, which read 628 W in, 380 W out and
# 83 minutes to full while registers 6, 39 and 58 held 628, 380 and 83. The
# device's accounting is internally consistent (6 = 20 + 3, so register 3 is the
# power going into the battery) but its absolute figures are reportedly higher
# than an external meter shows, which is the device's inaccuracy, not a scaling
# error here.
#
# Deliberately not exposed:
#   input 20 — byte-identical to register 39 in every sample; publishing both
#     would be two entities for one measurement.
#   input 21 — tracks register 18 about 0.3 V lower; whether the pair is AC
#     input versus output is unresolved, so only one is published.
#   input 42 — a bitfield, not a wattage, despite its plausible magnitude.
#   input 19 — constant 600, most likely AC input frequency at a different
#     scale from register 22; unconfirmed.


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower sensors from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        SydpowerSensor(coordinator, entry, desc) for desc in SENSOR_DESCRIPTIONS
    ]
    entities += [
        SydpowerFirmwareSensor(coordinator, entry, key, name, register)
        for key, name, register in FIRMWARE_REGISTERS
    ]
    async_add_entities(entities)


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


class SydpowerFirmwareSensor(SydpowerEntity, SensorEntity):
    """A component firmware version, read from the holding bank."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        register: int,
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._register = register

    @property
    def available(self) -> bool:
        return super().available and self._holding(self._register) is not None

    @property
    def native_value(self) -> str | None:
        """
        Format the version the way the app does.

        It takes the register's low byte and divides by ten, so 29 reads as 2.9.
        The high byte is reported alongside when non-zero rather than discarded,
        since its meaning is unconfirmed.
        """
        raw = self._holding(self._register)
        if raw is None:
            return None
        low, high = raw & 0xFF, raw >> 8
        version = f"{low / 10:.1f}"
        return version if high == 0 else f"{version} ({high})"
