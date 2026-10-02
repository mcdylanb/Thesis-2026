# Can we actively elicit RSSI/CSI from an unassociated hidden device?

_Researched 2026-09-30 against primary sources only: the IEEE 802.11
timing rules as quoted in the Polite WiFi paper, Espressif ESP-IDF headers
and docs, Espressif-staff-answered GitHub issues, and the original papers
(Abedi & Abari HotNets '20, Ju et al. BDCC 2025, Sharma et al. USENIX Sec
'22, Vanhoef et al. AsiaCCS '16). Every claim cites a URL. Text marked
**[Inference]** is my reasoning from those sources, not something a source
states directly; **[Verify]** marks a claim that must be confirmed on our
hardware._

## Question (user's words)

> "my understanding we are to use the 'looking for a wifi' state of a hidden
> device to send out information from our sniffers to fetch rssi and csi,
> with that identifying an algorithm we should be able to identify an
> estimate of the hidden device."

Read as: the hidden IoT device is unassociated and scanning (sending 802.11
probe requests); the ESP32 anchors actively transmit frames that make the
device respond, so the anchors can capture RSSI + CSI from those responses
and feed the localization algorithm. Is this feasible on classic ESP32
(2.4 GHz, single antenna, ESP-IDF v5.4 / arduino-esp32 3.x)?

## Short verdict

**The idea is real and has direct precedent — but not in the shape the
sentence assumes, and it breaks the project's "passive" framing.**

- You **cannot get CSI from a scanning device's probe requests** on ESP32.
  In 2.4 GHz, probe requests are sent with DSSS (1 Mbps), which has no OFDM
  training field, so the ESP32 produces RSSI but no CSI for them (this is
  the same "no CSI for 802.11b frames" limit already in our firmware
  README). Probe requests are also usually broadcast, so they are not
  acknowledged, and modern devices randomize their MAC in them.
- **The mechanism that works is "Polite WiFi" (Abedi & Abari, HotNets '20):**
  send a fake unicast frame (null-data or RTS) to the target's MAC; every
  tested WiFi device replies with an ACK (or CTS) at the PHY layer within
  SIFS, even when it is not associated with you and you have no key. Abedi &
  Abari implemented exactly this **on an ESP32**, specifically because the
  ESP32 can measure CSI for the **legacy (OFDM) bitrates that ACKs use**.
  So "transmit to make it talk, then measure the CSI of its reply" is
  demonstrated on our exact hardware.
- **But this is active, not passive.** It requires the anchors (or a
  dedicated illuminator node) to transmit crafted frames — the opposite of
  the "passive sniffer mesh" the thesis repeatedly claims. Ju et al. 2025,
  the paper the thesis cites for hidden-IoT localization, is itself active
  (RTS/CTS) and gets **RSSI only, not CSI**, on an **Android phone, not an
  ESP32**.
- **Most promising ESP32 variant:** one node transmits null-data/RTS at a
  forced OFDM rate to the target MAC; the ACK/CTS comes back at a legacy
  OFDM rate and its CSI is measurable. The transmitting node attributes the
  reply trivially (it knows whom it addressed). Multi-anchor attribution of
  the *same* reply is the hard, unproven part — see §3 and the experiment.

## Findings

### 1. Behaviour of an unassociated scanning device

- **Scanning = bursts of probe requests.** "During each scan iteration,
  devices send an ordered burst of probe requests over a small timeframe."
  A device is only reliably "observed" after several are captured ("at least
  5 probe requests from its MAC address")
  ([Vanhoef et al., AsiaCCS '16](https://papers.mathyvanhoef.com/asiaccs2016.pdf)).
  Scan iterations are seconds-to-tens-of-seconds apart when idle (e.g.
  Android's default scan interval is ~15 s disassociated / 20 s associated;
  a STA dwells <~20 ms per channel during a scan)
  ([802.11 active-scan overview](https://www.purple.ai/en-us/guides/what-is-a-probe-request-understanding-how-devices-discover-networks)).
- **PHY rate — the decisive point for CSI.** "probe requests are generally
  sent at the most reliable encoding available, DSSS is used in the 2.4
  [GHz band]"; only in 5 GHz are they "always sent at a bitrate of 6 Mbps"
  ([Vanhoef et al.](https://papers.mathyvanhoef.com/asiaccs2016.pdf)). DSSS
  (1–2 Mbps, 802.11b) carries no OFDM LTF, and our own firmware already
  documents "No CSI for 802.11b frames"
  ([firmware/README.md](../../firmware/README.md)). **[Inference]** So on
  2.4 GHz a scanning device's probe requests yield RSSI but effectively no
  CSI on ESP32. Whether a given device disables 11b rates and probes at
  OFDM 6 Mbps is vendor-dependent and cannot be assumed.
- **MAC randomization.** "Even when MAC address randomization is enabled, we
  found that iOS, Linux, and Windows all use incremental sequence numbers in
  probe requests"; Windows also randomizes per-probe
  ([Vanhoef et al.](https://papers.mathyvanhoef.com/asiaccs2016.pdf)). The
  MAC in a probe request is therefore often not the device's real,
  persistent MAC — a problem for keying observations by MAC (which our
  gateway's `DeviceRegistry` does).
- **What unconfigured IoT devices do.** Not covered by a single primary
  source here; **[Inference]** an unconfigured smart plug/camera/ESP32 in
  SoftAP-setup mode typically *is* an AP (beacons/probe responses) rather
  than a scanning client, while a device whose saved network is absent
  oscillates between scanning (probe-request bursts) and, if associated to a
  present AP, sitting on that AP's channel. This matters because the target
  must be *parked on our channel* for any elicitation to work (§3).

### 2. Elicitation mechanisms and what the device sends back

#### 2a. Answer its probe request with a probe response

Broadcast probe requests are not individually acknowledged, so replying with
a unicast probe response does not force an ACK unless the request was
directed. **[Inference]** This path is weak: it depends on the device's scan
state and gives at most an occasional response, and a probe *response* is
something the *AP side* emits — capturing its CSI would characterize the
responder, not the scanning client. Not a reliable RSSI/CSI source for a
client target.

#### 2b. Polite WiFi — fake unicast frame → ACK/CTS (the workable one)

- "all existing WiFi devices send back acknowledgments (ACK) to even fake
  packets received from WiFi devices outside of their network... as long as
  the destination address matches their MAC address. The physical layer
  acknowledges all frames even those without any valid payload"
  ([Abedi & Abari, HotNets '20, "WiFi Says 'Hi!' Back to Strangers!"](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf)).
- Tested on **5,328 devices from 186 vendors** (1,523 clients, 3,805 APs);
  **all** responded. Espressif chipsets were among the client vendors (47
  devices) — i.e. ESP-class IoT devices exhibit the behaviour too
  ([Abedi & Abari](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf), §3, Table 2).
- The eliciting frame in their experiment: a **null data frame, no payload,
  unencrypted**, with only the destination (victim) MAC valid; the ACK is
  returned to the (fake) transmitter MAC
  ([Abedi & Abari](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf), §2).
- **RTS→CTS is the un-fixable variant.** "if an attacker sends fake RTS
  frames, the victim responds with CTS frames... RTS and CTS frames cannot
  be encrypted." Works on unassociated devices (they cite Wang et al. for
  RTS/CTS to unassociated devices)
  ([Abedi & Abari](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf), §2.2).
- **Why it's unpreventable:** "an ACK must be transmitted by the end of the
  Short Interframe Space (SIFS)... which is **10 µs and 16 µs for the 2.4
  GHz and 5 GHz bands**"; verifying the frame first would need decryption
  taking "200 to 700 µs," orders of magnitude longer than SIFS
  ([Abedi & Abari](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf), §2.2).
- **They measured CSI of the ACK on an ESP32.** "We have implemented the
  attacking mechanism on an ESP32 WiFi module... The attacker sends **150
  fake 802.11 frames per second** (null frames)... and measures the CSI of
  received ACK frames." And crucially: "We use ESP32 instead of the...
  Intel 5300 WiFi card because it enables us to measure the CSI for legacy
  802.11a/g bitrates. This is an important feature for us because **ACKs are
  transmitted using legacy bitrates** which do not work with the CSI tool."
  The attack "still works" even if the victim is "not connected to any WiFi
  network"
  ([Abedi & Abari](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf), §4.1).
- Reliability: their large-scale result is essentially 100% response across
  all 5,328 devices; the single-device sensing demo ran on one ESP32
  transmitter measuring its own ACKs (not a multi-receiver setup).

#### 2c. Advertise a known SSID (Karma / evil-twin) → auth/assoc

Feasibility only, per the user's instruction — **no method here.** Vanhoef
et al. note "the well-known Karma attack relied on the SSIDs that the victim
broadcasts in probe requests," and that responding to SSID-bearing probes
"has the potential to improve the number of affected devices"
([Vanhoef et al.](https://papers.mathyvanhoef.com/asiaccs2016.pdf)). So it is
technically possible to make a device that is probing for a remembered
network attempt association. **Ethical/legal caveat:** this impersonates a
network the device trusts and induces it to connect — it crosses from
observation into deception/interception, is likely unlawful without consent,
and contradicts the thesis's own scope exclusion of "Evil Twin" scenarios
([introduction.tex:86](../../sections/introduction.tex)). Do not pursue it
for this project.

### 3. Technical blockers on ESP32

- **ACK/CTS carry a Receiver Address only — no transmitter address.** The
  ACK to our frame is addressed *back to us* (the eliciting node), not
  stamped with the target's address (Polite WiFi Fig. 2: the ACK returns to
  the fake sender MAC)
  ([Abedi & Abari](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf), §2).
  - *Transmitting node:* attribution is trivial — it knows which MAC it
    addressed, so any ACK arriving one SIFS later is that target's reply. It
    measures the target↔self channel.
  - *Other anchors:* they receive an ACK whose RA is the transmitting node,
    with nothing identifying the target. **[Inference]** They must attribute
    by **timing**: they also hear the eliciting frame (whose destination =
    target MAC), and the ACK arrives exactly one SIFS (~10 µs at 2.4 GHz)
    later. Pairing "frame to T at t" with "ACK at t+10 µs" is the only
    handle. ESP32 exposes a µs receive timestamp
    (`rx_ctrl.timestamp`), but resolving a 10 µs gap reliably at several
    independent, unsynchronized anchors is unproven — **[Verify]**, and it is
    the single biggest risk in the whole scheme. Note the physics is
    favourable: the ACK is a genuine over-the-air transmission *by the
    target*, so its CSI at each anchor is the true target→anchor channel we
    want; only the *labelling* is hard.
- **ESP32 does report CSI for ACK frames — documented for classic ESP32.**
  `wifi_csi_config_t` has a `dump_ack_en` field ("enable to receive CSI of
  ACK", default off)
  ([esp_wifi_types header](https://github.com/espressif/esp-idf/blob/master/components/esp_wifi/include/esp_wifi_types_generic.h)).
  On the classic ESP32 (and C3/S3/C5) enabling legacy CSI + `dump_ack_en`
  yields valid CSI from ACKs addressed to the station; only ESP32-**C6** was
  reported broken. The reporter's filter shows the ACK's header (frame
  control `0xd4`) with the addressed MAC at header offset 4, matched against
  the station MAC
  ([esp-idf issue #19062, IDFGH-18255](https://github.com/espressif/esp-idf/issues/19062)).
  Our Arduino sketch already has this field and currently sets it off
  (`csi_cfg.dump_ack_en = false`,
  [anchor_arduino_wireless.ino](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino)).
  **[Verify]** field naming differs by IDF version (`dump_ack_en` on v5.1/5.4;
  newer trees add `acquire_csi_legacy`) — confirm against the exact core in
  use.
- **Promiscuous mode can filter for control frames, incl. ACK/CTS.** The
  control sub-filter masks exist: `WIFI_PROMIS_CTRL_FILTER_MASK_RTS (1<<27)`,
  `..._CTS (1<<28)`, `..._ACK (1<<29)`, gated by
  `WIFI_PROMIS_FILTER_MASK_CTRL (1<<1)`
  ([esp_wifi_types header](https://github.com/espressif/esp-idf/blob/master/components/esp_wifi/include/esp_wifi_types_generic.h)).
  Our anchors currently pass only `MGMT|DATA`, i.e. **control frames are
  filtered out today**
  ([anchor_arduino_wireless.ino](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino)).
- **A node *can* see the ACK to its own transmission in promiscuous mode —
  after an Espressif bug fix.** A user reported the sender could not capture
  ACKs to its own TX; Espressif staff confirmed the bug, shipped a patch, and
  the user then confirmed "a sender sending data frames to a receiver is able
  to detect the acks sent back by the receiver while the sender is in
  promiscuous mode"
  ([esp-idf issue #8469](https://github.com/espressif/esp-idf/issues/8469)).
  **[Verify]** on our IDF/core. Whether the **CSI callback** (not just the
  promiscuous callback) fires for an ACK a *third-party* anchor merely
  overhears (RA ≠ that anchor) is **not documented** — `dump_ack_en` is
  described for ACKs "addressed to the station." This is **[Verify]** and
  determines whether multi-anchor CSI (not just RSSI) is even possible.
- **Transmitting arbitrary frames via `esp_wifi_80211_tx` is restricted, and
  the API may inject RTS/CTS on its own.**
  - Docs: it "can be used to send beacon, probe request, probe response,
    action frames, and non-QoS data frames... cannot be used for sending
    encrypted or QoS frames"
    ([ESP-IDF esp_wifi API ref](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/network/esp_wifi.html)).
    Either `esp_wifi_set_promiscuous(true)` or `esp_wifi_start()` must return
    OK before it can be called (same ref).
  - Espressif deliberately narrowed raw-TX: a user noted "Espressif removed
    this capability with a version change... You can no longer send arbitrary
    frames without rolling back," and another observed a single
    `esp_wifi_80211_tx()` call can emit "a dozen RTS" and that "My device
    never receives CTS." Staff acknowledged the limitation and pointed to
    undocumented internal APIs `esp_wifi_internal_set_rts()` /
    `esp_wifi_internal_set_retry_counter()` to suppress the automatic RTS,
    saying they "will consider officially making them available"
    ([esp-idf issue #10668, IDFGH-9284](https://github.com/espressif/esp-idf/issues/10668)).
  - **[Inference]** A null-data frame (type/subtype `0x48`, non-QoS,
    unencrypted) to the target MAC is within the allowed set and is exactly
    the Polite WiFi eliciting frame. Rate must be forced to a **legacy OFDM**
    rate (e.g. 6 Mbps) so the elicited ACK/CTS also comes back at a legacy
    OFDM rate and therefore carries an L-LTF the ESP32 can turn into CSI —
    consistent with Abedi & Abari's note that ACKs use legacy bitrates and
    that ESP32 reads legacy-rate CSI. Rate is set via
    `esp_wifi_internal_set_fix_rate()` / `esp_wifi_config_80211_tx_rate()`
    ([ESP-IDF esp_wifi API ref](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/network/esp_wifi.html)).
    **[Verify]** that a fixed OFDM TX rate yields an OFDM (CSI-bearing) ACK on
    real targets.
- **Half-duplex.** The transmitting anchor cannot receive during its own TX,
  but the ACK arrives one SIFS *after* TX completes, so the transmitter can
  capture it (issue #8469 confirms this once patched). Other anchors are not
  transmitting, so they can receive it freely. **[Inference]** This favours a
  design where one dedicated *illuminator* transmits and the four *anchors*
  only listen — keeping the anchors passive receivers of a signal the
  illuminator provoked.
- **Channel.** A scanning device hops across channels and dwells on ours only
  briefly, while the anchors (and the ESP-NOW/Relay backhaul) are pinned to
  one 2.4 GHz channel
  ([firmware/README.md UDP-mode constraint](../../firmware/README.md), and
  the [SoftAP/ESP-NOW note](esp32-softap-espnow-relay.md)). **[Inference]**
  Elicitation is only reliable when the target is *parked* on our channel —
  i.e. associated to an AP on that channel, or itself an AP. A purely
  scanning, hopping device can be elicited only in the short windows it
  visits our channel, which is unreliable. This strongly shapes the realistic
  test setup (target on a hotspot pinned to the sniff channel, as the README
  already recommends for cooperative trials).

### 4. Does this change the "passive" claim?

Yes — materially.

- The thesis calls the system a "passive sniffer mesh" and defines
  "non-cooperative" as localized "without requiring association,
  authentication, or active participation," and lists a passive
  objective/architecture throughout
  ([introduction.tex:32, 47, 68](../../sections/introduction.tex);
  [methodology.tex functional req. 1, network section](../../sections/methodology.tex)).
  Any elicitation scheme has *the mesh actively transmitting* frames to the
  target. That is active sensing. The device stays "non-cooperative" (it
  never associates or runs our software), but the *system* is no longer
  passive.
- **Ju et al. 2025** — the thesis's own hidden-IoT citation
  (`ju2025hidden`) — is the closest precedent and is **active**:
  "Detection and Localization of Hidden IoT Devices in Unknown Environments
  Based on Channel Fingerprints" (Ju, Chen, Li, Han, *Big Data Cogn.
  Comput.* 9(8):214, 2025) "actively capturing the RSSI sequence of hidden
  devices by sending RTS frames and receiving CTS frames," then an
  XGBoost RSSI-ranging model + multi-point localization + AR, **on an Android
  platform**
  ([Ju et al. 2025, doi:10.3390/bdcc9080214](https://doi.org/10.3390/bdcc9080214)).
  It gets **RSSI, not CSI**, and runs on a **phone, not ESP32**. So citing it
  as support for *passive* *CSI* localization on ESP32 is a stretch: it
  supports *active RSSI* fingerprinting.
- **Lumos (Sharma et al., USENIX Security '22)** is genuinely passive — it
  sniffs the devices' own transmissions and does not elicit — but it assumes
  the devices are *transmitting on their own* (associated to the site AP)
  ([Lumos paper](https://www.usenix.org/system/files/sec22summer_sharma-rahul.pdf)).
  That is the honest passive model, and it depends on the target being
  associated and talking, not merely scanning.

### Table — elicitation methods

| Method | Target sends back | Has transmitter addr? | CSI on ESP32? | Passive? | Verdict |
|---|---|---|---|---|---|
| Sniff probe requests (no elicitation) | Probe request (broadcast, DSSS 1 Mbps) | Yes (its MAC, often randomized) | **No** (DSSS, no OFDM LTF) | Yes | RSSI-only, sporadic, MAC-randomized; **no CSI** |
| Unicast probe response to a probe request | Usually nothing (broadcast probes unACKed) | — | — | No | Unreliable; wrong side of the link |
| **Polite WiFi: null-data → ACK** | ACK at legacy rate | **No — RA = our node** | **Yes** if elicited at OFDM rate ([Abedi & Abari](http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf)) | No (we transmit) | **Best.** Demonstrated on ESP32; multi-anchor attribution by timing is the open risk |
| **Polite WiFi: RTS → CTS** | CTS at legacy rate | **No — RA = our node** | **Yes** [Inference, as ACK] | No | Works on unassociated devices; CTS unencryptable; same attribution risk |
| Karma / evil-twin SSID → assoc | Auth/Assoc (then data) | Yes | Yes (OFDM data) | No | Feasible but **impersonation — out of scope, do not pursue** |

## Implications for thesis scope wording ([introduction.tex:73](../../sections/introduction.tex))

The scope item "Non-Associative Signal Acquisition" currently claims the
system "leverages 802.11 control and management frames (e.g., ACK, and Probe
Responses)... By capturing the PHY-layer preamble of these mandatory protocol
responses." Two problems:

1. **"Probe Responses"** are emitted by the AP/responder side, and probe
   *requests* (the scanning client's frames) are DSSS in 2.4 GHz → **no CSI
   on ESP32**. If the target is a scanning *client*, this wording promises
   CSI it cannot deliver.
2. **"mandatory protocol responses" (ACK)** only exist if *something
   transmits a frame the target must acknowledge*. That "something" is the
   mesh. So the sentence quietly assumes active elicitation while the rest of
   the chapter promises a *passive* mesh
   ([introduction.tex:47, 68](../../sections/introduction.tex);
   [methodology.tex](../../sections/methodology.tex)).

**Options (pick one and make the whole chapter consistent):**
- **(A) Stay honestly passive** (Lumos-style): localize from the target's
  *own* transmissions (data frames while it is associated to a present AP).
  Drop the ACK/probe-response CSI claim; accept that a silent scanning device
  yields only occasional RSSI. Keeps "passive" true.
- **(B) Adopt active elicitation** (Polite WiFi / Ju et al. style): add an
  illuminator that provokes ACK/CTS, and **relabel the system "active,
  non-cooperative"** — the target never cooperates, but the mesh transmits.
  Cite Abedi & Abari and Ju et al. correctly (active; Ju = RSSI-only).
  This is the only route that gets CSI from a non-transmitting device, and
  it is what the introduction's ACK sentence actually describes.
- Either way, correct the `ju2025hidden` framing: it is **active RTS/CTS,
  RSSI-only, on a phone.**

## Minimal hardware experiment (steps only)

Goal: confirm, on our actual ESP32s, (i) that an elicited ACK/CTS carries
CSI, and (ii) whether a *second* anchor can capture and attribute that reply.

1. **Two-node baseline (transmitter = receiver).** Node X: STA mode,
   promiscuous on the fixed channel, CSI enabled with `dump_ack_en = true`.
   Target T: a phone or spare ESP parked (associated) on that same channel.
   Feed T's MAC to X. X sends null-data frames to T at a **fixed OFDM rate
   (6 Mbps)**, ~100–150/s, with the automatic RTS suppressed
   (`esp_wifi_internal_set_rts` per issue #10668). Confirm the CSI callback
   fires with the ACK's MAC = X and `sig_mode` = OFDM, and that amplitudes
   perturb when a hand moves near T. This reproduces Abedi & Abari on our
   hardware.
2. **RTS variant.** Repeat sending RTS instead of null-data; confirm CTS is
   received and (if any) its CSI. Compare response rate vs null-data.
3. **Third-party anchor (the real test).** Add Node Y: STA mode,
   promiscuous with `MGMT|DATA|CTRL` and the CTS/ACK control sub-filters
   enabled, CSI on. While X illuminates T, check on Y: (a) does Y's
   promiscuous callback receive the ACK/CTS at all? (b) does Y's **CSI
   callback** fire for it? (c) can Y pair "X's frame to T" with "reply
   ~10 µs later" using `rx_ctrl.timestamp`? Log both nodes' timestamps for a
   fixed run and measure the timing-attribution error rate.
4. **Rate/PHY check.** Force X's TX rate to 1 Mbps DSSS and confirm the ACK
   comes back with no usable CSI — validating that OFDM elicitation is
   required.
5. **Channel-parking check.** Repeat with T *not* associated and free to
   scan/hop; measure how often T is actually on our channel and elicitable.
6. **Four-anchor mini-trial.** If step 3 yields CSI at ≥3 anchors with
   correct attribution, run one localization window at a known position and
   compare against the existing passive pipeline.

Success gate for the CSI story: **step 3(b) must succeed** (third-party CSI
for an overheard ACK). If only 3(a) succeeds (frame seen, no CSI), the
multi-anchor scheme is **RSSI-only** — i.e. Ju et al.'s result, not a CSI
system.

## Open questions / must verify on hardware

1. **[Verify]** Does the ESP32 CSI callback fire for an ACK/CTS a *third
   party* overhears (RA ≠ that anchor), or only for ACKs addressed to the
   node itself? (Determines CSI vs RSSI-only for the mesh.)
2. **[Verify]** Can independent, unsynchronized anchors attribute an
   RA-only ACK to the target by SIFS timing at ~10 µs resolution using
   `rx_ctrl.timestamp`? What is the mis-pairing rate under real traffic?
3. **[Verify]** On our exact core, does forcing an OFDM TX rate produce an
   OFDM (CSI-bearing) ACK across target vendors, or do some reply at DSSS?
4. **[Verify]** `dump_ack_en` vs `acquire_csi_legacy` field naming and
   behaviour on arduino-esp32 3.x / IDF v5.4 (classic ESP32).
5. **[Verify]** Reliability of `esp_wifi_80211_tx` null-data emission with
   RTS suppressed, and whether the internal RTS APIs survive our IDF version
   (they are undocumented — issue #10668).
6. **[Open]** How to key observations when the target randomizes its MAC in
   probe requests but exposes a stable MAC only once elicited/associated —
   reconcile with the gateway `DeviceRegistry`.
7. **[Open]** Legal/ethical review before any elicitation on non-consenting
   devices, even in a controlled testbed.

## Sources

- Abedi & Abari, "WiFi Says 'Hi!' Back to Strangers!" (Polite WiFi), HotNets '20: http://web.cs.ucla.edu/~omid/Papers/Hotnets20b.pdf (DOI https://doi.org/10.1145/3422604.3425951)
- Ju, Chen, Li, Han, "Detection and Localization of Hidden IoT Devices in Unknown Environments Based on Channel Fingerprints," Big Data Cogn. Comput. 9(8):214, 2025: https://doi.org/10.3390/bdcc9080214
- Sharma et al., "Lumos: Identifying and Localizing Diverse Hidden IoT Devices in an Unfamiliar Environment," USENIX Security '22: https://www.usenix.org/system/files/sec22summer_sharma-rahul.pdf
- Vanhoef et al., "Why MAC Address Randomization is not Enough," AsiaCCS '16: https://papers.mathyvanhoef.com/asiaccs2016.pdf
- ESP-IDF `esp_wifi` API reference (esp_wifi_80211_tx allowed frame types, fix-rate APIs, promiscuous prerequisite): https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/network/esp_wifi.html
- ESP-IDF `esp_wifi_types` header (`wifi_csi_config_t.dump_ack_en`, `WIFI_PROMIS_FILTER_MASK_CTRL`, `WIFI_PROMIS_CTRL_FILTER_MASK_ACK/CTS/RTS`): https://github.com/espressif/esp-idf/blob/master/components/esp_wifi/include/esp_wifi_types_generic.h
- esp-idf issue #10668 (IDFGH-9284) — `esp_wifi_80211_tx` restricted / injects RTS; internal RTS-suppress APIs; Espressif-staff answered: https://github.com/espressif/esp-idf/issues/10668
- esp-idf issue #8469 — promiscuous capture of ACKs to own TX; Espressif-staff-confirmed bug + patch: https://github.com/espressif/esp-idf/issues/8469
- esp-idf issue #19062 (IDFGH-18255) — CSI from ACK frames via `dump_ack_en`/`acquire_csi_legacy`; works on ESP32/C3/S3/C5, broken on C6; ACK header/MAC layout: https://github.com/espressif/esp-idf/issues/19062
- Project firmware line-format & "no CSI for 802.11b" note: [firmware/README.md](../../firmware/README.md)
- Prior research note (single-radio single-channel constraint): [esp32-softap-espnow-relay.md](esp32-softap-espnow-relay.md)
</content>
</invoke>
