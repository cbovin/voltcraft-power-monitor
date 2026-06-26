"""BLE discovery: find the SEM-3600BT by advertised service UUID or name."""
from __future__ import annotations

import logging

from bleak import BleakScanner

log = logging.getLogger(__name__)


async def discover(
    timeout: float,
    name_filters: list[str],
    service_uuid: str | None,
) -> list[dict]:
    """Scan and return matching devices, strongest signal first.

    Each match: ``{"address", "name", "rssi", "matched"}``. Matching is by the
    custom service UUID (preferred) or an advertised-name substring.
    """
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    su = (service_uuid or "").lower()
    matches: list[dict] = []

    for address, (device, adv) in found.items():
        name = device.name or adv.local_name or ""
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        by_service = bool(su) and su in uuids
        by_name = bool(name) and any(f.lower() in name.lower() for f in name_filters)
        if by_service or by_name:
            matches.append({
                "address": address,
                "name": name or "(unknown)",
                "rssi": adv.rssi,
                "matched": "service" if by_service else "name",
            })

    matches.sort(key=lambda d: d["rssi"] if d["rssi"] is not None else -999, reverse=True)
    log.info("discovery found %d matching device(s)", len(matches))
    return matches
