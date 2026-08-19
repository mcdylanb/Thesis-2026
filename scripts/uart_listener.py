import serial
import time
import os

# Ensure the data directory exists exactly where the laptop sync script expects it
save_dir = os.path.expanduser("~/Desktop/Thesis-2026/data")
os.makedirs(save_dir, exist_ok=True)

filename = os.path.join(save_dir, f"csi_capture_{int(time.time())}.csv")

SERIAL_PORT = '/dev/ttyUSB0' 
BAUD_RATE = 115200

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    ser.flush()

    print(f"Listening on {SERIAL_PORT} at {BAUD_RATE} baud...")
    print(f"Saving data to: {filename}")

    with open(filename, "a") as f:
        # Basic header
        f.write("Raw UART Stream\n")

        while True:
            if ser.in_waiting > 0:
                # 'errors=replace' prevents crashes if a malformed byte slips through
                line = ser.readline().decode('utf-8', errors='replace').rstrip()
                if line:
                    f.write(f"{line}\n")
                    f.flush() 
                    print(f"Saved: {line}")

except serial.SerialException as e:
    print(f"Connection error: {e}")
except KeyboardInterrupt:
    print("\nData collection stopped by user. Exiting...")

