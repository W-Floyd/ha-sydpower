"""DataUpdateCoordinator for Sydpower BLE devices."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import CoreState, HomeAssistant, callback

from sydpower.constants import BLE_NOTIFY_CHAR_UUID, BLE_WRITE_CHAR_UUID, MTU_SETTLE_DELAY
from sydpower.exceptions import CommandTimeoutError, SydpowerError
from sydpower.protocol import (
    RegisterResponse,
    ResponseBuffer,
    WriteResponse,
    build_read_holding_registers,
    build_read_input_registers,
)

from .const import POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class SydpowerData:
    """Register snapshot from the device."""

    holding: list[int]
    input: list[int]


class SydpowerCoordinator(ActiveBluetoothDataUpdateCoordinator[SydpowerData]):
    """
    Combines passive BLE advertisement monitoring with periodic active polling.

    On each poll cycle the coordinator opens a fresh BLE connection via
    bleak-retry-connector, reads holding and input register banks, then closes
    the connection.  Sensors derive their values from ``coordinator.data``.
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
            hass=hass,
            logger=_LOGGER,
            address=address,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_poll_device,
            mode=BluetoothScanningMode.ACTIVE,
            connectable=True,
        )
        self._device_name = name
        self._modbus_address = modbus_address
        self._modbus_count = modbus_count
        self._protocol_version = protocol_version
        self._poll_interval = timedelta(seconds=POLL_INTERVAL)
        self._ready = asyncio.Event()

    # ── ActiveBluetoothDataUpdateCoordinator hooks ────────────────────────────

    @callback
    def _needs_poll(
        self,
        service_info: BluetoothServiceInfoBleak,
        last_poll: float | None,
    ) -> bool:
        """Poll on first advertisement and then once every POLL_INTERVAL seconds."""
        if last_poll is None:
            return True
        return last_poll >= POLL_INTERVAL

    async def _async_poll_device(
        self, service_info: BluetoothServiceInfoBleak
    ) -> SydpowerData:
        """
        Open a BLE connection, read both register banks, and return the data.

        Called by the coordinator framework from a background task.
        """
        ble_device = service_info.device
        _LOGGER.debug("Polling %s (%s)", self._device_name, ble_device.address)

        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            ble_device.address,
            max_attempts=3,
        )
        try:
            await asyncio.sleep(MTU_SETTLE_DELAY)
            holding = await self._read_registers(client, func_code=0x03)
            input_regs = await self._read_registers(client, func_code=0x04)
        finally:
            await client.disconnect()

        self._ready.set()
        return SydpowerData(holding=holding, input=input_regs)

    # ── Register I/O ──────────────────────────────────────────────────────────

    async def _read_registers(
        self, client: BleakClientWithServiceCache, func_code: int
    ) -> list[int]:
        """Read a full register bank (holding=0x03 or input=0x04) over BLE."""
        if func_code == 0x03:
            packet = build_read_holding_registers(
                self._modbus_address, 0, self._modbus_count
            )
        else:
            packet = build_read_input_registers(
                self._modbus_address, 0, self._modbus_count
            )

        buf = ResponseBuffer(
            modbus_address=self._modbus_address,
            expected_func_code=func_code,
            protocol_version=self._protocol_version,
        )
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        def _on_notify(_char, data: bytearray) -> None:
            try:
                if buf.feed(bytes(data)) and not future.done():
                    future.set_result(None)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)

        await client.start_notify(BLE_NOTIFY_CHAR_UUID, _on_notify)
        try:
            await client.write_gatt_char(BLE_WRITE_CHAR_UUID, packet, response=True)
            await asyncio.wait_for(asyncio.shield(future), timeout=5.0)
        except asyncio.TimeoutError as exc:
            raise CommandTimeoutError(
                f"No response from {self._device_name} for FC 0x{func_code:02X}"
            ) from exc
        finally:
            try:
                await client.stop_notify(BLE_NOTIFY_CHAR_UUID)
            except Exception:
                pass

        resp = buf.result()
        if not isinstance(resp, RegisterResponse):
            raise SydpowerError(f"Unexpected response type: {type(resp).__name__}")
        return list(resp.registers)

    # ── Ready gate ────────────────────────────────────────────────────────────

    async def async_wait_ready(self) -> None:
        """Block until the first successful poll has completed."""
        await self._ready.wait()
