#!/usr/bin/env python3
"""
Intercepts KEY_F20 from LogiOps Virtual Input before X11 sees it,
and toggles GNOME Activities overview via D-Bus.
All other keys are forwarded transparently via uinput.

Loops internally when logid restarts so there is no gap where
KEY_F20 can escape to X11 and trigger XF86AudioMicMute.
"""
import evdev
import subprocess
import time
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

KEY_F20 = 190  # evdev keycode for KEY_F20


def find_logid_device(retries=60, interval=1):
    """Wait up to retries*interval seconds for LogiOps Virtual Input to appear."""
    for attempt in range(1, retries + 1):
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                if 'LogiOps' in dev.name:
                    return dev
            except Exception:
                pass
        if attempt % 5 == 0:
            logging.warning("LogiOps Virtual Input not found (attempt %d/%d)...", attempt, retries)
        time.sleep(interval)
    return None


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


def run_grab_loop(device):
    """Grab device and forward all events except KEY_F20. Returns when device disappears."""
    ui = evdev.UInput.from_device(device, name='mx4-forward')
    device.grab()
    logging.info("Device grabbed: %s at %s", device.name, device.path)
    try:
        for event in device.read_loop():
            if event.type == evdev.ecodes.EV_KEY and event.code == KEY_F20:
                if event.value == 1:  # press only
                    logging.info("Haptic panel pressed — toggling overview")
                    toggle_overview()
                # Never forward KEY_F20 to X11
            else:
                ui.write_event(event)
                ui.syn()
    except OSError:
        logging.warning("LogiOps device disappeared — waiting for logid to restart...")
    finally:
        try:
            device.ungrab()
        except Exception:
            pass
        ui.close()


def main():
    logging.info("mx4-overview starting...")
    while True:
        device = find_logid_device(retries=60, interval=1)
        if not device:
            logging.error("LogiOps Virtual Input not found after 60s — retrying...")
            continue
        run_grab_loop(device)
        # Device gone (logid restarted) — loop immediately to re-grab as fast as possible
        time.sleep(0.5)


if __name__ == '__main__':
    main()
