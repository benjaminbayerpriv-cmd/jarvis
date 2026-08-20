"""Global hotkey listener: Cmd/Ctrl+Shift+J pings the Jarvis backend to wake up
the frontend (start listening) even when the browser tab is not focused.

macOS needs Input Monitoring/Accessibility permission; Windows may show a
firewall or input-permission prompt on first use.
"""

import sys
from pathlib import Path

import requests
from pynput import keyboard

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import config, platform_utils  # noqa: E402

TRIGGER_URL = f"http://{config.JARVIS_HOST}:{config.JARVIS_PORT}/trigger"

MODIFIER = keyboard.Key.ctrl if platform_utils.is_windows() else keyboard.Key.cmd
COMBO = {MODIFIER, keyboard.Key.shift, keyboard.KeyCode.from_char("j")}
current_keys = set()


def normalize(key):
    if hasattr(key, "char") and key.char is not None:
        return keyboard.KeyCode.from_char(key.char.lower())
    return key


def on_press(key):
    current_keys.add(normalize(key))
    if COMBO.issubset(current_keys):
        try:
            requests.post(TRIGGER_URL, timeout=3)
            print("Jarvis getriggert.")
        except requests.RequestException as exc:
            print(f"Konnte Jarvis nicht erreichen ({TRIGGER_URL}): {exc}")


def on_release(key):
    current_keys.discard(normalize(key))


def main():
    hotkey = "Ctrl+Shift+J" if platform_utils.is_windows() else "Cmd+Shift+J"
    print(f"Hotkey-Listener aktiv: {hotkey} -> {TRIGGER_URL}")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
