"""Persistent JSON config for mx4notifications. Stored in ~/.config/mx4notifications/config.json."""
import json
from pathlib import Path

_CONFIG_DIR = Path.home() / ".config" / "mx4notifications"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

DEFAULTS = {
    "waveform": 0x02,       # WAVEFORM_SHARP_COLLISION
    "double_tap": False,    # play waveform twice with 80ms gap
    "debounce_secs": 1.5,
    "layers": {
        "dbus": True,
        "x11": True,
        "atspi": True,
    },
}


def load() -> dict:
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE) as f:
                data = json.load(f)
            merged = {**DEFAULTS, **data}
            merged["layers"] = {**DEFAULTS["layers"], **data.get("layers", {})}
            return merged
        except Exception:
            pass
    return {**DEFAULTS, "layers": {**DEFAULTS["layers"]}}


def save(config: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
