"""Sydpower BLE inverter integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from sydpower.catalog import preload

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

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DATETIME,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sydpower from a config entry."""
    address: str = entry.data[CONF_ADDRESS]

    # Warm the catalog from a thread before any platform queries it. Every platform
    # derives its entities from the catalog during setup, and the first accessor to
    # run would otherwise read the file from inside the event loop — which Home
    # Assistant detects and warns about. One executor call makes all of them cache
    # reads; the catalog is immutable for the life of the process.
    await hass.async_add_executor_job(preload)

    # Distinguish "no Bluetooth at all" from "this device is out of range" — the
    # two need very different things from the user.
    if not bluetooth.async_scanner_count(hass, connectable=True):
        raise ConfigEntryNotReady(
            "No connectable Bluetooth adapter or ESPHome Bluetooth proxy is "
            "available; Sydpower devices require an active connection."
        )

    if not bluetooth.async_ble_device_from_address(hass, address, connectable=True):
        raise ConfigEntryNotReady(
            f"Sydpower device {address} not reachable; ensure it is powered on and in range."
        )

    coordinator = SydpowerCoordinator(
        hass=hass,
        entry=entry,
        address=address,
        name=entry.data[CONF_NAME],
        modbus_address=entry.data[CONF_MODBUS_ADDRESS],
        modbus_count=entry.data[CONF_MODBUS_COUNT],
        protocol_version=entry.data[CONF_PROTOCOL_VERSION],
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Fail setup (and retry later) if the very first poll cannot complete, so
    # entities are never created against a device we have never read.
    await coordinator.async_config_entry_first_refresh()

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
