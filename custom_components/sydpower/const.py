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

# How often to poll the device for fresh register data (seconds). Overridable per
# entry through the options flow; this is the default.
POLL_INTERVAL = 30

# Home Assistant's documented floor for a polling integration. A healthy cycle here
# is 1.0-1.5 s, most of it spent establishing the BLE connection, and the retry path
# can run far longer, so anything near this floor risks overlapping refreshes.
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 3600

# Option keys (config entry options, not data).
CONF_POLL_INTERVAL = "poll_interval"

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

# Scheduled charging: holding 63 holds the delay in minutes until charging starts,
# and writing 0 cancels it. The app computes the delay from a requested time of day,
# wrapping midnight, then polls input 57 — the countdown — until it matches.
REG_SCHEDULED_CHARGE = 63
INPUT_SCHEDULED_CHARGE_COUNTDOWN = 57

# Powers the unit down. The app writes 1 behind a confirmation modal.
REG_REMOTE_SHUTDOWN = 64

# Maximum charging current. The app offers 1..holding[17] and writes the chosen
# value to holding[20], so the ceiling is declared by the device rather than fixed.
# Its label is unqualified — 最大充电电流设置, "maximum charging current setting" —
# and the page is titled AC charging settings, though 20 A at 110 V would exceed the
# charge-power ceiling of 1100 W, so it may govern the DC/PV input instead.
REG_MAX_CHARGE_CURRENT = 20
REG_MAX_CHARGE_CURRENT_CEILING = 17

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

# ── Options: calibration ──────────────────────────────────────────────────────
# The device under-reports its output while charging. Rather than store a chosen
# correction model, the options hold observations and the model is fitted from
# them — see sydpower/calibration.py for the measurements and the reasoning.
CONF_CALIBRATION_SAMPLES = "calibration_samples"

# The three power registers a calibration sample records. A sample must always
# hold the *raw* register values, never what the sensors display: once a correction
# is active the sensors are corrected, and fitting a new sample against corrected
# readings would measure the residual error and add it to the existing correction.
# The options flow therefore reads these registers itself rather than asking for
# them, so a sample cannot be contaminated by the correction it will replace.
REG_INPUT_POWER = 6
REG_OUTPUT_POWER = 39
REG_CHARGE_POWER = 3

# Fields of one observation, named to match CalibrationSample's arguments so a
# stored dict can be splatted straight into it.
CONF_SAMPLE_CHARGE_REPORTED = "charge_reported"
CONF_SAMPLE_OUT_REPORTED = "out_reported"
CONF_SAMPLE_OUT_TRUE = "out_true"
CONF_SAMPLE_IN_REPORTED = "in_reported"
CONF_SAMPLE_IN_TRUE = "in_true"

# What the options form should do, since a list needs more than one form.
CONF_ACTION = "action"
ACTION_KEEP = "keep"
ACTION_ADD_SAMPLE = "add_sample"
ACTION_REVIEW_SAMPLES = "review_samples"
ACTION_CLEAR_SAMPLES = "clear_samples"
ACTIONS = (
    ACTION_KEEP,
    ACTION_ADD_SAMPLE,
    ACTION_REVIEW_SAMPLES,
    ACTION_CLEAR_SAMPLES,
)

# Which stored samples to drop, on the review form.
CONF_REMOVE_SAMPLES = "remove"
