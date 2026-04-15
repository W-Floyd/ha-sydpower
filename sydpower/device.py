"""
SydpowerDevice — async BLE connection and Modbus register access.

Typical usage::

    # Discover devices, then connect to the first one found.
    from sydpower import scan, SydpowerDevice

    devices = await scan()
    async with SydpowerDevice.from_discovered(devices[0]) as dev:
        holding = await dev.read_holding_registers()
        inputs  = await dev.read_input_registers()
        await dev.write_register(start=42, value=1)

    # Or connect directly if the address is already known.
    async with SydpowerDevice("AA:BB:CC:DD:EE:FF") as dev:
        registers = await dev.read_holding_registers()
"""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from .constants import (
    BLE_NOTIFY_CHAR_UUID,
    BLE_WRITE_CHAR_UUID,
    COMMAND_TIMEOUT,
    CONNECT_TIMEOUT,
    DEFAULT_MODBUS_ADDRESS,
    DEFAULT_MODBUS_COUNT,
    MAX_COMMAND_RETRIES,
    MTU_SETTLE_DELAY,
)
from .exceptions import (
    CommandTimeoutError,
    ProtocolError,
)
from .exceptions import ConnectionError as SydConnectionError
from .protocol import (
    RegisterResponse,
    ResponseBuffer,
    WriteResponse,
    build_read_holding_registers,
    build_read_input_registers,
    build_write_registers,
)

_log = logging.getLogger(__name__)


class SydpowerDevice:
    """
    Async BLE interface for a single Sydpower inverter or smart-meter device.

    Parameters
    ----------
    address:
        OS-level BLE address (e.g. ``"AA:BB:CC:DD:EE:FF"``).
    modbus_address:
        Modbus slave address used in every packet (device-specific; default 18).
    modbus_count:
        Number of registers in a full bulk read (device-specific; default 85).
    protocol_version:
        0 = legacy single-register writes; 1+ = extended multi-register writes.
    connect_timeout:
        Seconds to wait while establishing the BLE connection.
    """

    def __init__(
        self,
        address: str,
        modbus_address: int = DEFAULT_MODBUS_ADDRESS,
        modbus_count: int = DEFAULT_MODBUS_COUNT,
        protocol_version: int = 1,
        connect_timeout: float = CONNECT_TIMEOUT,
    ) -> None:
        self.address = address
        self.modbus_address = modbus_address
        self.modbus_count = modbus_count
        self.protocol_version = protocol_version
        self.connect_timeout = connect_timeout

        self._client: BleakClient | None = None
        self._active_buffer: ResponseBuffer | None = None
        self._response_future: asyncio.Future[None] | None = None

    # ── Convenience constructor ───────────────────────────────────────────────

    @classmethod
    def from_discovered(cls, device: "DiscoveredDevice") -> "SydpowerDevice":  # type: ignore[name-defined]
        """
        Construct a ``SydpowerDevice`` from a ``DiscoveredDevice`` returned by
        :func:`sydpower.scan`.  Modbus parameters are taken from the discovered
        device (catalog-resolved or defaulted).
        """
        # Import here to avoid a circular dependency at module load time.
        from .scanner import DiscoveredDevice

        if not isinstance(device, DiscoveredDevice):
            raise TypeError(f"Expected DiscoveredDevice, got {type(device).__name__}")

        return cls(
            address=device.address,
            modbus_address=device.modbus_address,
            modbus_count=device.modbus_count,
            protocol_version=device.protocol_version,
        )

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "SydpowerDevice":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.disconnect()

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to the device and subscribe to BLE notifications."""
        _log.debug("Connecting to %s", self.address)
        client = BleakClient(self.address, timeout=self.connect_timeout)
        try:
            await client.connect()
        except Exception as exc:
            raise SydConnectionError(
                f"Failed to connect to {self.address}: {exc}"
            ) from exc

        # Brief pause to allow MTU negotiation to settle before sending commands.
        # Source: rm(200, "setBLEMTU") in app-service-beautified.js line 76197.
        await asyncio.sleep(MTU_SETTLE_DELAY)

        try:
            await client.start_notify(BLE_NOTIFY_CHAR_UUID, self._on_notification)
        except Exception as exc:
            await client.disconnect()
            raise SydConnectionError(
                f"Failed to subscribe to notifications on {self.address}: {exc}"
            ) from exc

        self._client = client
        _log.debug("Connected to %s", self.address)

    async def disconnect(self) -> None:
        """Unsubscribe from notifications and close the BLE connection."""
        if self._client is None:
            return
        try:
            await self._client.stop_notify(BLE_NOTIFY_CHAR_UUID)
        except Exception:
            pass
        try:
            await self._client.disconnect()
        except Exception:
            pass
        self._client = None
        _log.debug("Disconnected from %s", self.address)

    @property
    def is_connected(self) -> bool:
        """``True`` if a BLE connection is currently active."""
        return self._client is not None and self._client.is_connected

    # ── Register access ───────────────────────────────────────────────────────

    async def read_holding_registers(
        self,
        start: int = 0,
        count: int | None = None,
    ) -> list[int]:
        """
        FC 0x03 — Read Holding Registers.

        Returns a list of 16-bit unsigned integers starting at register *start*.
        Defaults to reading the full device register bank (``modbus_count``
        registers).
        """
        count = count if count is not None else self.modbus_count
        packet = build_read_holding_registers(self.modbus_address, start, count)
        resp = await self._send(packet, expected_func_code=0x03)
        if not isinstance(resp, RegisterResponse):
            raise ProtocolError(
                f"Expected RegisterResponse for FC 0x03, got {type(resp).__name__}"
            )
        return list(resp.registers)

    async def read_input_registers(
        self,
        start: int = 0,
        count: int | None = None,
    ) -> list[int]:
        """
        FC 0x04 — Read Input Registers.

        Returns a list of 16-bit unsigned integers starting at register *start*.
        Defaults to reading the full device register bank (``modbus_count``
        registers).
        """
        count = count if count is not None else self.modbus_count
        packet = build_read_input_registers(self.modbus_address, start, count)
        resp = await self._send(packet, expected_func_code=0x04)
        if not isinstance(resp, RegisterResponse):
            raise ProtocolError(
                f"Expected RegisterResponse for FC 0x04, got {type(resp).__name__}"
            )
        return list(resp.registers)

    async def write_register(self, start: int, value: int) -> None:
        """FC 0x06 — Write a single holding register."""
        await self.write_registers(start, [value])

    async def write_registers(self, start: int, values: list[int]) -> None:
        """FC 0x06 — Write one or more consecutive holding registers."""
        packet = build_write_registers(
            self.modbus_address, start, values, self.protocol_version
        )
        await self._send(packet, expected_func_code=0x06)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_notification(
        self, _char: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Called by bleak for every incoming BLE notification."""
        if self._active_buffer is None:
            return

        try:
            complete = self._active_buffer.feed(bytes(data))
        except Exception as exc:
            if self._response_future and not self._response_future.done():
                self._response_future.set_exception(exc)
            return

        if complete and self._response_future and not self._response_future.done():
            self._response_future.set_result(None)

    async def _send(
        self,
        packet: bytes,
        expected_func_code: int,
        retries: int = MAX_COMMAND_RETRIES,
    ) -> RegisterResponse | WriteResponse:
        """
        Write *packet* to the device and wait for the matching response.

        Retries up to *retries* times on timeout before raising
        ``CommandTimeoutError``.  Uses ``asyncio.shield`` around the response
        future so that a timeout cancellation does not cancel an in-flight
        notification callback.
        """
        if not self.is_connected:
            raise SydConnectionError("Device is not connected.")

        for attempt in range(1, retries + 1):
            self._active_buffer = ResponseBuffer(
                modbus_address=self.modbus_address,
                expected_func_code=expected_func_code,
                protocol_version=self.protocol_version,
            )
            loop = asyncio.get_running_loop()
            self._response_future = loop.create_future()

            _log.debug("TX attempt %d/%d: %s", attempt, retries, packet.hex())

            await self._client.write_gatt_char(  # type: ignore[union-attr]
                BLE_WRITE_CHAR_UUID, packet, response=True
            )

            try:
                await asyncio.wait_for(
                    asyncio.shield(self._response_future),
                    timeout=COMMAND_TIMEOUT,
                )
                result = self._active_buffer.result()
                _log.debug("RX: %s", result.raw.hex())
                return result

            except asyncio.TimeoutError:
                _log.warning("Command timed out (attempt %d/%d)", attempt, retries)
                if attempt == retries:
                    raise CommandTimeoutError(
                        f"No response after {retries} attempt(s) "
                        f"(FC 0x{expected_func_code:02X}, packet: {packet.hex()})"
                    )

            finally:
                # Always clear state before the next attempt or on success.
                # asyncio is single-threaded so there is no race between this
                # cleanup and an incoming notification callback.
                self._active_buffer = None
                self._response_future = None

        raise ProtocolError("Unexpected exit from retry loop")  # unreachable
