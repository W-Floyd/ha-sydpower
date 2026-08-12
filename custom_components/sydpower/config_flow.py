"""Config flow for Sydpower BLE integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from sydpower.constants import DEVICE_NAME_PREFIXES
from sydpower.calibration import CalibrationSample, fit_correction
from sydpower.catalog import get_device_params, get_product_model, preload

from .const import (
    ACTION_ADD_SAMPLE,
    ACTION_CLEAR_SAMPLES,
    ACTION_KEEP,
    ACTIONS,
    CONF_ACTION,
    CONF_CALIBRATION_SAMPLES,
    CONF_MODBUS_ADDRESS,
    CONF_POLL_INTERVAL,
    CONF_SAMPLE_CHARGE_REPORTED,
    CONF_SAMPLE_IN_REPORTED,
    CONF_SAMPLE_IN_TRUE,
    CONF_SAMPLE_OUT_REPORTED,
    CONF_SAMPLE_OUT_TRUE,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    POLL_INTERVAL,
    CONF_MODEL,
    CONF_MODBUS_COUNT,
    CONF_NAME,
    CONF_PRODUCT_KEY,
    CONF_PROTOCOL_VERSION,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Watts, as read off a meter or the device. Negative would be a typo, and the
# fit treats every field as watts regardless of which register it came from.
_watts = vol.All(vol.Coerce(float), vol.Range(min=0))

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
        # Resolved once here rather than on every entity construction.
        CONF_MODEL: get_product_model(product_key) if product_key else None,
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

    async def _async_params_from_service_info(
        self, service_info: BluetoothServiceInfoBleak
    ) -> dict[str, Any]:
        """
        Resolve Modbus parameters, warming the catalog off the event loop first.

        The lookup itself is a dict access, but the catalog file is read lazily on
        the first one, and here that first one would happen inside the event loop.
        """
        await self.hass.async_add_executor_job(preload)
        return _params_from_service_info(service_info)

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup of a Bluetooth-discovered device."""
        assert self._discovery_info is not None
        info = self._discovery_info

        if user_input is not None:
            return self.async_create_entry(
                title=info.name,
                data=await self._async_params_from_service_info(info),
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
                data=await self._async_params_from_service_info(service_info),
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

    # ── Options ───────────────────────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SydpowerOptionsFlow:
        """Return the options flow for this entry."""
        return SydpowerOptionsFlow()


class SydpowerOptionsFlow(OptionsFlow):
    """
    Poll interval, and calibration of the device's power reporting.

    The device under-reports its output while charging. Rather than ask for a
    correction model, this collects observations — what an external meter says
    against what the device says — and fits the model to them. Two observations at
    different charge rates are what separates a fixed shortfall from a proportional
    one; see sydpower/calibration.py.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the current fit and offer to change the interval or the samples."""
        if user_input is not None:
            action = user_input[CONF_ACTION]
            self._poll_interval = user_input[CONF_POLL_INTERVAL]
            if action == ACTION_ADD_SAMPLE:
                return await self.async_step_add_sample()
            samples = [] if action == ACTION_CLEAR_SAMPLES else self._samples
            return self._save(samples)

        return self.async_show_form(
            step_id="init",
            description_placeholders={"fit": self._describe_fit()},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_POLL_INTERVAL, POLL_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                    vol.Required(CONF_ACTION, default=ACTION_KEEP): vol.In(ACTIONS),
                }
            ),
        )

    async def async_step_add_sample(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Record one simultaneous reading of the device and external meters."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sample = {k: v for k, v in user_input.items() if v is not None}
            has_out = "out_true" in sample and "out_reported" in sample
            has_in = "in_true" in sample and "in_reported" in sample
            if not has_out and not has_in:
                # Without a true/reported pair there is no error to fit, and a
                # half-filled observation would silently contribute nothing.
                errors["base"] = "sample_needs_a_pair"
            else:
                return self._save([*self._samples, sample])

        return self.async_show_form(
            step_id="add_sample",
            errors=errors,
            description_placeholders={"count": str(len(self._samples))},
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SAMPLE_CHARGE_REPORTED): _watts,
                    vol.Optional(CONF_SAMPLE_OUT_REPORTED): _watts,
                    vol.Optional(CONF_SAMPLE_OUT_TRUE): _watts,
                    vol.Optional(CONF_SAMPLE_IN_REPORTED): _watts,
                    vol.Optional(CONF_SAMPLE_IN_TRUE): _watts,
                }
            ),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def _samples(self) -> list[dict[str, float]]:
        return list(self.config_entry.options.get(CONF_CALIBRATION_SAMPLES, []))

    def _save(self, samples: list[dict[str, float]]) -> ConfigFlowResult:
        """Persist the interval and samples, keeping any other options intact."""
        return self.async_create_entry(
            title="",
            data={
                **self.config_entry.options,
                CONF_POLL_INTERVAL: getattr(
                    self,
                    "_poll_interval",
                    self.config_entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL),
                ),
                CONF_CALIBRATION_SAMPLES: samples,
            },
        )

    def _describe_fit(self) -> str:
        """Human-readable summary of what the stored samples currently imply."""
        samples = self._samples
        if not samples:
            return (
                "No calibration samples yet, so readings are passed through "
                "untouched."
            )

        model = fit_correction([CalibrationSample(**s) for s in samples])
        if not model.active:
            return f"{model.samples} sample(s) recorded, implying no correction."

        parts = [f"{model.samples} sample(s)"]
        if model.slope_resolved:
            parts.append(
                f"correction = {model.offset:.0f} W + "
                f"{model.slope:.3f} x charge power"
            )
        else:
            parts.append(
                f"correction = {model.offset:.0f} W flat — all samples share one "
                "charge rate, so a proportional component cannot be separated. Add "
                "a sample at a different charge rate (change the AC charging power "
                "setting) to resolve it"
            )
        parts.append(f"worst residual {model.worst_residual:.0f} W")
        return "; ".join(parts)
