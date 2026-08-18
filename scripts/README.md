# Live Data Sync Pipeline Setup (Raspberry Pi -> Laptop)

This pipeline streams raw CSI/RSSI data captured on the Raspberry Pi directly to the Laptop over Wi-Fi using `rsync` over SSH.

---

## System Architecture & Directory Structure

```text
Thesis-2026/
|--- data/                          <-- Local CSV storage (Ignored by Git)
|--- scripts/
|       |--- rsync_data_transfer.sh <-- Live syncing script
|--- .gitignore                     <-- Contains 'data/' entry
```

* **Code (Git):** Synced across devices via GitHub.
* **Data (rsync):** Pulled directly from Pi (`~/Desktop/Thesis-2026/data/`) into Laptop (`Thesis-2026/data/`).

---

## One-Time Setup Instructions

### 1. Configure Passwordless SSH Access
Because the laptop continuously polls the Pi, passwordless SSH login must be configured within the **WSL/Bash** environment on the laptop.

Run these commands in PowerShell (or Git Bash):

```bash
# Step A: Generate an SSH key pair inside the Linux environment
bash -c "ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ''"

# Step B: Transfer the public key to the Pi (Type the Pi password 'passwordb' when prompted)
bash -c "ssh-copy-id pi-b-thesis@192.168.50.190"

# Step C: Test passwordless login
bash -c "ssh pi-b-thesis@192.168.50.190 'echo Connection successful!'"
```

---

## Running the Data Sync Script

1. Navigate to the `scripts` directory on your laptop:
   ```bash
   cd scripts
   ```

2. Fix line endings if editing on Windows:
   ```bash
   sed -i 's/\r$//' rsync_data_transfer.sh
   ```

3. Launch the syncing daemon:
   ```bash
   bash rsync_data_transfer.sh
   ```

To stop syncing at any time, press **`Ctrl + C`**.

