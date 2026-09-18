---
status: accepted
date: 2026-09-18
---

# Localization algorithms operationalized

## Context

The methodology chapter (`thesis/sections/methodology.tex`) names three
localizers — an MDN **Scout**, a D-CFR particle-filter **Sniper**, and a
"direct RSSI+CSI" baseline — but leaves each abstract: no feature vector, no
k, no mixture size, no rule for when the Sniper is trusted. The literature we
build on flags three risks that the abstract design does not answer: device
heterogeneity (different transmitters give different RSSI/CSI at the same
spot), the single-antenna limit of the ESP32 (no AoA, one CSI stream per
Anchor), and radio-map drift between calibration and test.

We now have a first real dataset to size thresholds against: the 2026-08-28
two-anchor capture (`data/A1_20260828_140440.csv`, `A2_20260828_140440.csv`;
3,760 CSI Records, 66 MACs). In it, one strong device at −65 dBm gives a
within-window D-CFR stability (median pairwise Pearson ρ between per-packet
D-CFR vectors) of ≈ 0.75–0.8, while ambient devices at −85 dBm and below give
ρ ≈ 0.0–0.1 at 0.02–0.2 packets/s. That gap is what every threshold below is
anchored to.

This ADR records the design settled in the 2026-09-18 grilling session so
that #25–#29 each have a spec to implement against.

## Decision

**Offline first.** Every localizer runs over the preprocessed windows output
(`gateway` preprocess → `windows.jsonl`), not over the live stream. A
live/streaming mode is a later ticket once the offline numbers exist.

**Spatial simulator.** A simulator (#25) emits Captures in the logger format
plus a positions file with ground truth, from a ray model for CSI,
log-distance path loss for RSSI, a per-device nuisance term (gain offset and
spectral tilt) and both sporadic and steady transmitters. Because it writes
the same format the Gateway lands, simulated and real Trials are
interchangeable everywhere downstream.

**Radio map.** Built from a Calibration session's windows joined to a
positions file: one stored feature vector per (Reference point, Anchor).

**Baseline = k-NN.** k = 3, inverse-distance weighted, on the concatenated
per-Anchor `[z-scored RSSI, D-CFR]` vector. The RSSI and D-CFR blocks get
equal weight. An Anchor missing from a window is imputed at its floor value
(RSSI floor, zero D-CFR) rather than dropping the window.

**Scout = MDN.** Inputs: four smoothed RSSI values plus a four-bit presence
mask. Output: a mixture of K = 3 diagonal Gaussians over (x, y). The 95 %
bounding box is taken by sampling the mixture. Trained on the reference grid,
augmented with path-loss perturbations so it does not memorise one device's
gain. When the Sniper does not run, the estimate is the bbox centre.

**Sniper = particle filter.** Particles are confined to the Scout's bbox.
Each particle looks up the D-CFR of its nearest Reference point; per-Anchor
Pearson ρ against the live window's D-CFR is fused as
`w = ∏ exp(ρ / σ)` over the Anchors present. Particles are resampled across
consecutive windows of a stationary target, so the estimate tightens over a
Trial instead of restarting each window.

**Fallback rule.** The Sniper runs only when, in the window:

- at least `min_anchors` Anchors have ≥ 3 valid CSI packets,
- each of those Anchors' within-window D-CFR stability is ≥ 0.6, and
- each of those Anchors' RSSI is above the floor, initially −80 dBm.

Otherwise the window's Mode is `fallback` and the Scout's bbox centre is the
estimate. Mode is logged per window and the fallback rate is a reported
metric, not hidden. The 0.6 stability threshold sits between the ≈ 0.75 seen
on the −65 dBm device and the ≈ 0.1 seen on ambient devices in the 2026-08-28
capture; the −80 dBm floor is where that capture's stability collapsed.
Both are initial values that #23's stability distribution and the ablations
in #29 are expected to refine.

**D-CFR justification.** D-CFR is used because differencing adjacent
subcarriers removes per-packet amplitude offset and linear tilt (scale is
already removed by normalization in `gateway/csi.py`). It is *not* claimed as
CFO/SFO cancellation — the thesis text is reworded to match (#31). The claim
is validated by an ablation of D-CFR against raw normalized amplitude (#29).

## Consequences

- #25 (simulator), #26 (radio map + k-NN), #27 (MDN), #28 (particle filter +
  fallback) and #29 (ablations) implement exactly the parameters above; a
  change to any of them is a change to this ADR.
- #23 must emit the per-Anchor stability score and above-floor flag, since
  the fallback rule cannot be evaluated without them.
- The fallback rate becomes a first-class result. A Trial where the Sniper
  never runs is a valid, reportable outcome, not a failed Trial.
- Single-antenna CSI means every Anchor contributes one D-CFR vector per
  packet; the design relies on multi-Anchor fusion and temporal resampling
  for precision, not on per-Anchor angle information.
- Device heterogeneity is addressed by z-scoring RSSI, by D-CFR's removal of
  offset/tilt, and by the path-loss augmentation of the Scout; the remaining
  cross-device gap is measured, not assumed away (see ADR-0003).
