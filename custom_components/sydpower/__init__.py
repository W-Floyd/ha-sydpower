"""Sydpower BLE inverter integration."""

from __future__ import annotations

import logging

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_ADDRESS,
    CONF_MODBUS_ADDRESS,
    CONF_MODBUS_COUNT,
    CONF_NAME,
    CONF_PROTOCOL_VERSION,
    DOMAIN,
)
from .coordinator import SydpowerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sydpower from a config entry."""
    address: str = entry.data[CONF_ADDRESS]

    if not async_ble_device_from_address(hass, address, connectable=True):
        raise ConfigEntryNotReady(
            f"Sydpower device {address} not reachable; ensure it is powered on and in range."
        )

    coordinator = SydpowerCoordinator(
        hass=hass,
        address=address,
        name=entry.data[CONF_NAME],
        modbus_address=entry.data[CONF_MODBUS_ADDRESS],
        modbus_count=entry.data[CONF_MODBUS_COUNT],
        protocol_version=entry.data[CONF_PROTOCOL_VERSION],
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # async_start() registers BT callbacks and returns a cancel callable.
    entry.async_on_unload(coordinator.async_start())
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates (e.g. options)."""
    await hass.config_entries.async_reload(entry.entry_id)
