#!/bin/bash
# MX Master 4 Haptic Setup — Install Script
# Run as your normal user (will prompt for sudo when needed)
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== MX Master 4 Haptic Setup ==="
echo "Repo: $REPO_DIR"
echo ""

# 1. Install system packages
echo "[1/8] Installing system packages..."
sudo dnf install -y logiops python3-gobject python3-xlib at-spi2-core python3-evdev

# 2. Install Python packages
echo "[2/8] Installing Python packages..."
pip3 install --user hid

# 3. Add user to input group
echo "[3/8] Adding $USER to input group..."
sudo usermod -a -G input "$USER"
echo "      NOTE: Log out and back in for group changes to take effect."

# 4. Install udev rule
echo "[4/8] Installing udev rule..."
sudo cp "$REPO_DIR/config/udev/99-mx4notifications.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules

# 5. Install logid config
echo "[5/8] Installing logid config..."
sudo cp "$REPO_DIR/config/logid.cfg" /etc/logid.cfg

# 6. Install logid systemd files (reinit timer + release-keys drop-in)
echo "[6/8] Installing logid systemd units..."
sudo cp "$REPO_DIR/config/systemd/system/logid-reinit.timer" /etc/systemd/system/
sudo cp "$REPO_DIR/config/systemd/system/logid-reinit.service" /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/logid.service.d
sudo cp "$REPO_DIR/config/systemd/system/logid.service.d/release-keys.conf" /etc/systemd/system/logid.service.d/
sudo cp "$REPO_DIR/scripts/logid-release-keys.py" /usr/local/bin/logid-release-keys.py
sudo chmod +x /usr/local/bin/logid-release-keys.py
sudo systemctl daemon-reload
sudo systemctl enable --now logid.service
sudo systemctl enable --now logid-reinit.timer

# 7. Install user systemd services
echo "[7/8] Installing user systemd services..."
mkdir -p ~/.config/systemd/user
cp "$REPO_DIR/config/systemd/user/mx4notifications.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mx4notifications.service

# 8. Fix GNOME Super key overlay
echo "[8/8] Fixing GNOME overlay-key..."
gsettings set org.gnome.mutter overlay-key 'Super_L'

# 9. Enable AT-SPI (for Layer 3 notification detection)
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
