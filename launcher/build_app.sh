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
  --icon "$(pwd)/launcher/icons/jarvis.icns" \
  --distpath launcher/dist --workpath launcher/build --specpath launcher \
  launcher/jarvis_launcher.py

# PyInstaller's generated Info.plist has no usage-description keys at all —
# without NSMicrophoneUsageDescription, macOS silently denies getUserMedia()
# in the app's webview instead of ever showing the permission prompt, which
# looks exactly like "clicking Freigeben does nothing." Patching it in here
# is simpler than hand-maintaining a full custom Info.plist via a .spec file.
PLIST="launcher/dist/Jarvis.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'Jarvis braucht Mikrofonzugriff, um dir zuzuhoeren.'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :NSMicrophoneUsageDescription 'Jarvis braucht Mikrofonzugriff, um dir zuzuhoeren.'" "$PLIST"

# PyInstaller signiert das Bundle beim BUNDLE-Schritt bereits ad-hoc; das
# nachtraegliche Patchen der Info.plist hier macht diese Signatur ungueltig
# (Info.plist ist danach nicht mehr an die Signatur gebunden). Ohne erneutes
# Signieren startet die App zwar per direktem Programmaufruf im Terminal
# (das umgeht Gatekeeper/LaunchServices), aber ein Doppelklick im Finder
# oder `open Jarvis.app` schlaegt dann fehl, ohne dass eine Fehlermeldung
# erscheint.
codesign --force --deep --sign - "launcher/dist/Jarvis.app"

echo
echo "Fertig: launcher/dist/Jarvis.app"
