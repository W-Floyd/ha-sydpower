"""
Setup script for sydpower.

This file is provided for backward compatibility with tools that still expect
a setup.py. The build system is configured via pyproject.toml.
"""

from __future__ import annotations

from setuptools import setup

__version__ = "0.3.3"

setup(
    name="sydpower",
    version=__version__,
    description="Python library for Sydpower / BrightEMS BLE inverter devices",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/your-username/sydpower",
    author="Your Name",
    author_email="your.email@example.com",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Hardware :: Hardware Drivers",
    ],
    python_requires=">=3.9",
    packages=["sydpower"],
    package_dir={"sydpower": "."},
    package_data={"sydpower": ["*.json"]},
    install_requires=[
        "bleak>=1.0.0",
    ],
    extras_require={
        "dev": [
            "build>=1.0.0",
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "twine>=4.0.0",
            "black>=23.0.0",
            "mypy>=1.0.0",
            "ruff>=0.1.0",
        ],
    },
    keywords="sydpower brightems ble bluetooth inverter modbus homeassistant",
    project_urls={
        "Bug Reports": "https://github.com/your-username/sydpower/issues",
        "Source": "https://github.com/your-username/sydpower",
    },
)
