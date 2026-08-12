"""
Command-line interface for sydpower.

Provides a CLI for scanning Sydpower BLE devices from the terminal, and for
dumping or watching their Modbus register banks.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from typing import Any

from .device import SydpowerDevice
from .exceptions import SydpowerError
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

  sydpower dump                 # Read both register banks once and print them
  sydpower dump --bank input    # Read only the input bank
  sydpower dump --watch         # Re-read on an interval, printing only changes
  sydpower dump --watch --interval 1 --address AA:BB:CC:DD:EE:FF
  sydpower dump --scan-timeout 15

Register mapping workflow:
  Run `sydpower dump --watch`, then press a button on the device.  Only the
  registers that actually changed are printed, which identifies them without
  guesswork.
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

    # Subcommands are optional; with none given the CLI scans, as it always has.
    subparsers = parser.add_subparsers(dest="command")

    dump = subparsers.add_parser(
        "dump",
        help="Read a device's Modbus register banks",
        description=(
            "Connect to a device and print its register banks. With --watch, "
            "re-read on an interval and print only registers that changed."
        ),
    )
    dump.add_argument(
        "--address",
        default=None,
        help="BLE address to connect to (default: first device found by a scan)",
    )
    # Named distinctly from the top-level --timeout: argparse would otherwise
    # have the subparser's default silently override it.
    dump.add_argument(
        "--scan-timeout",
        type=float,
        default=10.0,
        help="Seconds to scan while locating the device (default: 10.0)",
    )
    dump.add_argument(
        "--bank",
        choices=("both", "holding", "input"),
        default="both",
        help="Which register bank(s) to read (default: both)",
    )
    dump.add_argument(
        "--watch",
        action="store_true",
        default=False,
        help="Keep the connection open and re-read on an interval",
    )
    dump.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between reads in --watch mode (default: 2.0)",
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


# ── dump / watch ──────────────────────────────────────────────────────────────

_BANKS = ("holding", "input")


def print_bank(label: str, registers: list[int]) -> None:
    """Print a full register bank, 8 values per line, with index markers."""
    print(f"\n{label} — {len(registers)} registers")
    for i in range(0, len(registers), 8):
        chunk = registers[i : i + 8]
        print(f"  [{i:3d}] " + " ".join(f"{v:5d}" for v in chunk))


def print_changes(label: str, before: list[int], after: list[int]) -> bool:
    """
    Print only the registers whose value changed.

    Returns ``True`` if anything changed.  A changed length is reported too,
    since a differing register count means the device is not what we assumed.
    """
    if len(before) != len(after):
        print(f"  {label}: register count changed {len(before)} -> {len(after)}")
        return True

    changed = [(i, b, a) for i, (b, a) in enumerate(zip(before, after)) if b != a]
    for i, b, a in changed:
        print(
            f"  {label}[{i:3d}] {b:5d} -> {a:5d}"
            f"   (0x{b:04X} -> 0x{a:04X}, delta {a - b:+d})"
        )
    return bool(changed)


async def read_banks(device: SydpowerDevice, bank: str) -> dict[str, list[int]]:
    """Read the requested bank(s) from a connected device."""
    result: dict[str, list[int]] = {}
    if bank in ("both", "holding"):
        result["holding"] = await device.read_holding_registers()
    if bank in ("both", "input"):
        result["input"] = await device.read_input_registers()
    return result


async def resolve_device(address: str | None, timeout: float) -> SydpowerDevice | None:
    """
    Build a ``SydpowerDevice`` for *address*, or for the first device found.

    Scanning first is preferred even when an address is supplied, because the
    scan resolves the device's Modbus parameters from the product catalog.
    """
    devices = await scan(timeout=timeout)
    if not devices:
        print("No Sydpower devices found", file=sys.stderr)
        return None

    if address is None:
        discovered = devices[0]
    else:
        matches = [d for d in devices if d.address.upper() == address.upper()]
        if not matches:
            print(
                f"Device {address} not found in scan results "
                f"(saw: {', '.join(d.address for d in devices)})",
                file=sys.stderr,
            )
            return None
        discovered = matches[0]

    print(f"Using {discovered.name} @ {discovered.address}")
    print(
        f"  protocol_version={discovered.protocol_version} "
        f"modbus_address={discovered.modbus_address} "
        f"modbus_count={discovered.modbus_count}"
    )
    return SydpowerDevice.from_discovered(discovered)


async def run_dump(args: argparse.Namespace) -> int:
    """Read register banks once, or repeatedly with --watch."""
    device = await resolve_device(args.address, args.scan_timeout)
    if device is None:
        return 1

    try:
        # A single connection is held for the whole session: reconnecting per
        # read is slow and loses changes that happen in between.
        async with device:
            snapshot = await read_banks(device, args.bank)
            for bank in _BANKS:
                if bank in snapshot:
                    print_bank(f"{bank.upper()} ({'0x03' if bank == 'holding' else '0x04'})",
                               snapshot[bank])

            if not args.watch:
                return 0

            print(
                f"\nWatching every {args.interval}s — press a button on the "
                f"device to identify its register. Ctrl-C to stop.\n"
            )
            while True:
                await asyncio.sleep(args.interval)
                current = await read_banks(device, args.bank)
                any_change = False
                for bank in _BANKS:
                    if bank in current:
                        any_change |= print_changes(
                            bank, snapshot[bank], current[bank]
                        )
                if any_change:
                    print("  --")
                snapshot = current

    except SydpowerError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    return 0


# ── scan ──────────────────────────────────────────────────────────────────────


async def main_async() -> int:
    """Main async entry point."""
    args = parse_args()

    if args.command == "dump":
        return await run_dump(args)

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
    with contextlib.suppress(KeyboardInterrupt):
        return asyncio.run(main_async())
    print("\nStopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
