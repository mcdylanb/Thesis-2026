# File inventory — firmware, scripts, tools

Nothing was deleted in the 2026-09 cleanup. This is the map. Statuses:

- **live** — the path the team flashes / runs today
- **legacy** — superseded; kept until the team decides
- **needs-decision** — the team has not yet agreed keep / move to legacy / delete;
  tracked in the GitHub issue linked at the bottom

Vocabulary: see [`CONTEXT.md`](../CONTEXT.md).

## firmware/

| Path | Status | Purpose |
|---|---|---|
| `relay/relay.ino` | live | **Relay.** Receives Anchor records over ESP-NOW, re-emits `CSI,`/`STAT,` lines over USB serial and WiFi UDP to the Gateway. |
| `anchor_arduino_wireless/anchor_arduino_wireless.ino` | live | **Anchor** (wireless). Sniffs, packs each record into an ESP-NOW struct addressed to the Relay. |
| `anchor_arduino_wireless/esp_now_tx_rx/transmitter/transmitter.ino` | needs-decision | ESP-NOW bring-up spike (transmit side). No CSI. |
| `anchor_arduino_wireless/esp_now_tx_rx/receiver/receiver.ino` | needs-decision | ESP-NOW bring-up spike (receive side). Precursor of `relay.ino`. |
| `anchor_arduino/anchor_arduino.ino` | legacy | Anchor (wired). Original serial-only sketch; same line format as the ESP-IDF build. |
| `anchor_arduino/anchor2_arduino/anchor2_arduino.ino` | needs-decision | Byte-for-byte copy of `anchor_arduino.ino` with `ANCHOR_ID "A2"` and `WIFI_CHANNEL 4`. Only the CONFIG block differs. |
| `anchor/` (ESP-IDF project) | needs-decision | Anchor (wired), ESP-IDF v5.4 native build. Same output as the Arduino sketch; nobody on the team currently flashes it. |
| `tools/matlab/realtime_csi_dashboard.m` | legacy | Live heatmap that tails the newest `data/A1_*.csv` Capture. Superseded by `scripts/live_csi_dashboard.py` (`make dashboard`), which needs no MATLAB licence. |
| `tools/matlab/singleRawCSIpreprocess.m` | needs-decision | Offline single-Capture CSI plot (file picker). |
| `tools/matlab/multiRawCSIpreprocess.m` | needs-decision | Offline two-Capture comparison (file picker). |
| `tools/gateway_logger.py` | legacy | Multi-port serial logger for the wired Anchor era (one `--port` per Anchor). Has an unused `127.0.0.1` UDP loopback. |
| `tools/requirements.txt` | legacy | Superseded by `pyproject.toml` (`capture` extra). Kept so old `pip install -r` instructions still work. |

## scripts/

| Path | Status | Purpose |
|---|---|---|
| `relay_udp_listener.py` | live | `make listen`. Binds the Gateway IP/port, lands the Relay's UDP stream as per-Anchor Captures. Tested. |
| `live_csi_dashboard.py` | live | `make dashboard`. Python port of the MATLAB dashboard plus RSSI trace and per-MAC frame counts; `--snapshot` renders a PNG. Tested. |
| `uart_listener_2.py` | live | `make capture`. Single-port serial listener for a Relay on USB; `--verbose`, `--outdir` default `../data`. Has an unused UDP loopback. |
| `uart_listener.py` | needs-decision | Earlier revision of `uart_listener_2.py` (no `--verbose`, `--outdir` default `data`). Otherwise the same code. |
| `rsync_data_transfer.sh` | legacy | Pulls Captures from the Raspberry Pi over SSH. Pi retired — [ADR-0001](adr/0001-laptop-gateway-replaces-pi.md). Contains a hardcoded Pi IP/user. |
| `README.md` | live | Listener usage; Pi section marked legacy. |

## gateway/ and tests/

All live: the preprocessing package (`python -m gateway`) and its pytest suite (`make test`).

## Open decisions

The `needs-decision` rows above are listed as checkboxes in the GitHub issue
[#21](https://github.com/mcdylanb/Thesis-2026/issues/21) (label `needs-info`). Resolve
each there, then update this table and open a ticket for any move/delete.
