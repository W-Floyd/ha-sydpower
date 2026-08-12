"""Switch platform for Sydpower BLE devices."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    REG_AC_CONTROL,
    REG_AC_SILENT_CONTROL,
    REG_DC_CONTROL,
    REG_KEY_SOUND,
    REG_USB_CONTROL,
)
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SydpowerSwitchDescription(SwitchEntityDescription):
    """Describes a switch backed by a single holding register."""

    register: int


# The light is deliberately absent: it holds a mode rather than a boolean, so it
# is a light entity with effects (see light.py) instead of a switch plus a select.
#
# State is read back from the same holding register that is written, so the
# entity can never disagree with what was commanded. Input register 41 also
# carries live output bits (see const.STATE_*), but the control register is the
# authoritative round-trip and was verified to match physical state on hardware.
SWITCH_DESCRIPTIONS: tuple[SydpowerSwitchDescription, ...] = (
    SydpowerSwitchDescription(key="usb", name="USB", register=REG_USB_CONTROL),
    SydpowerSwitchDescription(key="dc", name="DC", register=REG_DC_CONTROL),
    SydpowerSwitchDescription(key="ac", name="AC", register=REG_AC_CONTROL),
    SydpowerSwitchDescription(
        key="ac_silent", name="AC silent charging", register=REG_AC_SILENT_CONTROL
    ),
    SydpowerSwitchDescription(
        key="key_sound", name="Key sound", register=REG_KEY_SOUND
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower switches from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SydpowerSwitch(coordinator, entry, desc) for desc in SWITCH_DESCRIPTIONS
    )


class SydpowerSwitch(SydpowerEntity, SwitchEntity):
    """A switch writing 0 or 1 to one holding register."""

    entity_description: SydpowerSwitchDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerSwitchDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Unavailable until the register has actually been read."""
        return super().available and self._holding(
            self.entity_description.register
        ) is not None

    @property
    def is_on(self) -> bool | None:
        # Non-zero rather than == 1: these registers are booleans in practice,
        # but treating any non-zero value as on avoids reporting "off" if a
        # device ever reports something unexpected.
        value = self._holding(self.entity_description.register)
        return None if value is None else value != 0

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._write(1)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._write(0)

    async def _write(self, value: int) -> None:
        """Write unless the device already reports the requested state."""
        # Skipping redundant writes matters here: each one costs a full BLE
        # connect/disconnect cycle, and these are settings registers.
        if self._holding(self.entity_description.register) == value:
            _LOGGER.debug(
                "Skipping %s write; register %d already reads %d",
                self.entity_id,
                self.entity_description.register,
                value,
            )
            return
        await self.coordinator.async_write_register(
            self.entity_description.register, value
        )
