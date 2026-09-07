"""Small, dependency-free operating-system helpers for Jarvis."""

from __future__ import annotations

import platform
from pathlib import Path


def system() -> str:
    """Return the current OS name; isolated for simple cross-platform tests."""
    return platform.system()


def is_macos() -> bool:
    return system() == "Darwin"


def is_windows() -> bool:
    return system() == "Windows"


def desktop_dir() -> Path:
    """Best-effort user desktop path on both supported platforms."""
    return Path.home() / "Desktop"


def powershell(script: str) -> list[str]:
    """Build a non-interactive PowerShell invocation for Windows only."""
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
