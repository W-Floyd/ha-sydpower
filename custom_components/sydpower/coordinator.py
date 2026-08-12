"""DataUpdateCoordinator for Sydpower BLE devices."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from sydpower import SydpowerDevice
from sydpower.exceptions import SydpowerError

from .const import POLL_INTERVAL

# Seconds to wait after a write before reading back, so the refresh reflects the
# change rather than the pre-write state.
WRITE_SETTLE_DELAY = 1.0

_LOGGER = logging.getLogger(__name__)

# Reachability diagnostics landed in a recent Home Assistant core release.  The
# integration must still load on older versions, so degrade gracefully.
try:
    from homeassistant.components.bluetooth import BluetoothReachabilityIntent
except ImportError:  # pragma: no cover - depends on HA core version
    BluetoothReachabilityIntent = None


@dataclass
class SydpowerData:
    """Register snapshot from the device."""

    holding: list[int]
    input: list[int]


class SydpowerCoordinator(DataUpdateCoordinator[SydpowerData]):
    """
    Polls a Sydpower device over BLE on a fixed interval.

    This is a plain ``DataUpdateCoordinator`` rather than one of the Bluetooth
    coordinators on purpose.  Sydpower advertisements carry only identity data
    (MAC, init status, serial) and no telemetry, and every sensor value comes
    from a GATT register read.  The Bluetooth coordinators are advertisement
    driven, and Home Assistant deduplicates advertisements whose payload is
    byte-identical to the previous one — so with a static payload like this one
    the poll trigger goes silent after the first packet.  A timer-driven
    coordinator is both correct per the Home Assistant developer docs and
    immune to that.

    Each cycle resolves a *connectable* ``BLEDevice`` for the address, which is
    what allows polling through an ESPHome Bluetooth proxy rather than only a
    local adapter, then opens a connection, reads both register banks, and
    closes it again.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        address: str,
        name: str,
        modbus_address: int,
        modbus_count: int,
        protocol_version: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Sydpower {name}",
            update_interval=timedelta(seconds=POLL_INTERVAL),
            # Required by recent Home Assistant cores; it ties the coordinator's
            # background refresh to the config entry's lifecycle.
            config_entry=entry,
        )
        self.address = address
        self._device_name = name
        self._modbus_address = modbus_address
        self._modbus_count = modbus_count
        self._protocol_version = protocol_version

    # ── Polling ───────────────────────────────────────────────────────────────

    def _device(self, ble_device: BLEDevice) -> SydpowerDevice:
        """
        Build a library device that connects through Home Assistant's stack.

        The injected factory is what allows an ESPHome Bluetooth proxy to carry
        the connection, and routing all I/O through ``SydpowerDevice`` means the
        library's write allowlist applies to Home Assistant too.
        """
        return SydpowerDevice(
            ble_device,
            modbus_address=self._modbus_address,
            modbus_count=self._modbus_count,
            protocol_version=self._protocol_version,
            client_factory=lambda: establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                ble_device.address,
                max_attempts=3,
            ),
        )

    async def _async_update_data(self) -> SydpowerData:
        """Read both register banks, raising ``UpdateFailed`` on any error."""
        ble_device = self._connectable_device()
        device = self._device(ble_device)

        try:
            async with device:
                holding = await device.read_holding_registers()
                input_regs = await device.read_input_registers()
        except (SydpowerError, BleakError, TimeoutError) as err:
            raise UpdateFailed(f"{self._device_name}: {err}") from err

        return SydpowerData(holding=holding, input=input_regs)

    # ── Writing ───────────────────────────────────────────────────────────────

    async def async_write_register(self, register: int, value: int) -> None:
        """
        Write a single holding register, then refresh so entities reflect it.

        Raises ``HomeAssistantError`` on failure so the originating service call
        surfaces the reason in the UI rather than failing silently.
        ``UnsafeRegisterWriteError`` is included deliberately: a rejected write
        is a bug in this integration, not a device fault, and it must be visible.
        """
        ble_device = self._connectable_device_or_error()
        device = self._device(ble_device)

        _LOGGER.debug(
            "Writing holding register %d = %d on %s",
            register,
            value,
            self._device_name,
        )
        try:
            async with device:
                await device.write_register(register, value)
        except (SydpowerError, BleakError, TimeoutError) as err:
            raise HomeAssistantError(
                f"Failed to write register {register} on {self._device_name}: {err}"
            ) from err

        # The device needs a moment to apply the change before it reads back.
        await asyncio.sleep(WRITE_SETTLE_DELAY)
        await self.async_request_refresh()

    def _connectable_device_or_error(self) -> BLEDevice:
        """As ``_connectable_device`` but raising for a user-initiated action."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise HomeAssistantError(
                f"No connectable Bluetooth adapter or proxy can reach "
                f"{self.address}: {self._reachability_reason()}"
            )
        return ble_device

    def _connectable_device(self) -> BLEDevice:
        """
        Resolve a connectable ``BLEDevice`` for this address.

        Raises ``UpdateFailed`` with Home Assistant's reachability diagnostics
        when no adapter or proxy can reach the device — that string reports
        which scanners see it, their RSSI and connection-slot allocation, and
        whether every scanner is currently paused because it is busy
        connecting.
        """
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is not None:
            return ble_device

        raise UpdateFailed(
            f"No connectable Bluetooth adapter or proxy can reach "
            f"{self.address}: {self._reachability_reason()}"
        )

    def _reachability_reason(self) -> str:
        """Human-readable explanation of why the address is unreachable."""
        intent = BluetoothReachabilityIntent
        if intent is None:
            return (
                f"{bluetooth.async_scanner_count(self.hass, connectable=True)} "
                f"connectable scanner(s) registered"
            )
        # Wording is not stable and is for humans only — never parse it.
        return bluetooth.async_address_reachability_diagnostics(
            self.hass, self.address, intent.CONNECTION
        )
