#!/usr/bin/env python3
"""
Monitors MX Master 4 haptic panel via HID++ protocol directly.

Reads raw HID++ reports from the Bolt receiver hidraw device — no keyboard
keys involved at any point, so there is zero risk of XF86AudioMicMute
or any other unintended key action leaking to X11.

Requires logid to divert CID 0x01a0 with NoAction so the device sends
HID++ divertedButtonsEvent reports instead of native SmartShift toggle.
"""
import os
import select
import subprocess
import time
import logging
import sys

# Add src dir so we can reuse MXMaster4.find() for device discovery
sys.path.insert(0, os.path.dirname(__file__))
from mx_master_4 import MXMaster4

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# CID 0x01a0 = haptic sense panel on MX Master 4
BUTTON_CID_HI = 0x01
BUTTON_CID_LO = 0xa0


def toggle_overview():
    result = subprocess.run([
        'gdbus', 'call', '--session',
        '--dest', 'org.gnome.Shell',
        '--object-path', '/org/gnome/Shell',
        '--method', 'org.freedesktop.DBus.Properties.Get',
        'org.gnome.Shell', 'OverviewActive'
    ], capture_output=True, text=True)
    active = 'true' in result.stdout
    new_state = 'false' if active else 'true'
    subprocess.run([
        'gdbus', 'call', '--session',
        '--dest', 'org.gnome.Shell',
        '--object-path', '/org/gnome/Shell',
        '--method', 'org.freedesktop.DBus.Properties.Set',
        'org.gnome.Shell', 'OverviewActive', f'<{new_state}>'
    ])


def monitor(path, device_idx):
    """
    Open hidraw device read-only and watch for divertedButtonsEvent for CID 0x01a0.

    HID++ 2.0 divertedButtonsEvent format:
      byte[0] : report_id (0x11 short / 0x12 long)
      byte[1] : device_index
      byte[2] : feature_index (REPROG_CONTROLS_V4, varies by firmware)
      byte[3] : (function_idx << 4) | sw_id  — function 0 = divertedButtonsEvent
      byte[4] : CID high byte of first pressed button (0x00 = released)
      byte[5] : CID low byte of first pressed button
    """
    fd = os.open(path, os.O_RDONLY)
    logging.info("Monitoring %s device_idx=%d for haptic panel (CID=0x01A0)...", path, device_idx)
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 2.0)
            if not r:
                continue
            data = os.read(fd, 20)
            if (len(data) >= 6 and
                    data[0] in (0x11, 0x12) and
                    data[1] == device_idx and
                    data[4] == BUTTON_CID_HI and
                    data[5] == BUTTON_CID_LO):
                logging.info("Haptic panel pressed — toggling overview")
                toggle_overview()
    finally:
        os.close(fd)


def main():
    logging.info("mx4-overview starting (HID++ direct mode)...")
    while True:
        mx = MXMaster4.find()
        if not mx:
            logging.warning("MX Master 4 not found — retrying in 5s...")
            time.sleep(5)
            continue

        logging.info("Found MX Master 4 at %s device_idx=%d", mx.path, mx.device_idx)
        try:
            monitor(mx.path, mx.device_idx)
        except Exception as e:
            logging.warning("Monitor error: %s — reconnecting in 3s", e)
            time.sleep(3)


if __name__ == '__main__':
    main()
