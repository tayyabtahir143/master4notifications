#!/usr/bin/env python3
"""
MX Master 4 haptic panel → GNOME Activities overview.

Fully self-contained HID++ approach:
  1. Finds the MX Master 4 Bolt receiver hidraw device
  2. Queries the REPROG_CONTROLS_V4 (0x1B04) feature index
  3. Diverts button CID 0x01A0 (haptic sense panel) to software
  4. Listens for divertedButtonsEvent and toggles GNOME Activities

No keyboard keys are used at any point, so XF86AudioMicMute or any
other unintended key action is physically impossible.
"""
import os
import select
import subprocess
import time
import logging
import sys

sys.path.insert(0, os.path.dirname(__file__))
from mx_master_4 import MXMaster4

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

REPROG_CONTROLS_V4_ID = 0x1B04
HAPTIC_PANEL_CID      = 0x01A0
SW_ID                 = 0x09   # arbitrary software ID for our HID++ requests


def _read_matching(fd, device_idx, feature_idx, timeout=2.0):
    """Read HID++ reports until we get one matching device_idx and feature_idx."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        r, _, _ = select.select([fd], [], [], remaining)
        if not r:
            break
        data = os.read(fd, 20)
        if len(data) >= 3 and data[1] == device_idx and data[2] == feature_idx:
            return data
    return None


def get_feature_index(fd, device_idx, feature_id):
    """IRoot.getFeature(feature_id) → runtime feature index, or None."""
    pkt = bytes([0x10, device_idx, 0x00, SW_ID,
                 (feature_id >> 8) & 0xFF, feature_id & 0xFF, 0x00])
    os.write(fd, pkt)
    # Response: [report_id, device_idx, 0x00, SW_ID, feat_idx, obsolete, sw_feat_id_hi, ...]
    for _ in range(12):
        r, _, _ = select.select([fd], [], [], 2.0)
        if not r:
            break
        data = os.read(fd, 20)
        if len(data) < 5 or data[1] != device_idx:
            continue
        if data[2] == 0x8F:
            return None   # error — feature not supported
        if data[2] == 0x00 and data[3] == SW_ID:
            return data[4] if data[4] != 0 else None
    return None


def divert_button(fd, device_idx, reprog_idx, cid, enable):
    """setControlIdReporting: divert (enable=True) or un-divert (enable=False) a CID."""
    flags = 0x01 if enable else 0x00
    pkt = bytes([0x11, device_idx, reprog_idx, (3 << 4) | SW_ID,
                 (cid >> 8) & 0xFF, cid & 0xFF, flags,
                 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    os.write(fd, pkt)
    resp = _read_matching(fd, device_idx, reprog_idx, timeout=3.0)
    if resp:
        confirmed_flags = resp[6] if len(resp) > 6 else '?'
        logging.info("Button 0x%04X diversion %s (flags=0x%02X confirmed)",
                     cid, "enabled" if enable else "disabled", confirmed_flags)
        return True
    logging.warning("No response to setControlIdReporting for CID=0x%04X", cid)
    return False


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


def run(path, device_idx):
    fd = os.open(path, os.O_RDWR)
    reprog_idx = None
    try:
        # Find REPROG_CONTROLS_V4 feature index
        reprog_idx = get_feature_index(fd, device_idx, REPROG_CONTROLS_V4_ID)
        if not reprog_idx:
            raise RuntimeError("REPROG_CONTROLS_V4 feature not found on device")
        logging.info("REPROG_CONTROLS_V4 feature index: 0x%02X", reprog_idx)

        # Divert haptic panel button to us
        divert_button(fd, device_idx, reprog_idx, HAPTIC_PANEL_CID, enable=True)

        logging.info("Monitoring haptic panel (CID=0x%04X)...", HAPTIC_PANEL_CID)

        cid_hi = (HAPTIC_PANEL_CID >> 8) & 0xFF
        cid_lo = HAPTIC_PANEL_CID & 0xFF

        while True:
            r, _, _ = select.select([fd], [], [], 2.0)
            if not r:
                continue
            data = os.read(fd, 20)

            # divertedButtonsEvent: device_idx, reprog_idx, func nibble=0, CID in bytes 4-5
            if (len(data) >= 6 and
                    data[1] == device_idx and
                    data[2] == reprog_idx and
                    (data[3] & 0xF0) == 0x00 and
                    data[4] == cid_hi and
                    data[5] == cid_lo):
                logging.info("Haptic panel pressed — toggling overview")
                toggle_overview()

    finally:
        if reprog_idx:
            try:
                divert_button(fd, device_idx, reprog_idx, HAPTIC_PANEL_CID, enable=False)
            except Exception:
                pass
        os.close(fd)


def main():
    logging.info("mx4-overview starting...")
    while True:
        mx = MXMaster4.find()
        if not mx:
            logging.warning("MX Master 4 not found — retrying in 5s...")
            time.sleep(5)
            continue
        logging.info("Found MX Master 4: %s device_idx=%d", mx.path, mx.device_idx)
        try:
            run(mx.path, mx.device_idx)
        except Exception as e:
            logging.warning("Error: %s — reconnecting in 3s", e)
            time.sleep(3)


if __name__ == '__main__':
    main()
