# Can the Relay use SoftAP instead of joining a trial network?

_Researched 2026-09-30 against ESP-IDF v5.4 docs/headers, arduino-esp32 3.x
source (`master`, latest release 3.3.12), and Espressif's own FAQ, example
and issue threads. Every claim cites its source; text marked **[Inference]**
is my reasoning, not something Espressif documents._

## Question

Can the ESP32 **Relay** run as a SoftAP that the **Gateway** laptop joins,
instead of joining a researcher-owned **trial network** (travel router or
hotspot), while still receiving the **Anchors'** ESP-NOW traffic and
forwarding it to the Gateway over UDP?

Current design, for reference
([firmware/gateway_arduino/gateway_arduino.ino](../../firmware/gateway_arduino/gateway_arduino.ino),
[firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino](../../firmware/anchor_arduino_wireless/anchor_arduino_wireless.ino)):
the Relay uses `WiFi.mode(WIFI_STA)` + `WiFi.begin()` to join the trial network,
then sends unicast UDP to a fixed Gateway IP (`192.168.1.100:5555`). Anchors run
in STA mode (not associated), promiscuous + CSI on `WIFI_CHANNEL`, and
`esp_now_send()` to `relay_mac`, which is the Relay's **station** MAC.

## Short verdict

**"We can't use SoftAP" is false.** ESP-NOW is officially supported on the
SoftAP interface, a SoftAP's channel is set by the application (so it can be
pinned to the target's channel), and a laptop can join it and receive UDP.
The true constraint behind the claim is a different one: **the single radio
means ESP-NOW, the Relay's uplink, the Anchors' sniffing and the target must
all be on one channel.** That holds for both designs. SoftAP doesn't remove
it, and it doesn't make it worse.

SoftAP actually makes the channel easier to control. The Relay's own code
sets the channel, so the travel router is no longer something that sets or
changes it. The costs are practical: the laptop's Wi-Fi is taken up by the
Relay's network (it loses internet unless it has a second interface), and
you have to address the Anchors to the Relay's **AP** MAC (or run the Relay
in AP+STA mode). Also, the documented ESP-NOW-while-connected-as-station
modem-sleep pitfall doesn't apply to a SoftAP, and the current STA Relay
code is exposed to it (see Q4).

## Findings

### 1. Can the Relay run SoftAP (or AP+STA) and receive ESP-NOW? Which interface, which channel?

- **Yes, it's supported.** The ESP-NOW guide says: "You can send ESP-NOW data
  via both the Station and the SoftAP interface. Make sure that the interface
  is enabled before sending ESP-NOW data."
  ([ESP-NOW guide, v5.4](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-reference/network/esp_now.html#add-paired-device))
  Espressif's own example is built for both. Its header says "ESPNOW can work in both
  station and softap mode. It is configured in menuconfig", mapping the
  SoftAP option to `WIFI_MODE_AP` / `ESP_IF_WIFI_AP`
  ([examples/wifi/espnow/main/espnow_example.h](https://github.com/espressif/esp-idf/blob/v5.4/examples/wifi/espnow/main/espnow_example.h)).
  The esp-now component user guide lists this as a feature: "When the device connects to a router or works
  as a hotspot, it can also realize a fast and stable communication by ESP-NOW"
  ([esp-now User_Guide.md](https://github.com/espressif/esp-now/blob/master/User_Guide.md)).
- **Interface / peer semantics.** `esp_now_peer_info_t.peer_addr` is "ESPNOW
  peer MAC address that is also the MAC address of station or softap".
  `ifidx` is the "Wi-Fi interface that peer uses to send/receive ESPNOW data".
  `esp_now_send()` returns `ESP_ERR_ESPNOW_IF` when the "current Wi-Fi interface
  doesn't match that of peer"
  ([esp_now.h v5.4](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_wifi/include/esp_now.h)).
  The same interface rule is stated explicitly for raw TX: "If the Wi-Fi mode is
  Station, the ifx should be WIFI_IF_STA. If the Wi-Fi mode is SoftAP, the ifx
  should be WIFI_IF_AP. If the Wi-Fi mode is Station+SoftAP, the ifx should be
  WIFI_IF_STA or WIFI_IF_AP"
  ([esp_wifi.h v5.4, `esp_wifi_80211_tx`](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_wifi/include/esp_wifi.h)).
  - **What this means for us:**
    - **Relay (receive only):** it doesn't send ESP-NOW, and the current Relay
      receives without adding any peers, so `ifidx` doesn't apply on the Relay.
    - **Anchors (senders):** they stay in STA mode, so their peer entry keeps
      `ifidx = WIFI_IF_STA` (the default zero value). What changes is the
      **destination MAC**. On a classic ESP32 the SoftAP MAC is by default
      "base_mac, +1 to the last octet", while the station MAC is base_mac
      ([MAC address table, v5.4](https://github.com/espressif/esp-idf/blob/v5.4/docs/en/api-reference/system/misc_system_api.rst)).
      So if the Relay runs AP-only, `relay_mac` in the anchor sketch must become the
      Relay's `WiFi.softAPmacAddress()`.
    - **[Inference]** A frame addressed to the STA MAC while the STA interface
      is disabled (AP-only) probably won't be delivered. Espressif doesn't state
      this directly. You can avoid the question by running the Relay in
      `WIFI_AP_STA` with the STA never connected, which keeps both MACs live.
- **Channel rule.** "The range of the channel of paired devices is from 0 to
  14. If the channel is set to 0, data will be sent on the current channel.
  Otherwise, the channel must be set as the channel that the local device is on"
  ([ESP-NOW guide](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-reference/network/esp_now.html#add-paired-device)).
  The header says the same: "If the value is 0, use the current channel which
  station or softap is on"
  ([esp_now.h](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_wifi/include/esp_now.h)).
  Sender and receiver "must be on the same channel"
  ([espnow example README](https://github.com/espressif/esp-idf/blob/v5.4/examples/wifi/espnow/README.md)).
  The FAQ adds that with Wi-Fi in use, "the channel of ESP-NOW must be the same as that of the
  connected AP" and "The device cannot switch channels after connecting to
  Wi-Fi"
  ([ESP-FAQ: ESP-NOW](https://docs.espressif.com/projects/esp-faq/en/latest/application-solution/esp-now.html)).

### 2. Who controls the channel in SoftAP / AP+STA?

- **SoftAP only: the application sets it.** `wifi_ap_config_t.channel`: "Channel of AP;
  if the channel is out of range, the Wi-Fi driver defaults to channel 1"
  ([Wi-Fi guide, AP Basic Configuration](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#ap-basic-configuration)).
  "In AP mode, the home channel is defined as the AP channel"
  ([Wi-Fi guide, Home Channel](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#home-channel)).
  In Arduino, `WiFi.softAP(ssid, passphrase, channel = 1, ssid_hidden = 0,
  max_connection = 4, ...)` passes `channel` straight into `conf.ap.channel`
  ([WiFiAP.h](https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/WiFiAP.h),
  [AP.cpp](https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/AP.cpp)).
  **So yes, it can be pinned to the target's channel** (within the range allowed by the
  configured Wi-Fi country code, 1–14 at most).
- **Changing it at runtime is restricted.** `esp_wifi_set_channel()` "should not be called
  when softAP has connected to external STAs"
  ([esp_wifi.h](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_wifi/include/esp_wifi.h)).
  Set the channel in the AP config before the laptop joins. To retune for a
  new target, restart the AP.
- **AP+STA with STA connected: the station's channel wins.** "In
  station/AP-coexistence mode, the home channel of AP and station must be the
  same, and if they are different, the station's home channel is always in
  priority ... the AP needs to switch its channel from 6 to 9 ... the ESP32 in
  AP mode will notify the connected stations about the channel migration using
  a Channel Switch Announcement (CSA)"
  ([Wi-Fi guide, Home Channel](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#home-channel)).
  Also: "the channel of the external AP, which the ESP station is connected to,
  has higher priority over the ESP AP channel"
  ([Wi-Fi guide, Wi-Fi mode](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html)).
  The HT40 secondary channel is also taken from the station's side
  ([Wi-Fi guide, bandwidth](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html)).
  - **What this means for us:** AP+STA only helps if the STA **never
    connects**. If the STA also joins a router, you're back to the router
    choosing the channel. Scanning or connection attempts also move the radio
    off its home channel
    ([Wi-Fi guide, scan / back-to-home channel](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#scan)).
    So a SoftAP Relay must not call `WiFi.begin()` or `WiFi.reconnect()`, unlike the
    current loop.
- **Bandwidth.** "The default bandwidth for ESP32 station and AP is HT40"
  ([Wi-Fi guide](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html)).
  **[Inference]** Set the AP to HT20 with `WiFi.softAPbandwidth(WIFI_BW_HT20)`
  ([WiFiAP.h](https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/WiFiAP.h)).
  This matches the anchors' `WIFI_SECOND_CHAN_NONE` and keeps the Relay from
  occupying a second 20 MHz channel.

### 3. Can the laptop join the SoftAP and receive UDP reliably?

- **Addressing.** The default ESP-IDF SoftAP netif is `192.168.4.1/24`, and that is also
  its gateway
  ([esp_netif_defaults.c](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_netif/esp_netif_defaults.c)).
  Its DHCP server hands out leases from server+1 upward, capped at
  `DHCPS_MAX_LEASE` = 100 (so `192.168.4.2`–`192.168.4.101`), with a default
  lease time of 120 min
  ([dhcpserver.c](https://github.com/espressif/esp-idf/blob/v5.4/components/lwip/apps/dhcpserver/dhcpserver.c),
  [dhcpserver.h](https://github.com/espressif/esp-idf/blob/v5.4/components/lwip/include/apps/dhcpserver/dhcpserver.h)).
  The address can be changed with `WiFi.softAPConfig(local_ip, gateway, subnet,
  dhcp_lease_start, dns)`
  ([WiFiAP.h](https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/WiFiAP.h)).
  The Relay can learn the laptop's IP instead of hard-coding it:
  `IP_EVENT_AP_STAIPASSIGNED` ("soft-AP assign an IP to a connected station")
  ([esp_netif_types.h](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_netif/include/esp_netif_types.h)),
  exposed in Arduino as `ARDUINO_EVENT_WIFI_AP_STAIPASSIGNED`
  ([NetworkEvents.h](https://github.com/espressif/arduino-esp32/blob/master/libraries/Network/src/NetworkEvents.h)).
  Two alternatives: give the laptop a static IP outside the pool (e.g. `192.168.4.200`),
  or keep `GATEWAY_IP` pointing at the first DHCP lease `192.168.4.2`. The existing
  [scripts/relay_udp_listener.py](../../scripts/relay_udp_listener.py) already
  binds `0.0.0.0` by default, so it needs no change.
- **Station limit.** `max_connection` defaults to 10 in IDF. ESP32 supports up to
  15, but the SoftAP shares its 17 hardware keys with encrypted ESP-NOW peers
  (`CONFIG_ESP_WIFI_ESPNOW_MAX_ENCRYPT_NUM`, default 7)
  ([Wi-Fi guide, AP Basic Configuration](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#ap-basic-configuration),
  [ESP-NOW guide](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-reference/network/esp_now.html#add-paired-device)).
  Arduino's `softAP()` defaults `max_connection` to 4
  ([WiFiAP.h](https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/WiFiAP.h)).
  One laptop is well within these limits.
- **Idle deauth.** "If the softAP doesn't receive any data from the connected
  STA during inactive time, the softAP will force deauth the STA. Default is
  300s", and this can be changed with `esp_wifi_set_inactive_time(WIFI_IF_AP, sec)`
  ([esp_wifi.h](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_wifi/include/esp_wifi.h)).
  **[Inference]** A laptop that only *receives* UDP normally still sends ARP,
  DHCP renewals and OS chatter. Still, raise the timeout or have the listener
  send an occasional keepalive, and verify on hardware.
- **Throughput.** The ESP32 Wi-Fi stack supports "Up to 20 MBit/s TCP throughput
  and 30 MBit/s UDP throughput over the air"
  ([Wi-Fi guide, features](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html)).
  That is far above the Relay's CSV-line uplink rate. The bottleneck is the ESP-NOW side and
  shared airtime (see Q4), not the SoftAP-to-laptop link.
- **Power save on the laptop side.** "the AP only caches unicast data for the
  stations connect to this AP, but does not cache the multicast data ... they
  may experience multicast packet loss"
  ([Wi-Fi guide, AP Sleep](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#ap-sleep)).
  **So use unicast UDP to the laptop, not broadcast or multicast**, which is
  what the Relay already does.
- **Laptop loses internet / macOS.** **[Inference, not from Espressif]** The SoftAP
  has no upstream connection, so a laptop whose only Wi-Fi is on the Relay's
  network has no internet unless it also has Ethernet, USB tethering or a second
  adapter. macOS may warn about "no internet connection" but will stay
  associated. The travel-router design has the same issue unless the router
  has an uplink.

### 4. Anchor promiscuous + ESP-NOW coexistence; SoftAP-specific pitfalls

- **The anchors don't change.** The Relay's mode doesn't affect the anchors except
  for the destination MAC. Sniffer mode "can be enabled in the Wi-Fi mode
  of WIFI_MODE_NULL, WIFI_MODE_STA, WIFI_MODE_AP, or WIFI_MODE_APSTA", but "the
  sniffer has a **great impact** on the throughput of the station or AP Wi-Fi
  connection"
  ([Wi-Fi guide, Sniffer Mode](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#wi-fi-sniffer-mode)).
  Espressif doesn't state outright that promiscuous RX and ESP-NOW TX can run
  together on one radio. The claim rests on the current anchor firmware, which
  already does both on STA-mode anchors (empirical, this repo). CSI docs recommend
  enabling sniffer mode to get more CSI
  ([Wi-Fi guide, CSI](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html)).
- **Modem sleep: a SoftAP Relay avoids it; the current STA Relay is exposed.**
  Espressif's example says: "if the receiving device is in station mode only and
  it connects to an AP, modem sleep should be disabled. Otherwise, it may fail to
  receive ESPNOW data from other devices"
  ([espnow example README, Troubleshooting](https://github.com/espressif/esp-idf/blob/v5.4/examples/wifi/espnow/README.md)).
  - **Defaults make the current Relay affected.** "The default Modem-sleep mode is WIFI_PS_MIN_MODEM"
    ([Wi-Fi guide](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#station-sleep)).
    Arduino also defaults ESP32 to `WIFI_PS_MIN_MODEM` and applies it when STA starts
    ([WiFiGeneric.cpp](https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/WiFiGeneric.cpp),
    [STA.cpp](https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/STA.cpp)).
    The current Relay never calls `WiFi.setSleep(false)` or
    `esp_wifi_set_ps(WIFI_PS_NONE)`. The anchors do; the Relay doesn't
    (`grep set_ps firmware/`).
  - **SoftAP doesn't have this problem.** "Modem-sleep mode works in station-only mode", and ESP-NOW
    "Sleep is supported only when ESP32 is configured as station"
    ([Wi-Fi guide](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#station-sleep),
    [ESP-NOW guide, power-saving](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-reference/network/esp_now.html)),
    so a SoftAP Relay's radio stays awake.
  - **Espressif's docs disagree with each other here.** The FAQ says "By default, the device can
    receive ESP-NOW data normally (the wake window ... defaults to the maximum
    value, so the RF stays on)"
    ([ESP-FAQ: ESP-NOW](https://docs.espressif.com/projects/esp-faq/en/latest/application-solution/esp-now.html)).
    Either way, adding `WiFi.setSleep(false)` to the current Relay costs nothing.
- **Encryption and the AP.** SoftAP clients and encrypted ESP-NOW peers share 17 hardware keys
  (see Q3). Our ESP-NOW traffic is unencrypted (`peerInfo.encrypt = false`), so
  this doesn't limit us.
- **Channel capacity is the real risk, and it affects both designs.** Default ESP-NOW PHY rate is 1
  Mbps, and Espressif measured one-to-one throughput at "Around 214 Kbps in an open
  environment"
  ([ESP-FAQ: ESP-NOW](https://docs.espressif.com/projects/esp-faq/en/latest/application-solution/esp-now.html)).
  The rate can be raised with `esp_wifi_config_espnow_rate()` (deprecated but
  still in v5.x) or `esp_now_set_peer_rate_config()`
  ([esp_now.h](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_wifi/include/esp_now.h),
  [ESP-FAQ](https://docs.espressif.com/projects/esp-faq/en/latest/application-solution/esp-now.html)).
  Each record is 149 bytes, and the anchor forwards the CSI of *every* sniffed
  frame.
  - **[Inference, calculation]** The README estimates 100–300 frames/s on a busy
    channel ([firmware/README.md](../../firmware/README.md)). With 4 anchors
    that is 400–1200 ESP-NOW frames/s, which needs about 0.5–1.4 Mbit/s of
    payload alone. That is well above the ~214 kbps measured at 1 Mbps.
  - Separately, "too short interval between sending two ESP-NOW data may lead
    to disorder of sending callback", and delivery "is not guaranteed"
    ([ESP-NOW guide, Send](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-reference/network/esp_now.html#send-esp-now-data)).
  - This bottleneck exists whichever uplink the Relay uses.
  - **[Inference]** SoftAP slightly *reduces* channel load compared with a
    travel router that the laptop reaches over Wi-Fi. There, every forwarded
    line crosses the air twice (Relay to router to laptop) on the same channel;
    with SoftAP it crosses once. The SoftAP also adds its own beacons, but a
    travel router's beacons are on that channel too.

### 5. Net verdict and tradeoffs

**False as stated, true in what it's really pointing at.** SoftAP works. What
you can't escape is the single-radio, single-channel rule. Anchors, the Relay's
ESP-NOW RX, the Relay's uplink and the target must all share one 2.4 GHz channel
in *either* design. Neither the travel router nor SoftAP lets anchors sniff one
channel while the backhaul runs on another.

| Aspect | Current: Relay STA on trial network | Alternative: Relay SoftAP (AP-only, or AP+STA with STA idle) |
|---|---|---|
| Who sets the shared channel | The travel router's channel setting. Must be manually pinned and trusted not to auto-change ([Home Channel](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#home-channel)) | The Relay's own code (`WiFi.softAP(..., channel)`) ([AP.cpp](https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/AP.cpp)) |
| Must equal target channel? | Yes | Yes |
| Extra hardware | Travel router or hotspot, plus its power | None |
| Anchor change | None | `relay_mac` becomes the Relay's AP MAC (base+1), unless the Relay runs AP+STA ([MAC table](https://github.com/espressif/esp-idf/blob/v5.4/docs/en/api-reference/system/misc_system_api.rst)) |
| Relay modem sleep risk | Present by default in Arduino; needs `WiFi.setSleep(false)` ([example README](https://github.com/espressif/esp-idf/blob/v5.4/examples/wifi/espnow/README.md), [WiFiGeneric.cpp](https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/WiFiGeneric.cpp)) | Not applicable, the AP doesn't sleep ([ESP-NOW guide](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-reference/network/esp_now.html)) |
| Airtime used by UDP uplink | 2 hops if the laptop is on router Wi-Fi, 1 hop if it's on router Ethernet **[Inference]** | 1 hop **[Inference]** |
| Laptop IP | Static reservation on router (`192.168.1.100`) | DHCP `192.168.4.2+`, a static IP, or learned via `AP_STAIPASSIGNED` ([esp_netif_types.h](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_netif/include/esp_netif_types.h)) |
| Laptop internet | Only if the router has an uplink | None over Wi-Fi; needs a second interface **[Inference]** |
| Multiple Gateways / phones on network | Router handles many clients | ≤10 by default (15 max) ([Wi-Fi guide](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html#ap-basic-configuration)); fine for 1 laptop |
| Relay CPU/RAM load | STA only | Also runs the AP and DHCP server **[Inference: small]** |
| Target-traffic trick (connect target to a hotspot you own, per [firmware/README.md](../../firmware/README.md)) | The trial network can also serve as the target's AP | The SoftAP *could* host a cooperative test target, but ESP32 AP throughput and shared airtime would then carry target traffic too **[Inference]** |
| Idle-client handling | Router-dependent | Deauth after 300 s idle by default; adjustable ([esp_wifi.h](https://github.com/espressif/esp-idf/blob/v5.4/components/esp_wifi/include/esp_wifi.h)) |

**Recommendation [Inference]:** SoftAP is a sound simplification for
non-cooperative trials. Use AP+STA with the STA left unconnected so the anchors'
current `relay_mac` still works (or switch them to the AP MAC and go AP-only).
Pin the channel and HT20 in `softAP()`, drop the `WiFi.begin()`/`reconnect()`
loop, and keep unicast UDP to the laptop. Whichever design is used, add
`WiFi.setSleep(false)` to any STA-mode Relay, and budget ESP-NOW airtime (raise
the ESP-NOW PHY rate or filter by target MAC on the anchors).

## Open questions / verify on hardware

1. With the Relay in **AP-only** mode, are ESP-NOW frames sent to its **STA** MAC
   dropped? (Expected yes. Test before choosing AP-only over AP+STA.)
2. With AP+STA and the STA never connected, does Arduino's `WiFi.mode(WIFI_AP_STA)`
   trigger any background scan or auto-connect that moves the channel? Log
   `WiFi.channel()` for a full session.
3. Does the laptop stay associated for a whole capture (> 300 s inactivity default)?
   Check macOS/Linux behavior; set `esp_wifi_set_inactive_time(WIFI_IF_AP, ...)`
   if needed.
4. ESP-NOW loss rate under realistic load (4 anchors, busy channel) at 1 Mbps vs
   a raised rate. Compare `seq` gaps per anchor in the Gateway CSVs. This
   question matters for both designs.
5. Does the Relay's own SoftAP traffic (beacons, UDP to laptop) show up in anchor
   captures? Expected yes, under the Relay's AP MAC and the laptop's MAC, so the
   `DeviceRegistry` should list them as known/`wanted` so they aren't mistaken
   for hidden devices.
6. Does the current STA Relay lose ESP-NOW frames with default modem sleep
   (A/B test with `WiFi.setSleep(false)`)? Espressif's own docs disagree here.

## Sources

- ESP-IDF v5.4 ESP-NOW guide: https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-reference/network/esp_now.html (source: https://github.com/espressif/esp-idf/blob/v5.4/docs/en/api-reference/network/esp_now.rst)
- ESP-IDF v5.4 Wi-Fi driver guide: https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/wifi.html (source: https://github.com/espressif/esp-idf/blob/v5.4/docs/en/api-guides/wifi.rst)
- `esp_now.h` v5.4: https://github.com/espressif/esp-idf/blob/v5.4/components/esp_wifi/include/esp_now.h
- `esp_wifi.h` v5.4: https://github.com/espressif/esp-idf/blob/v5.4/components/esp_wifi/include/esp_wifi.h
- ESP-IDF espnow example (README + header): https://github.com/espressif/esp-idf/tree/v5.4/examples/wifi/espnow
- ESP-IDF MAC address docs (misc system API): https://github.com/espressif/esp-idf/blob/v5.4/docs/en/api-reference/system/misc_system_api.rst
- `esp_netif_defaults.c` (SoftAP 192.168.4.1): https://github.com/espressif/esp-idf/blob/v5.4/components/esp_netif/esp_netif_defaults.c
- `esp_netif_types.h` (`IP_EVENT_AP_STAIPASSIGNED`): https://github.com/espressif/esp-idf/blob/v5.4/components/esp_netif/include/esp_netif_types.h
- lwIP DHCP server (lease pool / time): https://github.com/espressif/esp-idf/blob/v5.4/components/lwip/apps/dhcpserver/dhcpserver.c and https://github.com/espressif/esp-idf/blob/v5.4/components/lwip/include/apps/dhcpserver/dhcpserver.h
- ESP-FAQ, ESP-NOW: https://docs.espressif.com/projects/esp-faq/en/latest/application-solution/esp-now.html
- esp-now component User Guide: https://github.com/espressif/esp-now/blob/master/User_Guide.md
- arduino-esp32 `WiFiAP.h` / `AP.cpp`: https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/WiFiAP.h , https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/AP.cpp
- arduino-esp32 `WiFiGeneric.cpp` / `STA.cpp` (default sleep): https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/WiFiGeneric.cpp , https://github.com/espressif/arduino-esp32/blob/master/libraries/WiFi/src/STA.cpp
- arduino-esp32 `NetworkEvents.h`: https://github.com/espressif/arduino-esp32/blob/master/libraries/Network/src/NetworkEvents.h
- arduino-esp32 issue #8912 (Espressif maintainer me-no-dev: "ESP-NOW works only on the channel that the radio is currently on ... the radio's channel is equal to that of the AP that you have connected to"): https://github.com/espressif/arduino-esp32/issues/8912
