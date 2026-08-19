import serial
import os
from datetime import datetime

# Ensure the data directory exists
save_dir = os.path.expanduser("~/Desktop/Thesis-2026/data")
os.makedirs(save_dir, exist_ok=True)

SERIAL_PORT = '/dev/ttyUSB0' # Update if your Pi uses a different port
BAUD_RATE = 921600

# Dictionary to manage multiple file streams dynamically
open_files = {}

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    ser.flush()

    print(f"Listening on {SERIAL_PORT} at {BAUD_RATE} baud...")
    print(f"Waiting for CSI data... Files will be auto-generated in: {save_dir}")

    while True:
        if ser.in_waiting > 0:
            # Read line, decode, and strip whitespace
            line = ser.readline().decode('utf-8', errors='replace').rstrip()
            
            # Filter strictly for CSI data (drops headers, STAT, and INFO lines)
            if line.startswith("CSI,"):
                parts = line.split(',')
                if len(parts) > 2:
                    anchor_id = parts[1]  # Extracts 'A1', 'A2', etc.
                    
                    # If this is the first packet from this anchor, create its file
                    if anchor_id not in open_files:
                        # Generate the timestamp in YYYYMMDD_HHMMSS format
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        
                        # Build the exact filename: e.g., A1_20260717_030353.csv
                        filename = os.path.join(save_dir, f"{anchor_id}_{timestamp}.csv")
                        
                        # Open the file and store the handle
                        open_files[anchor_id] = open(filename, "a")
                        print(f"\n[+] Created new file for {anchor_id}: {filename}")
                    
                    # Write the raw CSI row directly to the appropriate anchor's file
                    f = open_files[anchor_id]
                    f.write(f"{line}\n")
                    f.flush() # Force write to disk so rsync can pick it up immediately
                    
except serial.SerialException as e:
    print(f"Connection error: {e}")
except KeyboardInterrupt:
    print("\nData collection stopped by user. Closing files...")
finally:
    # Safely close all open files when the script is stopped
    for f in open_files.values():
        f.close()
    print("Exited cleanly.")

