"""
Tests for the sydpower package.

This module contains basic tests for the scanner, device, and protocol
modules. These are placeholder tests to demonstrate the testing structure.
"""

from __future__ import annotations

import pytest

from sydpower import (
    DiscoveredDevice,
    SydpowerDevice,
    build_read_holding_registers,
    build_read_input_registers,
    build_write_registers,
    crc16_modbus,
    scan,
)
from sydpower.exceptions import (
    CommandTimeoutError,
    CRCError,
    DeviceNotFoundError,
    ProtocolError,
    SydpowerConnectionError,
    SydpowerError,
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
        packet = build_read_holding_registers(modbus_addr=1, start=0, count=10)

        assert isinstance(packet, bytes)
        assert len(packet) == 8  # Standard Modbus RTU frame

        # Packet structure: [slave][func][start_hi][start_lo][count_hi][count_lo][crc_lo][crc_hi]
        assert packet[0] == 0x01  # Slave address
        assert packet[1] == 0x03  # Function code

    def test_build_read_input_registers(self):
        """Test building a read input registers command."""
        packet = build_read_input_registers(modbus_addr=1, start=0, count=10)

        assert isinstance(packet, bytes)
        assert packet[1] == 0x04  # Function code for input registers

    def test_build_write_registers(self):
        """Test building a write registers command."""
        packet = build_write_registers(modbus_addr=1, start=0, values=[100, 200, 300])

        assert isinstance(packet, bytes)
        assert len(packet) > 0


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
