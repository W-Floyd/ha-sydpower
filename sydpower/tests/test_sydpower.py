"""
Tests for the sydpower package.

This module contains basic tests for the scanner, device, and protocol
modules. These are placeholder tests to demonstrate the testing structure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from bleak.backends.device import BLEDevice

from sydpower import (
    WRITABLE_HOLDING_REGISTERS,
    DiscoveredDevice,
    ResponseBuffer,
    SydpowerDevice,
    build_read_holding_registers,
    build_read_input_registers,
    build_write_registers,
    crc16_modbus,
    scan,
)
from sydpower import SydpowerConnectionError
from sydpower.exceptions import (
    CommandTimeoutError,
    CRCError,
    DeviceNotFoundError,
    ProtocolError,
    SydpowerError,
    UnsafeRegisterWriteError,
)


class TestSydpowerErrorHierarchy:
    """Test the exception hierarchy."""

    def test_sydpower_error_base(self):
        """Test that SydpowerError is the base class."""
        assert issubclass(SydpowerConnectionError, SydpowerError)
        assert issubclass(CommandTimeoutError, SydpowerError)
        assert issubclass(CRCError, SydpowerError)
        assert issubclass(ProtocolError, SydpowerError)
        assert issubclass(DeviceNotFoundError, SydpowerError)


class TestDiscoveredDevice:
    """Test the DiscoveredDevice dataclass."""

    def test_discovered_device_creation(self):
        """Test creating a DiscoveredDevice instance."""
        device = DiscoveredDevice(
            name="POWER-TEST",
            address="AA:BB:CC:DD:EE:FF",
            service_uuid="0000A002-0000-1000-8000-00805F9B34FB",
            product_key="0000A002-0000-1000-8000-00805F9B34FB_POWER-TEST",
            advertis="11:22:33:44:55:66",
            init_status=0,
            serial_no="TEST1234567890AB",
            modbus_address=18,
            modbus_count=85,
            protocol_version=1,
        )

        assert device.name == "POWER-TEST"
        assert device.address == "AA:BB:CC:DD:EE:FF"
        assert device.protocol_version == 1

    def test_discovered_device_defaults(self):
        """Test DiscoveredDevice with default values."""
        device = DiscoveredDevice(
            name="POWER-TEST",
            address="AA:BB:CC:DD:EE:FF",
            service_uuid="0000A002-0000-1000-8000-00805F9B34FB",
            product_key="0000A002-0000-1000-8000-00805F9B34FB_POWER-TEST",
            advertis="11:22:33:44:55:66",
            init_status=0,
            serial_no=None,
            modbus_address=18,
            modbus_count=85,
            protocol_version=1,
        )

        assert device.modbus_address == 18
        assert device.modbus_count == 85
        assert device.protocol_version == 1


class TestProtocolFunctions:
    """Test protocol primitive functions."""

    def test_crc16_modbus(self):
        """Test CRC16 Modbus calculation."""
        # Example from Modbus specification
        data = bytes([0x01, 0x02, 0x03, 0x04])
        crc = crc16_modbus(data)
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFF

    def test_build_read_holding_registers(self):
        """Test building a read holding registers command."""
        packet = build_read_holding_registers(address=1, start=0, count=10)

        assert isinstance(packet, bytes)
        assert len(packet) == 8  # Standard Modbus RTU frame

        # Packet structure: [slave][func][start_hi][start_lo][count_hi][count_lo][crc_lo][crc_hi]
        assert packet[0] == 0x01  # Slave address
        assert packet[1] == 0x03  # Function code

    def test_build_read_input_registers(self):
        """Test building a read input registers command."""
        packet = build_read_input_registers(address=1, start=0, count=10)

        assert isinstance(packet, bytes)
        assert packet[1] == 0x04  # Function code for input registers

    def test_build_write_registers(self):
        """Test building a write registers command."""
        packet = build_write_registers(address=1, start=0, values=[100, 200, 300])

        assert isinstance(packet, bytes)
        assert len(packet) > 0

    def test_legacy_write_single_register(self):
        """protocol_version 0 encodes a single register with a 2-byte address."""
        packet = build_write_registers(
            address=17, start=26, values=[1], protocol_version=0
        )

        # [addr, 0x06, start_hi, start_lo, val_hi, val_lo, crc_hi, crc_lo]
        assert len(packet) == 8
        assert packet[:6] == bytes([17, 0x06, 0x00, 26, 0x00, 0x01])

    def test_legacy_write_rejects_multiple_registers(self):
        """
        protocol_version 0 has no multi-register encoding.

        It must raise rather than silently writing only the first value — the
        legacy path previously truncated to two data bytes.
        """
        with pytest.raises(ProtocolError, match="single-register writes only"):
            build_write_registers(
                address=17, start=66, values=[100, 900], protocol_version=0
            )


class TestResponseFunctionCodeMatching:
    """
    A response must match the function code that was requested.

    Holding (0x03) and input (0x04) reads produce identically shaped frames for
    the same register count, so accepting either one silently misinterprets
    every register in the bank.
    """

    def _frame(self, func_code: int, count: int = 2) -> bytes:
        """Build a valid register-read response with a correct CRC."""
        body = [17, func_code, 0x00, 0x00, count >> 8, count & 0xFF]
        body += [0x00, 0x01] * count
        crc = crc16_modbus(body)
        return bytes([*body, crc >> 8, crc & 0xFF])

    def test_matching_function_code_accepted(self):
        buf = ResponseBuffer(
            modbus_address=17, expected_func_code=0x03, protocol_version=0
        )
        assert buf.feed(self._frame(0x03)) is True

    def test_input_response_rejected_for_holding_request(self):
        """The desync that produced garbage register data on real hardware."""
        buf = ResponseBuffer(
            modbus_address=17, expected_func_code=0x03, protocol_version=0
        )
        with pytest.raises(ProtocolError, match="desynchronised"):
            buf.feed(self._frame(0x04))

    def test_holding_response_rejected_for_input_request(self):
        buf = ResponseBuffer(
            modbus_address=17, expected_func_code=0x04, protocol_version=0
        )
        with pytest.raises(ProtocolError, match="desynchronised"):
            buf.feed(self._frame(0x03))


class TestWriteSafety:
    """
    Test the known-safe holding-register guard.

    A write to an unverified register or an out-of-range value can put the
    device into an unrecoverable boot loop, so these must be rejected before
    any packet is built.
    """

    def _device(self, **kwargs) -> SydpowerDevice:
        return SydpowerDevice("AA:BB:CC:DD:EE:FF", **kwargs)

    def test_known_register_in_range_passes(self):
        """A verified register with an in-range value is accepted."""
        # Register 26 is AC output, allowed 0-1.
        self._device()._check_writes_safe(26, [1])

    def test_unknown_register_rejected(self):
        """A register outside the allowlist is rejected."""
        with pytest.raises(UnsafeRegisterWriteError, match="not a known-safe"):
            self._device()._check_writes_safe(42, [1])

    def test_value_above_range_rejected(self):
        """A value above the register's verified maximum is rejected."""
        # Register 27 is light mode, allowed 0-3.
        with pytest.raises(UnsafeRegisterWriteError, match="outside the verified range"):
            self._device()._check_writes_safe(27, [4])

    def test_value_below_range_rejected(self):
        """A value below the register's verified minimum is rejected."""
        # Register 67 is the charge upper limit, allowed 100-1000 permille.
        with pytest.raises(UnsafeRegisterWriteError, match="outside the verified range"):
            self._device()._check_writes_safe(67, [50])

    def test_range_bounds_are_inclusive(self):
        """Both ends of a verified range are accepted."""
        dev = self._device()
        low, high = WRITABLE_HOLDING_REGISTERS[67]
        dev._check_writes_safe(67, [low])
        dev._check_writes_safe(67, [high])

    def test_multi_register_span_checks_every_register(self):
        """A consecutive write is rejected if any register in the span is unsafe."""
        # Registers 66 and 67 are both writable; 68 is not. Starting at 66 with
        # three values reaches 68 and must be refused.
        dev = self._device()
        dev._check_writes_safe(66, [100, 900])
        with pytest.raises(UnsafeRegisterWriteError, match="Register 68"):
            dev._check_writes_safe(66, [100, 900, 1])

    def test_multi_register_span_checks_each_value(self):
        """Each value is validated against its own register's range."""
        # 100 is valid for register 66 but below register 67's minimum of 100...
        # so use a value that is fine for 66 and invalid for 67.
        with pytest.raises(UnsafeRegisterWriteError, match="register 67"):
            self._device()._check_writes_safe(66, [0, 50])

    def test_empty_values_rejected(self):
        """An empty write is meaningless and rejected."""
        with pytest.raises(UnsafeRegisterWriteError, match="No values"):
            self._device()._check_writes_safe(26, [])

    def test_allow_unsafe_writes_bypasses_guard(self):
        """The opt-in escape hatch permits otherwise-rejected writes."""
        dev = self._device(allow_unsafe_writes=True)
        dev._check_writes_safe(42, [9999])

    def test_guard_defaults_to_enabled(self):
        """The guard must be on unless explicitly disabled."""
        assert self._device().allow_unsafe_writes is False


class TestClientInjection:
    """
    Test constructing a device from a BLEDevice and with an injected client.

    Home Assistant must be able to hand the library a connection established
    through whichever adapter or ESPHome Bluetooth proxy can reach the device,
    rather than having the library open a local one.
    """

    def test_accepts_ble_device_and_extracts_address(self):
        """A BLEDevice may be passed in place of an address string."""
        ble_device = BLEDevice("AA:BB:CC:DD:EE:FF", "POWER-TEST", None)
        dev = SydpowerDevice(ble_device)

        assert dev.address == "AA:BB:CC:DD:EE:FF"
        assert dev._ble_device is ble_device

    def test_accepts_address_string(self):
        """The plain address form still works and records no BLEDevice."""
        dev = SydpowerDevice("AA:BB:CC:DD:EE:FF")

        assert dev.address == "AA:BB:CC:DD:EE:FF"
        assert dev._ble_device is None

    @pytest.mark.asyncio
    async def test_connect_uses_injected_factory(self):
        """When a client factory is supplied, no local BleakClient is created."""
        client = AsyncMock()
        client.is_connected = True
        calls: list[str] = []

        async def factory():
            calls.append("factory")
            return client

        dev = SydpowerDevice("AA:BB:CC:DD:EE:FF", client_factory=factory)
        with patch("sydpower.device.BleakClient") as bleak_client:
            await dev.connect()

        assert calls == ["factory"]
        bleak_client.assert_not_called()
        client.start_notify.assert_awaited_once()
        assert dev.is_connected

    @pytest.mark.asyncio
    async def test_factory_failure_raises_connection_error(self):
        """A failing factory surfaces as a SydpowerConnectionError."""

        async def factory():
            raise OSError("proxy unreachable")

        dev = SydpowerDevice("AA:BB:CC:DD:EE:FF", client_factory=factory)
        with pytest.raises(SydpowerConnectionError, match="Injected client factory"):
            await dev.connect()


class TestModuleImports:
    """Test that all expected symbols are exported."""

    def test_sydpower_device_available(self):
        """Test SydpowerDevice is importable."""
        # This should not raise
        assert SydpowerDevice is not None

    def test_scan_available(self):
        """Test scan function is importable."""
        assert scan is not None
        assert callable(scan)

    def test_all_exceptions_available(self):
        """Test all exceptions are available."""
        assert SydpowerError is not None
        assert SydpowerConnectionError is not None
        assert CommandTimeoutError is not None
        assert DeviceNotFoundError is not None
        assert CRCError is not None
        assert ProtocolError is not None

    def test_protocol_primitives_available(self):
        """Test protocol primitives are available."""
        assert crc16_modbus is not None
        assert build_read_holding_registers is not None
        assert build_read_input_registers is not None
        assert build_write_registers is not None


@pytest.mark.asyncio
async def test_scan_function_signature():
    """Test that scan has the expected signature."""
    import inspect

    sig = inspect.signature(scan)

    # scan should accept a timeout parameter with default
    params = list(sig.parameters.keys())
    assert "timeout" in params
