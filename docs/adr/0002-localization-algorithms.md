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
Anchor), and Radio map drift between calibration and test.

We now have a first real dataset to size thresholds against: the 2026-08-28
two-anchor capture (`data/A1_20260828_140440.csv`, `A2_20260828_140440.csv`;
3,760 CSI Records, 66 MACs). In it, one strong device at −65 dBm gives a
within-window D-CFR stability (median pairwise Pearson ρ between the D-CFR
vectors of the window's Records) of ≈ 0.75–0.8, while ambient devices at
−85 dBm and below give ρ ≈ 0.0–0.1 at 0.02–0.2 frames/s. That gap is what every threshold below is
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

**Baseline = k-NN.** k = 3, inverse-distance weighted (the RADAR setting,
Bahl & Padmanabhan 2000 §4.1.2), on the concatenated per-Anchor
`[z-scored RSSI, D-CFR]` vector. RSSI is z-scored *within the window across
the four Anchors* (mean and sd over the Anchors present), which cancels a
per-device gain offset the way Kjærgaard's ratio fingerprints do; z-scoring
per feature over the Radio map would not. The RSSI block (4 dims) and the
D-CFR block (≈ 4 × 63 dims) get *equal total weight*: each block is scaled by
1/√dim so neither dominates the Euclidean distance (unscaled, D-CFR would
outweigh RSSI ≈ 50:1). The D-CFR block is mean-centred per Anchor so the
baseline, like the Sniper, is tilt-invariant (see the D-CFR paragraph). An
Anchor missing from a window is imputed at its floor value (RSSI floor, zero
D-CFR) rather than dropping the window.

**Scout = MDN.** Inputs: four smoothed RSSI values plus a four-bit presence
mask. Output: a mixture of K = 3 diagonal Gaussians over (x, y), in Bishop's
(1994) form — softmax mixing coefficients, `exp` variances, negative
log-likelihood loss with a variance floor and log-sum-exp for stability;
Qian et al. (2019) is the WiFi-RSSI precedent. The 95 % bounding box is taken
by sampling the mixture. Trained on the reference grid, augmented with
path-loss perturbations so it does not memorize one device's gain. When the
Sniper does not run, the estimate is the *mean of the most probable kernel*,
not the bbox center or the mixture mean: Bishop warns that the mean of a
multimodal mixture can fall between modes, in a place the target cannot be.

**Sniper = particle filter.** Particles are confined to the Scout's bbox.
Each particle looks up the D-CFR of its nearest Reference point; per-Anchor
Pearson ρ against the live window's D-CFR is fused as
`w = ∏ exp(ρ / σ)` over the Anchors present. The product of per-Anchor
Pearson correlations as a location likelihood follows FILA (Wu et al. 2013,
Eq. 10–11); the `exp(ρ / σ)` form — a softmax over Σρ with temperature σ — is
this work's surrogate and has no direct precedent. Particles are resampled
across consecutive windows of a stationary target, so the estimate tightens
over a Trial instead of restarting each window. σ is tuned in #28 on
simulated Trials; it is not fixed here.

**Fallback rule.** An Anchor is *Sniper-ready* in a window when it has ≥ 3
valid CSI Records, its within-window D-CFR stability is ≥ 0.6, and its RSSI
is above the floor, initially −80 dBm. The Sniper runs only when at least
`min_anchors` Anchors are Sniper-ready (`min_anchors` is the preprocess
`--min-anchors` option, default 3); an Anchor that fails any one condition
is simply not counted, it does not veto the window. Otherwise the window's
Mode is `fallback` and the Scout's bbox center is the estimate. Mode is
logged per window and the fallback rate is a reported metric, not hidden.
The 0.6 stability threshold sits between the ≈ 0.75 seen on the −65 dBm
device and the ≈ 0.1 seen on ambient devices in the 2026-08-28 capture; the
−80 dBm floor is set 5 dB above the −85 dBm level at which that capture's
stability had collapsed. Both are initial values that #23's stability
distribution and the ablations in #29 are expected to refine. The floor is
absolute dBm for now because the Record carries only `rx_ctrl.rssi`; ESP-IDF
also exposes `rx_ctrl.noise_floor`, and once the firmware emits it the floor
should become an SNR (`rssi − noise_floor`) so it survives a change of room
or channel.

**D-CFR justification.** With `|H_k| = s·(c + t·k + m_k)` (per-Record
scale `s`, offset `c`, linear tilt `t`, multipath `m_k`), L2 normalization
in `gateway/csi.py` removes `s`, and differencing adjacent subcarriers
removes the offset `c` exactly and *converts the tilt `t` into a constant*
added to every element. Pearson ρ is affine-invariant, so the Sniper never
sees that constant; a Euclidean consumer such as the k-NN baseline does,
which is why its D-CFR block is mean-centred per Anchor. The price is a
first-difference high-pass: the firmware sets `channel_filter_en = false`, so
adjacent subcarriers carry independent noise and differencing roughly doubles
its variance. D-CFR is *not* claimed as CFO/SFO cancellation — those are
phase terms and do not touch amplitude — and it is not attributed to FILA
(`wu2012csi`), which owns normalization + Pearson, not differencing;
rewording the thesis text to match is #31. Because Pearson on raw normalized
amplitude already discards scale and offset, the ablation in #29 must include
a *raw normalized amplitude + Pearson* arm: that arm isolates what
differencing adds (tilt tolerance) against what it costs (noise). The
Record's CSI buffer is auto-scaled per frame (`manu_scale = false`), which
is the documented reason per-Record normalization is mandatory.

## Consequences

- #25 (simulator), #26 (Radio map + k-NN), #27 (MDN), #28 (particle filter +
  fallback) and #29 (ablations) implement exactly the parameters above; a
  change to any of them is a change to this ADR.
- #23 must emit the per-Anchor stability score and above-floor flag, since
  the fallback rule cannot be evaluated without them.
- The fallback rate becomes a first-class result. A Trial where the Sniper
  never runs is a valid, reportable outcome, not a failed Trial.
- Single-antenna CSI means every Anchor contributes one D-CFR vector per
  Record; the design relies on multi-Anchor fusion and temporal resampling
  for precision, not on per-Anchor angle information.
- Device heterogeneity is addressed by within-window z-scoring of RSSI (a
  dB-difference fingerprint in the sense of Kjærgaard & Munk 2008), by
  D-CFR's removal of offset and neutralization of tilt, and by the path-loss
  augmentation of the Scout; the remaining cross-device gap is measured, not
  assumed away (see ADR-0003).
- #29's ablation table has at least these arms: D-CFR + Pearson (proposed),
  raw normalized amplitude + Pearson, D-CFR + Euclidean, and an RSSI-only
  k-NN (the CSI block dropped). The RSSI-only row is not the baseline — the
  baseline is the fused RSSI+CSI k-NN above — but it lets the chapter show
  that CSI adds value on its own, separately from the coarse-to-fine claim;
  the weight sweep, cross-device and dropout rows come on top.
- The thesis compares against the fused RSSI+CSI baseline, not RSSI-only
  trilateration; `introduction.tex` objective 4 still says the latter and
  #31 must reword it to match Chapter 3.
- The rationale above is checked against primary sources in
  `docs/research/2026-09-18-adr-0002-0003-validation.md`.
