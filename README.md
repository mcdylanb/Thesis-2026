# Thesis 2026 — Hybrid RSSI–CSI Localization

Passive WiFi localization: ESP32 **Anchors** sniff RSSI + CSI from nearby
transmitters, a **Relay** collects them over ESP-NOW, and the **Gateway**
laptop turns the stream into localization features. Terms are defined in
[`CONTEXT.md`](CONTEXT.md).

```
 Anchor A1 ─┐
 Anchor A2 ─┤ ESP-NOW            WiFi UDP (trial network)
 Anchor A3 ─┼──────────▶ Relay ──────────────────────────▶ Gateway laptop
 Anchor A4 ─┘                                               ├─ make listen   → data/<Anchor>_<ts>.csv  (Captures)
                                                            ├─ MATLAB dashboard tails the newest Capture
                                                            └─ make preprocess → windows + D-CFR features
```

## Repo map

| Path | What |
|---|---|
| `firmware/` | Anchor and Relay sketches (Arduino IDE). [`firmware/README.md`](firmware/README.md) has the line format and per-board config. |
| `scripts/` | Gateway listeners (`make listen`, `make capture`). [`scripts/README.md`](scripts/README.md). |
| `gateway/` | Python preprocessing package: parse Captures → windows → RSSI smoothing, CSI normalization, D-CFR. |
| `tests/` | pytest suite for `gateway/` and the UDP listener. |
| `thesis/` | LaTeX manuscript. `make thesis`. |
| `journal/` | Dated work log — read the latest entry before a hardware session. |
| `docs/INVENTORY.md` | Status of every firmware/script/tool file (live / legacy / needs-decision). |
| `docs/adr/` | Decisions, e.g. [why the Raspberry Pi was retired](docs/adr/0001-laptop-gateway-replaces-pi.md). |
| `CONTEXT.md` | Glossary. Use these words in code, issues and the thesis. |
| `data/` | Captures land here. Git-ignored. |

## Tool install

| Tool | macOS | Windows |
|---|---|---|
| `uv` (Python env) | `brew install uv` | `winget install astral-sh.uv` |
| `gh` (GitHub issues/PRs) | `brew install gh` then `gh auth login` | `winget install GitHub.cli` then `gh auth login` |
| `make` | comes with Xcode CLT (`xcode-select --install`) | not needed — use the `uv run` commands in the table below (or run `make` inside WSL for non-hardware targets) |
| `latexmk` (thesis) | MacTeX or BasicTeX | MiKTeX or TeX Live |
| Arduino IDE + esp32 core 3.x | [arduino.cc](https://www.arduino.cc/en/software), then Boards Manager URL `https://espressif.github.io/arduino-esp32/package_esp32_index.json` → install **esp32 by Espressif Systems** | same |
| MATLAB (live dashboard, optional) | campus licence | same |

Then, from the repo root:

```sh
make setup        # uv sync --extra dev --extra capture
make test         # 51 tests should pass
```

Windows teammates run the Python side natively (serial ports are `COMx`), not in WSL.

## Quickstart 1 — Flash

Open each sketch in Arduino IDE, board **ESP32 Dev Module**, upload speed 921600.

1. **Relay** — `firmware/relay/relay.ino`. Edit the CONFIG block:
   `WIFI_SSID` / `WIFI_PASSWORD` (the trial network), `GATEWAY_IP` (the
   laptop's static IP, default `192.168.1.100`), `GATEWAY_PORT` (`5555`).
   Serial Monitor at 921600 shows `INFO,wifi_connected,ip=…` when it joins.
2. **Anchors** — `firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino`,
   once per board. Edit `ANCHOR_ID` (`A1`..`A4`), `relay_mac` (the Relay's
   ESP-NOW MAC, printed on its serial boot banner), and `WIFI_CHANNEL` — it
   **must equal the trial network's channel**, because joining that network
   locks the Relay's radio to it.

Close the Serial Monitor before running a listener on the same port — a port
can only be held by one program.

## Quickstart 2 — Capture (wireless)

1. Start a hotspot with the SSID/password the Relay is flashed with, on a
   fixed 2.4 GHz channel that matches the Anchors' `WIFI_CHANNEL`.
2. Connect the laptop to it and give it the static `GATEWAY_IP`.
3. Power the Relay and Anchors.
4. `make listen` — you should see `new anchor A1 -> data/A1_<ts>.csv` and a
   `lines=… heartbeats=…` counter every 5 s. No lines? The Anchors are on the
   wrong channel or nothing is transmitting OFDM frames on it.
5. Live view: open `firmware/tools/matlab/realtime_csi_dashboard.m` in MATLAB
   and run it — it tails the newest `data/A1_*.csv`.

Serial fallback (Relay on USB, no hotspot): `make capture PORT=/dev/cu.usbserial-XXXX`
(Windows: `--port COM3`). Same Capture files.

## Quickstart 3 — Preprocess

```sh
make preprocess DATA=data OUT=out/windows.jsonl    # windows + features from Captures
make synth                                          # synthetic session in synth_data/ when you have no hardware
make preprocess DATA=synth_data OUT=out/synth.jsonl
```

Options (device list, window length, min anchors, subcarrier handling):
`uv run python -m gateway --help`. Per-trial authorized devices:
copy `gateway/devices.example.yaml`.

## Windows equivalents

| `make` target | PowerShell |
|---|---|
| `make setup` | `uv sync --extra dev --extra capture` |
| `make test` | `uv run pytest` |
| `make listen` | `uv run python scripts/relay_udp_listener.py --outdir data` |
| `make capture PORT=COM3` | `uv run python scripts/uart_listener_2.py --port COM3 --outdir data` |
| `make preprocess` | `uv run python -m gateway --in data --out out/windows.jsonl --summary` |
| `make synth` | `uv run python -m gateway.synth --out synth_data` |
| `make thesis` | `cd thesis; latexmk -pdf main.tex` |

`make help` prints the same table.

## Thesis

`make thesis` → `thesis/main.pdf`. See [`thesis/README.md`](thesis/README.md)
for the un-versioned appendix assets.

## Working on the repo

- Issues live in GitHub Issues (`gh issue list`). Tickets labelled
  `ready-for-agent` are unblocked; `needs-info` ones are waiting on a team decision.
- Log each hardware session in `journal/` (format in `journal/README.md`).
- Don't delete files under `firmware/` or `scripts/` without resolving them
  in `docs/INVENTORY.md` first.
