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

# ── Writable holding registers ────────────────────────────────────────────────
# Writing a bad value to a settings register can put the unit into a permanent
# 7-8 second boot loop.  This is NOT recoverable in software: Bluetooth never
# stays up long enough to accept a corrective write, and emulating the internal
# ESP32 over the ARM<->ESP32 UART to rewrite the registers has been tried and
# failed.  The only known recovery is physically cutting the ESP32 UART TX pin
# (pin 21), which permanently disables WiFi/Bluetooth on the unit.
# Source: Ylianst/ESP-FBot internals/README.md, "Fixing a PowerStation in a
#         Boot Loop" (upstream commits 4b809d6..2b22754).
#
# Therefore writes are restricted to registers with a verified meaning and a
# verified accepted range.  Map of register number -> (min_value, max_value),
# both inclusive.  Ranges are taken from the write paths in the upstream
# ESP-Home component, components/fbot/fbot.cpp lines 567-679.
# ── Setting register encodings ────────────────────────────────────────────────
# The catalog gives a register and its option list but not how the option is
# stored. The BrightEMS app applies these rules, keyed by register number, on the
# portable-power-station settings page (app-service.js, the read/write pair around
# `data_list.indexOf(...)`):
#
#   "raw"    the register holds the option value itself
#   "index1" the register holds the option's position plus one
#   "x60"    the register holds the option value multiplied by 60, so the
#            displayed unit is 60x coarser than what is stored
#
# The balcony-PV page carries its own copy of these rules with different register
# numbers, so this table is specific to the 80-register portable stations.
SETTING_ENCODING_RAW = "raw"
SETTING_ENCODING_INDEX1 = "index1"
SETTING_ENCODING_X60 = "x60"

SETTING_ENCODINGS: dict[int, str] = {
    13: SETTING_ENCODING_INDEX1,  # AC charging power
    60: SETTING_ENCODING_X60,     # AC no-load standby, listed in hours
    61: SETTING_ENCODING_X60,     # DC no-load standby, listed in hours
    62: SETTING_ENCODING_X60,     # screen rest time, listed in minutes
}


def setting_encoding(register: int) -> str:
    """Return how *register* stores its option, defaulting to the raw value."""
    return SETTING_ENCODINGS.get(register, SETTING_ENCODING_RAW)


WRITABLE_HOLDING_REGISTERS: dict[int, tuple[int, int]] = {
    13: (1, 5),      # AC charge limit, enumerated 1-5
    24: (0, 1),      # USB output on/off
    25: (0, 1),      # DC output on/off
    26: (0, 1),      # AC output on/off
    27: (0, 3),      # Light mode: 0=off, 1=on, 2=SOS, 3=flashing
    56: (0, 1),      # Key sound on/off
    57: (0, 1),      # AC silent charging on/off
    66: (0, 500),    # Discharge lower limit, permille (0-50.0%)
    67: (100, 1000), # Charge upper limit, permille (10.0-100.0%)
    # Settings described by the product catalog. Ranges span the app's own option
    # lists after the encoding above is applied, so nothing outside what the app
    # itself would write is permitted.
    15: (0, 1),      # DC input type: 0 = PV mode, 1 = DC mode
    59: (0, 30),     # USB no-load standby, minutes (raw)
    60: (0, 1440),   # AC no-load standby, 0-24 h stored x60
    61: (0, 1440),   # DC no-load standby, 0-24 h stored x60
    62: (180, 1800), # Screen rest time, 3-30 min stored x60
    68: (5, 480),    # Whole machine unused time, minutes (raw)
}
