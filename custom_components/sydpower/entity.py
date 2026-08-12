"""Shared base for Sydpower entities that read and write holding registers."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_NAME, DOMAIN
from .coordinator import SydpowerCoordinator


class SydpowerEntity(CoordinatorEntity[SydpowerCoordinator]):
    """Common device info and register accessors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_ADDRESS])},
            name=entry.data[CONF_NAME],
            manufacturer="Sydpower / BrightEMS",
        )

    def _holding(self, register: int) -> int | None:
        """Read a holding register from the latest poll, or None if absent."""
        data = self.coordinator.data
        if data is None or register >= len(data.holding):
            return None
        return data.holding[register]

    def _input(self, register: int) -> int | None:
        """Read an input register from the latest poll, or None if absent."""
        data = self.coordinator.data
        if data is None or register >= len(data.input):
            return None
        return data.input[register]
