# Hybrid RSSI–CSI Localization

Passive WiFi localization system for the 2026 thesis: ESP32 Anchors capture
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

**Beacon**:
An ESP32 on a USB power bank that transmits at a steady rate from a fixed
MAC; the calibration transmitter and primary test target (ADR-0003).
_Avoid_: tag, emitter, dummy device, target ESP32

### Network

**Trial network**:
The WiFi network the Relay joins to reach the Gateway at a fixed IP.
_Avoid_: lab WiFi, hotspot, LAN

### Data

**Record**:
One `CSI,` or `STAT,` line emitted by an Anchor.
_Avoid_: packet, sample, row

**Capture**:
A per-Anchor CSV file of Records landed by the Gateway during one Trial.
_Avoid_: log, dump, dataset

**Trial**:
One measurement pass with a fixed authorized-device list and target placement.
_Avoid_: experiment, run, session

### Localization

**Reference point**:
A surveyed position on the reference grid where the Beacon was placed to
build the Radio map (spacing in ADR-0003).
_Avoid_: fingerprint location, grid cell, training point

**Test position**:
A held-out position where a target is placed for evaluation Trials; never a
Reference point (ADR-0003).
_Avoid_: ground truth point, eval spot, test point

**Radio map**:
The stored per-(Reference point, Anchor) feature vectors built from a
Calibration session's windows and its positions file (ADR-0002).
_Avoid_: fingerprint database, training set, lookup table

**Calibration session**:
The set of Trials, one per Reference point, whose Captures build the Radio
map; a session is several Trials, never one (ADR-0003).
_Avoid_: training run, survey, offline phase

**Scout**:
The coarse localizer: an RSSI model that outputs a bounding box and a center
estimate (ADR-0002).
_Avoid_: coarse stage, RSSI model, first stage

**Sniper**:
The fine localizer: a particle filter inside the Scout's bounding box,
weighted by D-CFR similarity (ADR-0002).
_Avoid_: fine stage, CSI model, refinement step

**Mode**:
Per-window label, `sniper` or `fallback`, recording whether the Sniper ran or
the Scout's estimate (the mean of its most probable kernel) was used; its
rate is a reported metric.
_Avoid_: status, path, branch
