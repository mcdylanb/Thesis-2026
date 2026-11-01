---
status: accepted
date: 2026-09-18
---

# Calibration and evaluation protocol

## Context

ADR-0002 fixes the localizers; this ADR fixes how the Radio map is built and
how the proposed pipeline is compared to the baseline, so the numbers in the
results chapter come from a protocol written down before the data existed.

Two facts from the 2026-08-28 two-anchor capture shape the protocol. First,
ambient devices transmit at 0.02–0.2 frames/s, so a 1 s window frequently
holds zero or one Record from them and the Sniper's "≥ 3 valid CSI Records"
precondition cannot be met; a controlled steady transmitter is needed for
calibration. Second, stability fell to ρ ≈ 0.0–0.1 at −85 dBm and below,
which bounds how far a target can be from the Anchors before the Sniper stops
running.

## Decision

**Hardware: six ESP32s.** Four Anchors (A1–A4), one Relay, and one
**Beacon** — an ESP32 on a USB power bank transmitting at a steady rate from
a fixed MAC. The Beacon is the calibration transmitter and the primary test
target (#30).

**Reference grid.** The Radio map is built from a dense grid of Reference
points at roughly 1 m spacing across the trial area.

**Test positions P1–P10 are held out.** They are never Reference points and
never used to fit the Scout; they are chosen off-grid so that k-NN cannot
score by coincidence. This is the Horus protocol (Youssef & Agrawala 2005
§7.1: test locations that never coincide with a training point).

**Calibration and test are run on separate occasions.** The Calibration
session and the test Trials happen on different days so that Radio map drift
is inside the measurement, not excluded from it — again Horus §7.1 (test set
"collected by different persons on different days"), and the drift itself is
documented in RADAR's technical report (Bahl & Padmanabhan MSR-TR-2000-12
§6.2: one human body ≈ 3.5 dB). Each Test position gets ≥ 3
Trials, and each Trial must yield ≥ 30 sufficient windows — windows in which
≥ `min_anchors` Anchors have at least one Record, i.e. windows the
preprocess keeps — or it is repeated. A sufficient window may still be in
`fallback` Mode; sufficiency is about coverage, not Sniper eligibility.

**Same-device plus one cross-device Trial.** The main comparison uses the
Beacon for both calibration and test. One additional Trial uses a different
transmitter (a phone, or a second ESP32); the gap between same-device and
cross-device error is reported as a result, not hidden or averaged away.
Device diversity is a known, quantified effect (Haeberlen et al. 2004;
Kjærgaard & Munk 2008; Kjærgaard 2011); the single cross-device Trial
measures it here, and ADR-0002's within-window RSSI z-scoring is the
mitigation.

**Window length is a Trial parameter.** ≈ 1 s for the Beacon; 5–10 s for
sporadic ambient targets so that a window has a chance of holding the ≥ 3
Records the Sniper needs at the measured 0.02–0.2 frames/s.

**Anchor placement.** Anchors are placed so that every Test position keeps
the target above the Sniper's RSSI floor (−80 dBm initially) at ≥
`min_anchors` Anchors; a layout that cannot do this is changed before Trials
begin, not compensated for afterwards.

**Success criteria and reported metrics.** The proposed pipeline is judged
successful if coarse-zone accuracy is ≥ ~90 % and its median error beats the
baseline's in the 1–2 m range. In addition, every Trial reports MAE, RMSE,
p90 error, fallback rate and per-window latency, for both pipelines.

## Consequences

- #30 delivers the Beacon firmware and the Calibration session runbook; its
  positions file is what #26's Radio map builder reads.
- The evaluation harness (#26, #29) must keep Test positions and Reference
  points in separate files so held-out status is enforced by construction.
- A Test position whose Trials cannot reach ≥ 30 sufficient windows is a
  placement or floor problem and is fixed in the layout (#25's trial layout
  file), not by lowering the threshold silently; any threshold change goes
  through ADR-0002.
- The cross-device Trial may show the proposed pipeline losing its advantage;
  that is a valid finding and is written up as such.
- Calibration takes real time: ~1 m grid over the trial area × window length
  × enough windows per point. The runbook in #30 must budget for it. Horus
  used 1.52–2.13 m grids and FILA room-scale testbeds of 3×4 m and 5×8 m, so
  ~1 m is at the dense end of precedent, not outside it.
- The precedents above are traced to primary sources in
  `docs/research/2026-09-18-adr-0002-0003-validation.md`; the citation keys
  are in `thesis/references.bib`.

## Amendments

**2026-11-01, Reference grid spacing (TechHub, #44).** The TechHub
Calibration session used a 1.2 m lattice (every second 60 cm floor tile),
not the "roughly 1 m" above: 62 Reference points over 12 × 6 m, which at
a median 6.4 min per point took two days. 1.2 m is still denser than Horus's
1.52–2.13 m grids, so the precedent argument above holds. The spacing does
coarsen what leave-one-out and the Radio map can resolve, so a median error
near 1.2 m is not evidence of a better localizer.

**2026-11-02, Trial area and Anchor layout for the recapture (#49).** The
TechHub pilot (four corner Anchors, 12 × 6 m) met the placement rule above
at 1 of 62 Reference points. Fitting its RSSI against distance
(`make layout-search`, `out/techhub/layout_search/summary.md`) gives one
Anchor a range of 3.9 m at the −80 dBm floor (2.9 m with a 3 dB margin;
shadowing sd 4.5 dB). By that range the whole room needs about 11 Anchors
placed in and around it, or 13 on the walls, while four Anchors cover at
most about 4.8 × 4.8 m. We keep the six-ESP32 hardware above and shrink the
trial area: **4.8 × 4.8 m inside TechHub, the four Anchors on stands in a
2.4 m square, 1.2 m in from every edge** (`layouts/techhub_trial_4p8.yaml`).
Placed in that area's corners the same Anchors meet the rule over 20 % of
it, at its wall midpoints 67 %, in this square 100 %. 21 Reference points on
the 1.2 m lattice. The area is within FILA's 3 × 4 m to 5 × 8 m room-scale
testbeds. The −80 dBm floor and `min_anchors = 3` are unchanged (ADR-0002).
Limitation to report: the system needs every position within about 4 m of
3 Anchors, so a larger room needs more Anchors (about one per 6 m² of floor
here). The area's corners and edge midpoints sit right at the floor by the
model, so some will be weak on the day: the live checker (#50) shows which,
and there the Sniper falls back to the Scout by design.
