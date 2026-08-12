"""
SydpowerDevice — async BLE connection and Modbus register access.

Typical usage::

    # Discover devices, then connect to the first one found.
    from sydpower import scan, SydpowerDevice

    devices = await scan()
    async with SydpowerDevice.from_discovered(devices[0]) as dev:
        holding = await dev.read_holding_registers()
        inputs  = await dev.read_input_registers()
        await dev.write_register(start=26, value=1)  # AC output on

    # Or connect directly if the address is already known.
    async with SydpowerDevice("AA:BB:CC:DD:EE:FF") as dev:
        registers = await dev.read_holding_registers()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from .constants import (
    BLE_NOTIFY_CHAR_UUID,
    BLE_WRITE_CHAR_UUID,
    COMMAND_TIMEOUT,
    CONNECT_TIMEOUT,
    DEFAULT_MODBUS_ADDRESS,
    DEFAULT_MODBUS_COUNT,
    MAX_COMMAND_RETRIES,
    MTU_SETTLE_DELAY,
    WRITABLE_HOLDING_REGISTERS,
)
from .exceptions import (
    CommandTimeoutError,
    ProtocolError,
    UnsafeRegisterWriteError,
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
        OS-level BLE address (e.g. ``"AA:BB:CC:DD:EE:FF"``), or a bleak
        ``BLEDevice``.  Passing a ``BLEDevice`` is preferred when you already
        have one, since bleak can connect without re-resolving the address.
    client_factory:
        Optional coroutine returning an already-connected bleak client.  Supply
        this when the connection must be made by something other than a local
        adapter — notably Home Assistant, where ``establish_connection`` routes
        through whichever adapter or ESPHome Bluetooth proxy can reach the
        device.  When omitted, a local ``BleakClient`` is created and connected.
    modbus_address:
        Modbus slave address used in every packet (device-specific; default 18).
    modbus_count:
        Number of registers in a full bulk read (device-specific; default 85).
    protocol_version:
        0 = legacy single-register writes; 1+ = extended multi-register writes.
    connect_timeout:
        Seconds to wait while establishing the BLE connection.
    allow_unsafe_writes:
        Bypass the known-safe holding-register check in :meth:`write_registers`.
        Only for deliberate register probing — a bad settings write can put the
        device into a boot loop that cannot be fixed over BLE.
    """

    def __init__(
        self,
        address: str | BLEDevice,
        modbus_address: int = DEFAULT_MODBUS_ADDRESS,
        modbus_count: int = DEFAULT_MODBUS_COUNT,
        protocol_version: int = 1,
        connect_timeout: float = CONNECT_TIMEOUT,
        allow_unsafe_writes: bool = False,
        client_factory: Callable[[], Awaitable[BleakClient]] | None = None,
    ) -> None:
        if isinstance(address, BLEDevice):
            self._ble_device: BLEDevice | None = address
            self.address = address.address
        else:
            self._ble_device = None
            self.address = address

        self._client_factory = client_factory
        self.modbus_address = modbus_address
        self.modbus_count = modbus_count
        self.protocol_version = protocol_version
        self.connect_timeout = connect_timeout
        self.allow_unsafe_writes = allow_unsafe_writes

        self._client: BleakClient | None = None
        self._active_buffer: ResponseBuffer | None = None
        self._response_future: asyncio.Future[None] | None = None

    # ── Convenience constructor ───────────────────────────────────────────────

    @classmethod
    def from_discovered(
        cls,
        device: "DiscoveredDevice",  # type: ignore[name-defined]
        allow_unsafe_writes: bool = False,
    ) -> "SydpowerDevice":
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
            allow_unsafe_writes=allow_unsafe_writes,
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
        if self._client_factory is not None:
            # Caller owns connection establishment (e.g. Home Assistant routing
            # through a local adapter or an ESPHome Bluetooth proxy).
            try:
                client = await self._client_factory()
            except Exception as exc:
                raise SydConnectionError(
                    f"Injected client factory failed for {self.address}: {exc}"
                ) from exc
        else:
            # Prefer the BLEDevice when we have one; bleak avoids a re-scan.
            target = self._ble_device if self._ble_device is not None else self.address
            client = BleakClient(target, timeout=self.connect_timeout)
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
        """
        FC 0x06 — Write a single holding register.

        Raises ``UnsafeRegisterWriteError`` unless the register and value are
        known-safe; see :meth:`write_registers`.
        """
        await self.write_registers(start, [value])

    async def write_registers(self, start: int, values: list[int]) -> None:
        """
        FC 0x06 — Write one or more consecutive holding registers.

        Every register in the span ``start .. start + len(values) - 1`` is
        checked against :data:`WRITABLE_HOLDING_REGISTERS` before the packet is
        built.  A register outside that map, or a value outside the register's
        verified range, raises ``UnsafeRegisterWriteError`` and nothing is sent.

        This guard exists because a bad settings write can put the unit into a
        permanent boot loop that cannot be fixed over BLE — see the note on
        ``WRITABLE_HOLDING_REGISTERS``.  Set ``allow_unsafe_writes=True`` on the
        device to bypass it when deliberately probing unmapped registers.
        """
        self._check_writes_safe(start, values)
        packet = build_write_registers(
            self.modbus_address, start, values, self.protocol_version
        )
        await self._send(packet, expected_func_code=0x06)

    def _check_writes_safe(self, start: int, values: list[int]) -> None:
        """
        Validate a holding-register write against the known-safe register map.

        Raises ``UnsafeRegisterWriteError`` on the first offending register so
        that no partial write is ever emitted.
        """
        if not values:
            raise UnsafeRegisterWriteError("No values supplied to write.")

        if self.allow_unsafe_writes:
            _log.warning(
                "allow_unsafe_writes is set — skipping the safety check for "
                "register(s) %d..%d. A bad value here can put the device into "
                "an unrecoverable boot loop.",
                start,
                start + len(values) - 1,
            )
            return

        for offset, value in enumerate(values):
            register = start + offset
            allowed = WRITABLE_HOLDING_REGISTERS.get(register)
            if allowed is None:
                raise UnsafeRegisterWriteError(
                    f"Register {register} is not a known-safe holding register. "
                    f"Writable registers are "
                    f"{sorted(WRITABLE_HOLDING_REGISTERS)}. Writing an "
                    f"unverified register can put the device into an "
                    f"unrecoverable boot loop; pass allow_unsafe_writes=True "
                    f"only if you accept that risk."
                )
            low, high = allowed
            if not low <= value <= high:
                raise UnsafeRegisterWriteError(
                    f"Value {value} is outside the verified range "
                    f"{low}..{high} for register {register}."
                )

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
