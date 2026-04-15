# Development Guide for sydpower

This guide covers setting up your development environment and publishing the `sydpower` package to PyPI.

## Prerequisites

- Python 3.9 or higher
- pip and virtualenv
- Git (for version control)

## Setting Up the Development Environment

### 1. Clone and Install in Development Mode

```bash
# Navigate to the sydpower directory
cd /Users/william/Documents/Personal/git/ESP-FBot/sydpower

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the package in editable mode with development dependencies
pip install -e ".[dev]"
```

### 2. Verify Installation

```bash
# Check the installed version
pip show sydpower

# Test the CLI
sydpower --help

# Run the test suite
pytest -v
```

## Building the Package

### Build Wheel and Source Distributions

```bash
pip install build
python -m build
```

This creates:
- `dist/sydpower-<version>.whl` - Wheel distribution
- `dist/sydpower-<version>.tar.gz` - Source distribution

### Install the Built Package Locally

```bash
# Install the wheel
pip install dist/sydpower-<version>.whl

# Or install from source
pip install dist/sydpower-<version>.tar.gz
```

## Publishing to PyPI

### Prerequisites

1. **PyPI Account**: Create an account at https://pypi.org/account/register/
2. **Twine**: Install twine for secure uploads
   ```bash
   pip install twine
   ```
3. **API Token** (recommended): Create a token at https://pypi.org/manage/account/token/
   - Don't use your PyPI password (deprecated)
   - Save the token securely

### Configure PyPI Credentials

Option 1: Use environment variables
```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-<your-token>
```

Option 2: Use `.netrc` file (recommended)
```bash
echo "
machine pypi.org
  login __token__
  password pypi-<your-token>
" > ~/.netrc
chmod 600 ~/.netrc
```

### Upload to PyPI

#### Using the Publish Script

```bash
# Upload to PyPI (standard)
./scripts/publish.sh

# Upload to TestPyPI for testing
TESTPYPI=1 ./scripts/publish.sh
```

#### Manual Upload

```bash
# Build the package
python -m build

# Upload to PyPI
twine upload dist/*

# For TestPyPI (testing)
twine upload --repository testpypi dist/*
```

### Verify Upload

Visit https://test.pypi.org/project/sydpower/ to verify the package is live.

## Publishing Steps Checklist for TestPyPI

- [ ] Update version number in `pyproject.toml` and `setup.py`
- [ ] Run tests: `pytest -v`
- [ ] Run linters: `black .`, `ruff check .`, `mypy .`
- [ ] Build packages: `python -m build`
- [ ] Install locally: `pip install dist/*.whl`
- [ ] Test CLI: `sydpower --help`
- [ ] Upload to TestPyPI: `TESTPYPI=1 twine upload dist/*`

## Release Notes Template (for TestPyPI)

```
Version X.Y.Z - YYYY-MM-DD
===========================

## Changed
- ...

## Fixed
- ...

## Added
- ...

## Removed
- ...
```

## Code Quality Tools

### Black (Code Formatting)

```bash
black .           # Format all files
black --check .   # Check formatting without changing
```

### Ruff (Linting)

```bash
ruff check .      # Run all checks
ruff check --fix . # Auto-fix issues
```

### MyPy (Type Checking)

```bash
mypy sydpower/    # Type check the package
mypy --help       # Show options
```

## Troubleshooting

### Wheel Build Errors

```bash
# Ensure setuptools is up to date
pip install --upgrade setuptools wheel

# Clean and rebuild
rm -rf dist/ build/ *.egg-info/
python -m build
```

### Twine Upload Errors

```bash
# Check your .netrc file
cat ~/.netrc

# Verify package metadata
twine check dist/*

# Rebuild and re-upload
python -m build
twine upload dist/*
```

## Package Metadata

| Field | Value |
|-------|-------|
| Name | sydpower |
| Version | 0.3.0 |
| Description | Python library for Sydpower / BrightEMS BLE inverter devices |
| Python | >=3.9 |
| License | MIT |
| Keywords | sydpower, brightems, ble, bluetooth, inverter, modbus |

## Support

For issues and feature requests, see the project repository:
https://github.com/ESP-FBot/ESP-FBot/tree/main/sydpower