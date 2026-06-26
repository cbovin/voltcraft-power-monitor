"""Voltcraft SEM-3600BT BLE protocol (reverse-engineered and validated on hardware).

Custom service ``0000fee0-494c-4f47-4943-544543480000`` exposes:
  * ``fee1`` — realtime measurement notifications
  * ``fee3`` — command writes and their responses

Sequence: subscribe to fee1 + fee3, send LOGIN (sync + MAC-derived secret),
then relay ON/OFF works. Measurement frames are 16 bytes: a state byte followed
by five "value trios" (V, A, W, PF, Hz), each a decimal-point indicator plus two
BCD bytes.

Protocol inspired by https://github.com/Heckie75/voltcraft-sem-3600bt
"""
from __future__ import annotations

import datetime
import struct

UUID_MEAS = "0000fee1-494c-4f47-4943-544543480000"  # realtime notifications
UUID_CMD = "0000fee3-494c-4f47-4943-544543480000"   # commands + responses

# Magic mask the firmware uses to derive the login secret from the MAC ("iLogic").
_MASK = (105, 76, 111, 103, 105, 99)

# First byte of each value trio is a decimal-point indicator -> divisor.
_SCALE = {1: 1000.0, 2: 100.0, 3: 10.0, 4: 1.0, 5: 1000.0}

STATE = {0: "off", 1: "on", 2: "countdown"}


def secret_for(mac: str) -> int:
    """Login secret = sum over reversed MAC bytes of ``(byte ^ mask[i]) & 255``."""
    parts = [int(x, 16) for x in mac.split(":")]
    return sum(((v ^ _MASK[i]) & 255) for i, v in enumerate(reversed(parts)))


def sync_payload(mac: str, when: datetime.datetime | None = None) -> bytes:
    """LOGIN frame for fee3: ``03 <year LE> MM DD HH MM SS <secret LE>``."""
    n = when or datetime.datetime.now()
    return (
        bytes([0x03])
        + struct.pack("<H", n.year)
        + bytes([n.month, n.day, n.hour, n.minute, n.second])
        + struct.pack("<H", secret_for(mac))
    )


def switch_payload(on: bool) -> bytes:
    """Relay control for fee3: ``04 01`` = ON, ``04 00`` = OFF."""
    return bytes([0x04, 0x01 if on else 0x00])


def _value(indicator: int, hi: int, lo: int) -> float:
    """Decode one value trio. Value bytes are BCD (hex digits == decimal digits)."""
    try:
        digits = int(f"{hi:02x}{lo:02x}")
    except ValueError:                       # not valid BCD -> raw fallback
        digits = (hi << 8) | lo
    return digits / _SCALE.get(indicator, 10.0)


def parse(data: bytes) -> dict | None:
    """Decode a 16-byte measurement frame, or return ``None`` if malformed."""
    if not data or len(data) < 16:
        return None
    s = data[0]
    return {
        "state": s,
        "state_label": STATE.get(s, str(s)),
        "v": _value(data[1], data[2], data[3]),     # Volts
        "a": _value(data[4], data[5], data[6]),     # Amperes
        "w": _value(data[7], data[8], data[9]),     # Watts
        "pf": _value(data[10], data[11], data[12]),  # power factor
        "hz": _value(data[13], data[14], data[15]),  # Hertz
    }
