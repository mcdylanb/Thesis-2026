---
status: accepted
date: 2026-09-18
---

# The laptop is the Gateway; the Raspberry Pi is retired

The system was always ESP32 Anchors plus a laptop. A Raspberry Pi was
introduced only as a way to capture wirelessly: it sat next to the Relay on
USB, wrote Captures locally, and a laptop pulled them over rsync/SSH. The
Relay now uplinks the same line stream over WiFi UDP on the trial network, so
the laptop receives Captures directly and the Pi adds a device, an SSH setup,
and a sync loop for nothing. We dropped it: the **Gateway is the laptop**
running the UDP listener, and the wireless goal is met without extra hardware.

## Consequences

- `scripts/rsync_data_transfer.sh` and the Pi SSH instructions in
  `scripts/README.md` stay in the repo as **legacy** until the team decides
  their fate in the file inventory (see `docs/INVENTORY.md`). They are not
  part of any quickstart.
- The Pi's hardcoded IP/user/password in those files is a separate, still
  open team decision about secret handling; it is not addressed here.
- Whoever captures must give their laptop the static `GATEWAY_IP` the Relay
  is flashed with, on a hotspot named after the trial network.
