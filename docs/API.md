# API & BLE Reference

Reference for the **REST API** served by the app and the **BLE protocol** used to
talk to the Voltcraft SEM-3600BT. The protocol was reverse-engineered and
validated on hardware; it is inspired by
[Heckie75/voltcraft-sem-3600bt](https://github.com/Heckie75/voltcraft-sem-3600bt).

- Source of truth: `voltcraft_sem/server.py` (REST) and `voltcraft_sem/protocol.py` (BLE).
- Base URL: `http://127.0.0.1:8000` (configurable via `--host` / `--port`).
- All bodies and responses are JSON.

---

## REST API

| Method | Endpoint        | Body / Query                              | Description                                          |
|--------|-----------------|-------------------------------------------|------------------------------------------------------|
| GET    | `/`             | —                                         | Serves the web UI (`index.html`)                     |
| GET    | `/api/status`   | —                                         | Connection state, device info, latest reading, cost/h |
| POST   | `/api/switch`   | `{"on": true}`                            | Turn the socket relay on/off                         |
| POST   | `/api/rescan`   | —                                         | Force a fresh BLE scan                               |
| GET    | `/api/history`  | `?minutes=60`                             | Bucketed measurement points + energy/cost            |
| GET    | `/api/config`   | —                                         | Current electricity price + currency                 |
| POST   | `/api/config`   | `{"price_per_kwh":0.28,"currency":"€"}`   | Update price and/or currency                         |

Static assets are mounted under `/static`.

### `GET /api/status`

Snapshot of the BLE connection and the most recent measurement.

```json
{
  "state": "connected",
  "connected": true,
  "can_control": true,
  "device": {
    "address": "98:7B:F3:62:89:19",
    "name": "WiT Power Meter",
    "rssi": -67
  },
  "latest": {
    "state": 1,
    "state_label": "on",
    "v": 239.1,
    "a": 0.156,
    "w": 20.4,
    "pf": 0.544,
    "hz": 49.98,
    "ts": 1750000000.0
  },
  "error": null,
  "currency": "€",
  "price_per_kwh": 0.25,
  "cost_per_hour": 0.0051
}
```

| Field           | Type            | Notes                                                                 |
|-----------------|-----------------|-----------------------------------------------------------------------|
| `state`         | string          | `starting` \| `scanning` \| `connecting` \| `connected` \| `reconnecting` \| `stopped` |
| `connected`     | bool            | BLE link is up                                                        |
| `can_control`   | bool            | Connected **and** logged in (relay control available)                 |
| `device`        | object          | `address`, `name`, `rssi` (dBm); fields are `null` until discovered   |
| `latest`        | object \| null  | Most recent decoded measurement frame (`null` before first frame)     |
| `error`         | string \| null  | Last error, e.g. `"no matching device found"`                         |
| `cost_per_hour` | number \| null  | `w / 1000 * price_per_kwh`, rounded to 4 dp; `null` if no reading yet  |

`can_control` is `false` when monitor-only (no MAC for the login secret — see the
BLE login note below).

### `POST /api/switch`

Body `{"on": true}` / `{"on": false}`. Requires `can_control: true`.

```json
{ "ok": true, "on": true }
```

On failure (not connected, or not logged in) returns **HTTP 503**:

```json
{ "ok": false, "error": "control unavailable: device MAC unknown — pass --mac to enable it" }
```

The state update is optimistic; the next measurement frame confirms the real
relay state. Switch actions are logged to the `events` table.

### `POST /api/rescan`

Triggers a fresh BLE scan on the background loop. Returns immediately:

```json
{ "ok": true }
```

### `GET /api/history?minutes=60`

Measurement points over the window, bucket-averaged to at most ~400 points, plus
energy and cost figures. `minutes` defaults to `60`.

```json
{
  "minutes": 60,
  "points": [
    { "ts": 1750000000, "w": 20.4, "v": 239.1, "a": 0.156, "pf": 0.544, "hz": 49.98, "state": 1 }
  ],
  "energy_kwh_today": 0.485,
  "energy_kwh_range": 0.0,
  "cost_today": 0.15,
  "cost_range": 0.0,
  "currency": "€",
  "price_per_kwh": 0.25
}
```

- Energy is computed by trapezoidal integration of power over stored samples
  (gaps > 120 s from disconnects are skipped).
- `*_today` integrates from local midnight; `*_range` integrates over `minutes`.

### `GET /api/config` / `POST /api/config`

```json
{ "price_per_kwh": 0.25, "currency": "€" }
```

`POST` accepts `price_per_kwh` (number) and/or `currency` (string); both
optional, sent fields are persisted in the SQLite `settings` table. An
unparseable `price_per_kwh` returns **HTTP 400** `{"ok": false, "error": "invalid price"}`.
Returns the updated config (same shape as `GET`).

---

## BLE Protocol

The device exposes a custom GATT service and two characteristics:

| UUID                                       | Role                                  |
|--------------------------------------------|---------------------------------------|
| `0000fee0-494c-4f47-4943-544543480000`     | Custom service (advertised; used for discovery) |
| `0000fee1-494c-4f47-4943-544543480000`     | `fee1` — realtime measurement **notifications** |
| `0000fee3-494c-4f47-4943-544543480000`     | `fee3` — command **writes** and their responses |

### Discovery

Match the advertisement by **service UUID** (`0000fee0-…`, preferred) or by an
advertised-name substring. Default name filters:
`WiT Power Meter`, `WiT`, `SEM-3600`, `Voltcraft`. Strongest RSSI wins.

### Connection sequence

1. Connect (GATT).
2. Subscribe (start notify) to **`fee1`** and **`fee3`**.
3. Write a **LOGIN** frame to `fee3`.
4. Relay **ON/OFF** writes to `fee3` now work; measurement frames stream on `fee1`.

Only **one** BLE connection to the socket is allowed at a time.

### Login secret

Relay control requires a login frame whose secret is derived from the device
**hardware MAC**. (On macOS, CoreBluetooth hides the MAC behind an opaque UUID —
supply the real MAC with `--mac` to enable control; otherwise the app is
monitor-only.)

```
secret = Σ over reversed MAC bytes of  (byte ^ mask[i]) & 255
mask   = "iLogic"  =  (105, 76, 111, 103, 105, 99)   # per-byte XOR key
```

```python
def secret_for(mac: str) -> int:
    parts = [int(x, 16) for x in mac.split(":")]
    return sum(((v ^ MASK[i]) & 255) for i, v in enumerate(reversed(parts)))
```

### Command payloads (write to `fee3`)

**LOGIN** — opcode `0x03`, then date/time sync and the 16-bit secret (all
multi-byte values little-endian):

```
03 <year LE:2> MM DD HH MM SS <secret LE:2>
```

| Bytes | Field            |
|-------|------------------|
| 1     | `0x03` opcode    |
| 2–3   | year (uint16 LE) |
| 4     | month            |
| 5     | day              |
| 6     | hour             |
| 7     | minute           |
| 8     | second           |
| 9–10  | secret (uint16 LE) |

**RELAY** — opcode `0x04`, then state:

| Payload  | Meaning |
|----------|---------|
| `04 01`  | ON      |
| `04 00`  | OFF     |

### Measurement frame (notification on `fee1`)

A 16-byte frame: a **state** byte followed by five **value trios**
(V, A, W, PF, Hz). Each trio is a decimal-point indicator byte + two BCD value
bytes.

| Offset | Bytes | Meaning                          |
|--------|-------|----------------------------------|
| 0      | 1     | state (`0`=off, `1`=on, `2`=countdown) |
| 1–3    | 3     | Voltage (V)                      |
| 4–6    | 3     | Current (A)                      |
| 7–9    | 3     | Power (W)                        |
| 10–12  | 3     | Power factor                     |
| 13–15  | 3     | Frequency (Hz)                   |

**Decoding a value trio** `[indicator, hi, lo]`: the two value bytes are BCD
(each hex digit equals the decimal digit), concatenated to a 4-digit number, then
divided by a scale chosen by the indicator:

| Indicator | Divisor |
|-----------|---------|
| 1         | 1000    |
| 2         | 100     |
| 3         | 10      |
| 4         | 1       |
| 5         | 1000    |

Example: indicator `2`, bytes `0x23 0x91` → `2391 / 100 = 23.91`. Bytes that are
not valid BCD fall back to a raw `(hi << 8) | lo` big-endian read divided by 10.
Frames shorter than 16 bytes are rejected.
