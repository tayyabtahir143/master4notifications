#!/usr/bin/env python3
"""
Intercepts KEY_F20 from LogiOps Virtual Input before X11 sees it,
and toggles GNOME Activities overview via D-Bus.
All other keys are forwarded transparently via uinput.
"""
import evdev
import subprocess
import time
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

KEY_F20 = 190  # evdev keycode for KEY_F20


def find_logid_device():
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            if 'LogiOps' in dev.name:
                return dev
        except Exception:
            pass
    return None


def toggle_overview():
    # Read current OverviewActive state
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


def main():
    # Wait for logid virtual device to appear
    device = None
    for attempt in range(20):
        device = find_logid_device()
        if device:
            break
        logging.warning("LogiOps Virtual Input not found (attempt %d/20) — retrying in 3s", attempt + 1)
        time.sleep(3)

    if not device:
        logging.error("LogiOps Virtual Input not found — giving up")
        exit(1)

    logging.info("Found: %s at %s", device.name, device.path)

    # Create a forwarding uinput device with identical capabilities
    ui = evdev.UInput.from_device(device, name='mx4-forward')

    # Grab LogiOps Virtual Input exclusively — KEY_F20 will NOT reach X11
    device.grab()
    logging.info("Device grabbed. Monitoring for KEY_F20 (haptic panel)...")

    try:
        for event in device.read_loop():
            if event.type == evdev.ecodes.EV_KEY and event.code == KEY_F20:
                if event.value == 1:  # key press only
                    logging.info("Haptic panel pressed — toggling overview")
                    toggle_overview()
                # Don't forward KEY_F20 to X11
            else:
                ui.write_event(event)
                ui.syn()
    except KeyboardInterrupt:
        pass
    finally:
        device.ungrab()
        ui.close()


if __name__ == '__main__':
    main()
