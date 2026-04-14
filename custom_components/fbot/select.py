"""Select platform for the Fbot integration."""
from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    REG_LIGHT_CONTROL,
    REG_AC_CHARGE_LIMIT,
    KEY_LIGHT_MODE,
    KEY_AC_CHARGE_LIMIT,
    LIGHT_MODES,
    AC_CHARGE_LIMITS,
)
from .coordinator import FbotCoordinator


@dataclass(frozen=True, kw_only=True)
class FbotSelectEntityDescription(SelectEntityDescription):
    """Extends SelectEntityDescription with Fbot-specific fields."""
    data_key: str
    register: int
    options: list[str] = field(default_factory=list)
    # If True, the register value is option_index + 1 (1-based); otherwise 0-based.
    one_based: bool = False


SELECT_DESCRIPTIONS: tuple[FbotSelectEntityDescription, ...] = (
    FbotSelectEntityDescription(
        key="light_mode",
        data_key=KEY_LIGHT_MODE,
        name="Light Mode",
        options=LIGHT_MODES,
        register=REG_LIGHT_CONTROL,
        one_based=False,
    ),
    FbotSelectEntityDescription(
        key="ac_charge_limit",
        data_key=KEY_AC_CHARGE_LIMIT,
        name="AC Charge Limit",
        options=AC_CHARGE_LIMITS,
        register=REG_AC_CHARGE_LIMIT,
        one_based=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FbotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        FbotSelect(coordinator, description) for description in SELECT_DESCRIPTIONS
    )


class FbotSelect(CoordinatorEntity[FbotCoordinator], SelectEntity):
    """A select entity for Fbot device options."""

    _attr_has_entity_name = True
    entity_description: FbotSelectEntityDescription

    def __init__(
        self,
        coordinator: FbotCoordinator,
        description: FbotSelectEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_options = description.options
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name="Fbot Battery Station",
            manufacturer="Fbot",
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.entity_description.data_key in (self.coordinator.data or {})
        )

    @property
    def current_option(self) -> str | None:
        return (self.coordinator.data or {}).get(self.entity_description.data_key)

    async def async_select_option(self, option: str) -> None:
        desc = self.entity_description
        try:
            idx = desc.options.index(option)
        except ValueError:
            return
        reg_value = idx + 1 if desc.one_based else idx
        await self.coordinator.async_send_command(desc.register, reg_value)
        # Fetch updated settings to confirm the change
        await self.coordinator.async_send_settings_refresh()
