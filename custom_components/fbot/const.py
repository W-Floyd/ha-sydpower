"""Constants for the Fbot integration."""

DOMAIN = "fbot"

# BLE UUIDs
SERVICE_UUID = "0000a002-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000c304-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000c305-0000-1000-8000-00805f9b34fb"

# Holding register addresses (written via function code 0x06)
REG_AC_CHARGE_LIMIT = 13
REG_USB_CONTROL = 24
REG_DC_CONTROL = 25
REG_AC_CONTROL = 26
REG_LIGHT_CONTROL = 27
REG_USB_A1_OUT = 30
REG_USB_A2_OUT = 31
REG_USB_C1_OUT = 34
REG_USB_C2_OUT = 35
REG_USB_C3_OUT = 36
REG_USB_C4_OUT = 37
REG_KEY_SOUND = 56
REG_AC_SILENT_CONTROL = 57
REG_THRESHOLD_DISCHARGE = 66
REG_THRESHOLD_CHARGE = 67

# State flag bits in status register 41
STATE_USB_BIT = 512    # bit 9
STATE_DC_BIT = 1024    # bit 10
STATE_AC_BIT = 2048    # bit 11
STATE_LIGHT_BIT = 4096  # bit 12

# Data keys used in coordinator.data dict
KEY_BATTERY_PERCENT = "battery_percent"
KEY_BATTERY_S1_PERCENT = "battery_s1_percent"
KEY_BATTERY_S2_PERCENT = "battery_s2_percent"
KEY_BATTERY_S1_CONNECTED = "battery_s1_connected"
KEY_BATTERY_S2_CONNECTED = "battery_s2_connected"
KEY_AC_INPUT_POWER = "ac_input_power"
KEY_DC_INPUT_POWER = "dc_input_power"
KEY_INPUT_POWER = "input_power"
KEY_OUTPUT_POWER = "output_power"
KEY_SYSTEM_POWER = "system_power"
KEY_TOTAL_POWER = "total_power"
KEY_REMAINING_TIME = "remaining_time"
KEY_CHARGE_LEVEL = "charge_level"
KEY_AC_OUT_VOLTAGE = "ac_out_voltage"
KEY_AC_OUT_FREQUENCY = "ac_out_frequency"
KEY_AC_IN_FREQUENCY = "ac_in_frequency"
KEY_TIME_TO_FULL = "time_to_full"
KEY_USB_A1_POWER = "usb_a1_power"
KEY_USB_A2_POWER = "usb_a2_power"
KEY_USB_C1_POWER = "usb_c1_power"
KEY_USB_C2_POWER = "usb_c2_power"
KEY_USB_C3_POWER = "usb_c3_power"
KEY_USB_C4_POWER = "usb_c4_power"
KEY_USB_ACTIVE = "usb_active"
KEY_DC_ACTIVE = "dc_active"
KEY_AC_ACTIVE = "ac_active"
KEY_LIGHT_ACTIVE = "light_active"
KEY_THRESHOLD_CHARGE = "threshold_charge"
KEY_THRESHOLD_DISCHARGE = "threshold_discharge"
KEY_AC_SILENT = "ac_silent"
KEY_KEY_SOUND = "key_sound"
KEY_LIGHT_MODE = "light_mode"
KEY_AC_CHARGE_LIMIT = "ac_charge_limit"

# Select options
LIGHT_MODES = ["Off", "On", "SOS", "Flashing"]
AC_CHARGE_LIMITS = ["300W", "500W", "700W", "900W", "1100W"]
