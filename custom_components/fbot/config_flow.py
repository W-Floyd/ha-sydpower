"""Config flow for the Fbot integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, SERVICE_UUID


class FbotConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fbot."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Confirm Bluetooth discovery."""
        assert self._discovery_info is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or self._discovery_info.address,
                data={CONF_ADDRESS: self._discovery_info.address},
            )
        self._set_confirm_only()
        name = self._discovery_info.name or self._discovery_info.address
        self.context["title_placeholders"] = {"name": name}
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": name},
        )

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle a user-initiated flow."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS].upper()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=address,
                data={CONF_ADDRESS: address},
            )

        # Offer discovered devices as a dropdown, fall back to free-text entry
        discovered = {
            info.address: f"{info.name or info.address} ({info.address})"
            for info in async_discovered_service_info(self.hass, connectable=True)
            if SERVICE_UUID in (info.service_uuids or [])
        }

        if discovered:
            schema = vol.Schema({vol.Required(CONF_ADDRESS): vol.In(discovered)})
        else:
            schema = vol.Schema({vol.Required(CONF_ADDRESS): str})

        return self.async_show_form(step_id="user", data_schema=schema)
