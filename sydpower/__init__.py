"""
sydpower — Python library for Sydpower / BrightEMS BLE inverter devices.

Quick start::

    import asyncio
    from sydpower import scan, SydpowerDevice

    async def main():
        # Discover nearby devices (runs for SCAN_TIMEOUT seconds).
        devices = await scan()
        if not devices:
            print("No devices found")
            return

        # Connect and read registers.
        async with SydpowerDevice.from_discovered(devices[0]) as dev:
            holding = await dev.read_holding_registers()
            inputs  = await dev.read_input_registers()
            print(holding)
            print(inputs)

    asyncio.run(main())
"""

from .device import SydpowerDevice
from .exceptions import (
    CommandTimeoutError,
    CRCError,
    DeviceNotFoundError,
    ProtocolError,
    SydpowerError,
)
from .exceptions import ConnectionError as SydpowerConnectionError
from .protocol import (
    RegisterResponse,
    ResponseBuffer,
    WriteResponse,
    build_read_holding_registers,
    build_read_input_registers,
    build_write_registers,
    crc16_modbus,
)
from .scanner import DiscoveredDevice, scan

__all__ = [
    # Main interface
    "SydpowerDevice",
    "scan",
    "DiscoveredDevice",
    # Exceptions
    "SydpowerError",
    "SydpowerConnectionError",
    "CRCError",
    "ProtocolError",
    "DeviceNotFoundError",
    "CommandTimeoutError",
    # Protocol primitives (useful for custom commands / debugging)
    "crc16_modbus",
    "build_read_holding_registers",
    "build_read_input_registers",
    "build_write_registers",
    "RegisterResponse",
    "WriteResponse",
    "ResponseBuffer",
]
