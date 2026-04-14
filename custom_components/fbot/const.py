"""Constants for the Fbot integration."""

DOMAIN = "fbot"

# Config entry data key for the list of BLE service UUIDs seen at pairing time.
CONF_SERVICE_UUIDS = "service_uuids"

# BLE characteristic UUIDs
WRITE_CHAR_UUID = "0000c304-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000c305-0000-1000-8000-00805f9b34fb"

# ---------------------------------------------------------------------------
# Data keys in coordinator.data — passive telemetry (input registers, 0x04)
# ---------------------------------------------------------------------------
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

# Firmware version keys (from holding registers 0x03)
KEY_BMS_VERSION = "bms_version"
KEY_AC_VERSION = "ac_version"
KEY_PV_VERSION = "pv_version"
KEY_PANEL_VERSION = "panel_version"

# ---------------------------------------------------------------------------
# French → English translation map for catalog function_name / unit values.
# The BrightEMS product catalog uses French labels from the original app.
# Only phrases that are actually French are listed here; English-only labels
# (e.g. "AC", "QC3.0", "PD 100W") pass through untouched.
# ---------------------------------------------------------------------------
_FR_TO_EN: dict[str, str] = {
    "Sortie USB": "USB Output",
    "Sortie USB ": "USB Output",  # trailing-space variant present in catalog
    "Sortie AC": "AC Output",
    "Sortie DC": "DC Output",
    "Lampe LED": "LED Lamp",
    "Recharge de véhicule": "Vehicle Charging",
    "Mode d'éclairage continu": "Continuous Light Mode",
    "Mode SOS": "SOS Mode",
    "Mode Flash": "Flash Mode",
    "Puissance de charge AC": "AC Charge Power",
    "Réglage du type d'entrée DC": "DC Input Type",
    "Réglage de la puissance de sortie maximale connectée au réseau": "Max Grid Output Power",
    "Temps de veille à vide USB": "USB Idle Standby Time",
    "Temps de veille à vide AC": "AC Idle Standby Time",
    "Temps de veille à vide DC": "DC Idle Standby Time",
    "Temps d'arrêt complet de l'appareil": "Full Shutdown Time",
    "Temps d'arrêt du chargeur": "Charger Shutdown Time",
    "Temps d'extinction de l'écran": "Screen Off Time",
}

_FR_UNIT_TO_EN: dict[str, str] = {
    "Minute": "min",
    "Heure": "h",
    "Mode PV": "PV Mode",
}


def translate(text: str) -> str:
    """Return an English label for *text*, falling back to the original string."""
    return _FR_TO_EN.get(text.strip(), text)


def translate_unit(unit: str) -> str:
    """Return an English unit label, falling back to the original string."""
    return _FR_UNIT_TO_EN.get(unit.strip(), unit)
