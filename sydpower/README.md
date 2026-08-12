# sydpower

A Python library for discovering and communicating with Sydpower / BrightEMS BLE inverter devices and smart meters.

## Features

- **Device Discovery**: Automatically discover Sydpower devices on your local BLE network
- **Modbus Protocol**: Full support for Modbus TCP-like register access over BLE
- **Async API**: Designed for Python's `asyncio` with proper cancellation support
- **Product Catalog**: Built-in support for resolving device-specific Modbus parameters
- **Robust Error Handling**: Comprehensive exception hierarchy for different failure modes

## Installation

```bash
pip install sydpower
```

## Quick Start

### Discovering Devices

```python
import asyncio
from sydpower import scan

async def main():
    # Scan for nearby Sydpower devices (runs for 10 seconds by default)
    devices = await scan()
    
    if not devices:
        print("No devices found")
        return
    
    print(f"Found {len(devices)} device(s)")
    for device in devices:
        print(f"  - {device.name}: {device.address}")

asyncio.run(main())
```

### Connecting and Reading Registers

```python
import asyncio
from sydpower import scan, SydpowerDevice

async def main():
    # Discover devices
    devices = await scan()
    if not devices:
        return
    
    # Connect to the first device found
    async with SydpowerDevice.from_discovered(devices[0]) as dev:
        # Read holding registers (FC 0x03)
        holding = await dev.read_holding_registers()
        print(f"Holding registers: {holding}")
        
        # Read input registers (FC 0x04)
        inputs = await dev.read_input_registers()
        print(f"Input registers: {inputs}")
        
        # Write single register (FC 0x06). Only known-safe registers are
        # permitted -- see "Write Safety" below.
        await dev.write_register(start=26, value=1)   # AC output on
        
        # Write multiple consecutive registers. Requires protocol_version >= 1;
        # legacy v0 devices must issue one write per register.
        await dev.write_registers(start=66, values=[100, 900])  # 10% / 90% limits

asyncio.run(main())
```

### Direct Connection by Address

```python
from sydpower import SydpowerDevice

async def main():
    # Connect directly using a known BLE address
    async with SydpowerDevice("AA:BB:CC:DD:EE:FF") as dev:
        registers = await dev.read_holding_registers()
        print(registers)

asyncio.run(main())
```

## Package Structure

```
sydpower/
├── __init__.py       # Main package exports
├── constants.py      # Runtime configuration constants
├── device.py         # SydpowerDevice class for BLE communication
├── scanner.py        # BLE device discovery functionality
├── protocol.py       # Protocol primitives and helpers
├── catalog.py        # Product catalog for device parameters
├── exceptions.py     # Exception hierarchy
├── .catalog_data.json  # Device parameter catalog
└── tests/            # Test suite
```

## API Reference

### `scan(timeout=10.0)`

Scan for Sydpower BLE devices on the local network.

**Returns**: List of `DiscoveredDevice` objects sorted by signal strength.

### `SydpowerDevice(address, ...)`

Async BLE interface for a single Sydpower inverter or smart-meter device.

**Parameters**:
- `address`: OS-level BLE address (e.g., `"AA:BB:CC:DD:EE:FF"`)
- `modbus_address`: Modbus slave address (default: 18)
- `modbus_count`: Number of registers in bulk read (default: 85)
- `protocol_version`: 0 = legacy, 1+ = extended write format (default: 1)
- `allow_unsafe_writes`: Bypass the write allowlist (default: `False`)

**Methods**:
- `connect()`: Establish BLE connection and subscribe to notifications
- `disconnect()`: Close the BLE connection
- `read_holding_registers(start=0, count=None)`: Read holding registers (FC 0x03)
- `read_input_registers(start=0, count=None)`: Read input registers (FC 0x04)
- `write_register(start, value)`: Write single register (FC 0x06)
- `write_registers(start, values)`: Write multiple registers

## Write Safety

Writing a bad value to a settings register can put the unit into a permanent
7-8 second boot loop. This is **not recoverable in software**: Bluetooth never
stays up long enough to accept a corrective write, and emulating the internal
ESP32 over the ARM/ESP32 UART to rewrite the registers has been tried and
failed. The only known recovery is physically cutting the ESP32 UART TX pin,
which permanently disables WiFi and Bluetooth on the unit.

Because of that, writes are restricted to registers with both a verified
meaning and a verified accepted range. Anything else raises
`UnsafeRegisterWriteError` before a packet reaches the wire.

| Register | Meaning | Allowed values |
| --- | --- | --- |
| 13 | AC charge limit | 1-5 (enumerated) |
| 24 | USB output | 0 = off, 1 = on |
| 25 | DC output | 0 = off, 1 = on |
| 26 | AC output | 0 = off, 1 = on |
| 27 | Light mode | 0 = off, 1 = on, 2 = SOS, 3 = flashing |
| 56 | Key sound | 0 = off, 1 = on |
| 57 | AC silent charging | 0 = off, 1 = on |
| 66 | Discharge lower limit | 0-500 permille (0-50.0%) |
| 67 | Charge upper limit | 100-1000 permille (10.0-100.0%) |

The table lives in `WRITABLE_HOLDING_REGISTERS` in
[constants.py](constants.py). To probe unmapped registers deliberately, pass
`allow_unsafe_writes=True` — this logs a warning and accepts the brick risk.

### `DiscoveredDevice`

Dataclass representing a discovered Sydpower device:
- `name`: Device name from advertisement (e.g., "POWER-1234")
- `address`: OS BLE address for connection
- `service_uuid`: Advertised service UUID
- `product_key`: Catalog lookup key
- `advertis`: Parsed device ID from payload
- `modbus_address`: Device-specific Modbus slave address
- `modbus_count`: Device-specific register count
- `protocol_version`: Protocol version number

## Exceptions

| Exception | Description |
|-----------|-------------|
| `SydpowerError` | Base exception for all library errors |
| `SydpowerConnectionError` | BLE connection failures |
| `CommandTimeoutError` | Device didn't respond in time |
| `DeviceNotFoundError` | Device not found during scan |
| `CRCError` | Modbus CRC checksum mismatch |
| `ProtocolError` | Protocol-level errors |

## Development

### Running Tests

```bash
python -m pytest sydpower/tests/ -v
```

### Building the Package

```bash
pip install build
python -m build
```

This produces `dist/sydpower-*.whl` and `dist/sydpower-*.tar.gz`.

## Compatibility

- **Python**: 3.9+
- **Dependencies**: 
  - `bleak` ≥ 0.21 (async BLE client)
- **Platform Support**:
  - Linux (BlueZ 5+)
  - macOS (CoreBluetooth)
  - Windows (Windows BLE API)

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Acknowledgments

This library was reverse-engineered from the [BrightEMS](https://www.brightems.com/) mobile application. Special thanks to the Sydpower engineering team for their smart hardware.