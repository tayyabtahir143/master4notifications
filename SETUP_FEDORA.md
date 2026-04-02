# MX Master 4 Haptic Notifications — Fedora Setup

Tested on **Fedora 43**, GNOME, Wayland + XWayland.
Branch: `tayyabsfedora`

---

## What's changed from upstream

### `src/watch.py` — 3-layer notification monitor

| Layer | Method | Catches |
|---|---|---|
| 1 | D-Bus monitor | `notify-send`, Zapzap, GTK apps, portal apps |
| 2 | X11 window events | Chrome/Electron popup notifications (XWayland) |
| 3 | AT-SPI accessibility | Any app creating notification/alert windows |

All 3 layers share a 1.5-second debounce. On device error the process exits so
systemd restarts it and re-discovers the mouse automatically.

### `src/mx_master_4.py` — fixed device discovery and haptic command

Key bugs fixed vs upstream:

| Bug | Fix |
|---|---|
| `find()` grabbed first `FF00` device (often the wrong receiver) | Now scans **all** receivers and all device indices for HAPTIC feature `0x19B0` |
| `IRoot.getFeature` used `func_sw=0x10` (getProtocol) instead of `0x00` (getFeature) | Fixed |
| Haptic params `[0, 0, 0]` — `play_flag=0` means "don't play" | Fixed to `[waveform_id, 0x01, …]` |

Confirmed waveform IDs (via packet sniffing against Solaar):

| ID | Name |
|---|---|
| `0x00` | SHARP STATE CHANGE (default — crisp notification buzz) |
| `0x01` | DAMP STATE CHANGE |
| `0x05` | HAPPY ALERT |
| `0x0A` | FIREWORK |

---

## Requirements

- Python 3.10+
- MX Master 4 connected via Logi Bolt USB receiver
- Fedora with GNOME (Wayland + XWayland)
- Solaar installed (used for the optional settings menu)

---

## Installation

### 1. Clone and enter the repo

```bash
git clone git@github.com:tayyabtahir143/mx4notifications.git
cd mx4notifications
git checkout tayyabsfedora
```

### 2. Install dependencies

```bash
# System packages
sudo dnf install python3-gobject python3-xlib at-spi2-core

# Python package (hid)
pip3 install --user hid
```

### 3. Add your user to the input group

```bash
sudo usermod -a -G input $USER
# Log out and back in for this to take effect
```

### 4. Create the udev rule (permissions + auto-restart on reconnect)

Replace `yourusername` with your actual username:

```bash
sudo tee /etc/udev/rules.d/99-mx4notifications.rules << 'EOF'
# Grant 'input' group access to all Logitech hidraw devices
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", MODE="0660", GROUP="input"

# Restart the service whenever a Logitech device reconnects
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", ACTION=="add", \
    RUN+="/bin/systemctl --machine=yourusername@.host --user restart mx4notifications.service"
EOF

sudo udevadm control --reload-rules
```

This makes permissions permanent across reboots and USB port changes, and ensures
the service immediately picks up the mouse after you bring it back from another PC.

### 5. Enable AT-SPI accessibility

```bash
gsettings set org.gnome.desktop.interface toolkit-accessibility true
```

### 6. Create the systemd user service

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/mx4notifications.service << 'EOF'
[Unit]
Description=MX Master 4 Haptic Notifications
After=graphical-session.target gnome-session.target
Requires=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
Type=simple
WorkingDirectory=%h/mx4notifications/src
ExecStart=python3 %h/mx4notifications/src/watch.py
Restart=on-failure
RestartSec=5
Environment=PYTHONPATH=%h/mx4notifications/src

[Install]
WantedBy=graphical-session.target
EOF
```

> Adjust `WorkingDirectory` and `ExecStart` paths if you cloned elsewhere.

### 7. Enable and start the service

```bash
systemctl --user daemon-reload
systemctl --user enable --now mx4notifications
```

### 8. Verify it's running

```bash
systemctl --user status mx4notifications
journalctl --user -u mx4notifications -f
```

### 9. Test

```bash
notify-send "Test" "You should feel a buzz on your MX Master 4!"
```

---

## How it works

```
Any notification source
        ↓
   ┌────┴────────────────────┐
   │  Layer 1: D-Bus monitor │  ← notify-send, Zapzap, GTK apps
   │  Layer 2: X11 events    │  ← Chrome, Outlook snap, Electron apps
   │  Layer 3: AT-SPI        │  ← Accessible notification windows
   └────┬────────────────────┘
        ↓
  HID++ HAPTIC feature (0x19B0), func 4, waveform 0x00
        ↓
  MX Master 4 vibrates (SHARP STATE CHANGE)
```

### Device discovery

`MXMaster4.find()` enumerates every Logitech receiver on every USB port and calls
`IRoot.getFeature(0x19B0)` on each paired device. The first device that responds
with a non-zero feature index is the MX Master 4. This means:

- Any USB port works — no hardcoded hidraw paths
- Multiple Logitech receivers won't confuse it
- Offline devices (sleeping or on another PC) are skipped

### Reconnect behaviour

| Situation | What happens |
|---|---|
| Mouse away, comes back | udev rule restarts service → re-discovers immediately |
| Service running, device error | `os._exit(1)` → systemd restarts in 5s → re-discovers |
| Mouse not present at boot | Service retries every 5s until mouse appears |

---

## Solaar settings popup conflict

If you use Solaar with a haptic button rule (a settings menu), every notification
haptic will trigger that menu. The fix is already in `watch.py` — it writes a
timestamp to `/tmp/mx4-notif-haptic` before each haptic command.

In your Solaar rule script, add this near the top:

```bash
# Skip if haptic came from a notification (not a physical button press)
FLAG="/tmp/mx4-notif-haptic"
if [ -f "$FLAG" ]; then
    AGE=$(( $(date +%s) - $(date +%s -r "$FLAG" 2>/dev/null || echo 0) ))
    if [ "$AGE" -lt 10 ]; then exit 0; fi
fi
```

---

## Chrome Gmail notifications

Chrome uses its own popup notifications by default (bypasses D-Bus). Layer 2
catches these via X11 window type. To also use system notifications (Layer 1):

1. Open Chrome → `chrome://flags`
2. Search: **system notifications**
3. Set **"Enable system notifications"** → **Enabled**
4. Relaunch Chrome

---

## Ubuntu compatibility

Works on Ubuntu 22.04+ with minor changes:

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-atspi-2.0 python3-xlib
pip3 install --user hid
```

> Ubuntu 20.04 ships Python 3.8 which is **not supported** (requires 3.10+)
