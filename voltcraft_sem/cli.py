"""Command-line entry point."""
from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from . import __version__, discovery
from .config import DEFAULT_NAME_FILTERS, Settings


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="voltcraft-sem",
        description="Monitor and control a Voltcraft SEM-3600BT BLE power meter.",
    )
    p.add_argument("--scan", action="store_true",
                   help="scan for devices, print results and exit")
    p.add_argument("--address", default=None,
                   help="BLE address/UUID to use (default: auto-discover)")
    p.add_argument("--mac", default=None,
                   help="device MAC for the login secret (needed on macOS to control)")
    p.add_argument("--name-filter", action="append", dest="name_filters",
                   metavar="SUBSTR", help="advertised-name match (repeatable)")
    p.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    p.add_argument("--port", type=int, default=8000, help="HTTP port")
    p.add_argument("--db", default="voltcraft.db", help="SQLite file path")
    p.add_argument("--sample-interval", type=float, default=5.0,
                   help="seconds between persisted samples")
    p.add_argument("--scan-timeout", type=float, default=8.0, help="BLE scan duration")
    p.add_argument("--price", type=float, default=None,
                   help="electricity price per kWh (persisted)")
    p.add_argument("--currency", default=None, help="currency symbol (persisted)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _settings(a: argparse.Namespace) -> Settings:
    return Settings(
        address=a.address,
        mac=a.mac,
        name_filters=a.name_filters or list(DEFAULT_NAME_FILTERS),
        db_path=a.db,
        host=a.host,
        port=a.port,
        sample_interval=a.sample_interval,
        scan_timeout=a.scan_timeout,
        scan_only=a.scan,
    )


async def _scan(s: Settings):
    print(f"Scanning {s.scan_timeout:.0f}s ...")
    rows = await discovery.discover(s.scan_timeout, s.name_filters, s.service_uuid)
    if not rows:
        print("No matching device found. Is it powered and in range?")
        return
    for r in rows:
        print(f"  {r['rssi']:>4} dBm  {r['address']}  {r['name']}  (matched: {r['matched']})")
    print(f"\nBest match: {rows[0]['address']}")


def main(argv: list[str] | None = None):
    a = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    s = _settings(a)

    if a.scan:
        asyncio.run(_scan(s))
        return

    if a.price is not None or a.currency:
        from .db import Database
        Database(s.db_path).set_config(price_per_kwh=a.price, currency=a.currency)

    from .server import create_app
    app = create_app(s)
    print(f"\n  Voltcraft SEM-3600BT  ->  http://{s.host}:{s.port}\n")
    uvicorn.run(app, host=s.host, port=s.port, log_level="warning")


if __name__ == "__main__":
    main()
