#!/bin/bash
# MX Master 4 Haptic Setup — Ubuntu Install Script
# Tested on Ubuntu 22.04 / 24.04 with GNOME
# Run as your normal user (will prompt for sudo when needed)
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== MX Master 4 Haptic Setup (Ubuntu) ==="
echo "Repo: $REPO_DIR"
echo ""

# Check Ubuntu version
UBUNTU_VERSION=$(lsb_release -rs 2>/dev/null || echo "unknown")
echo "Ubuntu version: $UBUNTU_VERSION"
echo ""

# 1. Install logiops (not in default Ubuntu repos — build from source)
echo "[1/9] Installing logiops..."
if ! command -v logid &>/dev/null; then
    sudo apt install -y cmake libevdev-dev libudev-dev libconfig++-dev pkg-config git
    TMP=$(mktemp -d)
    git clone https://github.com/PixlOne/logiops.git "$TMP/logiops"
    cd "$TMP/logiops"
    mkdir build && cd build
    cmake ..
    make -j"$(nproc)"
    sudo make install
    cd "$REPO_DIR"
    rm -rf "$TMP"
    echo "logiops installed from source."
else
    echo "logid already installed, skipping."
fi

# 2. Install system packages
echo "[2/9] Installing system packages..."
sudo apt install -y \
    python3-gi python3-gi-cairo gir1.2-atspi-2.0 \
    python3-xlib at-spi2-core \
    python3-evdev \
    dbus-x11

# 3. Install Python packages
echo "[3/9] Installing Python packages..."
pip3 install --user hid

# 4. Add user to input group
echo "[4/9] Adding $USER to input group..."
sudo usermod -a -G input "$USER"
echo "      NOTE: Log out and back in for group changes to take effect."

# 5. Install udev rule
echo "[5/9] Installing udev rule..."
sudo cp "$REPO_DIR/config/udev/99-mx4notifications.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules

# 6. Install logid config
echo "[6/9] Installing logid config..."
sudo cp "$REPO_DIR/config/logid.cfg" /etc/logid.cfg

# 7. Install logid systemd files
echo "[7/9] Installing logid systemd units..."
sudo cp "$REPO_DIR/config/systemd/system/logid-reinit.timer" /etc/systemd/system/
sudo cp "$REPO_DIR/config/systemd/system/logid-reinit.service" /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/logid.service.d
sudo cp "$REPO_DIR/config/systemd/system/logid.service.d/release-keys.conf" /etc/systemd/system/logid.service.d/
sudo cp "$REPO_DIR/scripts/logid-release-keys.py" /usr/local/bin/logid-release-keys.py
sudo chmod +x /usr/local/bin/logid-release-keys.py
sudo systemctl daemon-reload
sudo systemctl enable --now logid.service
sudo systemctl enable --now logid-reinit.timer

# 8. Install user systemd services
echo "[8/9] Installing user systemd services..."
mkdir -p ~/.config/systemd/user
cp "$REPO_DIR/config/systemd/user/mx4notifications.service" ~/.config/systemd/user/
cp "$REPO_DIR/config/systemd/user/mx4-overview.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mx4notifications.service
systemctl --user enable --now mx4-overview.service

# 9. Fix GNOME settings
echo "[9/9] Fixing GNOME settings..."
gsettings set org.gnome.mutter overlay-key 'Super_L'
gsettings set org.gnome.desktop.interface toolkit-accessibility true

echo ""
echo "=== Done! ==="
echo ""
echo "Next steps:"
echo "  1. Log out and back in (for input group to take effect)"
echo "  2. Reconnect your MX Master 4 mouse if it was already connected"
echo "  3. Test haptic notification:  notify-send 'Test' 'You should feel a buzz!'"
echo "  4. Test haptic panel:         Press the oval haptic panel → GNOME Activities should open"
echo ""
echo "Check service status:"
echo "  systemctl --user status mx4notifications.service"
echo "  systemctl --user status mx4-overview.service"
echo "  sudo systemctl status logid.service"
