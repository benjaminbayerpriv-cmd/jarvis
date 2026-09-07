"""Global hotkey listener: pings the Jarvis backend to wake up the frontend
(start listening) even when the browser tab is not focused.

The modifier key is platform-dependent since Windows keyboards have no Cmd
key: Cmd+Shift+J on macOS, Ctrl+Shift+J on Windows.

macOS note: this process needs "Input Monitoring" / "Accessibility"
permission for whichever app runs it (Terminal, or python itself) under
System Settings -> Privacy & Security.

Windows note: no extra permission is needed, but some elevated (admin)
foreground windows can block a hotkey from a non-elevated listener — run
this the same way (elevated or not) as whatever you're using it to control.
"""

import sys
from pathlib import Path

import requests
from pynput import keyboard

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import config, platform_utils  # noqa: E402

TRIGGER_URL = f"http://{config.JARVIS_HOST}:{config.JARVIS_PORT}/trigger"

MODIFIER = keyboard.Key.ctrl if platform_utils.is_windows() else keyboard.Key.cmd
HOTKEY_LABEL = "Ctrl+Shift+J" if platform_utils.is_windows() else "Cmd+Shift+J"
COMBO = {MODIFIER, keyboard.Key.shift, keyboard.KeyCode.from_char("j")}
current_keys = set()


def normalize(key):
    if hasattr(key, "char") and key.char is not None:
        return keyboard.KeyCode.from_char(key.char.lower())
    # Left/right modifier variants (cmd_l/cmd_r, ctrl_l/ctrl_r) should all
    # count as the one modifier the combo cares about.
    if key in (keyboard.Key.cmd_l, keyboard.Key.cmd_r):
        return keyboard.Key.cmd
    if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        return keyboard.Key.ctrl
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
    print(f"Hotkey-Listener aktiv: {HOTKEY_LABEL} -> {TRIGGER_URL}")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
