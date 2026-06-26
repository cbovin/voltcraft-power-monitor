# Voltcraft SEM-3600BT — Web Monitor & Control

A small, cross-platform web app to **monitor power and switch on/off** a
**Voltcraft SEM-3600BT** Bluetooth smart socket (advertised as *"WiT Power
Meter"*) — a replacement for the discontinued vendor app.

It **auto-discovers** the device over Bluetooth Low Energy (no MAC to hard-code),
streams live measurements, logs history to **SQLite**, draws a power chart, and
estimates running **cost** from a configurable electricity price.

Built with [bleak](https://github.com/hbldh/bleak) (BLE), FastAPI and a tiny
vanilla-JS frontend. Protocol inspired by
[Heckie75/voltcraft-sem-3600bt](https://github.com/Heckie75/voltcraft-sem-3600bt).

## Features

- 🔌 Turn the socket **on/off** from the browser
- 📈 **Live** voltage, current, power, power factor, frequency (~1 Hz)
- 🗄️ History in **SQLite**, power chart with 15 m / 1 h / 6 h / 24 h ranges
- 💶 **Cost estimate**: set €/kWh, see cost-per-hour and cost/energy today
- 🔍 **Auto-discovery** by service UUID + name (not bound to one device)
- ♻️ **Auto-reconnect** with backoff; re-scans if the device disappears
- 🖥️ Cross-platform: Linux (BlueZ), Windows (WinRT), macOS (CoreBluetooth)

## Install

```bash
git clone https://github.com/cbovin/voltcraft-power-monitor.git
cd voltcraft-power-monitor

# create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e .
```

or just install the dependencies and run from source:

```bash
pip install -r requirements.txt
```

## Usage

```bash
# auto-discover the device and serve the UI on http://127.0.0.1:8000
voltcraft-sem
# or: python -m voltcraft_sem
```

Open **http://127.0.0.1:8000** in your browser.

### Useful flags

```bash
voltcraft-sem --scan                 # list nearby matching devices and exit
voltcraft-sem --address AA:BB:..     # skip discovery, use a fixed address
voltcraft-sem --mac AA:BB:..         # MAC for the control secret (see macOS note)
voltcraft-sem --port 9000 --host 0.0.0.0
voltcraft-sem --price 0.28 --currency €
voltcraft-sem --db /path/to/data.db --sample-interval 5
voltcraft-sem -v                     # debug logging
```

The electricity price is also editable live in the UI and persisted in the DB.

## Platform notes

- **Bluetooth must be available to the process.** `bleak` uses BlueZ on Linux,
  WinRT on Windows and CoreBluetooth on macOS.
- **macOS:** Core Bluetooth exposes an opaque device UUID, not the hardware MAC.
  Monitoring works out of the box, but the **relay control needs the real MAC**
  to compute the login secret — pass it with `--mac AA:BB:CC:DD:EE:FF`
  (find it on Linux/Windows or on the device label). The UI shows *"Monitor
  only"* when control is unavailable.
- **WSL2:** WSL2 has no Bluetooth stack. Run the app with **Windows** Python
  (which can execute a script living on the WSL filesystem), e.g.
  `python.exe \\wsl.localhost\<distro>\path\to\app`, then browse
  `http://127.0.0.1:8000` on Windows.
- Only **one** BLE connection to the socket is allowed at a time — close other
  apps/tools talking to it first.

## How it works

| Layer | File |
|-------|------|
| BLE protocol (parse, secret, payloads) | `voltcraft_sem/protocol.py` |
| Device discovery | `voltcraft_sem/discovery.py` |
| Connection manager (login, reconnect) | `voltcraft_sem/device.py` |
| SQLite storage + energy/cost | `voltcraft_sem/db.py` |
| FastAPI app + REST | `voltcraft_sem/server.py` |
| CLI | `voltcraft_sem/cli.py` |
| Web UI | `voltcraft_sem/web/` |

### Protocol summary (validated on hardware)

Custom GATT service `0000fee0-…`:

- `fee1` — realtime measurement notifications
- `fee3` — command writes + responses

Flow: subscribe to `fee1`/`fee3`, send **LOGIN**
`03 <year LE> MM DD HH MM SS <secret LE>`, then **ON** = `04 01` / **OFF** =
`04 00`. The login `secret = Σ ((mac_byte ^ mask[i]) & 255)` over the reversed
MAC bytes with `mask = "iLogic"`. Measurement frames are 16 bytes: a state byte
plus five value-trios (V, A, W, PF, Hz), each a decimal-point indicator and two
BCD bytes.

## REST API

| Method | Endpoint | Body / Query | Description |
|--------|----------|--------------|-------------|
| GET  | `/api/status`  | — | connection state, device, latest reading, live cost/h |
| POST | `/api/switch`  | `{"on": true}` | turn socket on/off |
| GET  | `/api/history` | `?minutes=60` | bucketed points + energy/cost |
| GET  | `/api/config`  | — | current price/currency |
| POST | `/api/config`  | `{"price_per_kwh":0.28,"currency":"€"}` | update price |
| POST | `/api/rescan`  | — | force a fresh BLE scan |

## License

Apache 2.0 — see [LICENSE](LICENSE).

> Not affiliated with Voltcraft / Conrad. Use at your own risk; mains switching
> involves real loads.
