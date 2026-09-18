---
status: accepted
date: 2026-09-18
---

# Calibration and evaluation protocol

## Context

ADR-0002 fixes the localizers; this ADR fixes how the radio map is built and
how the proposed pipeline is compared to the baseline, so the numbers in the
results chapter come from a protocol written down before the data existed.

Two facts from the 2026-08-28 two-anchor capture shape the protocol. First,
ambient devices transmit at 0.02–0.2 packets/s, so a 1 s window frequently
holds zero or one packet from them and the Sniper's "≥ 3 valid CSI packets"
precondition cannot be met; a controlled steady transmitter is needed for
calibration. Second, stability fell to ρ ≈ 0.0–0.1 at −85 dBm and below,
which bounds how far a target can be from the Anchors before the Sniper stops
running.

## Decision

**Hardware: six ESP32s.** Four Anchors (A1–A4), one Relay, and one
**Beacon** — an ESP32 on a USB power bank transmitting at a steady rate from
a fixed MAC. The Beacon is the calibration transmitter and the primary test
target (#30).

**Reference grid.** The radio map is built from a dense grid of Reference
points at roughly 1 m spacing across the trial area.

**Test positions P1–P10 are held out.** They are never Reference points and
never used to fit the Scout; they are chosen off-grid so that k-NN cannot
score by coincidence.

**Calibration and test are separate sessions.** The Calibration session and
the test Trials are run on different occasions so that radio-map drift is
inside the measurement, not excluded from it. Each test position gets ≥ 3
Trials, and each Trial must yield ≥ 30 sufficient windows (windows meeting
the ADR-0002 fallback preconditions) or it is repeated.

**Same-device plus one cross-device Trial.** The main comparison uses the
Beacon for both calibration and test. One additional Trial per test position
uses a different transmitter (a phone, or a second ESP32); the gap between
same-device and cross-device error is reported as a result, not hidden or
averaged away.

**Window length is a Trial parameter.** ≈ 1 s for the Beacon; 5–10 s for
sporadic ambient targets so that a window has a chance of holding the ≥ 3
packets the Sniper needs at the measured 0.02–0.2 packets/s.

**Anchor placement.** Anchors are placed so that every test position keeps
the target above the Sniper's RSSI floor (−80 dBm initially) at ≥
`min_anchors` Anchors; a layout that cannot do this is changed before Trials
begin, not compensated for afterwards.

**Success criteria and reported metrics.** The proposed pipeline is judged
successful if coarse-zone accuracy is ≥ ~90 % and its median error beats the
baseline's in the 1–2 m range. In addition, every Trial reports MAE, RMSE,
p90 error, fallback rate and per-window latency, for both pipelines.

## Consequences

- #30 delivers the Beacon firmware and the calibration-session runbook; its
  positions file is what #26's radio map builder reads.
- The evaluation harness (#26, #29) must keep test positions and Reference
  points in separate files so held-out status is enforced by construction.
- A test position whose Trials cannot reach ≥ 30 sufficient windows is a
  placement or floor problem and is fixed in the layout (#25's trial layout
  file), not by lowering the threshold silently; any threshold change goes
  through ADR-0002.
- The cross-device Trial may show the proposed pipeline losing its advantage;
  that is a valid finding and is written up as such.
- Calibration takes real time: ~1 m grid over the trial area × window length
  × enough windows per point. The runbook in #30 must budget for it.
