"""Keyboard input on macOS and Windows.

Same reasoning as mouse.py: osascript is Apple-signed and inherits the
Accessibility trust that Terminal already holds, whereas the ad-hoc-signed
Homebrew Python never became AX-trusted here. So typing goes through
`keystroke` / `key code` rather than Quartz.
"""

from __future__ import annotations

from __future__ import annotations

import subprocess

from . import platform_utils

# System Events key codes for keys that have no printable character.
_KEY_CODES = {
    "return": 36, "enter": 36,
    "tab": 48,
    "space": 49, "leertaste": 49,
    "delete": 51, "backspace": 51, "löschen": 51,
    "escape": 53, "esc": 53,
    "left": 123, "links": 123,
    "right": 124, "rechts": 124,
    "down": 125, "runter": 125, "unten": 125,
    "up": 126, "hoch": 126, "oben": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f11": 103, "f12": 111,
    "home": 115, "end": 119,
    "pageup": 116, "pagedown": 121,
    "forwarddelete": 117, "entf": 117,
}

_MODIFIERS = {
    "cmd": "command down", "command": "command down", "meta": "command down",
    "ctrl": "control down", "control": "control down", "strg": "control down",
    "alt": "option down", "option": "option down", "opt": "option down",
    "shift": "shift down", "umschalt": "shift down",
}


def _osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _powershell_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _windows_sendkeys(text: str) -> subprocess.CompletedProcess:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        f"[System.Windows.Forms.SendKeys]::SendWait({_powershell_quote(text)})"
    )
    return subprocess.run(platform_utils.powershell(script), capture_output=True, text=True, timeout=20)


def type_text(text: str) -> str:
    if not text:
        return "Was soll ich tippen?"
    if platform_utils.is_windows():
        # SendKeys reserves a handful of characters for shortcuts.
        escaped = "".join(f"{{{char}}}" if char in "+^%~()[]{}" else char for char in text)
        proc = _windows_sendkeys(escaped)
    else:
        proc = _osascript(f'tell application "System Events" to keystroke "{_escape(text)}"')
    if proc.returncode != 0:
        return f"Tippen fehlgeschlagen: {proc.stderr.strip()[:200]}"
    preview = text if len(text) <= 60 else text[:60] + "…"
    return f"Getippt: {preview}"


def press_key(key: str, modifiers: list[str] | None = None) -> str:
    """Press a single key, optionally with modifiers ("cmd+s" style input is
    also accepted directly in `key`)."""
    key = (key or "").strip().lower()
    if not key:
        return "Welche Taste soll ich drücken?"

    mods = list(modifiers or [])
    # Accept "cmd+s" / "cmd shift s" written into the key itself.
    if "+" in key or " " in key:
        parts = [p for p in key.replace(" ", "+").split("+") if p]
        key = parts[-1]
        mods += parts[:-1]

    using = [_MODIFIERS[m.strip().lower()] for m in mods if m.strip().lower() in _MODIFIERS]
    using_clause = f" using {{{', '.join(using)}}}" if using else ""

    if key in _KEY_CODES:
        action = f"key code {_KEY_CODES[key]}"
    elif len(key) == 1:
        action = f'keystroke "{_escape(key)}"'
    else:
        return f"Unbekannte Taste: {key}"

    if platform_utils.is_windows():
        windows_key = {
            "return": "{ENTER}", "enter": "{ENTER}", "tab": "{TAB}", "space": " ",
            "leertaste": " ", "delete": "{BACKSPACE}", "backspace": "{BACKSPACE}",
            "löschen": "{BACKSPACE}", "escape": "{ESC}", "esc": "{ESC}",
            "left": "{LEFT}", "links": "{LEFT}", "right": "{RIGHT}", "rechts": "{RIGHT}",
            "up": "{UP}", "hoch": "{UP}", "oben": "{UP}", "down": "{DOWN}",
            "runter": "{DOWN}", "unten": "{DOWN}", "home": "{HOME}", "end": "{END}",
            "pageup": "{PGUP}", "pagedown": "{PGDN}", "entf": "{DELETE}", "forwarddelete": "{DELETE}",
        }.get(key, f"{{{key.upper()}}}" if key.startswith("f") and key[1:].isdigit() else key)
        prefix = {"command down": "^", "control down": "^", "option down": "%", "shift down": "+"}
        proc = _windows_sendkeys("".join(prefix[m] for m in using) + windows_key)
    else:
        proc = _osascript(f'tell application "System Events" to {action}{using_clause}')
    if proc.returncode != 0:
        return f"Tastendruck fehlgeschlagen: {proc.stderr.strip()[:200]}"

    combo = "+".join([m.split()[0] for m in using] + [key]) if using else key
    return f"Taste gedrückt: {combo}"
