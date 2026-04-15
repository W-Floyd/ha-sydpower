"""
Sydpower Modbus-over-BLE packet construction and response parsing.

Protocol summary (reverse-engineered from app-service-beautified.js):

  CRC: CRC16/Modbus — polynomial 0xA001, init 0xFFFF, appended MSB-first.

  Read request (FC 0x03 / 0x04):
      [addr, fc, start_hi, start_lo, count_hi, count_lo, crc_hi, crc_lo]

  Read response — echoes the request header, then register data, then CRC:
      [addr, fc, start_hi, start_lo, count_hi, count_lo,
       d0_hi, d0_lo, …, dN_hi, dN_lo, crc_hi, crc_lo]

  Write request (FC 0x06), protocol_version >= 1:
      [addr, 0x06, start, count_hi, count_lo, d0_hi, d0_lo, …, crc_hi, crc_lo]

  Write request (FC 0x06), protocol_version == 0 (legacy, single register only):
      [addr, 0x06, start_hi, start_lo, val_hi, val_lo, crc_hi, crc_lo]

  Write response mirrors the write request structure.

Sources: modbus_core_pretty.js (Gn/jn/qn functions), app-service-beautified.js
         GET_BLE_CMD_INFO action (lines 76859–77049).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .exceptions import CRCError, ProtocolError


# ── CRC16 / Modbus ────────────────────────────────────────────────────────────

def crc16_modbus(data: bytes | list[int]) -> int:
    """
    CRC16/Modbus — polynomial 0xA001, initial value 0xFFFF.

    Source: Mn() in modbus_core_pretty.js lines 28–35.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


# ── Packet builders ───────────────────────────────────────────────────────────

def _frame(address: int, func_code: int, payload: list[int]) -> bytes:
    """Assemble address + function code + payload and append a CRC (MSB-first)."""
    frame = [address, func_code, *payload]
    crc = crc16_modbus(frame)
    frame.append(crc >> 8)
    frame.append(crc & 0xFF)
    return bytes(frame)


def build_read_holding_registers(address: int, start: int, count: int) -> bytes:
    """
    FC 0x03 — Read Holding Registers request.

    Source: jn() / getReadModbusCRCLowFront() in modbus_core_pretty.js lines 92–97.
    """
    return _frame(address, 0x03, [start >> 8, start & 0xFF, count >> 8, count & 0xFF])


def build_read_input_registers(address: int, start: int, count: int) -> bytes:
    """
    FC 0x04 — Read Input Registers request.

    Source: getModbusDataCRCLowFront() / Gn() in modbus_core_pretty.js lines 104–108,
            GET_BLE_INPUT_REGISTER action lines 76673–76695.
    """
    return _frame(address, 0x04, [start >> 8, start & 0xFF, count >> 8, count & 0xFF])


def build_write_registers(
    address: int,
    start: int,
    values: list[int],
    protocol_version: int = 1,
) -> bytes:
    """
    FC 0x06 — Write register(s).

    protocol_version >= 1 (extended — supports multiple registers):
        [addr, 0x06, start, count_hi, count_lo, val0_hi, val0_lo, …, crc_hi, crc_lo]

    protocol_version == 0 (legacy — single register only):
        [addr, 0x06, start_hi, start_lo, val_hi, val_lo, crc_hi, crc_lo]

    Source: GET_BLE_HOLDING_REGISTER_SET action, app-service-beautified.js lines
            76587–76629.  getWriteModbusCRCLowFront_new / getWriteModbusCRCLowFront.
    """
    data_bytes: list[int] = []
    for v in values:
        data_bytes.extend([v >> 8, v & 0xFF])

    if protocol_version >= 1:
        count = len(values)
        payload = [start, count >> 8, count & 0xFF, *data_bytes]
    else:
        # Legacy path: FC 0x06 writes a single register with a 2-byte address.
        payload = [start >> 8, start & 0xFF, *data_bytes[:2]]

    return _frame(address, 0x06, payload)


# ── Response types ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RegisterResponse:
    """A fully parsed and CRC-verified read response (FC 0x03 or 0x04)."""
    func_code: int          # 0x03 or 0x04
    start: int              # starting register address (echoed from request)
    count: int              # number of registers (echoed from request)
    registers: tuple[int, ...]  # decoded 16-bit register values
    raw: bytes              # complete raw packet (for diagnostics)


@dataclass(frozen=True)
class WriteResponse:
    """A fully parsed and CRC-verified write response (FC 0x06)."""
    func_code: int   # 0x06
    start: int       # starting register address
    raw: bytes       # complete raw packet (for diagnostics)


# ── Response accumulator ──────────────────────────────────────────────────────

@dataclass
class ResponseBuffer:
    """
    Accumulates BLE notification chunks into a single complete Modbus response.

    The device may split a long response across multiple BLE notifications if
    the payload exceeds the negotiated MTU.  Call ``feed()`` with each incoming
    chunk; it returns ``True`` once a complete, CRC-verified response has been
    assembled.  Then call ``result()`` to obtain the parsed response object.

    Usage::

        buf = ResponseBuffer(modbus_address=18, expected_func_code=0x03,
                             protocol_version=1)
        async for chunk in ble_notifications:
            if buf.feed(chunk):
                response = buf.result()
                break
    """

    modbus_address: int
    expected_func_code: int
    protocol_version: int

    def __post_init__(self) -> None:
        self._raw: list[int] = []
        self._complete: bool = False
        self._expected_total: int = 0  # total expected bytes including CRC

    def feed(self, chunk: bytes) -> bool:
        """
        Append a notification chunk.

        Returns ``True`` once a complete, CRC-verified packet has been received.
        Raises ``CRCError`` if the CRC does not match.
        Raises ``ProtocolError`` for unexpected function codes.
        """
        if self._complete:
            return True

        self._raw.extend(chunk)

        # Need at least address + function code to determine packet shape.
        if len(self._raw) < 2:
            return False

        # Bit 7 of the function code is set by the device to signal a Modbus
        # exception response; mask it off to get the actual function code.
        fc = self._raw[1] & 0x7F

        if fc in (0x03, 0x04):
            # Header: [addr, fc, start_hi, start_lo, count_hi, count_lo]
            if len(self._raw) < 6:
                return False
            count = (self._raw[4] << 8) | self._raw[5]
            self._expected_total = 6 + 2 * count + 2  # header + data + CRC
            if len(self._raw) < self._expected_total:
                return False  # still waiting for more chunks

        elif fc in (0x05, 0x06):
            # Write echo — arrives in a single notification in all observed cases.
            head_size = 5 if self.protocol_version >= 1 else 4
            if len(self._raw) < head_size + 2:
                return False
            self._expected_total = len(self._raw)

        else:
            raise ProtocolError(
                f"Unexpected function code 0x{fc:02X} in response "
                f"(raw prefix: {bytes(self._raw[:8]).hex()})"
            )

        # Verify CRC over all bytes except the trailing two.
        body = self._raw[: self._expected_total - 2]
        crc_recv = (
            self._raw[self._expected_total - 2] << 8
            | self._raw[self._expected_total - 1]
        )
        crc_calc = crc16_modbus(body)
        if crc_calc != crc_recv:
            raise CRCError(
                f"CRC mismatch: calculated 0x{crc_calc:04X}, "
                f"received 0x{crc_recv:04X} "
                f"(raw: {bytes(self._raw[:self._expected_total]).hex()})"
            )

        self._complete = True
        return True

    def result(self) -> RegisterResponse | WriteResponse:
        """
        Return the parsed response object.

        Raises ``ProtocolError`` if called before ``feed()`` has returned ``True``.
        """
        if not self._complete:
            raise ProtocolError("Response is not yet complete; call feed() first.")

        raw = bytes(self._raw[: self._expected_total])
        fc = raw[1] & 0x7F

        if fc in (0x03, 0x04):
            start = (raw[2] << 8) | raw[3]
            count = (raw[4] << 8) | raw[5]
            data = raw[6 : 6 + 2 * count]
            registers = tuple(
                (data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)
            )
            return RegisterResponse(
                func_code=fc,
                start=start,
                count=count,
                registers=registers,
                raw=raw,
            )

        if fc in (0x05, 0x06):
            start = (
                raw[2]
                if self.protocol_version >= 1
                else (raw[2] << 8) | raw[3]
            )
            return WriteResponse(func_code=fc, start=start, raw=raw)

        raise ProtocolError(f"Cannot parse response with FC 0x{fc:02X}")
