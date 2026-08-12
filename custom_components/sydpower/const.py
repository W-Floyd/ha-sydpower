"""Constants for the Sydpower integration."""

DOMAIN = "sydpower"

# Config entry keys
CONF_ADDRESS = "address"
CONF_NAME = "name"
CONF_PRODUCT_KEY = "product_key"
CONF_MODBUS_ADDRESS = "modbus_address"
CONF_MODBUS_COUNT = "modbus_count"
CONF_PROTOCOL_VERSION = "protocol_version"

# How often to poll the device for fresh register data (seconds).
POLL_INTERVAL = 30

# ── Control registers (holding bank) ──────────────────────────────────────────
# Registers 24, 25, 26 and 27 are transition-confirmed on a protocol v0 device
# and match upstream's v1 constants; 27 is additionally write-verified.
# See docs/register-map-v0.md. Every write goes through the library's
# WRITABLE_HOLDING_REGISTERS allowlist, which is the authority on valid ranges.
REG_AC_CHARGE_LIMIT = 13
REG_USB_CONTROL = 24
REG_DC_CONTROL = 25
REG_AC_CONTROL = 26
REG_LIGHT_CONTROL = 27
REG_KEY_SOUND = 56
REG_AC_SILENT_CONTROL = 57
REG_THRESHOLD_DISCHARGE = 66
REG_THRESHOLD_CHARGE = 67

# ── Output state bits in input register 41 ────────────────────────────────────
# Confirmed empirically by toggling each output in isolation.
STATE_REGISTER = 41
STATE_USB_BIT = 1 << 9
STATE_DC_BIT = 1 << 10
STATE_AC_BIT = 1 << 11
STATE_LIGHT_BIT = 1 << 12

# ── Select options ────────────────────────────────────────────────────────────
# Light modes map directly to register 27's value (0-3). Modes 2 and 3 are
# untested on v0 hardware.
LIGHT_MODES = ["Off", "On", "SOS", "Flashing"]
# AC charge limit is 1-based: option index + 1 is written to register 13.
AC_CHARGE_LIMITS = ["300W", "500W", "700W", "900W", "1100W"]

# Thresholds are stored in permille on the device (80% -> 800).
THRESHOLD_SCALE = 10
