# Wireless capture runbook

Step-by-step, from a powered-off MP700 to a verified Capture over the wireless
chain:

```
Anchor A1..A4 ──ESP-NOW (ch 11)──▶ Relay ──WiFi UDP──▶ MP700 ──▶ Gateway laptop (make listen)
```

Do the steps in order. Each step ends in a **✅ Checkpoint**. Don't move on
until it passes: every later hop depends on the earlier ones, and a failure
further down the chain usually looks the same as silence. If a checkpoint
fails, go to [Troubleshooting](#troubleshooting).

Terms (Anchor, Relay, Gateway, Trial network, Capture, Beacon) are defined in
[`CONTEXT.md`](../CONTEXT.md).

## 0. What to bring

- TP-Link MP700 pocket WiFi + charger (the trial network)
- Relay ESP32 and 1–4 Anchor ESP32s, labelled `A1`..`A4`, plus a note of
  which board is the Relay
- USB **data** cables (charge-only cables flash nothing), power banks for the
  Anchors
- The Gateway laptop
- A target that transmits: a phone (see step 7) or a Beacon ESP32

## 1. Laptop, one time

1. Install the tools in the root [`README.md`](../README.md#tool-install)
   (`uv`, `make`, Arduino IDE + **esp32 by Espressif Systems** 3.x).
2. `make setup`, then `make test`. All tests must pass.
3. Arduino IDE: **Tools → Board → ESP32 Dev Module**, **Upload Speed 115200**.
   921600 fails on the team's CH340 boards.
4. Plug in one ESP32. A serial port must appear (`/dev/cu.usbserial-*` on
   macOS, `COMx` on Windows). If none appears, install the CH340 or CP2102
   driver, or swap the cable.

✅ **Checkpoint:** `make test` passes and the board shows up as a port.

## 2. Set up the MP700 (trial network)

Power it on and join its WiFi from the laptop. Open the admin page at
`http://192.168.0.1`. Settings are under the wireless / advanced sections;
menu names vary by firmware version.

| Setting | Value | Why |
|---|---|---|
| 2.4 GHz band | **On** (5 GHz may stay on, but the Relay only joins 2.4 GHz) | ESP32 is 2.4 GHz only |
| 2.4 GHz channel | **11, fixed. Not Auto** | Anchors sniff and send ESP-NOW on a hard-coded `WIFI_CHANNEL 11`; the Relay follows the MP700's channel |
| Channel width | 20 MHz, if offered | Matches the Anchors (`WIFI_SECOND_CHAN_NONE`) |
| SSID / password | `TP-Link_40F1` / as in `relay.ino` | Must match `WIFI_SSID` / `WIFI_PASSWORD` |
| AP isolation / client isolation | **Off**, if the option exists | When on, the Relay's UDP can't reach the laptop. This failure is silent |
| DHCP pool | Must **not** hand out `192.168.0.197`, or reserve .197 for the laptop | The laptop uses that address statically |

Write down the MP700's 2.4 GHz MAC. It belongs in the Anchors' `ignore_macs`
(currently `8c:90:2d:19:40:f1`).

✅ **Checkpoint:** a phone WiFi-analyzer app shows `TP-Link_40F1` on
**channel 11**.

## 3. Put the laptop on the trial network

1. Join `TP-Link_40F1`.
2. Set IPv4 manually to `192.168.0.197`, mask `255.255.255.0`, router
   `192.168.0.1`.
   - macOS: System Settings → Wi-Fi → (i) Details → TCP/IP → Configure IPv4:
     Manually.
   - Windows: Settings → Network → Wi-Fi → `TP-Link_40F1` properties → IP
     assignment → Edit → Manual.
3. **Disconnect any VPN.** A work VPN can capture the 192.168.0.0/24 route.
   Unplug Ethernet or other networks that also use 192.168.0.x.
4. Firewall:
   - macOS: allow incoming connections for Python when prompted. If you
     declined earlier, fix it in System Settings → Network → Firewall →
     Options.
   - Windows: set the network profile to **Private** and allow Python on
     Private networks. Windows blocks inbound UDP on Public networks.

✅ **Checkpoint:**
- `ping 192.168.0.1` replies.
- `ipconfig getifaddr en0` (macOS) or `ipconfig` (Windows) shows
  `192.168.0.197`.

## 4. Flash the Relay

1. Open `firmware/relay/relay.ino`. Check its CONFIG block: `WIFI_SSID`,
   `WIFI_PASSWORD`, `GATEWAY_IP "192.168.0.197"`, `GATEWAY_PORT 5555`.
2. Upload. If `Connecting...` stalls, hold **BOOT**. Copy the `MAC: xx:xx:…`
   line from the upload log. That is the Relay's MAC, needed in step 6.
3. Open Serial Monitor at **115200** and press **EN/RST**. Expected:

   ```
   INFO,relay_mac=20:E7:C8:AD:96:68
   INFO,wifi_connecting,ssid=TP-Link_40F1,status=…     (a few, once a second)
   INFO,wifi_connected,ip=192.168.0.x,channel=11,gateway=192.168.0.197:5555
   HEARTBEAT,2000,rx=0,ch=11,wifi=1                     (every 2 s)
   ```

4. **Close the Serial Monitor.** A port can only be held by one program, and
   the Relay can stay on USB power.

✅ **Checkpoint:** `wifi_connected` appears and `channel=11`. Any other
channel means the MP700 isn't fixed to 11, and ESP-NOW from the Anchors will
never arrive.

## 5. Check Relay → laptop **before** adding Anchors

```sh
make listen              # Windows: uv run python scripts/relay_udp_listener.py --outdir data
```

A status line prints every 5 s, even when nothing arrives:

```
[relay_udp_listener] lines=0 heartbeats=3 skipped=0 last_sender=192.168.0.x
```

✅ **Checkpoint:** `heartbeats` climbs by about 2–3 every 5 s, and
`last_sender` is the Relay's IP. `lines=0` is expected because no Anchors
are running yet.

❌ **`heartbeats=0`, `last_sender=none yet`:** the Relay's packets don't
reach this laptop. Fix this before going further. See
[Listener silent](#listener-silent-lines0-heartbeats0).

Leave `make listen` running from here on.

## 6. Flash each Anchor

1. Open `firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino`. Edit
   the CONFIG block:
   - `ANCHOR_ID`: `"A1"`..`"A4"`, a different value per board.
   - `WIFI_CHANNEL`: `11`, the same as the Relay's `channel=` in step 4.
   - `relay_mac`: the Relay MAC from step 4, as hex bytes. For
     `20:e7:c8:ad:96:68`, write
     `{0x20, 0xe7, 0xc8, 0xad, 0x96, 0x68}`.
   - `ignore_macs`: the MP700's MAC from step 2.
2. Upload, then Serial Monitor at 115200 and press **EN/RST**. Expected:

   ```
   INFO,A1,channel=11,esp_now_mode=ready,anchor_mac=…,relay_mac=20:e7:c8:ad:96:68
   STATUS,A1,csi=0,sent_ok=0,sent_fail=0,dropped=0,ch=11      (every 5 s)
   ```

   Any `ERROR,…` line means setup failed. Read it before going on.
3. Check that `relay_mac` in the banner matches step 4 exactly.

✅ **Checkpoint:** the banner shows the right `relay_mac` and `ch=11`, with no
`ERROR` lines. `csi=0` is normal here. The Anchor drops the Relay's and the
MP700's own frames, so with no target transmitting there is nothing to
forward. **This is why the listener can show `lines=0` even when everything
works.**

## 7. Start a target

The Anchors only forward frames from transmitters that aren't on the ignore
list. Something has to be transmitting on channel 11:

- **Phone:**
  - Join `TP-Link_40F1` with MAC randomization **off** for that network.
    - iPhone: Wi-Fi → (i) → Private Wi-Fi Address off.
    - Android: Wi-Fi → network → Privacy → Use device MAC.
  - Then stream video, or from the laptop run `ping -i 0.05 <phone-ip>`.
    The phone's IP is in the MP700 client list.
- **Beacon ESP32:** power it and confirm it is set to channel 11.

✅ **Checkpoint:** all three hops move together:

| Where | What climbs |
|---|---|
| Anchor Serial Monitor | `csi` and `sent_ok`; `sent_fail` stays ~0 |
| Relay heartbeat (in `make listen` it shows as a climbing `heartbeats`) | `rx` (visible on the Relay's Serial Monitor if it's open) |
| `make listen` | prints `new anchor A1 -> data/A1_<ts>.csv`, then `lines` climbs |

Close each Anchor's Serial Monitor once it checks out.

## 8. Verify the Capture

```sh
make dashboard ANCHOR=A1      # live CSI heatmap, RSSI trace, frames per source MAC
```

Which MACs did the Anchor hear?

```sh
tail -n +2 data/A1_*.csv | awk -F'"' '{print $2}' | cut -d, -f4 | sort | uniq -c | sort -rn
```

✅ **Checkpoint:** the target's MAC dominates. The Relay's and the MP700's
MACs are absent, because the firmware filter drops them.

## 9. Scale to all four Anchors

Repeat step 6 for each board with its own `ANCHOR_ID`. Place them, power
them from power banks, and restart `make listen` so all files share one
session timestamp.

✅ **Checkpoint:** `make listen` prints `new anchor A1`..`A4`, and
`data/A1_<ts>.csv`..`data/A4_<ts>.csv` all grow. The Anchor nearest the
target should have the strongest RSSI.

## 10. After the trial

1. Ctrl-C `make listen`. Files are closed on exit.
2. Copy `data/` somewhere safe. It is git-ignored.
3. Write a journal entry (`journal/YYYYMMDD.md`, format in
   [`journal/README.md`](../journal/README.md)). Include the board MACs,
   channel, layout, and anything that broke.

## Troubleshooting

Find the first hop that doesn't behave. Everything after it will look dead
too.

### Listener silent (`lines=0`, `heartbeats=0`)

Nothing reaches the laptop's UDP socket. Go down this list in order:

1. **Is the Relay connected?** Open its Serial Monitor.
   - Stuck on `wifi_connecting`: see
     [Relay stuck connecting](#relay-stuck-on-wifi_connecting).
   - Connected: it prints `HEARTBEAT` lines.
2. **Is the laptop really at `192.168.0.197`?** Check with
   `ipconfig getifaddr en0`. DHCP may have given it another address, or
   another device may already hold .197.
3. **Is a VPN on?** Disconnect it.
4. **Firewall:** macOS, allow Python. Windows, use a Private profile and
   allow Python.
5. **AP/client isolation on the MP700:** turn it off.
6. **Wrong port or listener:** the Relay sends to `GATEWAY_PORT` (5555), and
   `make listen` binds 5555. Only one listener can hold the port.
7. **Independent check:** stop `make listen` and run `nc -ul 5555`.
   `HEARTBEAT` lines should scroll. If they appear here but not in the
   listener, something else is holding the port.

### Heartbeats arrive but `lines=0`

The Relay → laptop link works. The problem is upstream:

| Anchor `STATUS` shows | Meaning | Fix |
|---|---|---|
| `csi=0` | Nothing transmitting on ch 11 that isn't on the ignore list | Start a target (step 7). Check the target is on the MP700, which is on ch 11 |
| `csi` climbs, `sent_fail` climbs, `sent_ok=0` | The Relay isn't acking | `relay_mac` ≠ the Relay's MAC, or the Relay's `channel` ≠ `WIFI_CHANNEL`. Compare the banner with step 4 |
| `csi` and `sent_ok` climb, but the Relay's `rx` stays 0 | Frames are acked by some other device with that MAC, or the Relay rebooted | Re-read `relay_mac` from the Relay's boot banner. Power-cycle the Relay |
| Relay `rx` climbs, `lines` stays 0 | Records arrive, but their size doesn't match | Relay and Anchor were built from different `esp_now_csi_t` versions. Reflash both from the same commit |
| `dropped` climbs | Anchor queue full: more traffic than ESP-NOW can carry | Expected on a very busy channel. Reduce traffic or filter to the target |
| No `STATUS` line at all | Old Anchor firmware, or the board crashed | Reflash. Watch for a reboot loop on the Serial Monitor |

### Relay stuck on `wifi_connecting`

- `status=1` (no SSID available): the MP700 is off, out of range, or 2.4 GHz
  is disabled, or `WIFI_SSID` has a typo.
- `status=4` (connect failed) or `status=6` (disconnected): usually a wrong
  `WIFI_PASSWORD`.
- MP700 client limit reached: disconnect a device.

### Relay reports `channel` ≠ 11

The MP700 isn't fixed to channel 11, or it reverted to Auto after a reset.
Fix it in step 2. Alternatively, set every Anchor's `WIFI_CHANNEL` to match,
but then the target must be on that channel too.

### Capture holds only the Relay's or the MP700's MAC

The Anchor is running firmware older than the ignore filter, or `relay_mac`
or `ignore_macs` don't match the real MACs. Reflash with the right values.

### Garbled Serial Monitor or flash fails at `Unable to verify flash chip connection`

The baud is 921600. Use 115200 for both Upload Speed and the Serial Monitor.
