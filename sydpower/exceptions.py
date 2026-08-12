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


class UnsafeRegisterWriteError(SydpowerError):
    """
    Rejected a holding-register write that is not known to be safe.

    Raised when the target register is not in
    :data:`sydpower.constants.WRITABLE_HOLDING_REGISTERS`, or when the value
    falls outside that register's verified range.  Writing an unverified
    register or value can put the device into an unrecoverable boot loop, so
    this is enforced before anything reaches the wire.
    """
