"""Config flow for Sydpower BLE integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from sydpower.constants import DEVICE_NAME_PREFIXES
from sydpower.catalog import get_device_params

from .const import (
    CONF_MODBUS_ADDRESS,
    CONF_MODBUS_COUNT,
    CONF_NAME,
    CONF_PRODUCT_KEY,
    CONF_PROTOCOL_VERSION,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_MODBUS_ADDRESS = 18
DEFAULT_MODBUS_COUNT = 85


def _is_sydpower_device(service_info: BluetoothServiceInfoBleak) -> bool:
    return any(service_info.name.startswith(p) for p in DEVICE_NAME_PREFIXES)


def _params_from_service_info(
    service_info: BluetoothServiceInfoBleak,
) -> dict[str, Any]:
    """Resolve Modbus parameters for a discovered device."""
    svc_uuids = [u.upper() for u in (service_info.service_uuids or [])]
    service_uuid = svc_uuids[0] if svc_uuids else ""
    product_key = f"{service_uuid}_{service_info.name}" if service_uuid else ""

    params = get_device_params(product_key) if product_key else None
    return {
        CONF_ADDRESS: service_info.address,
        CONF_NAME: service_info.name,
        CONF_PRODUCT_KEY: product_key,
        CONF_MODBUS_ADDRESS: params["modbus_address"] if params else DEFAULT_MODBUS_ADDRESS,
        CONF_MODBUS_COUNT: params["modbus_count"] if params else DEFAULT_MODBUS_COUNT,
        CONF_PROTOCOL_VERSION: params["protocol_version"] if params else 1,
    }


class SydpowerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sydpower BLE."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    # ── Bluetooth-triggered flow ──────────────────────────────────────────────

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device discovered via the bluetooth integration."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if not _is_sydpower_device(discovery_info):
            return self.async_abort(reason="no_devices_found")

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name,
            "address": discovery_info.address,
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup of a Bluetooth-discovered device."""
        assert self._discovery_info is not None
        info = self._discovery_info

        if user_input is not None:
            return self.async_create_entry(
                title=info.name,
                data=_params_from_service_info(info),
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": info.name,
                "address": info.address,
            },
        )

    # ── Manual / user-initiated flow ──────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup — show a list of nearby Sydpower devices."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            service_info = self._discovered_devices[address]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=service_info.name,
                data=_params_from_service_info(service_info),
            )

        # Collect all Sydpower devices visible in the current HA BT scan cache.
        current_addresses = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address not in current_addresses and _is_sydpower_device(info):
                self._discovered_devices[info.address] = info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            addr: f"{info.name} ({addr})"
                            for addr, info in self._discovered_devices.items()
                        }
                    )
                }
            ),
        )
