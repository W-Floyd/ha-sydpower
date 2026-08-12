"""
Sensor platform for Sydpower BLE devices.

Sensors are defined from registers verified against real hardware — see
docs/register-map-v0.md — rather than derived from the product catalog.

The catalog is authoritative for Modbus parameters (slave address, register count,
protocol version), and its ``holding_index`` and ``input_index`` are meaningful —
but neither names an *input* register. ``input_index`` is a bit position in the
combined state word, which is what the binary sensor platform reads it as. Taking
those values for input-register numbers, reading both banks and averaging non-zero
results is what once produced readings like 32,893 W (``0xFFFF`` from a holding
sentinel averaged with an input value), so the measured registers here stay
explicit.

Two of these readings can be corrected for a device defect: while charging, the
device under-reports its output, and its total input with it. Nothing is corrected
unless configured — see ``sydpower.calibration``.
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

from sydpower.catalog import state_word

from .const import DOMAIN, INPUT_SCHEDULED_CHARGE_COUNTDOWN, STATE_AC_BIT
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity


# Register 41 is the state word's high half, so its AC bit sits 16 places up.
AC_OUTPUT_STATE_BIT = 16 + STATE_AC_BIT.bit_length() - 1

# Charge power, which gates the output correction: the under-report has only been
# observed while charging, and in pass-through the output figure was accurate.
REG_CHARGE_POWER = 3


# Firmware versions, from the holding bank. The app posts exactly these four
# registers to its backend under these names (app-service.js, the MCU_version
# comparison), and reads a component version as the register's low byte divided
# by ten — so 29 is v2.9. It also gates some setting options on the DC value, so
# these are worth surfacing rather than hiding.
FIRMWARE_REGISTERS: tuple[tuple[str, str, int], ...] = (
    ("ac_version", "AC firmware", 47),
    ("bms_version", "BMS firmware", 48),
    ("pv_version", "PV firmware", 49),
    # The app's constant for register 50 is Panel_Version, though it posts the
    # same value to its backend as DC_version, and gates setting options on it.
    ("dc_version", "Panel firmware", 50),
)


@dataclass(frozen=True, kw_only=True)
class SydpowerSensorDescription(SensorEntityDescription):
    """Describes a sensor backed by one input register."""

    register: int
    # Raw register value is divided by this to reach the reported unit.
    divisor: float = 1.0
    # Bit of the state word that must be set for the reading to mean anything. The
    # inverter's output voltage, for instance, floats when the output is off.
    requires_state_bit: int | None = None
    # Whether the configured output-power correction applies to this reading. Both
    # the output figure and the total input are affected, the latter because the
    # device derives it from the former.
    correctable: bool = False


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
        key="ac_input_frequency",
        name="AC input frequency",
        register=22,
        divisor=100,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        # Input side, not output: with the mains unplugged this went to 0 while the
        # inverter was still running and producing 120.7 V on register 18. Left
        # ungated for that reason — 0 Hz alongside register 21's 0 V is an accurate
        # report of "no mains", not the floating noise that gating exists to hide.
    ),
    SydpowerSensorDescription(
        key="ac_input_voltage",
        name="AC input voltage",
        register=21,
        divisor=10,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="ac_output_voltage",
        name="AC output voltage",
        register=18,
        divisor=10,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # Unenergised, this register floats: with the output off it was seen
        # reporting 139.8, 69.2, 118.4, 90.9 and 69.4 V in consecutive polls, while
        # the mains reading held steady. Reporting nothing beats recording noise.
        requires_state_bit=AC_OUTPUT_STATE_BIT,
    ),
    SydpowerSensorDescription(
        key="input_power",
        correctable=True,
        name="Input power",
        register=6,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        key="output_power",
        correctable=True,
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
        # Confirmed once solar was producing with the mains disconnected: 162 W
        # then 151 W, having read 0 in every earlier sample for want of anything
        # connected. Register 6 equalled it exactly in those frames.
        key="dc_input_power",
        name="DC input power",
        register=4,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SydpowerSensorDescription(
        # The countdown the app polls to confirm a schedule took effect. Zero when
        # no charge is scheduled.
        key="scheduled_charge_countdown",
        name="Scheduled charge in",
        register=INPUT_SCHEDULED_CHARGE_COUNTDOWN,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
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
#   Registers 18 and 21 are now distinguished. Both read about 118 V while the AC
#   output is on, but with it off register 21 held steady while 18 floated across
#   139.8, 69.2, 118.4, 90.9 and 69.4 V — so 21 is the mains input and 18 the
#   inverter output.
#   input 42 — a bitfield, not a wattage, despite its plausible magnitude.
#   input 19 — constant 600. Not a frequency measurement: it held 600 with the
#     mains unplugged and again with the inverter off, where any live frequency
#     reading drops to zero as register 22 does. That invariance makes it a
#     nominal rating rather than a measurement, and 60.0 Hz is the plausible
#     reading for a 120 V unit. A constant is not worth an entity either way.


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

    def _meaningful(self) -> bool:
        """False when this reading's precondition is not met."""
        bit = self.entity_description.requires_state_bit
        if bit is None:
            return True
        data = self.coordinator.data
        word = None if data is None else state_word(data.input)
        return word is not None and bool(word >> bit & 1)

    @property
    def native_value(self) -> float | int | None:
        if not self._meaningful():
            return None
        value = self._input(self.entity_description.register)
        if value is None:
            return None
        divisor = self.entity_description.divisor
        correction = self._correction()
        if divisor == 1 and not correction:
            # Raw watts and minutes stay integers rather than gaining a ".0".
            return value
        return round(value / divisor + correction, 2)

    def _correction(self) -> float:
        """
        Watts to add to this reading, per the entry's options.

        Zero unless this is one of the affected registers and calibration samples
        have been recorded. The device is only known to under-report while charging,
        so the model gates itself on charge power rather than applying always.
        """
        if not self.entity_description.correctable:
            return 0.0
        return self.coordinator.correction.watts(self._input(REG_CHARGE_POWER))


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
