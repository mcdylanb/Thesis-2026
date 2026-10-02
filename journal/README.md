# Development Journal

Chronological record of decisions, issues, fixes, and setup steps for the
hybrid RSSI–CSI localization system.

## Entry convention

- One file per working session, named `YYYYMMDD.md`.
- Each entry has, in order:
  1. **Summary** — a few sentences on what the session accomplished.
  2. **Log** — chronologically ordered bullets of what happened.
  3. **Issues & Fixes** — problems encountered and how they were resolved.
  4. **Setup / Reproduce** — the concrete steps to repeat the work.
  5. **Next Action Items** — what to do next.

## Index

- [20260713](20260713.md) — Firmware (ESP-IDF + Arduino) and gateway preprocessing pipeline built and verified on synthetic data.
- [20260717](20260717.md) — First real two-anchor hardware capture; CSI debugging; corrupt subcarrier +1 found and fixed.
- [20260918](20260918.md) — First wireless Anchor → Relay → Gateway capture on the MP700; 921600→115200 fix; Anchor found to be sniffing the Relay itself.
- [20261002](20261002.md) — Spatial simulator (#25); Radio map, evaluation harness and k-NN baseline (#26): first accuracy number on simulated data; per-Anchor stability score and RSSI-floor flag (#23); legacy Capture reader (#24 part 1); MDN Scout (#27); Sniper, fallback rule and proposed pipeline (#28).
