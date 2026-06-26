"""Runtime settings (populated from CLI / environment)."""
from __future__ import annotations

from dataclasses import dataclass, field

# Custom GATT service the device advertises — the most reliable way to find it.
SERVICE_UUID = "0000fee0-494c-4f47-4943-544543480000"

# Advertised names seen across firmware revisions.
DEFAULT_NAME_FILTERS = ["WiT Power Meter", "WiT", "SEM-3600", "Voltcraft"]

DEFAULT_PRICE = 0.25      # currency units per kWh
DEFAULT_CURRENCY = "€"


@dataclass
class Settings:
    # Connection target. None -> auto-discover by service UUID / name.
    address: str | None = None
    # MAC used to derive the login secret needed for relay control.
    # On Linux/Windows it equals `address`; on macOS `address` is an opaque
    # CoreBluetooth UUID, so the real MAC must be supplied to enable control.
    mac: str | None = None

    name_filters: list[str] = field(default_factory=lambda: list(DEFAULT_NAME_FILTERS))
    service_uuid: str = SERVICE_UUID

    db_path: str = "voltcraft.db"
    host: str = "127.0.0.1"
    port: int = 8000

    sample_interval: float = 5.0     # seconds between persisted DB rows
    scan_timeout: float = 8.0        # BLE scan duration
    connect_timeout: float = 20.0

    reconnect_min: float = 2.0       # backoff floor
    reconnect_max: float = 30.0      # backoff ceiling
    scan_retry_delay: float = 4.0    # wait between scans when device is absent

    scan_only: bool = False          # --scan: just list devices and exit
