# Hybrid RSSI–CSI Localization

Passive WiFi localization system for the 2026 thesis: ESP32 sniffers capture
RSSI and CSI from nearby transmitters, and a laptop turns those captures into
localization features.

## Language

### Devices

**Anchor**:
An ESP32 that passively sniffs 802.11 frames on a fixed channel and emits one
record per frame (source MAC, timestamp, RSSI, CSI amplitudes, anchor id).
Identified as A1..A4.
_Avoid_: node, sniffer board, sensor

**Relay**:
The ESP32 that receives Anchor records over ESP-NOW and forwards them to the
Gateway over WiFi UDP on the trial network (USB serial is the fallback link).
_Avoid_: gateway_arduino, receiver, hub

**Gateway**:
The laptop that receives the Relay's stream over the trial network, writes
Captures, and runs the preprocessing pipeline. Earlier setups used a Raspberry Pi as the Gateway;
the laptop replaces it.
_Avoid_: Pi, host, server, base station

### Network

**Trial network**:
The WiFi network the Relay joins to reach the Gateway at a fixed IP.
_Avoid_: lab WiFi, hotspot, LAN

### Data

**Record**:
One `CSI,` or `STAT,` line emitted by an Anchor.
_Avoid_: packet, sample, row

**Capture**:
A per-Anchor CSV file of Records landed by the Gateway during one session.
_Avoid_: log, dump, dataset

**Trial**:
One experimental run with a fixed authorized-device list and target placement.
_Avoid_: experiment, session, run
