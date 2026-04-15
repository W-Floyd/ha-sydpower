"""
All runtime constants in one place.

Adjust values here before connecting if your environment differs from the
defaults extracted from the BrightEMS application.
"""

# ── BLE UUIDs ─────────────────────────────────────────────────────────────────
# Source: app-service-beautified.js lines 75631–75633
BLE_SERVICE_UUID     = "0000A002-0000-1000-8000-00805F9B34FB"
BLE_WRITE_CHAR_UUID  = "0000C304-0000-1000-8000-00805F9B34FB"
BLE_NOTIFY_CHAR_UUID = "0000C305-0000-1000-8000-00805F9B34FB"

# ── BLE advertisement filter ──────────────────────────────────────────────────
# Source: ble_handler_pretty.js line 49
DEVICE_NAME_PREFIXES: tuple[str, ...] = ("POWER-", "Socket-", "Meter-", "DC_DC-")

# ── Modbus defaults ───────────────────────────────────────────────────────────
# Source: app-service-beautified.js lines 75650–75651 (productInfo defaults)
# These are overridden per-device by the product catalog when available.
DEFAULT_MODBUS_ADDRESS: int = 18  # 0x12 — slave address byte in every packet
DEFAULT_MODBUS_COUNT:   int = 85  # register count in a bulk read

# ── Timing (seconds) ──────────────────────────────────────────────────────────
SCAN_TIMEOUT:     float = 10.0  # BLE scan duration
CONNECT_TIMEOUT:  float = 10.0  # BLE connection attempt timeout
COMMAND_TIMEOUT:  float =  5.0  # wait for response after write
MTU_SETTLE_DELAY: float =  0.2  # pause after MTU negotiation (mirrors rm(200, "setBLEMTU"))

# ── Retry limits ──────────────────────────────────────────────────────────────
# Source: app-service-beautified.js line 76411 (app allows 4 total sends = 3 retries)
MAX_COMMAND_RETRIES: int = 3
