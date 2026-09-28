"""Jarvis — lokaler Sprachassistent: Steuerung, Installation, LM Studio.

Aufruf:

    python jarvis.py            interaktives Menü
    python jarvis.py setup      Einrichtungs-Assistent
    python jarvis.py --help     alle Befehle

Läuft absichtlich ohne Abhängigkeiten: der Installer legt erst .venv und
Pakete an, also darf dieses Skript nur die Standardbibliothek benutzen.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis_cli.cli import main  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
