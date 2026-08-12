# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.7] - 2026-08-12

First release verified end to end against real hardware in Home Assistant: a
FOSSiBOT/SYDPOWER `POWER-8043` (protocol v0, Modbus address 17, 80 registers)
reached over an ESPHome Bluetooth proxy. Seven of the nine writable registers
were commanded and read back, including all four persisted settings registers.

### Fixed
- **A stale frame no longer fails an exchange.** The device can deliver a queued
  write echo on the *next* connection, ahead of the reply being awaited; that
  aborted the following poll. Such a frame is now discarded and the buffer keeps
  waiting. It is still never interpreted as register data, and the caller's
  timeout continues to bound the wait.
- **Advertisement parsing was off by one byte.** These devices put their payload
  straight into the AD structure, so bleak reads its first two bytes as a
  manufacturer company ID and strips them into the dict key — but both are
  payload. On air the device sends `99 50 78 7D BA A6 5A 00`; parsing only
  bleak's remainder yielded `78:7D:BA:A6:5A:00` instead of `50:78:7D:BA:A6:5A`,
  the address Home Assistant's own Bluetooth stack reports. The company ID is now
  reassembled before parsing.

### Changed
- **The product catalog ships only `products` and `categories`.** Its 438 KB
  `features` section is dropped: nothing reads it, and its contents mislead — a
  child entry's `input_index` is a sub-index within its parent, not a register
  number. The unabridged file is kept in the repository at
  `reference/product_catalog.full.json`, outside the package. This takes the
  wheel from roughly 45 KB to 30 KB; device parameter lookup is unaffected.

## [0.3.6] - 2026-08-11

### Changed
- Version bump only, to carry Home Assistant integration fixes (DeviceInfo
  import location and the DataUpdateCoordinator config_entry requirement) under
  the shared `v*` tag. No library code changes since 0.3.5.

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
