import logging
import os
import subprocess
import threading
import time

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi, GLib

from Xlib import X, display as xdisplay
from Xlib.protocol import event as xevent

from mx_master_4 import MXMaster4, NOTIFICATION_WAVEFORM

DEBOUNCE_SECS = 1.5
_last_trigger = 0.0
_lock = threading.Lock()


def trigger_haptic(device, source=""):
    global _last_trigger
    with _lock:
        now = time.monotonic()
        if now - _last_trigger < DEBOUNCE_SECS:
            return
        _last_trigger = now
    try:
        # Flag file tells mx-master4-menu.sh this haptic came from a notification,
        # not a physical button press — so the settings popup won't appear.
        with open("/tmp/mx4-notif-haptic", "w") as f:
            f.write(str(time.time()))
        device.play_haptic(NOTIFICATION_WAVEFORM)
        time.sleep(0.25)
        device.play_haptic(NOTIFICATION_WAVEFORM)
        logging.info("✓ Haptic triggered! [%s]", source)
    except Exception as e:
        logging.error("Device error: %s — restarting to re-discover device", e)
        os._exit(1)


# ── Layer 1: D-Bus ────────────────────────────────────────────────────────────
def dbus_thread(device):
    """Catches: notify-send, Zapzap, GTK apps, portal-based apps."""
    cmd = [
        "dbus-monitor", "--session",
        "interface='org.freedesktop.Notifications',member='Notify'",
        "interface='org.gtk.Notifications',member='AddNotification'",
        "interface='org.freedesktop.portal.Notification',member='AddNotification'",
    ]
    while True:
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )
            for line in process.stdout:
                line = line.strip()
                if "method call" in line and (
                    "member=Notify" in line or "member=AddNotification" in line
                ):
                    trigger_haptic(device, "dbus")
            process.wait()
            logging.warning("dbus-monitor exited (code %d) — restarting in 3s", process.returncode)
        except Exception as e:
            logging.warning("dbus_thread error: %s — restarting in 3s", e)
        time.sleep(3)


# ── Layer 2: X11 window monitor ───────────────────────────────────────────────
def x11_thread(device):
    """Catches: Chrome/Electron notification popups on XWayland.
    These are X11 windows with _NET_WM_WINDOW_TYPE_NOTIFICATION."""
    while True:
        try:
            dpy = xdisplay.Display(os.environ.get("DISPLAY", ":0"))
            root = dpy.screen().root
            root.change_attributes(event_mask=X.SubstructureNotifyMask)
            dpy.sync()

            NET_WM_WINDOW_TYPE = dpy.intern_atom("_NET_WM_WINDOW_TYPE")
            NET_WM_WINDOW_TYPE_NOTIFICATION = dpy.intern_atom("_NET_WM_WINDOW_TYPE_NOTIFICATION")

            logging.info("X11 monitor active — Chrome popup notifications will be caught.")

            while True:
                ev = dpy.next_event()
                if ev.type == X.CreateNotify:
                    win = ev.window
                    try:
                        prop = win.get_full_property(NET_WM_WINDOW_TYPE, X.AnyPropertyType)
                        if prop and NET_WM_WINDOW_TYPE_NOTIFICATION in prop.value:
                            trigger_haptic(device, "x11:notification-window")
                    except Exception:
                        pass
        except Exception as e:
            logging.warning("X11 monitor error: %s — restarting in 5s", e)
            time.sleep(5)


# ── Layer 3: AT-SPI ───────────────────────────────────────────────────────────
def get_atspi_bus_address():
    try:
        result = subprocess.run(
            ["gdbus", "call", "--session",
             "--dest", "org.a11y.Bus",
             "--object-path", "/org/a11y/bus",
             "--method", "org.a11y.Bus.GetAddress"],
            capture_output=True, text=True, timeout=5
        )
        addr = result.stdout.strip().strip("()',\n ")
        if addr.startswith("unix:"):
            return addr
    except Exception:
        pass
    return None


def atspi_thread(device):
    """Catches: any accessible app that creates notification/alert windows."""
    for attempt in range(10):
        addr = get_atspi_bus_address()
        if addr:
            os.environ["AT_SPI_BUS_ADDRESS"] = addr
            break
        logging.warning("Waiting for AT-SPI bus (%d/10)...", attempt + 1)
        time.sleep(3)
    else:
        logging.warning("AT-SPI bus not found — skipping AT-SPI layer")
        return

    try:
        Atspi.init()
    except Exception as e:
        logging.warning("AT-SPI init failed: %s — skipping AT-SPI layer", e)
        return

    logging.info("AT-SPI monitor active.")

    def on_window_create(event):
        try:
            role = event.source.get_role_name().lower()
            name = (event.source.get_name() or "").lower()
            app_obj = event.source.get_application()
            app = (app_obj.get_name() or "").lower() if app_obj else ""

            if role in ("notification", "alert"):
                trigger_haptic(device, f"atspi:{app}:{role}")
            elif any(w in name for w in ("notif", "new message", "new email")) and \
                 any(x in app for x in ("chrome", "chromium", "outlook", "electron")):
                trigger_haptic(device, f"atspi-name:{app}:{name[:30]}")
        except Exception:
            pass

    listener = Atspi.EventListener.new(on_window_create)
    listener.register("window:create")

    loop = GLib.MainLoop()
    loop.run()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    device = None
    for attempt in range(1, 13):  # retry up to ~60s at boot
        device = MXMaster4.find()
        if device:
            break
        logging.warning("MX Master 4 not found (attempt %d/12) — retrying in 5s", attempt)
        time.sleep(5)
    if not device:
        logging.error("MX Master 4 not found after retries — giving up")
        exit(1)

    with device as dev:
        logging.info("MX Master 4 connected!")
        logging.info("Starting 3-layer notification monitor:")
        logging.info("  Layer 1: D-Bus (system/GTK/portal apps)")
        logging.info("  Layer 2: X11 window events (Chrome/Electron popups)")
        logging.info("  Layer 3: AT-SPI accessibility events")
        logging.info("")

        for target, name in [
            (dbus_thread, "D-Bus"),
            (x11_thread, "X11"),
        ]:
            t = threading.Thread(target=target, args=(dev,), name=name, daemon=True)
            t.start()

        # AT-SPI runs in main thread (needs GLib event loop)
        try:
            atspi_thread(dev)
        except KeyboardInterrupt:
            logging.info("\nStopping...")


if __name__ == "__main__":
    main()
