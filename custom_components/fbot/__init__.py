"""The Fbot Battery Station integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import FbotCoordinator

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fbot from a config entry."""
    coordinator = FbotCoordinator(
        hass,
        address=entry.data[CONF_ADDRESS],
        name=entry.title,
    )

    # Initialise coordinator.data to {} so entities can be created without
    # waiting for a BLE connection.
    await coordinator.async_refresh()

    # Start the BLE connection process in the background.
    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: FbotCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_stop()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
