"""Shared base for Sydpower entities that read and write holding registers."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from sydpower.catalog import get_product_model

from .const import CONF_ADDRESS, CONF_MODEL, CONF_NAME, CONF_PRODUCT_KEY, DOMAIN
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
        # `model` is the manufacturer's own code, e.g. "P210-A0E01" for an
        # AFERIY P210. No consumer brand is available: the catalog's largest
        # group is the OEM's white-label bucket and resellers do not appear in
        # it, so `manufacturer` stays generic. `model_id` carries the product key
        # so the exact catalog entry is identifiable even without a model name.
        product_key = entry.data.get(CONF_PRODUCT_KEY) or ""
        # Prefer a live catalog lookup over the stored value so entries created
        # before the model was recorded still report one, and so a catalog
        # refresh takes effect without re-adding the device.
        model = get_product_model(product_key) or entry.data.get(CONF_MODEL)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_ADDRESS])},
            name=entry.data[CONF_NAME],
            manufacturer="Sydpower / BrightEMS",
            model=model,
            model_id=product_key or None,
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
