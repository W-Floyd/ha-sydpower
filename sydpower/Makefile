# Sydpower Package Makefile
# Provides convenient shortcuts for development, testing, and publishing

.PHONY: all help test lint check install develop clean build docs help
.PHONY: publish publish-testpypi dev-requirements setup-env

PYTHON := python3
PIP := $(PYTHON) -m pip
BUILDPACK := $(PYTHON) -m build
TWINE := twine
PYTEST := $(PYTHON) -m pytest
BLACK := $(PYTHON) -m black
RUFF := $(PYTHON) -m ruff
MYPY := $(PYTHON) -m mypy

# Default target
all: help

help:
	@echo "Sydpower Package Makefile"
	@echo "========================"
	@echo ""
	@echo "Development:"
	@echo "  make develop    Install package in editable mode"
	@echo "  make install    Install package normally"
	@echo "  make test       Run test suite"
	@echo "  make lint       Run linters (black, ruff)"
	@echo "  make check      Run all checks (tests + linters)"
	@echo "  make build      Build distribution packages"
	@echo "  make clean      Clean build artifacts"
	@echo ""
	@echo "Publishing:"
	@echo "  make publish    Publish to PyPI (requires TWINE credentials)"
	@echo "  make publish-testpypi  Publish to TestPyPI"
	@echo ""
	@echo "Environment:"
	@echo "  make venv       Create virtual environment"
	@echo "  make activate   Activate virtual environment"
	@echo ""

# Virtual Environment
venv:
	@echo "Creating virtual environment..."
	$(PYTHON) -m venv .venv
	@echo "Virtual environment created at .venv/"
	@echo "Run 'make activate' to activate it."

activate:
	@echo "Activate the virtual environment manually:"
	@echo "  source .venv/bin/activate"

# Installation
develop:
	@echo "Installing sydpower in editable mode with dev dependencies..."
	$(PIP) install -e ".[dev]"
	@echo "Installation complete."

install:
	@echo "Installing sydpower..."
	$(PIP) install -e .
	@echo "Installation complete."

dev-requirements:
	@echo "Installing development requirements..."
	$(PIP) install pytest pytest-asyncio pytest-cov mypy black ruff twine build
	@echo "Development requirements installed."

# Testing
test:
	@echo "Running test suite..."
	$(PYTEST) -v tests/
	@echo "Tests complete."

test-cov:
	@echo "Running tests with coverage..."
	$(PYTEST) -v --cov=sydpower --cov-report=term --cov-report=html tests/
	@echo "Coverage report generated in htmlcov/"

# Linting and Quality
lint:
	@echo "Running black..."
	$(BLACK) --check sydpower/ tests/
	@echo "Running ruff..."
	$(RUFF) check sydpower/ tests/
	@echo "Linting complete."

fix:
	@echo "Running black..."
	$(BLACK) sydpower/ tests/
	@echo "Running ruff..."
	$(RUFF) check --fix sydpower/ tests/
	@echo "Auto-fix complete."

check: test lint
	@echo "All checks passed!"

type-check:
	@echo "Running mypy type check..."
	$(MYPY) sydpower/
	@echo "Type check complete."

# Building
build:
	@echo "Building distribution packages..."
	$(BUILDPACK)
	@echo "Build complete."
	@echo ""
	@echo "Distribution packages created:"
	@ls -lh dist/

clean:
	@echo "Cleaning build artifacts..."
	rm -rf dist/ build/ *.egg-info/ .eggs/ .pytest_cache/ .mypy_cache/ .ruff_cache/
	rm -rf htmlcov/ coverage.xml
	@echo "Cleanup complete."

# Publishing
publish: build
	@echo ""
	@echo "=== PyPI Upload ==="
	@echo "IMPORTANT: Configure credentials before running!"
	@echo "Option 1 (env vars):"
	@echo "  export TWINE_USERNAME=__token__"
	@echo "  export TWINE_PASSWORD=pypi-yourtoken"
	@echo ""
	@echo "Option 2 (netrc file):"
	@echo "  cat ~/.netrc"
	@echo ""
	@echo "Uploading to PyPI..."
	$(TWINE) upload dist/*
	@echo ""
	@echo "Upload complete!"
	@echo "View your package at: https://pypi.org/project/sydpower/"

publish-testpypi: build
	@echo ""
	@echo "=== TestPyPI Upload ==="
	@echo "Uploading to TestPyPI..."
	$(TWINE) upload --repository testpypi dist/*
	@echo ""
	@echo "Upload to TestPyPI complete!"
	@echo "View at: https://test.pypi.org/project/sydpower/"

# Documentation
docs:
	@echo "Generating documentation..."
	@echo "See README.md for package documentation"
	@echo "See DEVELOP.md for development guide"

# Development workflow
dev-check: check build
	@echo ""
	@echo "=== Pre-Submit Checklist ==="
	@echo "Package built successfully!"
	@echo "All tests passed!"
	@echo "All lints passed!"
	@echo ""
	@echo "Ready to commit and push!"
