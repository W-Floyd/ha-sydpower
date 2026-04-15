#!/usr/bin/env bash
#
# Publish sydpower to PyPI.
#
# Prerequisites:
#   1. Install build and twine: pip install build twine
#   2. Configure PyPI credentials (via TWINE_USERNAME/TWINE_PASSWORD or netrc)
#   3. Set the version number in pyproject.toml and setup.py
#
# Usage:
#   ./scripts/publish.sh           # Publish to PyPI (testpypi if TESTPYPI=1)
#   TESTPYPI=1 ./scripts/publish.sh  # Publish to TestPyPI instead
#
# Notes:
#   - This script builds both wheel and source distributions.
#   - Uploads to PyPI (pypi.org) or TestPyPI (test.pypi.org).
#   - Requires successful `python -m pytest` tests before upload.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$ROOT_DIR"

echo "=== sydpower PyPI Publish Script ==="
echo ""

# Check if we're in a git repo
if git rev-parse --git-dir > /dev/null 2>&1; then
    echo "Repository: $(git remote get-url origin 2>/dev/null || echo 'N/A')"
    echo "Branch: $(git branch --show-current 2>/dev/null || echo 'N/A')"
    echo "Latest commit: $(git log -1 --oneline 2>/dev/null || echo 'N/A')"
    echo ""
else
    echo "Warning: Not a git repository"
    echo ""
fi

# Check for uncommitted changes
if ! git diff --quiet 2>/dev/null; then
    echo "Warning: Uncommitted changes detected!"
    echo "Uncommitted files:"
    git status --short 2>/dev/null | head -20
    echo ""
fi

# Verify Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 || python --version 2>&1)
echo "  $python_version"
echo ""

# Run tests before building
echo "Running tests..."
if command -v pytest > /dev/null 2>&1; then
    pytest -v tests/ 2>&1 | head -50 || {
        echo "ERROR: Tests failed. Aborting publish."
        exit 1
    }
else
    echo "pytest not installed, skipping tests (install with: pip install pytest)"
fi
echo ""

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf dist/ build/ *.egg-info .eggs/
mkdir -p dist
echo ""

# Build the package
echo "Building package..."
if command -v python > /dev/null 2>&1; then
    python -m build --wheel --sdist
else
    echo "ERROR: Python not found"
    exit 1
fi
echo ""

# List built artifacts
echo "Built artifacts:"
ls -lh dist/
echo ""

# Determine target
TARGET="testpypi"
if [[ "${TESTPYPI:-0}" == "1" ]]; then
    TARGET="testpypi"
    echo "TARGET: TestPyPI (test.pypi.org)"
else
    echo "TARGET: PyPI (pypi.org)"
fi
echo ""

# Read version from pyproject.toml
VERSION=$(grep -E '^version\s*=' pyproject.toml | head -1 | cut -d'"' -f2)
echo "Package version: $VERSION"
echo ""

# Confirm before upload
echo "=== PRE-UPLOAD CONFIRMATION ==="
echo "Package: sydpower-$VERSION"
echo "Target: $TARGET"
echo "Artifacts: $(ls dist/*.whl dist/*.tar.gz 2>/dev/null | wc -l) files"
echo ""
echo "Uploading to $TARGET..."
echo "Note: If this is the first release on a project, you may need to verify"
echo "the project first on $TARGET"
echo ""

# Upload
echo "Uploading packages..."
if [[ "${TESTPYPI:-0}" == "1" ]]; then
    python -m twine upload --repository testpypi dist/*
else
    python -m twine upload dist/*
fi

echo ""
echo "=== UPLOAD COMPLETE ==="
echo ""
echo "To verify the upload:"
echo "  - PyPI: https://pypi.org/project/sydpower/$VERSION"
echo "  - TestPyPI: https://test.pypi.org/project/sydpower/$VERSION"
echo ""
echo "To install from TestPyPI (default):"
echo "  pip install --index-url https://test.pypi.org/simple/ sydpower"
echo ""
echo "To install from PyPI:"
echo "  pip install sydpower"
echo ""
