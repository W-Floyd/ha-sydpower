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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    async_add_entities(
        SydpowerBinarySensor(coordinator, entry, desc)
        for desc in BINARY_SENSOR_DESCRIPTIONS
    )


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
