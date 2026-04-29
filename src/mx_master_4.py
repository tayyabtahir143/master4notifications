import logging

import hid

LOGITECH_VID = 0x046D
HAPTIC_FEATURE_ID = 0x19B0  # MX Master 4 HAPTIC feature (confirmed via Solaar)

# Waveforms supported on MX Master 4 (bitmask 0x0001003C confirmed via GetCapabilities).
# 0x00/0x01 exist in the spec but are NOT supported by this device — sending them
# causes the device to silently ignore the command.
WAVEFORM_SHARP_COLLISION  = 0x02  # crisp tap — good for notifications
WAVEFORM_DAMP_COLLISION   = 0x03  # softer tap
WAVEFORM_SUBTLE_COLLISION = 0x04  # very gentle
WAVEFORM_HAPPY_ALERT      = 0x05  # pleasant double-pulse — default for notifications

NOTIFICATION_WAVEFORM = WAVEFORM_HAPPY_ALERT


class MXMaster4:
    device: hid.Device | None = None

    def __init__(self, path: str, device_idx: int, haptic_feat_idx: int):
        self.path = path
        self.device_idx = device_idx
        self.haptic_feat_idx = haptic_feat_idx

    @staticmethod
    def _iroot_get_feature(dev, didx, feature_id):
        """IRoot.getFeature(feature_id) → runtime index, or None if not found/no response."""
        pkt = bytes([0x10, didx, 0x00, 0x0E,  # IRoot (feat=0), func=0 GetFeature, SW_ID=0xE
                     (feature_id >> 8) & 0xFF, feature_id & 0xFF, 0x00])
        dev.write(pkt)
        # Drain up to 8 packets — unsolicited receiver packets may arrive first
        for _ in range(8):
            resp = dev.read(20, 2000)
            if not resp:
                break
            if resp[1] != didx:
                continue  # packet for a different device on this receiver
            if resp[2] == 0x8F:  # HID++ error — feature not found or device offline
                return None
            if resp[2] == 0x00 and resp[3] == 0x0E:  # IRoot GetFeature response
                idx = resp[4]
                return idx if idx != 0 else None
        return None

    @classmethod
    def find(cls):
        """Scan every Logitech receiver on every USB port for the MX Master 4.

        Identifies the device by the presence of feature 0x19B0 (HAPTIC).
        Works regardless of which USB port the Bolt receiver is plugged into,
        and regardless of how many other Logitech devices are paired.
        """
        devices = hid.enumerate(LOGITECH_VID)
        seen = set()

        for device in devices:
            if device["usage_page"] != 65280:  # 0xFF00 = HID++ vendor page
                continue
            path_bytes = device["path"]
            path = path_bytes.decode()
            if path in seen:
                continue
            seen.add(path)

            try:
                dev = hid.Device(path=path_bytes)
                for didx in range(1, 7):
                    haptic_idx = cls._iroot_get_feature(dev, didx, HAPTIC_FEATURE_ID)
                    if haptic_idx:
                        logging.info(
                            "MX Master 4 found: %s  device_idx=%d  haptic_feat=0x%02X",
                            path, didx, haptic_idx,
                        )
                        dev.close()
                        return cls(path, didx, haptic_idx)
                dev.close()
            except Exception as e:
                logging.debug("Could not probe %s: %s", path, e)

        return None

    def __enter__(self):
        self.device = hid.Device(path=self.path.encode())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.device:
            self.device.close()

    def write(self, data: bytes):
        if not self.device:
            raise Exception("Device not open")
        self.device.write(data)

    def play_haptic(self, waveform_id: int = NOTIFICATION_WAVEFORM):
        """Play a haptic waveform on the MX Master 4.

        Supported waveform IDs (verified via Solaar GetCapabilities bitmask 0x0001003C):
          0x02 = SHARP_COLLISION   (crisp tap)
          0x03 = DAMP_COLLISION    (softer tap)
          0x04 = SUBTLE_COLLISION  (gentle tap)
          0x05 = HAPPY_ALERT       (double-pulse — default for notifications)

        Note: 0x00/0x01 exist in the HID++ spec but are NOT supported on MX Master 4.
        Sending unsupported waveforms causes silent no-op — no vibration, no error.

        Raises on device error so the caller (watch.py) can exit and systemd restarts.
        """
        if not self.device:
            raise Exception("Device not open")
        # func 4 = PlayHapticWaveform (0x40 >> 4), SW_ID=0xE
        func_sw = (4 << 4) | 0xE  # 0x4E
        pkt = bytes([0x10, self.device_idx, self.haptic_feat_idx, func_sw,
                     waveform_id, 0x00, 0x00])
        self.write(pkt)
        # Read back, skipping unsolicited packets from other devices
        for _ in range(8):
            resp = self.device.read(20, 1000)
            if not resp:
                raise Exception("No response from device (timeout)")
            if resp[1] != self.device_idx:
                continue
            if resp[2] == 0x8F:
                raise Exception(f"Device returned error: {bytes(resp[:7]).hex()}")
            break  # success echo


def demo():
    """Play each supported waveform so you can pick the one you prefer."""
    from time import sleep
    import sys

    logging.basicConfig(level=logging.INFO)

    mx = MXMaster4.find()
    if not mx:
        logging.error("MX Master 4 not found!")
        sys.exit(1)

    supported = [
        (WAVEFORM_SHARP_COLLISION,  "SHARP_COLLISION  (crisp tap)"),
        (WAVEFORM_DAMP_COLLISION,   "DAMP_COLLISION   (softer tap)"),
        (WAVEFORM_SUBTLE_COLLISION, "SUBTLE_COLLISION (gentle tap)"),
        (WAVEFORM_HAPPY_ALERT,      "HAPPY_ALERT      (double-pulse)"),
    ]

    with mx as dev:
        for wid, name in supported:
            logging.info("Waveform 0x%02X: %s", wid, name)
            dev.play_haptic(wid)
            sleep(3)


if __name__ == "__main__":
    demo()
