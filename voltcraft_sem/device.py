"""Async BLE manager: auto-discovery, login, persistent connection, reconnect."""
from __future__ import annotations

import asyncio
import logging
import re
import time

from bleak import BleakClient
from bleak.exc import BleakError

from . import discovery, protocol
from .config import Settings
from .db import Database

log = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


class DeviceManager:
    """Owns the BLE lifecycle and exposes a thread-safe snapshot via ``status()``."""

    def __init__(self, settings: Settings, db: Database):
        self.s = settings
        self.db = db
        self.client: BleakClient | None = None

        self.state = "starting"          # starting|scanning|connecting|connected|reconnecting|stopped
        self.connected = False
        self.logged_in = False           # relay control requires a successful login
        self.latest: dict | None = None
        self.last_error: str | None = None
        self.device = {"address": settings.address, "name": None, "rssi": None}

        self._lock = asyncio.Lock()      # serialize command writes
        self._stop = False
        self._rescan = False
        self._last_db = 0.0

    # ---- public API -----------------------------------------------------
    def status(self) -> dict:
        return {
            "state": self.state,
            "connected": self.connected,
            "can_control": self.connected and self.logged_in,
            "device": dict(self.device),
            "latest": self.latest,
            "error": self.last_error,
        }

    async def switch(self, on: bool):
        if not self.connected or not self.client:
            raise RuntimeError("device not connected")
        if not self.logged_in:
            raise RuntimeError(
                "control unavailable: device MAC unknown — pass --mac to enable it"
            )
        async with self._lock:
            await self.client.write_gatt_char(
                protocol.UUID_CMD, protocol.switch_payload(on), response=True
            )
        if self.latest:                  # optimistic update; next frame confirms
            self.latest = {**self.latest, "state": 1 if on else 0,
                           "state_label": "on" if on else "off"}
        self.db.insert_event("on" if on else "off")
        log.info("relay -> %s", "ON" if on else "OFF")

    def request_rescan(self):
        self._rescan = True

    def stop(self):
        self._stop = True

    # ---- background loop ------------------------------------------------
    async def run(self):
        backoff = self.s.reconnect_min
        while not self._stop:
            try:
                if not self.device["address"] or self._rescan:
                    await self._discover()
                if not self.device["address"]:
                    self.state = "scanning"
                    await asyncio.sleep(self.s.scan_retry_delay)
                    continue
                await self._session()
                backoff = self.s.reconnect_min
            except BleakError as e:
                self.last_error = f"{type(e).__name__}: {e}"
                self.state = "reconnecting"
                log.warning("BLE error: %s", self.last_error)
                if "not found" in str(e).lower():
                    self.device["address"] = None   # force a fresh scan
            except Exception as e:                  # noqa: BLE001 - keep loop alive
                self.last_error = f"{type(e).__name__}: {e}"
                self.state = "reconnecting"
                log.warning("session error: %s", self.last_error)
            finally:
                self.connected = False
                self.logged_in = False
                self.client = None
            if self._stop:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, self.s.reconnect_max)
        self.state = "stopped"

    async def _discover(self):
        self._rescan = False
        self.state = "scanning"
        log.info("scanning for device ...")
        matches = await discovery.discover(
            self.s.scan_timeout, self.s.name_filters, self.s.service_uuid
        )
        if matches:
            best = matches[0]
            self.device = {"address": best["address"], "name": best["name"], "rssi": best["rssi"]}
            log.info("selected %s (%s, %s dBm)", best["address"], best["name"], best["rssi"])
        else:
            self.device = {"address": None, "name": None, "rssi": None}
            self.last_error = "no matching device found"

    def _secret_mac(self) -> str | None:
        if self.s.mac:
            return self.s.mac
        addr = self.device["address"] or ""
        return addr if _MAC_RE.match(addr) else None   # None on macOS UUIDs

    async def _session(self):
        addr = self.device["address"]
        self.state = "connecting"
        log.info("connecting to %s ...", addr)
        async with BleakClient(addr, timeout=self.s.connect_timeout) as client:
            self.client = client
            self.connected = True
            self.last_error = None
            self.db.insert_event("connect")
            await client.start_notify(protocol.UUID_MEAS, self._on_measurement)
            await client.start_notify(protocol.UUID_CMD, self._on_command)

            mac = self._secret_mac()
            if mac:
                async with self._lock:
                    await client.write_gatt_char(
                        protocol.UUID_CMD, protocol.sync_payload(mac), response=True
                    )
                self.logged_in = True
                log.info("logged in; control enabled")
            else:
                self.logged_in = False
                log.warning("no MAC for login secret; monitor-only (pass --mac to control)")

            self.state = "connected"
            while not self._stop and client.is_connected:
                await asyncio.sleep(1.0)
        self.connected = False
        self.logged_in = False
        self.db.insert_event("disconnect")
        log.info("disconnected")

    # ---- notification callbacks ----------------------------------------
    def _on_measurement(self, _sender, data: bytearray):
        p = protocol.parse(bytes(data))
        if not p:
            return
        now = time.time()
        p["ts"] = now
        self.latest = p
        if now - self._last_db >= self.s.sample_interval:
            self._last_db = now
            try:
                self.db.insert_measurement(p)
            except Exception as e:       # noqa: BLE001
                log.error("db insert failed: %s", e)

    def _on_command(self, _sender, data: bytearray):
        log.debug("cmd-resp %s", bytes(data).hex(" "))
