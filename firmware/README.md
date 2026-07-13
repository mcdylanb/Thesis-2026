# Anchor Firmware — Passive RSSI + CSI Sniffer (ESP32)

Firmware for the thesis anchors (A1–A4): each ESP32 NodeMCU passively sniffs
802.11 packets on a fixed 2.4 GHz channel and emits one CSV line per packet
containing the tuple required by the methodology chapter:

```
(source MAC, timestamp, RSSI, CSI amplitudes, anchor id)
```

Data is streamed over **USB serial (default, 921600 baud)** and optionally
mirrored over **WiFi UDP** to the laptop gateway. All localization processing
(windowing, RSSI smoothing, CSI normalization, D-CFR, MDN, particle filter)
happens on the gateway — the firmware is deliberately dumb.

Two interchangeable firmware implementations are provided — **pick one**;
they emit the identical line format and the gateway logger works with either:

- `anchor/` — ESP-IDF v5.4 project (native toolchain, menuconfig-based config)
- `anchor_arduino/` — single-sketch Arduino IDE version (easiest to flash)

## Requirements

- Classic **ESP32** NodeMCU dev boards (CP2102 or CH340 USB-UART)
- Python 3.9+ with `pyserial` for the gateway logger (`pip install -r tools/requirements.txt`)
- For `anchor/`: **ESP-IDF v5.4** (`git clone -b release/v5.4 https://github.com/espressif/esp-idf`)
- For `anchor_arduino/`: **Arduino IDE** with the **arduino-esp32 core 3.x**

## Build and flash (per anchor)

```sh
cd firmware/anchor
idf.py set-target esp32
idf.py menuconfig          # Anchor Configuration -> set Anchor identifier (A1..A4)
idf.py -p /dev/cu.usbserial-XXXX flash monitor
```

The only per-board difference is `ANCHOR_ID`. Everything else (channel,
filter, baud, UDP) is shared configuration under **Anchor Configuration** in
menuconfig:

| Option | Default | Meaning |
|---|---|---|
| `ANCHOR_ID` | `A1` | Emitted in every line; set per board |
| `ANCHOR_WIFI_CHANNEL` | 6 | Fixed sniff channel (serial mode only) |
| Frame filter | MGMT+DATA | 802.11 frame classes passed up by the radio |
| `ANCHOR_UART_BAUD` | 921600 | Serial output rate (fallback: 460800 for flaky CH340 clones) |
| `ANCHOR_CSI_OUTPUT_RAW_IQ` | off | Debug: emit 128 raw int8 I/Q values instead of 64 amplitudes |
| `ANCHOR_UDP_ENABLE` | off | Mirror lines via UDP; see constraint below |

## Build and flash — Arduino IDE version

1. Install the ESP32 board support: **Arduino IDE → Settings → Additional
   boards manager URLs** →
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`,
   then **Boards Manager → "esp32" by Espressif Systems** (3.x).
2. Open `firmware/anchor_arduino/anchor_arduino.ino`.
3. Edit the `==== CONFIG ====` block at the top — per board, only
   `ANCHOR_ID` ("A1".."A4") needs changing. Channel, baud, frame filter,
   raw-I/Q debug mode, and UDP settings live in the same block.
4. **Tools → Board → "ESP32 Dev Module"**, select the board's serial port,
   Upload Speed 921600, then **Upload**.
5. **Serial Monitor at 921600 baud** (must match `SERIAL_BAUD`) — expect an
   `INFO,...` banner, then `CSI,...` lines and a `STAT` line every 5 s.

The Arduino sketch is a direct port of the ESP-IDF project: same callback
architecture (CSI callback produces the whole tuple; promiscuous callback
only counts), same CSI configuration (LLTF-only, 64 subcarriers), same
output format below.

## Output format

One ASCII line per record, `\n`-terminated, comma-separated, no spaces.
Any line not starting with `CSI,` or `STAT,` (boot ROM noise, warnings)
must be ignored by parsers.

```
CSI,<anchor_id>,<seq>,<mac>,<rssi>,<sig_mode>,<channel>,<timestamp_us>,<n_sub>,<v1>,...,<vN>
STAT,<anchor_id>,<uptime_ms>,<pkts_seen>,<csi_cb_count>,<queued>,<dropped>,<free_heap>
```

- `seq` — uint32, monotonic per boot (gaps ⇒ drops; reset ⇒ reboot)
- `mac` — transmitter MAC, lowercase hex (`a4:cf:12:3b:9e:01`). No on-device
  filtering: the gateway's wanted/unwanted classifier keys on this field.
- `rssi` — signed dBm of the same packet the CSI came from
- `sig_mode` — 0 = non-HT (802.11g), 1 = HT (802.11n)
- `timestamp_us` — uint32 local WiFi MAC clock in µs. **Anchors are not
  time-synchronized and this wraps every ~71.6 min.** Cross-anchor alignment
  uses the host arrival timestamps prepended by `tools/gateway_logger.py`.
- `n_sub` — 64 in amplitude mode (default), 128 in raw I/Q mode
- `v_i` — amplitude mode: `round(sqrt(I²+Q²))`, integers 0–181, in hardware
  buffer order; raw mode: int8 values alternating imag, real

Example:

```
CSI,A2,10482,a4:cf:12:3b:9e:01,-58,1,6,1849302811,64,0,0,0,0,12,14,15,15,17, ... ,0
```

### Subcarrier mapping (gateway-side)

The 64 values are in LLTF hardware buffer order: entries 0–31 map to
subcarriers 0…+31, entries 32–63 map to −32…−1. Usable data subcarriers are
−26…−1 and +1…+26 (**52 values**); DC (entry 0) and the guard band
(±27…±32) are null and must be dropped by the gateway. 52 amplitudes yield
the 51 D-CFR differentials used by the proposed pipeline. The first two
entries of the raw buffer are additionally hardware-invalid
(`first_word_invalid`) — they land in the null region, but never interpret
them.

### Known signal caveats

- **No CSI for 802.11b frames.** DSSS/CCK frames carry no OFDM training
  field, so `csi_cb_count < pkts_seen` in STAT lines is expected, not a bug.
- **AGC.** Amplitudes are post-automatic-gain-control, so absolute scale
  varies per packet. The gateway's CSI normalization and the shape-based
  D-CFR/Pearson comparison make this acceptable.

## Serial bandwidth

An amplitude line is ~320 bytes ⇒ ~3200 bits on the wire:

| Baud | Max CSI lines/s |
|---|---|
| 115200 | ~36 |
| 460800 | ~144 |
| 921600 | ~288 |

A busy classroom channel carries 100–300 sniffable frames/s, so 921600 is
the default. If the queue still overflows, `dropped` in STAT lines counts
the loss (drop-and-count, never blocking the radio).

## UDP mode constraint

Enabling `ANCHOR_UDP_ENABLE` associates the anchor to an AP as a station,
which **locks the radio to the AP's channel** — the fixed-channel setting is
ignored and the target is only observable on the AP's channel. Practical
recipe: pin the laptop/phone hotspot to a known 2.4 GHz channel and connect
the target device to that hotspot, so sniff, backhaul, and target channels
coincide. Serial output stays active in UDP mode. Test with:

```sh
nc -ul 5555
```

## Gateway logger

```sh
cd firmware/tools
pip install -r requirements.txt
python gateway_logger.py --port /dev/cu.usbserial-0001:A1 \
                         --port /dev/cu.usbserial-0002:A2 \
                         --port /dev/cu.usbserial-0003:A3 \
                         --port /dev/cu.usbserial-0004:A4
```

Writes `data/<anchor>_<timestamp>.csv` with two host columns prepended
(`host_iso`, `host_ns`) and prints per-anchor line rates every 5 s.

## Verification checklist

1. **Boot:** after flashing, `idf.py monitor` shows a short banner, then
   continuous `CSI,...` lines and a `STAT` line every 5 s.
2. **Hand-wave test:** put a transmitting device ~1 m from the anchor, log
   30 s, plot one MAC's amplitudes over time. Waving a hand between device
   and anchor must visibly perturb mid-band subcarriers; guard entries stay ~0.
3. **Rate test:** from the laptop, `ping -i 0.05 <target-phone-ip>` (phone on
   the sniffed channel, screen on) ⇒ ~20 CSI lines/s from the target MAC and
   `dropped=0` in STAT.
4. **Multi-anchor:** run the logger on all four ports for 5 min; all four
   files contain the target MAC and RSSI ordering roughly matches geometry
   (nearest anchor strongest).
5. **Long-run:** past ~72 min `timestamp_us` wraps — confirm downstream
   processing relies on the host timestamps.

## Generating target traffic for trials

The thesis target is non-cooperative, but controlled trials need packets:

- **Simplest:** a phone on a hotspot pinned to the sniff channel, with the
  laptop running `ping -i 0.05 <phone-ip>` (or the phone streaming media)
  ⇒ steady, repeatable frames from a known MAC.
- **Optional:** a 5th ESP32 sending a small UDP datagram every 50 ms gives a
  fully controllable packet rate for fingerprint/radio-map collection (not
  included yet; easy follow-up).
