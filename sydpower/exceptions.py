"""Custom exceptions for the sydpower library."""


class SydpowerError(Exception):
    """Base class for all sydpower errors."""


class CRCError(SydpowerError):
    """Response CRC does not match the computed checksum."""


class ProtocolError(SydpowerError):
    """Unexpected or malformed response from the device."""


class DeviceNotFoundError(SydpowerError):
    """No matching Sydpower device found during BLE scan."""


class CommandTimeoutError(SydpowerError):
    """Device did not respond within COMMAND_TIMEOUT seconds."""


class ConnectionError(SydpowerError):
    """Failed to establish or maintain a BLE connection."""
