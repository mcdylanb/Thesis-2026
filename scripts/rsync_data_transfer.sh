#!/bin/bash

# Define connection variables
PI_USER="pi-b-thesis"
PI_IP="192.168.50.190"
REMOTE_DIR="test_data/"
LOCAL_DIR="test_data/"

# Define the delay between syncs (in seconds)
# 2 seconds is a good balance for near real-time updates without spamming SSH connections
SYNC_DELAY=2

echo "==================================================="
echo " Starting continuous rsync from ${PI_USER}@${PI_IP}"
echo " Press [CTRL+C] to stop."
echo "==================================================="

# Infinite loop to keep syncing
while true; do
    # Execute the rsync command
    rsync -avz -e ssh "${PI_USER}@${PI_IP}:${REMOTE_DIR}" "${LOCAL_DIR}"
    
    # Wait before the next poll
    sleep $SYNC_DELAY
done
