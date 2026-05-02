#!/usr/bin/env python3
"""GTK4 + libadwaita GUI for MX4 Notifications — configure and manage the daemon."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

import os
import sys
import threading
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gi.repository import Gtk, Adw, GLib, Gio
from config import load as load_config, save as save_config
from mx_master_4 import (
    MXMaster4,
    WAVEFORM_SHARP_COLLISION, WAVEFORM_DAMP_COLLISION,
    WAVEFORM_SUBTLE_COLLISION, WAVEFORM_HAPPY_ALERT,
)

WAVEFORMS = [
    (WAVEFORM_SHARP_COLLISION,  "Sharp Collision",  "Crisp tap — default for notifications"),
    (WAVEFORM_DAMP_COLLISION,   "Damp Collision",   "Softer tap"),
    (WAVEFORM_SUBTLE_COLLISION, "Subtle Collision",  "Very gentle tap"),
    (WAVEFORM_HAPPY_ALERT,      "Happy Alert",       "Pleasant double-pulse"),
]

SERVICE = "mx4notifications.service"


class MX4Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("MX4 Notifications")
        self.set_default_size(680, 750)
        self.config = load_config()
        self._mx_device = None
        self._build_ui()
        # Initial status check then refresh every 5s
        self._refresh_service_status()
        GLib.timeout_add_seconds(5, self._refresh_service_status)
        threading.Thread(target=self._find_device_bg, daemon=True).start()

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scrolled.set_child(outer)

        header = Adw.HeaderBar()
        outer.append(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(16)
        content.set_margin_bottom(24)
        content.set_margin_start(16)
        content.set_margin_end(16)
        outer.append(content)

        # ── Device status ───────────────────────────────────────────────────
        device_box = Gtk.Box(spacing=8)
        device_box.set_halign(Gtk.Align.CENTER)
        self._device_dot = Gtk.Label(label="●")
        self._device_dot.add_css_class("dim-label")
        self._device_label = Gtk.Label(label="Looking for MX Master 4…")
        self._device_label.add_css_class("dim-label")
        device_box.append(self._device_dot)
        device_box.append(self._device_label)
        content.append(device_box)

        # ── Service group ───────────────────────────────────────────────────
        svc_group = Adw.PreferencesGroup()
        svc_group.set_title("Daemon Service")
        content.append(svc_group)

        svc_row = Adw.ActionRow()
        svc_row.set_title("mx4notifications.service")
        self._svc_label = Gtk.Label(label="…")
        self._svc_label.add_css_class("dim-label")
        svc_row.add_suffix(self._svc_label)
        svc_group.add(svc_row)

        btn_row = Adw.ActionRow()
        btn_row.set_title("Controls")
        btn_box = Gtk.Box(spacing=6)
        btn_box.set_valign(Gtk.Align.CENTER)

        self._btn_start = Gtk.Button(label="Start")
        self._btn_start.add_css_class("suggested-action")
        self._btn_start.connect("clicked", lambda *_: self._svc_action("start"))

        self._btn_stop = Gtk.Button(label="Stop")
        self._btn_stop.add_css_class("destructive-action")
        self._btn_stop.connect("clicked", lambda *_: self._svc_action("stop"))

        self._btn_enable = Gtk.Button(label="Enable Autostart")
        self._btn_enable.connect("clicked", lambda *_: self._svc_action("enable", "--now"))

        self._btn_disable = Gtk.Button(label="Disable Autostart")
        self._btn_disable.connect("clicked", lambda *_: self._svc_action("disable", "--now"))

        for btn in (self._btn_start, self._btn_stop, self._btn_enable, self._btn_disable):
            btn_box.append(btn)
        btn_row.add_suffix(btn_box)
        svc_group.add(btn_row)

        # ── Haptic group ────────────────────────────────────────────────────
        haptic_group = Adw.PreferencesGroup()
        haptic_group.set_title("Haptic Feedback")
        haptic_group.set_description("Vibration pattern played on each notification")
        content.append(haptic_group)

        self._waveform_radios = []
        first_radio = None
        for wid, name, desc in WAVEFORMS:
            row = Adw.ActionRow()
            row.set_title(name)
            row.set_subtitle(desc)
            radio = Gtk.CheckButton()
            if first_radio is None:
                first_radio = radio
            else:
                radio.set_group(first_radio)
            radio.set_active(self.config["waveform"] == wid)
            radio._wid = wid
            radio.connect("toggled", self._on_waveform_toggled)
            row.add_prefix(radio)
            row.set_activatable_widget(radio)
            self._waveform_radios.append(radio)
            haptic_group.add(row)

        test_row = Adw.ActionRow()
        test_row.set_title("Test Haptic")
        test_row.set_subtitle("If service is running, fires via notify-send; otherwise opens device directly")
        test_btn = Gtk.Button(label="Test Now")
        test_btn.set_valign(Gtk.Align.CENTER)
        test_btn.connect("clicked", self._on_test_haptic)
        test_row.add_suffix(test_btn)
        haptic_group.add(test_row)

        # ── Debounce group ──────────────────────────────────────────────────
        debounce_group = Adw.PreferencesGroup()
        debounce_group.set_title("Debounce")
        debounce_group.set_description("Minimum gap between consecutive haptic triggers")
        content.append(debounce_group)

        deb_row = Adw.ActionRow()
        deb_row.set_title("Debounce window")
        self._deb_val = Gtk.Label(label=f"{self.config['debounce_secs']:.1f}s")
        self._deb_val.set_width_chars(5)
        self._deb_val.set_xalign(1.0)
        deb_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 5.0, 0.1)
        deb_scale.set_value(self.config["debounce_secs"])
        deb_scale.set_draw_value(False)
        deb_scale.set_hexpand(True)
        deb_scale.set_size_request(220, -1)
        deb_scale.set_valign(Gtk.Align.CENTER)
        deb_scale.connect("value-changed", self._on_debounce_changed)
        deb_box = Gtk.Box(spacing=8)
        deb_box.set_valign(Gtk.Align.CENTER)
        deb_box.append(deb_scale)
        deb_box.append(self._deb_val)
        deb_row.add_suffix(deb_box)
        debounce_group.add(deb_row)

        # ── Layers group ────────────────────────────────────────────────────
        layers_group = Adw.PreferencesGroup()
        layers_group.set_title("Notification Layers")
        layers_group.set_description("Restart the service after changing these")
        content.append(layers_group)

        self._switches = {}
        for key, name, desc in [
            ("dbus",  "D-Bus Layer",  "notify-send, GTK apps, portal apps, Zapzap"),
            ("x11",   "X11 Layer",    "Chrome and Electron popups via XWayland"),
            ("atspi", "AT-SPI Layer", "Accessible app notification windows"),
        ]:
            row = Adw.ActionRow()
            row.set_title(name)
            row.set_subtitle(desc)
            sw = Gtk.Switch()
            sw.set_active(self.config["layers"].get(key, True))
            sw.set_valign(Gtk.Align.CENTER)
            sw._key = key
            sw.connect("state-set", self._on_layer_toggled)
            row.add_suffix(sw)
            row.set_activatable_widget(sw)
            self._switches[key] = sw
            layers_group.add(row)

        # ── Live log ────────────────────────────────────────────────────────
        log_group = Adw.PreferencesGroup()
        log_group.set_title("Live Log")
        log_group.set_description("Daemon output — last 50 lines then streaming")
        content.append(log_group)

        self._log_view = Gtk.TextView()
        self._log_view.set_editable(False)
        self._log_view.set_cursor_visible(False)
        self._log_view.set_monospace(True)
        self._log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._log_buf = self._log_view.get_buffer()

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_child(self._log_view)
        log_scroll.set_min_content_height(200)
        log_scroll.set_margin_top(4)
        log_group.add(log_scroll)

        threading.Thread(target=self._tail_logs, daemon=True).start()

        self.set_content(scrolled)

    # ── Device ──────────────────────────────────────────────────────────────

    def _find_device_bg(self):
        dev = MXMaster4.find()
        GLib.idle_add(self._on_device_result, dev)

    def _on_device_result(self, dev):
        self._mx_device = dev
        if dev:
            self._device_dot.remove_css_class("dim-label")
            self._device_dot.add_css_class("accent")
            self._device_label.set_text("MX Master 4 connected")
            self._device_label.remove_css_class("dim-label")
        else:
            self._device_label.set_text("MX Master 4 not found — check USB receiver")

    # ── Service ─────────────────────────────────────────────────────────────

    def _svc_action(self, *args):
        def run():
            subprocess.run(
                ["systemctl", "--user"] + list(args) + [SERVICE],
                capture_output=True, timeout=10,
            )
            GLib.idle_add(self._refresh_service_status)
        threading.Thread(target=run, daemon=True).start()

    def _refresh_service_status(self):
        try:
            r = subprocess.run(["systemctl", "--user", "is-active", SERVICE],
                               capture_output=True, text=True, timeout=3)
            active = r.stdout.strip() == "active"
            status_text = r.stdout.strip()
        except Exception:
            active, status_text = False, "unknown"

        try:
            r2 = subprocess.run(["systemctl", "--user", "is-enabled", SERVICE],
                                capture_output=True, text=True, timeout=3)
            enabled = r2.stdout.strip() == "enabled"
        except Exception:
            enabled = False

        self._svc_label.set_text(
            f"{status_text}  ({'autostart on' if enabled else 'autostart off'})"
        )
        self._btn_start.set_sensitive(not active)
        self._btn_stop.set_sensitive(active)
        self._btn_enable.set_sensitive(not enabled)
        self._btn_disable.set_sensitive(enabled)
        return GLib.SOURCE_CONTINUE

    # ── Haptic ──────────────────────────────────────────────────────────────

    def _on_waveform_toggled(self, radio):
        if radio.get_active():
            self.config["waveform"] = radio._wid
            save_config(self.config)

    def _on_test_haptic(self, *_):
        svc_text = self._svc_label.get_text()
        if "active" in svc_text:
            # Full pipeline test via notify-send
            subprocess.Popen(["notify-send", "MX4 Haptic Test", "Waveform test from GUI"])
        else:
            # Direct hardware test (device not held by the service)
            def direct():
                dev = MXMaster4.find()
                if dev:
                    try:
                        with dev as d:
                            d.play_haptic(self.config["waveform"])
                    except Exception as e:
                        GLib.idle_add(self._append_log, f"Test error: {e}\n")
                else:
                    GLib.idle_add(self._append_log, "Device not connected — cannot test haptic\n")
            threading.Thread(target=direct, daemon=True).start()

    # ── Debounce ────────────────────────────────────────────────────────────

    def _on_debounce_changed(self, scale):
        val = round(scale.get_value(), 1)
        self.config["debounce_secs"] = val
        self._deb_val.set_text(f"{val:.1f}s")
        save_config(self.config)

    # ── Layers ──────────────────────────────────────────────────────────────

    def _on_layer_toggled(self, sw, state):
        self.config["layers"][sw._key] = state
        save_config(self.config)
        return False  # allow GTK to animate the switch

    # ── Logs ────────────────────────────────────────────────────────────────

    def _tail_logs(self):
        try:
            proc = subprocess.Popen(
                ["journalctl", "--user", "-u", SERVICE, "-f", "-n", "50", "--no-pager"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                GLib.idle_add(self._append_log, line)
        except Exception as e:
            GLib.idle_add(self._append_log, f"(log error: {e})\n")

    def _append_log(self, text):
        end = self._log_buf.get_end_iter()
        self._log_buf.insert(end, text)
        if self._log_buf.get_line_count() > 500:
            s = self._log_buf.get_start_iter()
            cut = self._log_buf.get_iter_at_line(self._log_buf.get_line_count() - 500)
            self._log_buf.delete(s, cut)
        parent = self._log_view.get_parent()
        if parent:
            adj = parent.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
        return False


class MX4App(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.tayyabtahir143.mx4notifications",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.connect("activate", lambda app: MX4Window(app).present())


def main():
    MX4App().run(sys.argv)


if __name__ == "__main__":
    main()
