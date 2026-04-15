# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
