#!/bin/bash
# Builds launcher/dist/Jarvis.app — a thin double-click launcher that
# starts the existing .venv-based server and opens the browser once it's
# up. Run this once, on macOS, after SETUP.md's install steps.
set -e
cd "$(dirname "$0")/.."

if [ ! -f ".venv/bin/python3" ]; then
  echo "Bitte zuerst die Installation aus SETUP.md ausfuehren."
  exit 1
fi

.venv/bin/python3 -m pip install --quiet pyinstaller
.venv/bin/python3 -m PyInstaller --onedir --windowed --name Jarvis \
  --distpath launcher/dist --workpath launcher/build --specpath launcher \
  launcher/jarvis_launcher.py

echo
echo "Fertig: launcher/dist/Jarvis.app"
