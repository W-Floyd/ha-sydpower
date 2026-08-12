"""
Binary sensor platform for Sydpower BLE devices.

Output states come from the bitfield in input register 41, whose bits were
confirmed by toggling each output in isolation on real hardware. See
docs/register-map-v0.md.

These report the device's own view of what is live, which is not always the same
as the control register a switch writes: the light's control register can hold a
mode value while bit 12 simply reports whether it is lit.
"""

from __future__ import annotations

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

from sydpower.catalog import active_faults, fault_value, get_faults

from .const import (
    DOMAIN,
    STATE_AC_BIT,
    STATE_DC_BIT,
    STATE_LIGHT_BIT,
    STATE_REGISTER,
    STATE_USB_BIT,
)
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity


@dataclass(frozen=True, kw_only=True)
class SydpowerBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor backed by one bit of an input register."""

    register: int
    bit_mask: int


BINARY_SENSOR_DESCRIPTIONS: tuple[SydpowerBinarySensorDescription, ...] = (
    SydpowerBinarySensorDescription(
        key="usb_active",
        name="USB output",
        register=STATE_REGISTER,
        bit_mask=STATE_USB_BIT,
        device_class=BinarySensorDeviceClass.POWER,
    ),
    SydpowerBinarySensorDescription(
        key="dc_active",
        name="DC output",
        register=STATE_REGISTER,
        bit_mask=STATE_DC_BIT,
        device_class=BinarySensorDeviceClass.POWER,
    ),
    SydpowerBinarySensorDescription(
        key="ac_active",
        name="AC output",
        register=STATE_REGISTER,
        bit_mask=STATE_AC_BIT,
        device_class=BinarySensorDeviceClass.POWER,
    ),
    SydpowerBinarySensorDescription(
        key="light_active",
        name="Light",
        register=STATE_REGISTER,
        bit_mask=STATE_LIGHT_BIT,
        device_class=BinarySensorDeviceClass.LIGHT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower binary sensors from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = [
        SydpowerBinarySensor(coordinator, entry, desc)
        for desc in BINARY_SENSOR_DESCRIPTIONS
    ]
    entities.append(SydpowerConnectivitySensor(coordinator, entry))
    if get_faults():
        entities.append(SydpowerProblemSensor(coordinator, entry))
    async_add_entities(entities)


class SydpowerBinarySensor(SydpowerEntity, BinarySensorEntity):
    """A binary sensor reading one bit of the output state bitfield."""

    entity_description: SydpowerBinarySensorDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerBinarySensorDescription,
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
    def is_on(self) -> bool | None:
        value = self._input(self.entity_description.register)
        if value is None:
            return None
        return bool(value & self.entity_description.bit_mask)


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
