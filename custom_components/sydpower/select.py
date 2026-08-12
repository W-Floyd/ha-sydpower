"""Select platform for Sydpower BLE devices."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AC_CHARGE_LIMITS,
    DOMAIN,
    LIGHT_MODES,
    REG_AC_CHARGE_LIMIT,
    REG_LIGHT_CONTROL,
)
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity


@dataclass(frozen=True, kw_only=True)
class SydpowerSelectDescription(SelectEntityDescription):
    """Describes a select backed by a single holding register."""

    register: int
    choices: tuple[str, ...]
    # AC charge limit writes option_index + 1; light mode writes the index itself.
    one_based: bool = False


SELECT_DESCRIPTIONS: tuple[SydpowerSelectDescription, ...] = (
    SydpowerSelectDescription(
        key="light_mode",
        name="Light mode",
        register=REG_LIGHT_CONTROL,
        choices=tuple(LIGHT_MODES),
    ),
    SydpowerSelectDescription(
        key="ac_charge_limit",
        name="AC charge limit",
        register=REG_AC_CHARGE_LIMIT,
        choices=tuple(AC_CHARGE_LIMITS),
        one_based=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower select entities from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SydpowerSelect(coordinator, entry, desc) for desc in SELECT_DESCRIPTIONS
    )


class SydpowerSelect(SydpowerEntity, SelectEntity):
    """A select mapping option index to a holding register value."""

    entity_description: SydpowerSelectDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerSelectDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description
        self._attr_options = list(description.choices)

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None

    @property
    def current_option(self) -> str | None:
        """Map the register value back to an option, or None if out of range."""
        value = self._holding(self.entity_description.register)
        if value is None:
            return None
        index = value - 1 if self.entity_description.one_based else value
        if not 0 <= index < len(self.entity_description.choices):
            # An unexpected value means the mapping is wrong for this model;
            # reporting unknown is safer than showing a misleading option.
            return None
        return self.entity_description.choices[index]

    async def async_select_option(self, option: str) -> None:
        desc = self.entity_description
        index = desc.choices.index(option)
        await self.coordinator.async_write_register(
            desc.register, index + 1 if desc.one_based else index
        )
