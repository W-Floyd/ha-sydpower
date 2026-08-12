# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-08-12

The catalog stops being a lookup table for a few constants and becomes the source
the entities are built from, so a product this was never tested against gets its
own controls rather than the test device's. Alongside that, several registers were
resolved against hardware — including the two AC voltages, which had been
indistinguishable while mains was connected and the output enabled.

**Entity unique IDs changed.** State entities are now keyed on the catalog's own
identifier instead of a hardcoded list, and the AC frequency sensor was renamed to
`ac_input_frequency`. Remove and re-add the device; the old entities are orphaned
and will show as unavailable until they are deleted.

### Added
- **Controls derived from the catalog** rather than hardcoded: switches, selects,
  binary sensors and the light's effect list. `holding_index` turned out to be a
  real register number, validated against hardware for all four controls and all
  seven settings of the test device.
- **The light is a light entity** with its modes — Always On, SOS Mode, Flash Mode
  — as effects, instead of a switch plus a separate mode select. Register 27 holds
  a mode, which is what Home Assistant's effect model describes.
- **Scheduled charging as a datetime entity.** The device stores a countdown in
  minutes, so the requested wall-clock time is remembered and reported verbatim,
  with the countdown used only to check it. The value therefore never drifts, and
  a schedule changed from the app still wins. Re-arming daily is left to an
  automation, the schedule being one-shot on the device.
- **Buttons** to cancel a scheduled charge and to shut the unit down remotely. The
  shutdown button ships disabled — Home Assistant has no confirmation step for a
  button press where the app puts a dialog in front of it.
- **Maximum charging current**, whose ceiling is read from holding 17 rather than
  fixed, bounded by the write allowlist as a backstop.
- **A problem sensor decoding device faults**, with English wording supplied for
  the 26 messages the backend ships untranslated.
- **Firmware version diagnostics** for the AC, BMS, PV and panel controllers, and
  setting options gated on panel firmware as the app gates them.
- **Model reporting** — the test unit identifies as `P210-A0E01`.
- `analysis/extract_catalog.py`, which regenerates the catalog from an XAPK,
  including the authenticated endpoints, and regenerates the manifest's 169
  Bluetooth matchers so they cannot drift from it.

### Fixed
- **The charge threshold accepts 10-100% again.** It had been narrowed to 60-100%
  to match the app's slider, which removed a setting that works: the hardware
  accepts and holds a ceiling of 100 permille, and a ceiling that low is how you
  hold charging off through a high-tariff period from an automation. The app's
  floor is a product decision rather than a device limit.
- **Two switches were wrongly removed** as unverified. Key sound (register 56) and
  AC silent charging (register 57) are both written by the app; the catalog simply
  does not describe them, which is not the same as the device not having them.
- **A multi-register write on protocol v0 raises** instead of silently writing only
  the first value.
- **Deploying a manifest whose pinned wheel is not yet downloadable is refused**,
  after a deploy raced CI by 17 seconds and left Home Assistant unable to resolve
  the requirement.

### Changed
- **State sensors are diagnostic only where a control already writes the same
  thing**, derived from the catalog rather than from a maintained register list.
- **Registers 18 and 21 are now distinguished**: 21 is the mains input, 18 the
  inverter output, and the output reading is suppressed while the output is off
  rather than recording the 70 V swing an unenergised output samples as.
- **Register 22 is AC *input* frequency**, confirmed by it reading 0.00 Hz while
  the inverter ran from the battery at 120.7 V.
- **Register 19 is not a frequency measurement.** It held 600 with no mains and
  again with the inverter stopped, where a live reading falls to zero.

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
