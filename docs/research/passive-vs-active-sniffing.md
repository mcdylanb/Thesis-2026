# Passive vs. active sniffing: what we run now, and should we go active?

_Researched 2026-10-02. Primary sources only: the firmware in this repo
(file:line), ESP-IDF headers/docs and Espressif-staff-answered GitHub issues,
IEEE 802.11 power-save behaviour as described by vendor/standard references,
and the original papers (Abedi & Abari HotNets '20; Vanhoef et al. AsiaCCS
'16). Text marked **[Inference]** is my reasoning from those sources, not a
direct quote; **[Verify]** marks a claim to confirm on our hardware._

This note answers the user's question directly and then backs it with
sources. For the deeper feasibility study of elicitation on ESP32 (attribution,
rates, blockers), see the companion note
[active-elicitation-unassociated-devices.md](active-elicitation-unassociated-devices.md);
this note does not repeat that detail.

## Short answer

**We are 100% passive today.** Every Anchor firmware variant only puts the
radio into promiscuous (listen-only) mode plus the CSI callback, and
transmits nothing toward the target. The only frames any Anchor transmits are
ESP-NOW backhaul packets to the Relay, which is our own plumbing, not
elicitation of the target. So capture depends entirely on the target choosing
to transmit on our channel — the user's "window" worry is real and correct.

## 1. What the codebase currently does

**Passive promiscuous capture, no target-directed TX.** All three Anchor
trees are listen-only:

- ESP-IDF tree: `esp_wifi_set_promiscuous(true)` with a MGMT|DATA filter and
  a CSI RX callback; the promiscuous callback body only counts frames
  ([firmware/anchor/main/sniffer.c:64-91](../../firmware/anchor/main/sniffer.c);
  filter default `WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA`
  at [anchor_config.h:17](../../firmware/anchor/main/anchor_config.h)).
- Arduino serial/UDP tree: same pattern — `FILTER_MASK = MGMT|DATA`,
  `esp_wifi_set_promiscuous(true)`, CSI callback
  ([firmware/anchor_arduino/anchor_arduino.ino:37,213-241](../../firmware/anchor_arduino/anchor_arduino.ino)).
- Arduino ESP-NOW/wireless tree: identical, and its promiscuous callback is
  an explicit no-op — _"keeping promiscuous active to satisfy radio
  requirements"_
  ([anchor_arduino_wireless.ino:23,56-58,114-134](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino)).

**No elicitation primitives anywhere.** A repo-wide grep finds no
`esp_wifi_80211_tx`, no `esp_wifi_internal_set_fix_rate`, no probe/null-frame
injection, and no RTS/CTS crafting in any firmware tree. The single transmit
call in the whole firmware is `esp_now_send(relay_mac, ...)` — the Anchor
forwarding its captured record to the Relay over the backhaul
([anchor_arduino_wireless.ino:87](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino)),
not a frame aimed at the target.

**ACK-based capture is off.** `dump_ack_en = false` in every tree
([sniffer.c:87](../../firmware/anchor/main/sniffer.c),
[anchor_arduino.ino:238](../../firmware/anchor_arduino/anchor_arduino.ino),
[anchor_arduino_wireless.ino:131](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino)),
and control frames (ACK/CTS/RTS) are filtered out because the filter is
MGMT|DATA only (same lines as above). So even the one "free" response frame a
device emits (an ACK) is neither captured nor CSI-dumped today.

**Fixed single channel.** Anchors sniff one channel for the whole session
(hardcoded `WIFI_CHANNEL`/`ANCHOR_CHANNEL`, or the AP's channel in STA mode)
([anchor_arduino.ino:33,44-45](../../firmware/anchor_arduino/anchor_arduino.ino),
[sniffer.c:94-96](../../firmware/anchor/main/sniffer.c)). Open issue #13
("Anchor channel hopping to discover hidden IoT devices on unknown channels")
records that this means we can only detect a device whose channel is already
known, and that the ESP-NOW backhaul shares that channel so hopping is not
free ([gh issue #13](https://github.com/mcdylanb/Thesis-2026/issues/13)).

**The whole stack is framed "passive."** CONTEXT.md:
_"Passive WiFi localization system... ESP32 Anchors capture RSSI and CSI from
nearby transmitters"_ and defines an Anchor as _"An ESP32 that passively
sniffs 802.11 frames on a fixed channel"_
([CONTEXT.md:3-4,12](../../CONTEXT.md)); README.md repeats it
([README.md:3-4](../../README.md)).

**The simulator bakes in the transmit-on-its-own assumption.** The sim has no
elicitation — it models each device emitting on its own schedule: `steady`
(beacon-like fixed `rate_hz`, default 20 Hz) or `sporadic` ("ambient IoT:
Poisson bursts") ([gateway/sim.py:33,361-377](../../gateway/sim.py);
[layouts/techhub_default.yaml:61-91](../../layouts/techhub_default.yaml) has an
ambient device at `rate_hz: 0.1`, i.e. one packet every ~10 s on average).
Evaluation requires _">= 30 windows each"_ per test position
([sim.py:44](../../gateway/sim.py)) — which only accrues if the target keeps
transmitting. This is exactly the dependency the user is worried about.

**Relevant open issues:** #13 (channel hopping, above); #30 (Beacon firmware)
— note our *calibration/test target is itself an active beacon* we build and
control ([CONTEXT.md:29-30](../../CONTEXT.md)), so the window problem is hidden
during calibration and only bites against a real uncooperative device. No
issue proposes active elicitation of the target.

## 2. Is the "window" concern valid? (Yes.)

A passive mesh captures a device only when that device transmits on our
channel. An idle IoT device or a phone in power save transmits rarely:

- **Power-save stations sleep between beacons.** In 802.11 power-save mode a
  station enters the Doze state and only wakes for selected beacons chosen by
  its **Listen Interval** (the number of beacon intervals it skips before
  waking); a longer listen interval saves more power but adds delay
  ([Nordic Developer Academy, Wi-Fi power-save modes](https://academy.nordicsemi.com/courses/wi-fi-fundamentals/lessons/lesson-6-wifi-fundamentals/topic/power-save-modes-2/)).
  Downlink for a sleeping STA is buffered at the AP and released on a **DTIM**
  beacon (DTIM period = N beacon intervals)
  ([USPTO 8005032, DTIM period description](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8005032)).
  **[Inference]** An idle associated STA with nothing to send may emit nothing
  but an occasional PS-Poll/null frame and whatever keep-alive its OS runs —
  seconds apart, not the 20 Hz the sim assumes.
- **TWT makes the gap much worse.** 802.11ax Target Wake Time lets a STA
  _"sleep for some intervals and wake up at a Target Wake Time"_, and is
  _"most beneficial for IoT devices, such as sensors and actuators"_; wake
  intervals are set by exponent/mantissa and can reach **minutes** (the cited
  worked example configures a 15-minute wake interval)
  ([ST wiki, Wi-Fi 6 TWT](https://wiki.st.com/stm32mcu/wiki/Connectivity:Wi-Fi6_Target_Wake_Time_(TWT));
  [NXP AN14111, TWT on FreeRTOS](https://www.nxp.com/docs/en/application-note/AN14111.pdf)).
  A TWT device can be silent for minutes — a passive window may never fill.
- **An unassociated/scanning device is on our channel only briefly.** A
  scanning STA sends probe-request bursts seconds-to-tens-of-seconds apart and
  dwells only ~20 ms per channel, and those probes are usually DSSS (1 Mbps)
  broadcast with a randomized MAC — RSSI but effectively **no CSI** on ESP32
  ([Vanhoef et al., AsiaCCS '16](https://papers.mathyvanhoef.com/asiaccs2016.pdf);
  our own "No CSI for 802.11b frames" note,
  [firmware/README.md](../../firmware/README.md)).

So the user's fear is well founded: with passive-only capture, a device in
power save / TWT / scanning can starve the pipeline of windows, and for a
scanning device the frames we *do* catch carry no CSI.

## 3. Would active sniffing fix it? (Partly — it has its own ceiling.)

**The mechanism exists and runs on our exact hardware.** "Polite WiFi"
(Abedi & Abari): send a fake unicast null-data (or RTS) frame to the target's
MAC and the PHY returns an ACK (or CTS) within one SIFS — even unassociated,
unencrypted, no key — because the ACK must go out in **10 µs (2.4 GHz)**,
far too little time to validate the frame. Tested on 5,328 devices from 186
vendors, **all** responded; they implemented it **on an ESP32** precisely
because the ESP32 can read CSI at the **legacy OFDM bitrates ACKs use**
([Abedi & Abari, HotNets '20](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf)).
That converts "wait for the device's window" into "poll it at ~150 frames/s",
removing the rate dependency for an on-channel device.

**On ESP32 specifically:** `esp_wifi_80211_tx` can send non-QoS data (incl.
null) frames once promiscuous/started
([ESP-IDF esp_wifi ref](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/network/esp_wifi.html));
CSI from ACKs is available via `dump_ack_en` on classic ESP32/C3/S3/C5
([esp-idf #19062](https://github.com/espressif/esp-idf/issues/19062)); a
sender can capture ACKs to its own TX in promiscuous mode after an Espressif
fix ([esp-idf #8469](https://github.com/espressif/esp-idf/issues/8469)); raw
TX is restricted and injects its own RTS unless suppressed via undocumented
internal APIs ([esp-idf #10668](https://github.com/espressif/esp-idf/issues/10668)).

**But active probing has its own limits:**

1. **A sleeping radio cannot ACK while dozing.** Polite WiFi elicits a reply
   only from a device that is *awake and on our channel*. A STA in deep power
   save or a TWT sleep window has its receiver off, so our frame is neither
   heard nor acknowledged until its next wake — the same minutes-long gaps
   from §2 reappear as "ACK only during wake windows."
   **[Inference]** Active probing collapses the *within-wake* starvation (idle
   but awake devices) but does not defeat genuine sleep scheduling.
2. **Channel.** The target must be parked on our channel; a hopping/scanning
   device is reachable only in its brief dwell (ties to issue #13).
3. **Multi-anchor attribution is unproven.** The ACK is addressed back to the
   *transmitting* node, not the target, so the transmitter attributes its
   reply trivially but the *other* anchors must pair "frame to T at t" with
   "ACK at t+~10 µs" by `rx_ctrl.timestamp` — the single biggest open risk
   (**[Verify]**; see the companion note's §3 and experiment plan).
4. **It breaks the "passive" framing** and raises an ethics/consent step
   before probing any non-consenting device (one line, per instruction).

## 3a. Is active capture doable on ESP32? (Partly — yes for the single-node CSI case, unproven for the mesh.)

**Our hardware is classic ESP32.** The repo targets the classic ESP32
(NodeMCU / "ESP32 Dev Module"), not S3 or a C-series part:
[firmware/anchor/CMakeLists.txt:1](../../firmware/anchor/CMakeLists.txt)
("classic ESP32"), [sdkconfig.defaults:1](../../firmware/anchor/sdkconfig.defaults)
("target: esp32 (classic)"), [firmware/README.md:70](../../firmware/README.md)
("Classic ESP32 NodeMCU dev boards"), ESP-IDF v5.4 / arduino-esp32 core 3.x
([README.md:40](../../README.md)). This matters because CSI and raw-TX support
differ by variant — and the classic ESP32 is the one Abedi & Abari used and the
one #19062 confirms works.

- **`esp_wifi_80211_tx` frame-type restriction.** It "can be used to send
  beacon, probe request, probe response, action frames, and non-QoS data
  frames... cannot be used for sending encrypted or QoS frames," and requires
  `esp_wifi_set_promiscuous(true)` or `esp_wifi_start()` to have returned OK
  first ([ESP-IDF esp_wifi ref](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/network/esp_wifi.html)).
  A **null-data frame** (non-QoS, unencrypted) — the Polite WiFi eliciting
  frame — is inside that allowed set. **Caveat:** Espressif narrowed raw TX and
  a single call may inject its own RTS; staff point to undocumented internal
  APIs (`esp_wifi_internal_set_rts`) to suppress it
  ([esp-idf #10668](https://github.com/espressif/esp-idf/issues/10668)).
  **[Verify]** these survive our IDF v5.4 / core 3.x.
- **Can it send to an unassociated MAC?** Yes — the frame type is unrestricted
  as to destination, and the whole point of Polite WiFi is that the *target*
  need not be associated with us: the PHY ACKs any frame whose destination
  matches its MAC, no key, within one SIFS, demonstrated across 5,328 devices
  on an ESP32 ([Abedi & Abari](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf)).
- **Is CSI reported for the reply (ACK)?** Yes on classic ESP32: enable legacy
  CSI plus `dump_ack_en` and the CSI callback fires for ACK frames; the
  reporter confirms it works on ESP32/C3/S3/C5 and is broken only on **C6**
  ([esp-idf #19062](https://github.com/espressif/esp-idf/issues/19062)). ACKs
  ride legacy OFDM bitrates, which is exactly what the ESP32 CSI engine reads
  ([Abedi & Abari](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf)). A
  sender can also *see* the ACK to its own TX in promiscuous mode after an
  Espressif fix ([esp-idf #8469](https://github.com/espressif/esp-idf/issues/8469)).
- **The unresolved part — CSI at a third-party anchor.** `dump_ack_en` is
  documented for ACKs *addressed to the station*. Whether a *different* anchor
  that merely overhears an ACK (RA != that anchor) gets a **CSI** callback (not
  just a promiscuous one) is undocumented — **[Verify]**. This is the hinge
  between "active CSI works at one node" (proven) and "active CSI works across
  the mesh" (unproven); see the companion note's experiment step 3b.

**Verdict:** single-node active CSI (one ESP32 pings a MAC, reads the ACK's
CSI) is **doable and demonstrated on our exact chip**. Multi-anchor active CSI
is **partly** doable — frames and RSSI will be seen; per-anchor CSI of an
overheard ACK and reliable timing attribution are the open risks.

## 3b. What would change in this setup?

Concrete change list against the current repo. Scope note: all three firmware
trees are listen-only today (§1); the one most worth changing first is the
Arduino ESP-NOW tree we actually deploy
([anchor_arduino_wireless.ino](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino)).

**Firmware (the proven single-node path first):**
- **Capture filter + ACK CSI.** Flip `dump_ack_en = false` -> `true` and widen
  the filter from `MGMT|DATA` to include `WIFI_PROMIS_FILTER_MASK_CTRL` (with
  the ACK/CTS control sub-filters) so reply frames are captured:
  [anchor_arduino_wireless.ino:23,131](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino)
  (mirror in [anchor_arduino.ino:37,238](../../firmware/anchor_arduino/anchor_arduino.ino),
  [sniffer.c:64,87](../../firmware/anchor/main/sniffer.c) /
  [anchor_config.h:17](../../firmware/anchor/main/anchor_config.h)).
- **TX path (new).** Add an `esp_wifi_80211_tx` null-data sender to a target
  MAC, with TX rate forced to legacy OFDM 6 Mbps
  (`esp_wifi_internal_set_fix_rate` / `esp_wifi_config_80211_tx_rate`) and
  auto-RTS suppressed (`esp_wifi_internal_set_rts`, #10668). The target MAC
  must be configurable (new `target_mac` alongside the existing
  `ignore_macs`/`relay_mac` config block,
  [anchor_arduino_wireless.ino](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino)).
- **MAC matching.** The CSI callback already drops ignored MACs
  ([anchor_arduino_wireless.ino:62](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino));
  add target-MAC matching, noting an ACK is addressed back to the *sender*, so
  at the transmitting node the match is by "I just TX'd to T", and at other
  anchors by SIFS timing on `rx_ctrl.timestamp` (**[Verify]**).
- **Injector topology.** **[Inference]** Prefer *one dedicated injector* node
  rather than every Anchor injecting: the ESP32 is half-duplex and the four
  Anchors should stay pure receivers of the ACK the injector provokes
  (cleaner CSI, no mutual interference, simpler scheduling). This reuses the
  "5th ESP32" idea already floated in [firmware/README.md:252](../../firmware/README.md).
- **Channel locking / scheduling.** The target must be parked on the sniff
  channel; this collides with the ESP-NOW backhaul sharing that channel and
  with issue #13's hopping. Injection rate ~100-150/s from the single injector
  (no cross-Anchor TX scheduling needed if only one node injects).

**Serial / data format.** The line format
`CSI,<anchor>,<seq>,<mac>,<rssi>,<sig_mode>,<channel>,<timestamp_us>,<n_sub>,...`
([anchor_arduino/anchor_arduino.ino:18](../../firmware/anchor_arduino/anchor_arduino.ino),
[csv_out.c:45](../../firmware/anchor/main/csv_out.c)) already carries
`sig_mode` and `timestamp_us`, so ACK CSI fits the existing schema — but add a
field (or reuse `sig_mode`/a flag) to mark **elicited vs. ambient** frames so
the pipeline can tell them apart; the parser fixes `CSI_HEADER_FIELDS = 9`
([gateway/parser.py:26](../../gateway/parser.py)) and would need a bump if a
field is added.

**Python pipeline / simulator.**
- The simulator has **no elicitation model** — devices transmit on their own
  `steady`/`sporadic` schedule ([gateway/sim.py:361-377](../../gateway/sim.py),
  [layouts/techhub_default.yaml:61-91](../../layouts/techhub_default.yaml)). To
  evaluate active mode, add an "elicited" device whose effective rate is the
  injector rate (not the device's own), and relax the ">= 30 windows"
  dependency ([sim.py:44](../../gateway/sim.py)).
- The **stability score** and **RSSI-floor flag** feed off per-window CSI
  spectra ([gateway/features.py:39-40](../../gateway/features.py),
  `dcfr_stability`); ACK CSI (short legacy frames) may have different
  stability characteristics, so the `DEFAULT_RSSI_FLOOR_DBM = -80`
  ([features.py:15](../../gateway/features.py)) and stability thresholds should
  be re-characterized on elicited data, not assumed from ambient.

**CONTEXT.md terms.** The glossary defines the system as "Passive WiFi
localization" and an Anchor as one that "passively sniffs"
([CONTEXT.md:3-4,12](../../CONTEXT.md)). Active/hybrid mode needs new terms
(e.g. **Injector**, **elicited capture**) and a reworded Anchor definition.

**Is an ADR warranted? Yes.** This changes a core architectural stance
(passive -> hybrid), is hard to reverse quietly, and interacts with the
undecided channel-hopping design (#13) — the repo already flags #13 as "a
candidate for an ADR." An ADR should record the passive-default + rate-gated-
active decision, the injector topology, and the channel/backhaul tradeoff.

**Effort estimate (classic ESP32, single-node CSI first):**
- Firmware filter + `dump_ack_en` + null-data TX + fix-rate/RTS-suppress:
  ~1-2 days coding, **plus** hardware bring-up to confirm #10668 internal APIs
  and that a forced-OFDM ACK carries CSI (the companion note's steps 1-2).
- Python elicited-device sim + flag plumbing + parser field: ~1 day.
- Multi-anchor CSI attribution (step 3b): **this is research, not an estimate**
  — gate the thesis's CSI-from-elicitation claim on that experiment.

**Risks:** (1) third-party-anchor CSI for overheard ACKs may not fire —
collapses mesh active mode to RSSI-only (= Ju et al.'s result); (2) undocumented
RTS/fix-rate internal APIs may break on our IDF/core; (3) some target vendors
may reply at DSSS, yielding no CSI; (4) channel-parking vs. backhaul/#13
conflict; (5) sleeping/TWT devices still unreachable (§3); (6) ethics/consent
before probing non-consenting devices.

## 4. Recommendation

**Go hybrid, not fully active — and gate it on observed frame rate.** Keep the
passive mesh as the default and primary path (it needs no TX, preserves the
thesis framing, and already works for our active Beacon target and for chatty
associated devices). Add an **active-probe mode** that triggers only when a
tracked MAC's passive frame rate falls below a threshold (e.g. < a few
frames/s over the current window): one node then sends forced-OFDM null-data
to that MAC at ~100-150/s and captures the ACK's CSI, exactly reproducing
Abedi & Abari. This directly targets the user's "window" failure (idle-but-
awake devices) while leaving behaviour unchanged for devices that already
transmit enough. **[Inference]** It will *not* rescue a device in deep
sleep/TWT or off-channel — those need the §3 caveats and issue #13's hopping,
and should be stated as a known limit rather than solved by probing.

**Implementation cost in this firmware (first, single-node CSI, the proven
part):** enable control frames in the promiscuous filter and set
`dump_ack_en = true` (one line each, all three trees); add an
`esp_wifi_80211_tx` null-data sender to a target MAC with the TX rate forced
to legacy OFDM (6 Mbps) and the auto-RTS suppressed; add a gateway-driven
rate threshold to switch modes. **[Verify]** the internal RTS/fix-rate APIs on
our IDF/core (#10668) and whether forcing OFDM yields an OFDM, CSI-bearing ACK
across target vendors. The **multi-anchor** (mesh) CSI variant is a research
risk, not a config change — do the companion note's experiment (third-party
anchor must get CSI for an overheard ACK, step 3b) before committing the
thesis to CSI-from-elicitation across anchors.

## Claims I could not confirm against a primary source

- The concrete per-device idle transmit rate of a specific IoT camera/phone
  (seconds vs. minutes between frames) — vendor-dependent, **[Verify]** by
  measurement; the standard mechanisms above only bound it.
- Whether a *third-party* anchor's **CSI callback** (not just its promiscuous
  callback) fires for an ACK it merely overhears (RA != that anchor) — not
  documented; `dump_ack_en` is described for ACKs addressed to the station
  (**[Verify]**; carried over from the companion note).
- That a forced OFDM TX rate produces an OFDM (CSI-bearing) ACK on all target
  vendors (some may still reply at DSSS) — **[Verify]** on hardware.

## Sources

- Firmware (this repo): [anchor/main/sniffer.c](../../firmware/anchor/main/sniffer.c),
  [anchor/main/anchor_config.h](../../firmware/anchor/main/anchor_config.h),
  [anchor_arduino/anchor_arduino.ino](../../firmware/anchor_arduino/anchor_arduino.ino),
  [anchor_arduino_wireless/anchor_arduino_wireless.ino](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino),
  [firmware/README.md](../../firmware/README.md),
  [CONTEXT.md](../../CONTEXT.md), [README.md](../../README.md),
  [gateway/sim.py](../../gateway/sim.py),
  [layouts/techhub_default.yaml](../../layouts/techhub_default.yaml)
- GitHub issue #13 (channel hopping): https://github.com/mcdylanb/Thesis-2026/issues/13
- Abedi & Abari, "WiFi Says 'Hi!' Back to Strangers!" (Polite WiFi), HotNets '20: http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf
- Vanhoef et al., "Why MAC Address Randomization is not Enough," AsiaCCS '16: https://papers.mathyvanhoef.com/asiaccs2016.pdf
- Nordic Developer Academy, Wi-Fi power-save modes: https://academy.nordicsemi.com/courses/wi-fi-fundamentals/lessons/lesson-6-wifi-fundamentals/topic/power-save-modes-2/
- USPTO 8005032 (DTIM period / buffered traffic description): https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8005032
- ST wiki, Wi-Fi 6 Target Wake Time (TWT): https://wiki.st.com/stm32mcu/wiki/Connectivity:Wi-Fi6_Target_Wake_Time_(TWT)
- NXP AN14111, TWT on NXP platforms with FreeRTOS: https://www.nxp.com/docs/en/application-note/AN14111.pdf
- ESP-IDF esp_wifi API reference (esp_wifi_80211_tx allowed frames, fix-rate): https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/network/esp_wifi.html
- esp-idf issue #19062 (CSI from ACK via dump_ack_en): https://github.com/espressif/esp-idf/issues/19062
- esp-idf issue #8469 (promiscuous capture of own ACKs): https://github.com/espressif/esp-idf/issues/8469
- esp-idf issue #10668 (esp_wifi_80211_tx restrictions, auto-RTS suppression): https://github.com/espressif/esp-idf/issues/10668
- Companion note: [active-elicitation-unassociated-devices.md](active-elicitation-unassociated-devices.md)
