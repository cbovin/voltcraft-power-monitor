"""SQLite persistence: measurements, events, user settings, energy + cost."""
from __future__ import annotations

import datetime
import sqlite3
import time

from .config import DEFAULT_CURRENCY, DEFAULT_PRICE

# Cap chart payloads: long ranges are bucketed down to roughly this many points.
_MAX_POINTS = 400


def _local_midnight_ts() -> int:
    now = datetime.datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


class Database:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        # WAL is faster but unsupported on some network filesystems (e.g. the
        # \\wsl.localhost 9P share); fall back to the default journal there.
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS measurements(
                ts    INTEGER PRIMARY KEY,   -- unix seconds
                state INTEGER,
                v REAL, a REAL, w REAL, pf REAL, hz REAL
            );
            CREATE TABLE IF NOT EXISTS events(
                ts     INTEGER,
                action TEXT                  -- on | off | connect | disconnect
            );
            CREATE TABLE IF NOT EXISTS settings(
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self.conn.commit()
        self._seed("price_per_kwh", str(DEFAULT_PRICE))
        self._seed("currency", DEFAULT_CURRENCY)

    # ---- settings -------------------------------------------------------
    def _seed(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value)
        )
        self.conn.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_config(self) -> dict:
        return {
            "price_per_kwh": float(self.get_setting("price_per_kwh", str(DEFAULT_PRICE))),
            "currency": self.get_setting("currency", DEFAULT_CURRENCY),
        }

    def set_config(self, price_per_kwh: float | None = None, currency: str | None = None):
        if price_per_kwh is not None:
            self.set_setting("price_per_kwh", str(float(price_per_kwh)))
        if currency:
            self.set_setting("currency", currency)
        return self.get_config()

    # ---- writes ---------------------------------------------------------
    def insert_measurement(self, p: dict):
        self.conn.execute(
            "INSERT OR REPLACE INTO measurements(ts,state,v,a,w,pf,hz) "
            "VALUES(?,?,?,?,?,?,?)",
            (int(p["ts"]), p["state"], p["v"], p["a"], p["w"], p["pf"], p["hz"]),
        )
        self.conn.commit()

    def insert_event(self, action: str):
        self.conn.execute(
            "INSERT INTO events(ts,action) VALUES(?,?)", (int(time.time()), action)
        )
        self.conn.commit()

    # ---- reads ----------------------------------------------------------
    def history(self, minutes: int) -> list[dict]:
        """Power/metrics over the window, bucket-averaged to <= _MAX_POINTS points."""
        since = int(time.time()) - minutes * 60
        span = max(1, minutes * 60)
        bucket = max(1, span // _MAX_POINTS)
        cur = self.conn.execute(
            """
            SELECT (ts/?)*? AS b,
                   AVG(w), AVG(v), AVG(a), AVG(pf), AVG(hz), MAX(state)
            FROM measurements WHERE ts>=?
            GROUP BY ts/? ORDER BY b
            """,
            (bucket, bucket, since, bucket),
        )
        return [
            {"ts": int(r[0]), "w": r[1], "v": r[2], "a": r[3],
             "pf": r[4], "hz": r[5], "state": r[6]}
            for r in cur.fetchall()
        ]

    def energy_kwh(self, since_ts: int) -> float:
        """Trapezoidal integration of power over stored samples -> kWh."""
        rows = self.conn.execute(
            "SELECT ts,w FROM measurements WHERE ts>=? ORDER BY ts", (since_ts,)
        ).fetchall()
        wh = 0.0
        for (t0, w0), (t1, w1) in zip(rows, rows[1:]):
            dt = t1 - t0
            if 0 < dt <= 120:                        # skip gaps from disconnects
                wh += (w0 + w1) / 2.0 * dt / 3600.0  # W*s -> Wh
        return wh / 1000.0

    def energy_today(self) -> float:
        return self.energy_kwh(_local_midnight_ts())

    def energy_range(self, minutes: int) -> float:
        return self.energy_kwh(int(time.time()) - minutes * 60)
