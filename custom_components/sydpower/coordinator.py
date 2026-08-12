"""DataUpdateCoordinator for Sydpower BLE devices."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from sydpower import SydpowerDevice
from sydpower.exceptions import SydpowerError

from .const import POLL_INTERVAL

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
        )
        self.address = address
        self._device_name = name
        self._modbus_address = modbus_address
        self._modbus_count = modbus_count
        self._protocol_version = protocol_version

    # ── Polling ───────────────────────────────────────────────────────────────

    async def _async_update_data(self) -> SydpowerData:
        """Read both register banks, raising ``UpdateFailed`` on any error."""
        ble_device = self._connectable_device()

        device = SydpowerDevice(
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

        try:
            async with device:
                holding = await device.read_holding_registers()
                input_regs = await device.read_input_registers()
        except (SydpowerError, BleakError, TimeoutError) as err:
            raise UpdateFailed(f"{self._device_name}: {err}") from err

        return SydpowerData(holding=holding, input=input_regs)

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
