"""Voltcraft SEM-3600BT — monitor power and control a BLE smart socket from the web.

A small, cross-platform web app (FastAPI + bleak + SQLite) that auto-discovers a
Voltcraft SEM-3600BT ("WiT Power Meter") over Bluetooth Low Energy, streams live
measurements, controls the relay, logs history and estimates running cost.
"""

__version__ = "0.1.0"
