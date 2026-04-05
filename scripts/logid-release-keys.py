#!/usr/bin/env python3
"""Release any stuck keys on logid's uinput virtual devices.
Run this at logid stop to prevent stuck modifier keys (especially META/Super)
from persisting when logid crashes mid-gesture."""
import struct
import time
import os
import glob

# evdev event struct: timeval (8 bytes) + type (2) + code (2) + value (4) = 16 bytes (32-bit)
# or 24 bytes on 64-bit. Use the 24-byte struct for x86_64.
EV_KEY  = 1
EV_SYN  = 0
SYN_REPORT = 0
KEY_UP  = 0

# Keys that could get stuck from logid gesture button mappings
MODIFIER_KEYS = [
    125,  # KEY_LEFTMETA  (Super/Windows)
    126,  # KEY_RIGHTMETA
    29,   # KEY_LEFTCTRL
    97,   # KEY_RIGHTCTRL
    42,   # KEY_LEFTSHIFT
    54,   # KEY_RIGHTSHIFT
    56,   # KEY_LEFTALT
    100,  # KEY_RIGHTALT
    183,  # KEY_F13
    184,  # KEY_F14
]

def send_key_up(fd, keycode):
    """Send EV_KEY keyup + SYN_REPORT to an evdev fd."""
    now = time.time()
    sec = int(now)
    usec = int((now - sec) * 1e6)
    # struct input_event { struct timeval tv; __u16 type; __u16 code; __s32 value; }
    # On 64-bit Linux: timeval = 2×8 bytes, so total = 24 bytes
    ev_key_up = struct.pack('llHHi', sec, usec, EV_KEY, keycode, KEY_UP)
    ev_syn    = struct.pack('llHHi', sec, usec, EV_SYN, SYN_REPORT, 0)
    os.write(fd, ev_key_up)
    os.write(fd, ev_syn)

def release_on_device(path):
    try:
        with open(path, 'rb+', buffering=0) as f:
            fd = f.fileno()
            # Read current key state via EVIOCGKEY ioctl
            import ctypes, fcntl, array
            KEY_MAX = 0x2ff
            key_b = array.array('B', [0] * ((KEY_MAX + 7) // 8 + 1))
            EVIOCGKEY = 0x80604518  # _IOC(_IOC_READ, 'E', 0x18, KEY_MAX/8+1) on 64-bit... use simpler approach
            try:
                fcntl.ioctl(fd, 0x80604518, key_b, True)
            except OSError:
                # fallback: just send key-up for all modifiers blindly
                for k in MODIFIER_KEYS:
                    send_key_up(fd, k)
                return
            # Check which modifier keys are pressed and release them
            released = []
            for k in MODIFIER_KEYS:
                if key_b[k // 8] & (1 << (k % 8)):
                    send_key_up(fd, k)
                    released.append(k)
            if released:
                print(f"Released keys {released} on {path}")
    except Exception as e:
        print(f"Could not process {path}: {e}")

# Find all evdev event devices
for path in sorted(glob.glob('/dev/input/event*')):
    try:
        # Only process devices that have key capabilities
        with open(path, 'rb', buffering=0) as f:
            import array, fcntl
            # EVIOCGNAME
            buf = array.array('B', [0]*256)
            try:
                fcntl.ioctl(f.fileno(), 0x80ff4506, buf)
                name = bytes(buf).rstrip(b'\x00').decode('utf-8', errors='replace')
                if 'logid' in name.lower() or 'logitech' in name.lower() or 'virtual' in name.lower():
                    release_on_device(path)
            except Exception:
                pass
    except Exception:
        pass
