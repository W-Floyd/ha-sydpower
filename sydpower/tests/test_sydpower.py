"""
Tests for the sydpower package.

This module contains basic tests for the scanner, device, and protocol
modules. These are placeholder tests to demonstrate the testing structure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from bleak.backends.device import BLEDevice

from sydpower import (
    WRITABLE_HOLDING_REGISTERS,
    DiscoveredDevice,
    RegisterResponse,
    ResponseBuffer,
    SydpowerDevice,
    build_read_holding_registers,
    build_read_input_registers,
    build_write_registers,
    crc16_modbus,
    scan,
)
from sydpower import SydpowerConnectionError
from sydpower.exceptions import (
    CommandTimeoutError,
    CRCError,
    DeviceNotFoundError,
    ProtocolError,
    SydpowerError,
    UnsafeRegisterWriteError,
)


class TestSydpowerErrorHierarchy:
    """Test the exception hierarchy."""

    def test_sydpower_error_base(self):
        """Test that SydpowerError is the base class."""
        assert issubclass(SydpowerConnectionError, SydpowerError)
        assert issubclass(CommandTimeoutError, SydpowerError)
        assert issubclass(CRCError, SydpowerError)
        assert issubclass(ProtocolError, SydpowerError)
        assert issubclass(DeviceNotFoundError, SydpowerError)


class TestDiscoveredDevice:
    """Test the DiscoveredDevice dataclass."""

    def test_discovered_device_creation(self):
        """Test creating a DiscoveredDevice instance."""
        device = DiscoveredDevice(
            name="POWER-TEST",
            address="AA:BB:CC:DD:EE:FF",
            service_uuid="0000A002-0000-1000-8000-00805F9B34FB",
            product_key="0000A002-0000-1000-8000-00805F9B34FB_POWER-TEST",
            advertis="11:22:33:44:55:66",
            init_status=0,
            serial_no="TEST1234567890AB",
            modbus_address=18,
            modbus_count=85,
            protocol_version=1,
        )

        assert device.name == "POWER-TEST"
        assert device.address == "AA:BB:CC:DD:EE:FF"
        assert device.protocol_version == 1

    def test_discovered_device_defaults(self):
        """Test DiscoveredDevice with default values."""
        device = DiscoveredDevice(
            name="POWER-TEST",
            address="AA:BB:CC:DD:EE:FF",
            service_uuid="0000A002-0000-1000-8000-00805F9B34FB",
            product_key="0000A002-0000-1000-8000-00805F9B34FB_POWER-TEST",
            advertis="11:22:33:44:55:66",
            init_status=0,
            serial_no=None,
            modbus_address=18,
            modbus_count=85,
            protocol_version=1,
        )

        assert device.modbus_address == 18
        assert device.modbus_count == 85
        assert device.protocol_version == 1


class TestProtocolFunctions:
    """Test protocol primitive functions."""

    def test_crc16_modbus(self):
        """Test CRC16 Modbus calculation."""
        # Example from Modbus specification
        data = bytes([0x01, 0x02, 0x03, 0x04])
        crc = crc16_modbus(data)
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFF

    def test_build_read_holding_registers(self):
        """Test building a read holding registers command."""
        packet = build_read_holding_registers(address=1, start=0, count=10)

        assert isinstance(packet, bytes)
        assert len(packet) == 8  # Standard Modbus RTU frame

        # Packet structure: [slave][func][start_hi][start_lo][count_hi][count_lo][crc_lo][crc_hi]
        assert packet[0] == 0x01  # Slave address
        assert packet[1] == 0x03  # Function code

    def test_build_read_input_registers(self):
        """Test building a read input registers command."""
        packet = build_read_input_registers(address=1, start=0, count=10)

        assert isinstance(packet, bytes)
        assert packet[1] == 0x04  # Function code for input registers

    def test_build_write_registers(self):
        """Test building a write registers command."""
        packet = build_write_registers(address=1, start=0, values=[100, 200, 300])

        assert isinstance(packet, bytes)
        assert len(packet) > 0

    def test_legacy_write_single_register(self):
        """protocol_version 0 encodes a single register with a 2-byte address."""
        packet = build_write_registers(
            address=17, start=26, values=[1], protocol_version=0
        )

        # [addr, 0x06, start_hi, start_lo, val_hi, val_lo, crc_hi, crc_lo]
        assert len(packet) == 8
        assert packet[:6] == bytes([17, 0x06, 0x00, 26, 0x00, 0x01])

    def test_legacy_write_rejects_multiple_registers(self):
        """
        protocol_version 0 has no multi-register encoding.

        It must raise rather than silently writing only the first value — the
        legacy path previously truncated to two data bytes.
        """
        with pytest.raises(ProtocolError, match="single-register writes only"):
            build_write_registers(
                address=17, start=66, values=[100, 900], protocol_version=0
            )


class TestCatalogModel:
    """
    Test model resolution from the shipped catalog.

    The catalog carries no consumer brand — its largest group is the OEM's
    white-label bucket and resellers such as AFERIY do not appear in it — so the
    model code is the only identity available.
    """

    def test_known_product_resolves_to_a_model(self):
        from sydpower.catalog import get_product_model

        model = get_product_model("00004380-0000-1000-8000-00805F9B34FB_POWER-8043")
        assert model == "P210-A0E01"

    def test_unknown_product_returns_none(self):
        from sydpower.catalog import get_product_model

        assert get_product_model("00000000-0000-0000-0000-000000000000_NOPE") is None

    def test_every_catalog_product_has_a_model(self):
        """A product without a model would silently show a blank in the UI."""
        from sydpower.catalog import get_product_model, list_product_keys

        keys = list_product_keys()
        assert keys, "catalog is empty"
        missing = [k for k in keys if not get_product_model(k)]
        assert not missing, f"{len(missing)} product(s) lack a model, e.g. {missing[:3]}"


class TestSettingEncodings:
    """
    Test how a setting's option maps onto its register value.

    The catalog gives a register and an option list but not the encoding. The app
    applies rules keyed by register number, and applying the wrong one writes a
    plausible-looking but incorrect value to a persisted settings register.
    """

    def test_defaults_to_the_raw_value(self):
        from sydpower.constants import SETTING_ENCODING_RAW, setting_encoding

        assert setting_encoding(59) == SETTING_ENCODING_RAW
        assert setting_encoding(9999) == SETTING_ENCODING_RAW

    def test_charge_power_is_a_one_based_index(self):
        from sydpower.constants import SETTING_ENCODING_INDEX1, setting_encoding

        assert setting_encoding(13) == SETTING_ENCODING_INDEX1

    def test_standby_timers_are_scaled_by_sixty(self):
        from sydpower.constants import SETTING_ENCODING_X60, setting_encoding

        for register in (60, 61, 62):
            assert setting_encoding(register) == SETTING_ENCODING_X60

    def test_every_encoded_register_is_writable(self):
        """An encoding for a register the guard rejects would be unreachable."""
        from sydpower.constants import SETTING_ENCODINGS, WRITABLE_HOLDING_REGISTERS

        missing = sorted(set(SETTING_ENCODINGS) - set(WRITABLE_HOLDING_REGISTERS))
        assert not missing, f"encoded but not writable: {missing}"


class TestProductSettings:
    """Test resolving a product's settings from the catalog."""

    KEY = "00004380-0000-1000-8000-00805F9B34FB_POWER-8043"

    def test_resolves_settings_for_a_known_product(self):
        from sydpower.catalog import get_product_settings

        settings = get_product_settings(self.KEY)
        registers = {s["holding_index"] for s in settings}
        assert registers == {13, 15, 59, 60, 61, 62, 68}

    def test_unknown_product_has_no_settings(self):
        from sydpower.catalog import get_product_settings

        assert get_product_settings("00000000-0000-0000-0000-000000000000_NOPE") == []

    def test_encoded_options_stay_inside_the_write_allowlist(self):
        """
        Every option this device can offer must be an allowed write.

        Otherwise the integration would present controls whose values the safety
        guard rejects — and these are persisted settings registers.
        """
        from sydpower.catalog import get_product_settings
        from sydpower.constants import (
            SETTING_ENCODING_INDEX1,
            SETTING_ENCODING_X60,
            WRITABLE_HOLDING_REGISTERS,
            setting_encoding,
        )

        for setting in get_product_settings(self.KEY):
            register = setting["holding_index"]
            assert register in WRITABLE_HOLDING_REGISTERS, register
            low, high = WRITABLE_HOLDING_REGISTERS[register]
            encoding = setting_encoding(register)
            for index, option in enumerate(setting["data_list"]):
                if encoding == SETTING_ENCODING_INDEX1:
                    value = index + 1
                elif encoding == SETTING_ENCODING_X60:
                    value = option * 60
                else:
                    value = option
                assert low <= value <= high, (
                    f"register {register} option {option} encodes to {value}, "
                    f"outside {(low, high)}"
                )


class TestFaultDecoding:
    """
    Test decoding the device's fault bitfields.

    These live in the *input* bank. Their register numbers overlap the firmware
    versions at holding 47-50, which are a different address space — conflating
    the two would report a firmware version as a fault bitfield.
    """

    def test_catalog_defines_fault_groups(self):
        from sydpower.catalog import get_faults

        groups = get_faults()
        assert groups, "catalog has no fault groups"
        for group in groups:
            assert group["registers"], group
            assert group["bits"], group

    def test_single_register_supplies_the_low_bits(self):
        from sydpower.catalog import fault_value

        registers = [0] * 60
        registers[43] = 0b1010
        assert fault_value([43], registers) == 0b1010

    def test_two_registers_put_the_second_in_the_low_half(self):
        """
        Mirrors the app: byte_list[1] is bits 0-15, byte_list[0] is bits 16-31.

        So a 32-bit group's bit 17 is bit 1 of its *first* register.
        """
        from sydpower.catalog import fault_value

        registers = [0] * 60
        registers[50] = 0b10  # first register, bit 1 -> combined bit 17
        registers[51] = 0b01  # second register, bit 0 -> combined bit 0
        value = fault_value([50, 51], registers)
        assert value >> 17 & 1
        assert value & 1
        assert value == (0b10 << 16) | 0b01

    def test_out_of_range_registers_return_none(self):
        from sydpower.catalog import fault_value

        assert fault_value([99], [0] * 10) is None

    def test_healthy_device_reports_no_faults(self):
        """
        Values read from real hardware with nothing wrong.

        Registers 47 and 48 do have bits set — 0x3000 and 0x4000 — but those bits
        carry no fault message, and the app ignores unnamed bits.
        """
        from sydpower.catalog import active_faults

        registers = [0] * 80
        registers[47] = 0x3000
        registers[48] = 0x4000
        assert active_faults(registers) == []

    def test_a_named_bit_produces_its_message(self):
        from sydpower.catalog import active_faults, get_faults

        group = next(g for g in get_faults() if g["registers"] == [43])
        bit = min(int(b) for b in group["bits"])
        registers = [0] * 80
        registers[43] = 1 << bit
        assert active_faults(registers) == [group["bits"][str(bit)]]


class TestFirmwareGate:
    """
    Test hiding setting options that a device's firmware cannot honour.

    The gate table is only reachable with a signed-in user token, so these use
    synthetic rules; the matching logic mirrors the app's.
    """

    SETTING = {"holding_index": 60, "data_list": [0, 8, 16, 24]}

    def _with_rules(self, rules):
        """Install a gate table into the cached catalog for one test."""
        from sydpower import catalog

        catalog._load()  # ensure the cache is populated before mutating it
        catalog._cache = {**catalog._cache, "firmware_gates": {"ac_standby_time": rules}}
        return catalog

    def teardown_method(self):
        from sydpower import catalog

        catalog.invalidate_cache()

    def test_no_gate_table_leaves_options_untouched(self):
        from sydpower.catalog import gated_setting_options

        assert gated_setting_options(self.SETTING, "POWER-8043", 29) == [0, 8, 16, 24]

    def test_matching_rule_drops_the_never_option(self):
        catalog = self._with_rules(
            [{"product_name": "POWER-8043", "panel_version": "2.9"}]
        )
        # 29 is the raw register value; the app compares its low byte against
        # ten times the rule's version, so 2.9 matches 29.
        assert catalog.gated_setting_options(self.SETTING, "POWER-8043", 29) == [8, 16, 24]

    def test_other_product_is_unaffected(self):
        catalog = self._with_rules(
            [{"product_name": "POWER-OTHER", "panel_version": "2.9"}]
        )
        assert catalog.gated_setting_options(self.SETTING, "POWER-8043", 29) == [0, 8, 16, 24]

    def test_other_panel_version_is_unaffected(self):
        catalog = self._with_rules(
            [{"product_name": "POWER-8043", "panel_version": "3.1"}]
        )
        assert catalog.gated_setting_options(self.SETTING, "POWER-8043", 29) == [0, 8, 16, 24]

    def test_only_the_low_byte_is_compared(self):
        """The register's high byte is not part of the version."""
        catalog = self._with_rules(
            [{"product_name": "POWER-8043", "panel_version": "2.9"}]
        )
        # Low byte 29 (decimal, i.e. version 2.9) with an arbitrary high byte set.
        raw = (4 << 8) | 29
        assert catalog.gated_setting_options(self.SETTING, "POWER-8043", raw) == [8, 16, 24]

    def test_unknown_panel_version_leaves_options_untouched(self):
        catalog = self._with_rules(
            [{"product_name": "POWER-8043", "panel_version": "2.9"}]
        )
        assert catalog.gated_setting_options(self.SETTING, "POWER-8043", None) == [0, 8, 16, 24]

    def test_malformed_rule_is_skipped(self):
        catalog = self._with_rules(
            [{"product_name": "POWER-8043", "panel_version": "not-a-number"}]
        )
        assert catalog.gated_setting_options(self.SETTING, "POWER-8043", 29) == [0, 8, 16, 24]


class TestAdvertisementParsing:
    """
    Test recovery of the device MAC from the advertisement payload.

    These devices put their payload directly into the AD structure, so bleak
    parses its first two bytes as a manufacturer company ID and strips them into
    the dict key. Both bytes are payload, so they must be put back or every
    field shifts by one byte.
    """

    def _adv(self, **overrides):
        from bleak.backends.scanner import AdvertisementData

        kwargs = dict(
            local_name="POWER-8043",
            manufacturer_data={},
            service_data={},
            service_uuids=["00004380-0000-1000-8000-00805f9b34fb"],
            tx_power=None,
            rssi=-55,
            platform_data=(),
        )
        kwargs.update(overrides)
        return AdvertisementData(**kwargs)

    def test_mac_recovered_from_manufacturer_data(self):
        """
        Regression test using bytes captured from real hardware.

        On air: 99 50 78 7D BA A6 5A 00 — a 0x99 legacy prefix, the six MAC
        octets, then the init-status byte. bleak reports company id 0x5099 with
        remainder 787dbaa65a00. Home Assistant's Bluetooth stack independently
        reports this device as 50:78:7D:BA:A6:5A, which is the expected result;
        parsing the remainder alone yielded 78:7D:BA:A6:5A:00, shifted by one.
        """
        from sydpower.scanner import _parse_advertisement

        device = BLEDevice("50:78:7D:BA:A6:5A", "POWER-8043", None)
        adv = self._adv(manufacturer_data={0x5099: bytes.fromhex("787dbaa65a00")})

        parsed = _parse_advertisement(device, adv)

        assert parsed is not None
        assert parsed.advertis == "50:78:7D:BA:A6:5A"
        assert parsed.init_status == 0

    def test_non_sydpower_name_ignored(self):
        from sydpower.scanner import _parse_advertisement

        device = BLEDevice("AA:BB:CC:DD:EE:FF", "SomeOtherDevice", None)
        assert _parse_advertisement(device, self._adv(local_name="SomeOther")) is None


class TestResponseFunctionCodeMatching:
    """
    A response must match the function code that was requested.

    Holding (0x03) and input (0x04) reads produce identically shaped frames for
    the same register count, so accepting either one silently misinterprets
    every register in the bank.
    """

    def _frame(self, func_code: int, count: int = 2) -> bytes:
        """Build a valid register-read response with a correct CRC."""
        body = [17, func_code, 0x00, 0x00, count >> 8, count & 0xFF]
        body += [0x00, 0x01] * count
        crc = crc16_modbus(body)
        return bytes([*body, crc >> 8, crc & 0xFF])

    def test_matching_function_code_accepted(self):
        buf = ResponseBuffer(
            modbus_address=17, expected_func_code=0x03, protocol_version=0
        )
        assert buf.feed(self._frame(0x03)) is True

    def test_input_response_not_accepted_for_holding_request(self):
        """
        The desync that produced garbage register data on real hardware.

        The wrong bank must never be reported as complete; it is discarded and
        the buffer keeps waiting.
        """
        buf = ResponseBuffer(
            modbus_address=17, expected_func_code=0x03, protocol_version=0
        )
        assert buf.feed(self._frame(0x04)) is False

    def test_holding_response_not_accepted_for_input_request(self):
        buf = ResponseBuffer(
            modbus_address=17, expected_func_code=0x04, protocol_version=0
        )
        assert buf.feed(self._frame(0x03)) is False

    def test_resyncs_after_a_stale_write_echo(self):
        """
        A queued write echo can be delivered ahead of the reply we asked for.

        This is the exact sequence seen on hardware: a register-66 write echo
        arrived on the connection opened for the following read. The buffer must
        discard it and still accept the real response.
        """
        buf = ResponseBuffer(
            modbus_address=17, expected_func_code=0x03, protocol_version=0
        )
        stale_echo = bytes.fromhex("110600420064a52a")

        assert buf.feed(stale_echo) is False
        assert buf.feed(self._frame(0x03)) is True

        result = buf.result()
        assert isinstance(result, RegisterResponse)
        assert list(result.registers) == [1, 1]


class TestWriteSafety:
    """
    Test the known-safe holding-register guard.

    A write to an unverified register or an out-of-range value can put the
    device into an unrecoverable boot loop, so these must be rejected before
    any packet is built.
    """

    def _device(self, **kwargs) -> SydpowerDevice:
        return SydpowerDevice("AA:BB:CC:DD:EE:FF", **kwargs)

    def test_known_register_in_range_passes(self):
        """A verified register with an in-range value is accepted."""
        # Register 26 is AC output, allowed 0-1.
        self._device()._check_writes_safe(26, [1])

    def test_unknown_register_rejected(self):
        """A register outside the allowlist is rejected."""
        with pytest.raises(UnsafeRegisterWriteError, match="not a known-safe"):
            self._device()._check_writes_safe(42, [1])

    def test_value_above_range_rejected(self):
        """A value above the register's verified maximum is rejected."""
        # Register 27 is light mode, allowed 0-3.
        with pytest.raises(UnsafeRegisterWriteError, match="outside the verified range"):
            self._device()._check_writes_safe(27, [4])

    def test_value_below_range_rejected(self):
        """A value below the register's verified minimum is rejected."""
        # Register 67 is the charge upper limit, allowed 100-1000 permille.
        with pytest.raises(UnsafeRegisterWriteError, match="outside the verified range"):
            self._device()._check_writes_safe(67, [50])

    def test_range_bounds_are_inclusive(self):
        """Both ends of a verified range are accepted."""
        dev = self._device()
        low, high = WRITABLE_HOLDING_REGISTERS[67]
        dev._check_writes_safe(67, [low])
        dev._check_writes_safe(67, [high])

    def test_multi_register_span_checks_every_register(self):
        """
        A consecutive write is rejected if any register in the span is unsafe.

        The boundary is derived rather than hardcoded: this test previously used
        66/67 as writable and 68 as not, and silently stopped testing anything
        when 68 was added to the allowlist.
        """
        dev = self._device()
        start = next(
            r
            for r in sorted(WRITABLE_HOLDING_REGISTERS)
            if r + 1 not in WRITABLE_HOLDING_REGISTERS
        )
        low, _high = WRITABLE_HOLDING_REGISTERS[start]

        dev._check_writes_safe(start, [low])  # the writable register alone is fine
        with pytest.raises(UnsafeRegisterWriteError, match=f"Register {start + 1}"):
            dev._check_writes_safe(start, [low, 0])

    def test_multi_register_span_checks_each_value(self):
        """Each value is validated against its own register's range."""
        # 100 is valid for register 66 but below register 67's minimum of 100...
        # so use a value that is fine for 66 and invalid for 67.
        with pytest.raises(UnsafeRegisterWriteError, match="register 67"):
            self._device()._check_writes_safe(66, [0, 50])

    def test_empty_values_rejected(self):
        """An empty write is meaningless and rejected."""
        with pytest.raises(UnsafeRegisterWriteError, match="No values"):
            self._device()._check_writes_safe(26, [])

    def test_allow_unsafe_writes_bypasses_guard(self):
        """The opt-in escape hatch permits otherwise-rejected writes."""
        dev = self._device(allow_unsafe_writes=True)
        dev._check_writes_safe(42, [9999])

    def test_guard_defaults_to_enabled(self):
        """The guard must be on unless explicitly disabled."""
        assert self._device().allow_unsafe_writes is False


class TestClientInjection:
    """
    Test constructing a device from a BLEDevice and with an injected client.

    Home Assistant must be able to hand the library a connection established
    through whichever adapter or ESPHome Bluetooth proxy can reach the device,
    rather than having the library open a local one.
    """

    def test_accepts_ble_device_and_extracts_address(self):
        """A BLEDevice may be passed in place of an address string."""
        ble_device = BLEDevice("AA:BB:CC:DD:EE:FF", "POWER-TEST", None)
        dev = SydpowerDevice(ble_device)

        assert dev.address == "AA:BB:CC:DD:EE:FF"
        assert dev._ble_device is ble_device

    def test_accepts_address_string(self):
        """The plain address form still works and records no BLEDevice."""
        dev = SydpowerDevice("AA:BB:CC:DD:EE:FF")

        assert dev.address == "AA:BB:CC:DD:EE:FF"
        assert dev._ble_device is None

    @pytest.mark.asyncio
    async def test_connect_uses_injected_factory(self):
        """When a client factory is supplied, no local BleakClient is created."""
        client = AsyncMock()
        client.is_connected = True
        calls: list[str] = []

        async def factory():
            calls.append("factory")
            return client

        dev = SydpowerDevice("AA:BB:CC:DD:EE:FF", client_factory=factory)
        with patch("sydpower.device.BleakClient") as bleak_client:
            await dev.connect()

        assert calls == ["factory"]
        bleak_client.assert_not_called()
        client.start_notify.assert_awaited_once()
        assert dev.is_connected

    @pytest.mark.asyncio
    async def test_factory_failure_raises_connection_error(self):
        """A failing factory surfaces as a SydpowerConnectionError."""

        async def factory():
            raise OSError("proxy unreachable")

        dev = SydpowerDevice("AA:BB:CC:DD:EE:FF", client_factory=factory)
        with pytest.raises(SydpowerConnectionError, match="Injected client factory"):
            await dev.connect()


class TestModuleImports:
    """Test that all expected symbols are exported."""

    def test_sydpower_device_available(self):
        """Test SydpowerDevice is importable."""
        # This should not raise
        assert SydpowerDevice is not None

    def test_scan_available(self):
        """Test scan function is importable."""
        assert scan is not None
        assert callable(scan)

    def test_all_exceptions_available(self):
        """Test all exceptions are available."""
        assert SydpowerError is not None
        assert SydpowerConnectionError is not None
        assert CommandTimeoutError is not None
        assert DeviceNotFoundError is not None
        assert CRCError is not None
        assert ProtocolError is not None

    def test_protocol_primitives_available(self):
        """Test protocol primitives are available."""
        assert crc16_modbus is not None
        assert build_read_holding_registers is not None
        assert build_read_input_registers is not None
        assert build_write_registers is not None


@pytest.mark.asyncio
async def test_scan_function_signature():
    """Test that scan has the expected signature."""
    import inspect

    sig = inspect.signature(scan)

    # scan should accept a timeout parameter with default
    params = list(sig.parameters.keys())
    assert "timeout" in params


class TestFaultMessageOverrides:
    """
    Test the English wording applied to untranslated fault messages.

    The overrides are keyed by the backend's exact source string, so a catalog
    refresh that reworded something would silently stop matching. These tests
    fail in that case rather than quietly reverting to Chinese.
    """

    def test_every_override_still_matches_a_catalog_message(self):
        from sydpower.catalog import get_faults
        from sydpower.fault_messages import FAULT_MESSAGE_OVERRIDES

        present = {m for g in get_faults() for m in g["bits"].values()}
        stale = sorted(set(FAULT_MESSAGE_OVERRIDES) - present)
        assert not stale, f"overrides no longer in the catalog: {stale}"

    def test_no_catalog_message_is_left_untranslated(self):
        from sydpower.catalog import get_faults
        from sydpower.fault_messages import translate_fault

        untranslated = [
            translate_fault(m)
            for g in get_faults()
            for m in g["bits"].values()
            if any("一" <= c <= "鿿" for c in translate_fault(m))
        ]
        assert not untranslated, f"still Chinese after override: {untranslated}"

    def test_unknown_message_passes_through(self):
        from sydpower.fault_messages import translate_fault

        assert translate_fault("Temperature fault") == "Temperature fault"

    def test_active_faults_reports_english(self):
        from sydpower.catalog import active_faults, get_faults

        # Pick a group and bit whose source message is Chinese.
        group, bit = next(
            (g, b)
            for g in get_faults()
            for b in g["bits"]
            if any("一" <= c <= "鿿" for c in g["bits"][b])
        )
        registers = [0] * 80
        value = 1 << int(bit)
        if len(group["registers"]) == 1:
            registers[group["registers"][0]] = value
        else:
            registers[group["registers"][0]] = value >> 16
            registers[group["registers"][1]] = value & 0xFFFF

        reported = active_faults(registers)
        assert reported, "no fault reported for a set bit"
        assert not any("一" <= c <= "鿿" for c in reported[0]), reported
