"""Constants for the Sydpower integration."""

DOMAIN = "sydpower"

# Config entry keys
CONF_ADDRESS = "address"
CONF_NAME = "name"
CONF_PRODUCT_KEY = "product_key"
CONF_MODEL = "model"
CONF_MODBUS_ADDRESS = "modbus_address"
CONF_MODBUS_COUNT = "modbus_count"
CONF_PROTOCOL_VERSION = "protocol_version"

# How often to poll the device for fresh register data (seconds).
POLL_INTERVAL = 30

# ── Control registers (holding bank) ──────────────────────────────────────────
# Only the registers the integration must name explicitly. Output controls are no
# longer listed here: switches and state sensors are derived from the catalog,
# which carries each output's control register. See docs/register-map-v0.md for
# the full map, and the library's WRITABLE_HOLDING_REGISTERS for valid ranges.
#
# The light stays named because the catalog cannot express what makes it special:
# its register holds a mode, and its children are values rather than state bits.
# The thresholds stay because the catalog does not describe them at all, yet
# writing them and reading the values back was verified on hardware.
REG_LIGHT_CONTROL = 27
REG_THRESHOLD_DISCHARGE = 66
REG_THRESHOLD_CHARGE = 67

# Controls the app itself hardcodes, absent from the catalog for every product.
# Evidenced in the beautified bundle rather than inherited on trust:
#   56  a toggle written by the setting page, labelled device.key-sound
#   57  bound as a form control over the holding bank, labelled
#       device.silent-charging, which is rendered in three places
REG_KEY_SOUND = 56
REG_AC_SILENT_CONTROL = 57

# ── Output state bits in input register 41 ────────────────────────────────────
# Confirmed empirically by toggling each output in isolation.
STATE_REGISTER = 41
STATE_USB_BIT = 1 << 9
STATE_DC_BIT = 1 << 10
STATE_AC_BIT = 1 << 11
STATE_LIGHT_BIT = 1 << 12

# ── Select options ────────────────────────────────────────────────────────────
# Light modes map directly to register 27's value (0-3); all four are
# write-verified on v0 hardware. Register 27 is a state register, so the catalog
# does not describe it — unlike the settings registers, which are catalog-driven
# (see select.py) with encodings in the library's SETTING_ENCODINGS.
LIGHT_MODES = ["Off", "On", "SOS", "Flashing"]

# Thresholds are stored in permille on the device (80% -> 800).
THRESHOLD_SCALE = 10
