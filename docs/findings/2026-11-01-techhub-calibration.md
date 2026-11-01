# Findings: TechHub Calibration session (29-30 Oct 2026)

Status: **the session works as a pilot, not as the final Radio map.** The Anchor
layout must change before the Test-position day (ADR-0003), so the Calibration
session will be recorded again. Work is tracked in **GitHub issue #57**
(tracking) and its sub-issues #49-#56.

Every number below comes from a generated file; regenerate them with
`make import-session calibration-report trim-ablation calibration-plots`
(raw zips under `data/4-sniffer-1-beacon-mode-irl/compiled_data/`, gitignored).

| File | What it holds |
|---|---|
| `out/techhub/report/report.md` (`report.json`) | holes, Anchor coverage, above-floor rate, Sniper eligibility, distance fit, day table |
| `out/techhub/trim_ablation/summary.md`, `recordings.csv` | trimmed vs untrimmed, recording lengths, leave-one-out |
| `out/techhub/plots/*.png` / `*.pdf` | heatmaps over the room: RSSI per Anchor, coverage, leave-one-out error |
| `thesis/sections/appendix.tex`, Appendix H | the write-up of all of this |

## Setup

12 x 6 m room, four Anchors at the corners (A1 (0, 6), A2 (12, 6), A3 (12, 0),
A4 (0, 0)), Beacon `68:fe:71:fa:df:fc`, 62 Reference points on a 1.2 m lattice
(p1-p62, `layouts/techhub_default.yaml`). Day 1: p1-p28, day 2: p29-p62.

## Findings

1. **The Sniper almost never runs with this layout (the main finding).**
   Only 0.5 % of Beacon windows have >= 3 Anchors above the -80 dBm floor
   (`report.md`). Only p56 has 3 Anchors above the floor in most windows;
   most of the room has 0-1 (`plots/coverage.png`). Tested on the
   current data, the comparison would be k-NN vs the Scout, nearly always
   with the Sniper skipped.
2. **It is a distance problem.** Share of (point, Anchor) pairs whose median
   RSSI clears -80 dBm, by distance to the Anchor: 0-2 m 100 %, 2-4 m 81 %,
   4-6 m 28 %, 6-8 m 16 %, >= 8 m <= 5 %. Rule of thumb: **every point needs 3
   Anchors within about 4 m.** The 15 hardest points (p3, p5, p6, p7, p14-p17,
   p24, p26-p28, p35, p37, p39) all lie in the middle band x = 3.6-8.4 m,
   farthest from every corner; none has even one Anchor above the floor.
   (Computed from `report.json`; not yet a generated output, see the layout
   issue.)
3. **Relaxing the thresholds does not rescue it.** On the same windows, >= 3
   Anchors above -85 dBm: 12 %; above -88 dBm: 23 % (raw RSSI, quick
   check). Below about -85 dBm the CSI is too unstable anyway (ADR-0003, the
   August capture), and any threshold change needs an ADR-0002 amendment.
4. **Calibration cannot fix weak signal**; it only records it. Swapping
   Anchors between corners keeps the same distances, so it does not help. It
   only tells whether a fault belongs to the board or the spot. Turning or
   raising antennas may gain a few dB: enough for the -80 to -82 dBm points,
   not for the middle of the room (down to -89 dBm).
5. **Holes.** 9 points have < 30 sufficient windows: p10, p12, p20, p22, p23,
   p46, p47, p54, p57. Four have none (p10, p20, p23, p57) and are in
   neither Radio map.
6. **A1 faults** at p28, p47, p53, p57, p61 (field notes; the data cannot
   tell a fault from range). Fix A1 before the next session.
7. **Trimming makes no difference.** Median |change in RSSI| 0.05 dB, max
   2.16 dB; D-CFR and amplitude change about 0.007. A ~5 min recording per
   point (30 s settle + 4 min kept) is enough. Median recording was 6.4 min,
   and the longest were p3 16 min, p5 23.6 min, p21 17.4 min and p37 42.2 min.
8. **Leave-one-out k-NN** (sanity check only, not an accuracy result):
   median 1.84 m trimmed, 2.11 m untrimmed, over 58/62 points. It is close to
   the 1.2 m grid spacing, so it says little about real accuracy.
9. **Overnight drift is small**: -1 to +3 dB for fixed-MAC ambient devices
   (-8 dB for one at A1). The A3/A4 Beacon hear rate rose on day 2 (62 -> 96 %,
   70 -> 93 %), but day-2 points are nearer those Anchors.
10. **Walk order verified**: median RSSI vs log distance, r = -0.78 over 224
    pairs.

## What carries over to the next session

- The distance curve above, to pick the new layout in the simulator first.
- A ~5 min recording per point, the toolchain (one `make` line per step),
  and checking each day's results the same evening while the Anchors are
  still in place.
- This session itself, as the pilot that justified the final layout
  (Appendix H).

## Open decisions (humans)

- Trial area and Anchor count/positions. The trade-off: a smaller area or
  more Anchors. With 4 corner Anchors only about 3.6 x 3.6 m meets the
  rule of thumb above.
- Fix or replace A1; build extra Anchors if the chosen layout needs them.
- Whether to report the current layout's Sniper result as a finding (it is
  one either way).

## Process for the next capture

1. The co-author runs the live point checker during each point (#50,
   `make check-point`) to see whether 3 Anchors clear -80 dBm before moving on.
2. Upload the day's zips the same day; the report and plots run that evening.
3. Recapture holes the next morning, before anything is moved.
4. Do not move the Anchors between Calibration and the Test-position day.
   Measure and photograph their positions.

## Tracking

#57 tracks the path, in this order: #49 simulate layout -> #50 live checker,
#51 hardware, #52 Test positions -> #53 capture day (pilot gate, then full
Calibration) -> #54 Test-position day -> #55 evaluation -> #56 thesis.
