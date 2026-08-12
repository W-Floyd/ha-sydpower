"""
Button platform for Sydpower BLE devices.

Two momentary actions the app performs, neither described by the catalog:

* Cancelling scheduled charging, by writing 0 to the delay register.
* Remote shutdown, by writing 1. **This powers the unit down**, and the app puts a
  confirmation dialog in front of it. Home Assistant has no equivalent for a button
  press, so this one ships disabled and has to be enabled in the entity settings
  before it appears.

Setting a schedule is not offered. The register takes a delay in minutes that the
app derives from a requested time of day, wrapping midnight, which is a poor fit
for a button and belongs in a service or a datetime entity if it is ever wanted.
The remaining countdown is published as a sensor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from sydpower.constants import WRITABLE_HOLDING_REGISTERS

from .const import DOMAIN, REG_REMOTE_SHUTDOWN, REG_SCHEDULED_CHARGE
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SydpowerButtonDescription(ButtonEntityDescription):
    """Describes a button that writes one value to one holding register."""

    register: int
    value: int


BUTTON_DESCRIPTIONS: tuple[SydpowerButtonDescription, ...] = (
    SydpowerButtonDescription(
        key="cancel_scheduled_charge",
        name="Cancel scheduled charge",
        register=REG_SCHEDULED_CHARGE,
        value=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SydpowerButtonDescription(
        key="remote_shutdown",
        name="Remote shutdown",
        register=REG_REMOTE_SHUTDOWN,
        value=1,
        # Disabled until deliberately enabled. Home Assistant has no confirmation
        # for a button press where the app puts a dialog in front of this, and a
        # dashboard button is one tap away from powering down whatever the unit is
        # running. Enable it in the entity settings to use it.
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower buttons from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SydpowerButton(coordinator, entry, desc)
        for desc in BUTTON_DESCRIPTIONS
        # The library would refuse the write, so do not offer a button that cannot
        # work.
        if desc.register in WRITABLE_HOLDING_REGISTERS
    )


class SydpowerButton(SydpowerEntity, ButtonEntity):
    """A button writing one fixed value to a holding register."""

    entity_description: SydpowerButtonDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerButtonDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """
        Available whenever the device is reachable.

        Unlike the other platforms this does not require a particular register to
        have been read: a button writes rather than reflects, and there is no
        state to be missing.
        """
        return super().available

    async def async_press(self) -> None:
        description = self.entity_description
        _LOGGER.debug(
            "Button %s writing %d to register %d",
            self.entity_id,
            description.value,
            description.register,
        )
        await self.coordinator.async_write_register(
            description.register, description.value
        )
