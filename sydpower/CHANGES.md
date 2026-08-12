# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.5] - 2026-08-11

### Changed
- Version aligned with the Home Assistant integration so both ship under a
  single `v*` tag. There are no library changes since 0.3.4; the release exists
  to give the integration's requirement pin an asset on the same tag it is
  distributed from.

## [0.3.4] - 2026-08-11

### Fixed
- **Response desynchronisation went undetected.** `ResponseBuffer` declared
  `expected_func_code` but never compared it to the function code received.
  Holding (0x03) and input (0x04) reads produce identically shaped frames for a
  given register count, so an out-of-order reply was accepted as valid and every
  register in the bank was misinterpreted. Observed on real hardware:
  `read_holding_registers()` returned input-bank data for tens of seconds before
  resynchronising on its own. Now raises `ProtocolError` so `_send` retries.
- **Legacy writes silently dropped data.** With `protocol_version=0`,
  `build_write_registers` truncated to the first value, so a multi-register call
  wrote only one register while appearing to succeed. There is no v0 wire
  encoding for multi-register writes, so it now raises `ProtocolError`.

### Added
- Write safety guard. `WRITABLE_HOLDING_REGISTERS` maps each known-safe holding
  register to its verified value range; `write_register`/`write_registers` reject
  anything else with `UnsafeRegisterWriteError` before a packet is framed.
  Writing an unverified settings register can put the device into a boot loop
  that cannot be recovered over BLE. Override with `allow_unsafe_writes=True`.
- `SydpowerDevice` accepts a `BLEDevice` in place of an address string, and an
  optional `client_factory` supplying an already-connected client. This lets
  Home Assistant route connections through any adapter or ESPHome Bluetooth
  proxy while reusing the library's protocol handling and safety checks.
- `sydpower dump` CLI subcommand, with `--watch` to re-read on an interval and
  print only registers that changed — used for register mapping.

## [0.3.0] - 2024-XX-XX

### Added
- Initial public release of sydpower
- BLE scanner for discovering Sydpower/BrightEMS devices
- `SydpowerDevice` class for BLE communication with Modbus register access
- CLI tool (`sydpower`) for scanning devices from the command line
- Product catalog for device-specific Modbus parameters
- Comprehensive exception hierarchy (`SydpowerError`, `CommandTimeoutError`, `CRCError`, etc.)
- Documentation (README.md, DEVELOP.md)
- Test suite with pytest
- PyPI publishing configuration (pyproject.toml, setup.py)
- Makefile for development workflow

### Changed
- N/A (initial release)

### Fixed
- N/A (initial release)

### Security
- N/A (initial release)

## [0.2.0] - (Planned)
### Planned
- [ ] Add support for device firmware updates
- [ ] Add certificate-based authentication
- [ ] Implement device registration
- [ ] Add comprehensive integration tests

## [0.1.0] - (Planned - Initial Internal Version)
### Planned
- Initial internal development version
- Core BLE scanning functionality
- Basic register read/write operations
- Product catalog integration

---

## Unreleased

### Added
- Initial package structure
- All core modules (device, scanner, protocol, catalog)
- CLI entry point
- PyPI publishing setup
- Development workflow tools (Makefile, scripts/publish.sh)
