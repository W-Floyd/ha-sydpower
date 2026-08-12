# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.2] - 2026-08-12

### Fixed
- **A calibration sample now re-polls the device on submit.** The readings shown on
  the form come from the last scheduled poll and can be a whole interval old — 30
  seconds by default — while the meter figures being typed in were read moments ago.
  Pairing those was the largest remaining source of error in a sample. Submitting
  now takes a fresh reading, about a second, and records that instead, so the form
  no longer needs to be opened promptly after reading the meters.

  The charging check moved to the fresh reading too, so charging stopping while the
  form was open is caught rather than stored. A failed poll falls back to the last
  successful reading rather than discarding what was typed, and a reading that moves
  between drawing the form and submitting it is logged, that being exactly what
  shows up as a large residual later.

## [0.5.1] - 2026-08-12

Completes the calibration flow 0.5.0 introduced, which had a design flaw serious
enough that it should not be used: samples could be contaminated by the correction
they were meant to replace.

### Fixed
- **A calibration sample can no longer be corrupted by the existing correction.**
  0.5.0 asked for the device's own readings alongside the true ones — but once a
  correction is active, the sensors *are* corrected, so a sample transcribed from
  them measured the leftover error and stacked it onto the correction already in
  force. Each sample was therefore affected by every sample before it.

  The form now asks only for the external meter readings and takes the device's
  figures straight from the raw registers, so samples are independent of the fit
  they feed. Demonstrated with the real measurement: a sample copied from a
  corrected sensor produced a +66 W correction and a 424 W reading against a true
  490 W — worse than no correction at all — where reading the register gives +132 W
  and 490 W.

### Added
- **Samples can be reviewed and removed individually.** The options flow lists each
  one with its raw and true values, its error, and its residual against the current
  fit, so a sample taken while the load moved stands out and can be dropped without
  clearing the whole set. Previously the only options were adding and clearing all.
- **The uncorrected figure is exposed as an attribute** on the two corrected
  sensors, `reported_by_device` alongside `correction_applied`, so what the device
  actually said stays visible and the correction can be checked rather than taken on
  trust.
- **A sample is refused unless the device is charging**, that being the only state
  in which the error appears. One taken in pass-through would anchor the fit at zero
  and flatten it.

## [0.5.0] - 2026-08-12

An options flow, and with it calibration for a device defect found by measuring
against external instruments.

### Added
- **An options flow**, reachable from the integration entry's Configure button.
- **Configurable poll interval**, 5 to 3600 seconds, defaulting to the previous
  fixed 30. A poll costs 1.0-1.5 s, most of it spent opening the Bluetooth
  connection, and the retry path runs longer, so intervals near the floor risk
  overlapping refreshes.
- **Power calibration fitted from measurements.** The device under-reports its AC
  output while charging, and its total input with it, by ~130 W on the unit tested
  — confirmed against a plug meter and a UPS's own reporting, with charging stopped
  mid-measurement and nothing else altered.

  Rather than ask for a correction factor, the options collect *observations* —
  what an external meter says against what the device says — and fit
  `error = offset + slope x charge power` to them. This matters because one charge
  rate cannot tell a flat error from a proportional one: at 249 W of charging, a
  flat 130 W and 0.53 x charge power are indistinguishable. Samples at two or more
  different charge rates separate them by least squares, and the fit reports both
  whether the slope was actually measured and its worst residual, so a model that
  does not describe the device shows itself instead of being trusted.

  Nothing is corrected until samples are recorded, and no correction ever applies
  while the device is not charging — in pass-through its output figure matched the
  external instruments to within 1.5%, so correcting there would introduce an error
  rather than remove one.

### Changed
- **Register 39 (output power) and register 6 (total input) are documented as
  unreliable while charging**, with the measurements in
  `docs/register-map-v0.md`. Register 3 (charge power) is accurate — 249 W against
  254 W derived independently as wall-meter-minus-load.
- **Register 6 is derived by the device, not measured.** It equals `39 + 3` in every
  sample, including `497 = 497 + 0` in pass-through where a real input measurement
  must exceed output by the conversion losses. It therefore carries no information
  of its own and inherits register 39's error. An earlier note read this identity as
  evidence the device's accounting could be trusted; it only shows the device does
  one subtraction consistently.
- **Register 4 is confirmed as DC/solar input**, having read 0 in every earlier
  sample for want of anything connected. With the mains disconnected it reported
  162 W then 151 W and register 6 equalled it exactly.
- **Register 22 is AC input frequency, and register 19 is not a frequency
  measurement** — the latter held 600 with no mains and again with the inverter
  stopped, where a live reading falls to zero. No settable 50/60 Hz mode is
  reachable: the app has no `Hz` string and no frequency setting for any of its 169
  products, and no holding register holds 50, 60 or 600.
- The note claiming the device's figures run *higher* than an external meter,
  inherited from upstream rather than measured, is corrected. Locally they run
  lower, and the display is not independent corroboration since it reads the same
  registers.

## [0.4.1] - 2026-08-12

Follow-ups from running 0.4.0 on hardware.

### Fixed
- **The catalog is no longer read from inside the event loop.** Every platform
  derives its entities from the catalog during setup, and the file is loaded lazily
  on the first lookup, so whichever platform ran first read it from the event loop
  — which Home Assistant detects and warns about twice per startup. It is now
  warmed once from an executor thread before any platform is forwarded, and in the
  config flow before a discovered device is resolved, leaving every accessor a pure
  cache read.
- **No more "AC output AC".** The AC output's sole port is called "AC" in the
  catalog and the DC output's is called "DC", so qualifying each port with its
  parent produced "AC output AC" and "DC output DC". A port contributing no word
  its parent lacks is that output's only port and says nothing the parent does not,
  so it is now dropped rather than named — leaving one "AC output" and one "DC
  output". Ports that do contribute something are untouched: "DC output XT60",
  "DC output Car charging", "USB output PD 100W".

  This drops two state-word bits from the entity list, 18 and 15, whose parents are
  bits 27 and 26. Bit 18 tracked bit 27 exactly across every frame captured while
  the mains and the AC output were switched independently, so nothing observable is
  lost; if they are ever seen to diverge, the port deserves a name of its own
  rather than its parent's.

### Note
Six entities from before 0.4.0 linger in the registry as unavailable, their unique
IDs having changed: `binary_sensor.*_{ac,dc,usb}_output`, `binary_sensor.*_light`,
`sensor.*_ac_frequency` and `sensor.*_ac_voltage`. Delete them; nothing recreates
them. The controls that appear to have gone missing — AC charging power, key sound,
the standby times — have only moved to the device page's Configuration section,
being `EntityCategory.CONFIG`.

## [0.4.0] - 2026-08-12

The catalog stops being a lookup table for a few constants and becomes the source
the entities are built from, so a product this was never tested against gets its
own controls rather than the test device's. Alongside that, several registers were
resolved against hardware — including the two AC voltages, which had been
indistinguishable while mains was connected and the output enabled.

The other theme is a correction. Several bounds in this integration had been taken
from the app's sliders and option lists, on the reasoning that the app would not
offer a setting the device could not take. The converse does not follow, and
treating it as though it did cost a charge ceiling that was in real use. Ranges are
now justified by what the hardware accepts, and where a bound is only the app's it
says so.

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
  accepts and holds a ceiling of 100 permille, and a ceiling that low is how
  charging is held off through a high-tariff period from an automation. The app's
  floor is a product decision rather than a device limit. The bound is now asserted
  in a test so it cannot be narrowed again without the reason being stated, and the
  entity's minimum drops to 10% to match.

  Register 66, the discharge floor, takes its 0-50% range from the same slider and
  may well go higher on the hardware. It is left alone for now — it is one of the
  persisted registers implicated in the boot loop, so widening it wants a
  deliberate test rather than an assumption in the other direction.
- **Two switches were wrongly removed** as unverified. Key sound (register 56) and
  AC silent charging (register 57) are both written by the app; the catalog simply
  does not describe them, which is not the same as the device not having them.
- **A multi-register write on protocol v0 raises** instead of silently writing only
  the first value.
- **Deploying a manifest whose pinned wheel is not yet downloadable is refused**,
  after a deploy raced CI by 17 seconds and left Home Assistant unable to resolve
  the requirement.

### Changed
- **`input_index` is a state-word bit, retracting what 0.3.7 said about it.** That
  release described it as "a sub-index within its parent, not a register number"
  and dropped the catalog section carrying it. Half of that was right: read as
  input-register numbers these values do produce wildly wrong readings, which is
  what prompted the claim. But they are bit positions in the combined 32-bit state
  word — input register 42 as the low half, 41 as the high — and read that way all
  17 states of the test device validate. This is what makes deriving binary sensors
  and ports from the catalog possible at all.
- **State sensors are diagnostic only where a control already writes the same
  thing**, derived from the catalog rather than from a maintained register list.
- **Registers 18 and 21 are now distinguished**: 21 is the mains input, 18 the
  inverter output, and the output reading is suppressed while the output is off
  rather than recording the 70 V swing an unenergised output samples as.
- **Register 22 is AC *input* frequency**, confirmed by it reading 0.00 Hz while
  the inverter ran from the battery at 120.7 V, and renamed accordingly. It is
  deliberately left ungated: 0 Hz beside register 21's 0 V reports "no mains"
  accurately, unlike the floating output voltage that gating exists to hide.
- **Register 19 is not a frequency measurement**, and gets no entity. It held
  exactly 600 with no mains and again with the inverter stopped, where a live
  reading falls to zero as register 22 does. A nominal 60.0 Hz is the best reading
  of the value, and `holding[18]` carrying 115 makes a 115 V/60 Hz nominal pair,
  but nothing makes it *settable*: the app contains no `Hz` string and no frequency
  setting for any of its 169 products, and no holding register holds 50, 60 or 600.
  A 50/60 Hz mode, if one exists, is not reachable from anything documented.

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
