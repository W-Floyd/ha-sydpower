"""
BLE scanner for Sydpower / BrightEMS devices.

Devices are identified by their local name prefix (POWER-, Socket-, Meter-,
DC_DC-) and the presence of at least one advertised service UUID.  When a
product catalog is available the scanner also populates per-device Modbus
parameters so callers can construct a ``SydpowerDevice`` without guessing.

Source: onBluetoothDeviceFound handler, app-service-beautified.js lines
        75837–75943 and ble_handler_pretty.js lines 46–97.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from . import catalog as _catalog
from .constants import (
    DEFAULT_MODBUS_ADDRESS,
    DEFAULT_MODBUS_COUNT,
    DEVICE_NAME_PREFIXES,
    SCAN_TIMEOUT,
)

_log = logging.getLogger(__name__)


@dataclass
class DiscoveredDevice:
    """
    A Sydpower device found during a BLE scan.

    ``address`` is the OS-level identifier to pass to ``SydpowerDevice``.
    ``advertis`` is the colon-separated MAC-like device ID parsed from the
    advertisement payload (used by the BrightEMS app as ``device_id``).
    ``modbus_address``, ``modbus_count``, and ``protocol_version`` are resolved
    from the product catalog when available; otherwise the library defaults
    from ``constants.py`` are used.
    """

    name: str
    address: str            # OS BLE address for BleakClient
    service_uuid: str       # first advertised service UUID (identifies product)
    product_key: str        # "<SERVICE_UUID>_<NAME>" — catalog lookup key
    advertis: str           # parsed device ID, e.g. "AA:BB:CC:DD:EE:FF"
    init_status: int        # status byte from advertisement payload
    serial_no: str | None   # 16-byte serial number if present in payload
    modbus_address: int     # Modbus slave address (from catalog or default)
    modbus_count: int       # bulk-read register count (from catalog or default)
    protocol_version: int   # 0 = legacy, 1+ = extended write format


def _parse_advertisement(
    device: BLEDevice,
    adv: AdvertisementData,
) -> DiscoveredDevice | None:
    """
    Attempt to parse a BLE advertisement as a Sydpower device.

    Returns ``None`` if the device does not match the expected name prefixes.
    """
    name = device.name or adv.local_name or ""
    if not any(name.startswith(p) for p in DEVICE_NAME_PREFIXES):
        return None

    svc_uuids = [u.upper() for u in (adv.service_uuids or [])]
    if not svc_uuids:
        return None

    service_uuid = svc_uuids[0]
    product_key = f"{service_uuid}_{name}"

    # Resolve Modbus parameters from the catalog; fall back to defaults.
    params = _catalog.get_device_params(product_key)
    modbus_address   = params["modbus_address"]   if params else DEFAULT_MODBUS_ADDRESS
    modbus_count     = params["modbus_count"]     if params else DEFAULT_MODBUS_COUNT
    protocol_version = params["protocol_version"] if params else 1

    # Parse the advertisement payload for the device ID, init status, and
    # optional serial number.
    #
    # Payload layout (source: app-service-beautified.js lines 75871–75891):
    #   [optional 0x99 prefix byte for legacy protocol]
    #   [6 bytes: device MAC / advertis ID]
    #   [1 byte:  init status]
    #   [16 bytes optional: ASCII serial number]
    #
    # The payload is carried in service_data for the device's service UUID, or
    # in manufacturer_data if service_data is absent.
    raw_payload: bytes | None = None
    for key, value in (adv.service_data or {}).items():
        if key.upper() == service_uuid:
            raw_payload = value
            break
    if raw_payload is None and adv.manufacturer_data:
        raw_payload = next(iter(adv.manufacturer_data.values()))

    advertis = ""
    init_status = 0
    serial_no: str | None = None

    if raw_payload:
        hex_data = raw_payload.hex()
        offset = 0

        # Legacy devices with protocol_version == 0 may prefix payload with 0x99.
        if protocol_version == 0 and hex_data[:2] == "99":
            offset = 2  # skip 1 byte (2 hex chars)

        if len(hex_data) >= offset + 12:
            mac_hex = hex_data[offset : offset + 12]
            advertis = ":".join(
                mac_hex[i : i + 2].upper() for i in range(0, 12, 2)
            )

        if len(hex_data) >= offset + 14:
            init_status = int(hex_data[offset + 12 : offset + 14], 16)

        remainder = hex_data[offset + 14 :]
        if len(remainder) == 32:  # 16 bytes
            serial_no = bytes.fromhex(remainder).decode("ascii", errors="replace")

    return DiscoveredDevice(
        name=name,
        address=device.address,
        service_uuid=service_uuid,
        product_key=product_key,
        advertis=advertis,
        init_status=init_status,
        serial_no=serial_no,
        modbus_address=modbus_address,
        modbus_count=modbus_count,
        protocol_version=protocol_version,
    )


async def scan(timeout: float = SCAN_TIMEOUT) -> list[DiscoveredDevice]:
    """
    Scan for Sydpower BLE devices.

    Runs for ``timeout`` seconds and returns all discovered devices sorted by
    signal strength (strongest RSSI first).  Each unique BLE address appears
    at most once; if multiple advertisements are received the one with the
    best RSSI is kept.
    """
    # address → (DiscoveredDevice, rssi)
    results: dict[str, tuple[DiscoveredDevice, int]] = {}

    def _callback(device: BLEDevice, adv: AdvertisementData) -> None:
        parsed = _parse_advertisement(device, adv)
        if parsed is None:
            return
        rssi = adv.rssi or -100
        existing = results.get(device.address)
        if existing is None or rssi > existing[1]:
            results[device.address] = (parsed, rssi)
            _log.debug("Found %s (%s) RSSI=%d", parsed.name, device.address, rssi)

    async with BleakScanner(detection_callback=_callback):
        await asyncio.sleep(timeout)

    return [dev for dev, _rssi in sorted(results.values(), key=lambda x: -x[1])]
