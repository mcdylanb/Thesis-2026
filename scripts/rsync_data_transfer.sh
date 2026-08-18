#!/bin/bash

PI_USER="pi-b-thesis"
PI_IP="192.168.50.190"

REMOTE_DIR="Desktop/Thesis-2026/data/"
LOCAL_DIR="../data/"
SYNC_DELAY=1

echo "==================================================="
echo " Starting continuous rsync from ${PI_USER}@${PI_IP}"
echo " Syncing node files to:"
echo " ${LOCAL_DIR}"
echo " Press [CTRL+C] to stop."
echo "==================================================="

while true; do
    # Simply ignore the fingerprint and let Bash use its own native key
    rsync -avz -e "ssh -o StrictHostKeyChecking=no" "${PI_USER}@${PI_IP}:${REMOTE_DIR}" "${LOCAL_DIR}"

    sleep $SYNC_DELAY
done

