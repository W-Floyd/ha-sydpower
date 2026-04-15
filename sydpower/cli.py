"""
Command-line interface for sydpower.

Provides a CLI for scanning Sydpower BLE devices from the terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .scanner import DiscoveredDevice, scan


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="sydpower",
        description="Scan for Sydpower / BrightEMS BLE devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sydpower                      # Scan with default 10 second timeout
  sydpower --timeout 15         # Scan for 15 seconds
  sydpower --json               # Output results as JSON
  sydpower --csv devices.csv    # Output results as CSV
        """,
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Scan timeout in seconds (default: 10.0)",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON (mutually exclusive with --csv)",
    )

    parser.add_argument(
        "--csv",
        metavar="FILE",
        default=None,
        help="Output results to a CSV file (mutually exclusive with --json)",
    )

    parser.add_argument(
        "--csv-header",
        action="store_true",
        default=False,
        help="Include CSV header row (default: False)",
    )

    return parser.parse_args()


def device_to_dict(device: DiscoveredDevice) -> dict[str, Any]:
    """Convert a DiscoveredDevice to a dictionary."""
    return {
        "name": device.name,
        "address": device.address,
        "service_uuid": device.service_uuid,
        "product_key": device.product_key,
        "advertis": device.advertis,
        "init_status": device.init_status,
        "serial_no": device.serial_no,
        "modbus_address": device.modbus_address,
        "modbus_count": device.modbus_count,
        "protocol_version": device.protocol_version,
    }


def output_json(devices: list[DiscoveredDevice]) -> None:
    """Output device list as JSON."""
    result = [device_to_dict(d) for d in devices]
    print(json.dumps(result, indent=2))


def output_csv(devices: list[DiscoveredDevice], header: bool) -> None:
    """Output device list as CSV."""
    fieldnames = [
        "name",
        "address",
        "service_uuid",
        "product_key",
        "advertis",
        "init_status",
        "serial_no",
        "modbus_address",
        "modbus_count",
        "protocol_version",
    ]

    if header:
        print(",".join(fieldnames))

    for device in devices:
        row = [str(device_to_dict(device)[f]) for f in fieldnames]
        print(",".join(row))


async def main_async() -> int:
    """Main async entry point."""
    args = parse_args()

    # Check for mutually exclusive options
    if args.json and args.csv:
        print(
            "Error: --json and --csv are mutually exclusive",
            file=sys.stderr,
        )
        return 1

    # Scan for devices
    print(f"Scanning for Sydpower devices for {args.timeout} seconds...")

    try:
        devices = await scan(timeout=args.timeout)
    except KeyboardInterrupt:
        print("\nScan cancelled by user")
        return 0

    # Output results
    if args.csv:
        output_csv(devices, header=args.csv_header)

        # Save to file if a filename was provided
        if args.csv:
            filename = args.csv
            with open(filename, "w", encoding="utf-8") as f:
                if args.csv_header:
                    fieldnames = [
                        "name",
                        "address",
                        "service_uuid",
                        "product_key",
                        "advertis",
                        "init_status",
                        "serial_no",
                        "modbus_address",
                        "modbus_count",
                        "protocol_version",
                    ]
                    f.write(",".join(fieldnames) + "\n")
                    for device in devices:
                        row = [str(device_to_dict(device)[f]) for f in fieldnames]
                        f.write(",".join(row) + "\n")
            print(f"Results saved to {filename}")
    elif args.json:
        output_json(devices)
    else:
        # Default: human-readable output
        if not devices:
            print("No Sydpower devices found")
        else:
            print(f"\nFound {len(devices)} device(s):")
            print("-" * 80)
            for device in devices:
                print(f"  Name:        {device.name}")
                print(f"  Address:     {device.address}")
                print(f"  Service UUID: {device.service_uuid}")
                print(f"  Device ID:   {device.advertis}")
                print(
                    f"  Protocol:    v{device.protocol_version} "
                    f"(modbus_addr={device.modbus_address}, "
                    f"modbus_count={device.modbus_count})"
                )
                if device.serial_no:
                    print(f"  Serial No:   {device.serial_no}")
                print()

    return 0 if devices else 0  # Always return 0, devices empty is not an error


def main() -> int:
    """CLI entry point."""
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
