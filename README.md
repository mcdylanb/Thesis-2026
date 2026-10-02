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
                                                            ├─ make dashboard  → live CSI/RSSI plots of the newest Capture
                                                            └─ make preprocess → windows + D-CFR features
```

## Repo map

| Path | What |
|---|---|
| `firmware/` | Anchor and Relay sketches (Arduino IDE). [`firmware/README.md`](firmware/README.md) has the line format and per-board config. |
| `scripts/` | Gateway listeners (`make listen`, `make capture`) and the live dashboard (`make dashboard`). [`scripts/README.md`](scripts/README.md). |
| `gateway/` | Python preprocessing package: parse Captures → windows → RSSI smoothing, CSI normalization, D-CFR. |
| `tests/` | pytest suite for `gateway/` and the UDP listener. |
| `thesis/` | LaTeX manuscript. `make thesis`. |
| `journal/` | Dated work log — read the latest entry before a hardware Trial. |
| `docs/INVENTORY.md` | Status of every firmware/script/tool file (live / legacy / needs-decision). |
| `docs/adr/` | Decisions, e.g. [why the Raspberry Pi was retired](docs/adr/0001-laptop-gateway-replaces-pi.md). |
| `CONTEXT.md` | Glossary. Use these words in code, issues and the thesis. |
| `data/` | Captures land here. Git-ignored. |

## Tool install

| Tool | macOS | Windows |
|---|---|---|
| `uv` (Python env) | `brew install uv` | `winget install astral-sh.uv` |
| `gh` (GitHub issues/PRs) | `brew install gh` then `gh auth login` | `winget install GitHub.cli` then `gh auth login` |
| `make` | comes with Xcode CLT (`xcode-select --install`) | use the `uv run` commands in the table below; `make` itself only exists inside WSL, which cannot see USB serial ports |
| `latexmk` (thesis) | MacTeX or BasicTeX | MiKTeX or TeX Live |
| Arduino IDE + esp32 core 3.x | [arduino.cc](https://www.arduino.cc/en/software), then Boards Manager URL `https://espressif.github.io/arduino-esp32/package_esp32_index.json` → install **esp32 by Espressif Systems** | same |

Then, from the repo root:

```sh
make setup        # uv sync --extra dev --extra capture --extra viz --extra scout
make test         # full pytest suite should pass
```

The `scout` extra is PyTorch (CPU is enough), used only by the MDN Scout
(`gateway/scout.py`); outside uv, `pip install '.[scout]'`. `make test`
installs it; a plain `pytest` run without it skips the Scout's tests.

Windows teammates run the Python side natively (serial ports are `COMx`), not in WSL.

## Quickstart 1 — Flash

Open each sketch in Arduino IDE, board **ESP32 Dev Module**, upload speed 115200 (921600 fails on many CH340 clones).

1. **Relay** — `firmware/relay/relay.ino`. The CONFIG block is set for the
   team's trial network: the TP-Link MP700 pocket WiFi (`TP-Link_40F1`,
   2.4 GHz fixed channel 11, Gateway at `192.168.0.197`, port `5555`).
   Only edit it if you're on a different network.
   Serial Monitor at 115200 shows `INFO,wifi_connected,ip=…` when it joins.
2. **Anchors** — `firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino`,
   once per board. Edit `ANCHOR_ID` (`A1`..`A4`), `relay_mac` (the Relay's
   ESP-NOW MAC, printed on its serial boot banner), and `WIFI_CHANNEL` — it
   **must equal the trial network's channel**, because joining that network
   locks the Relay's radio to it.

Close the Serial Monitor before running a listener on the same port — a port
can only be held by one program.

## Quickstart 2 — Capture (wireless)

1. Power the MP700 (admin `http://192.168.0.1`: 2.4 GHz, fixed channel 11
   — must match the Anchors' `WIFI_CHANNEL`).
2. Connect the laptop to `TP-Link_40F1` and set IPv4 manually to
   `192.168.0.197` / `255.255.255.0` / router `192.168.0.1`.
3. Power the Relay and Anchors.
4. `make listen` — you should see `new anchor A1 -> data/A1_<ts>.csv` and a
   `lines=… heartbeats=…` counter every 5 s. No lines? The Anchors are on the
   wrong channel or nothing is transmitting OFDM frames on it.
5. Live view: `make dashboard` (matplotlib) tails the newest `data/A1_*.csv` —
   CSI heatmaps, RSSI trace and a frames-per-source-MAC bar so you can see
   *who* the Anchor is hearing. `--exclude-mac <Relay MAC>` hides the Relay's
   own traffic. The MATLAB `firmware/tools/matlab/realtime_csi_dashboard.m` is
   the legacy equivalent.

Serial fallback (Relay on USB, no hotspot): `make capture PORT=/dev/cu.usbserial-XXXX`
(Windows: `--port COM3`). Same Capture files.

## Quickstart 3 — Preprocess

```sh
make preprocess DATA=data OUT=out/windows.jsonl    # windows + features from Captures
make synth                                          # synthetic Trial in synth_data/ when you have no hardware
make preprocess DATA=synth_data OUT=out/synth.jsonl
make sim                                            # simulated calibration + test sessions (one dir per Trial) in sim_data/
make preprocess DATA=sim_data/calibration/R01 OUT=out/r01.jsonl
make eval-baseline                                  # sim -> radio map -> k-NN baseline results table (out/eval/)
make eval-scout                                     # same, plus the MDN Scout trained on that radio map (out/eval/scout.json, scout.pt)
make eval                                           # k-NN, Scout and the proposed Scout -> fallback -> Sniper side by side, with fallback rate and latency (out/eval/proposed.json)
```

Options (device list, window length, min anchors, subcarrier handling):
`uv run python -m gateway --help`. Per-trial authorized devices:
copy `gateway/devices.example.yaml`.

## Windows equivalents

| `make` target | PowerShell |
|---|---|
| `make setup` | `uv sync --extra dev --extra capture --extra viz --extra scout` |
| `make test` | `uv run --extra dev --extra scout pytest` |
| `make listen` | `uv run python scripts/relay_udp_listener.py --outdir data` |
| `make dashboard` | `uv run python scripts/live_csi_dashboard.py --data data --anchor A1` |
| `make replay FILE=data/A1_x.csv` | `uv run python scripts/live_csi_dashboard.py --file data/A1_x.csv --from-start --replay-rate 6` |
| `make capture PORT=COM3` | `uv run python scripts/uart_listener_2.py --port COM3 --outdir data` |
| `make preprocess` | `uv run python -m gateway --in data --out out/windows.jsonl --summary` |
| `make synth` | `uv run python -m gateway.synth --out synth_data` |
| `make sim` | `uv run python -m gateway.sim --layout layouts/techhub_default.yaml --out sim_data` |
| `make eval` | run the `make sim` line, then `uv run --extra scout python -m gateway.sniper --sim sim_data --layout layouts/techhub_default.yaml --out out/eval --min-stability 0` |
| `make eval-baseline` | run the `make sim` line, then `uv run python -m gateway.evaluate --sim sim_data --layout layouts/techhub_default.yaml --out out/eval` |
| `make eval-scout` | run the `make sim` line, then `uv run --extra scout python -m gateway.scout --sim sim_data --layout layouts/techhub_default.yaml --out out/eval` |
| `make thesis` | `cd thesis; latexmk -pdf main.tex` |

`make help` prints the same table.

## Thesis

`make thesis` → `thesis/main.pdf`. See [`thesis/README.md`](thesis/README.md)
for the un-versioned appendix assets.

## Working on the repo

- Issues live in GitHub Issues (`gh issue list`). Tickets labelled
  `ready-for-agent` are unblocked; `needs-info` ones are waiting on a team decision.
- Log each hardware Trial in `journal/` (format in `journal/README.md`).
- Don't delete files under `firmware/` or `scripts/` without resolving them
  in `docs/INVENTORY.md` first.
