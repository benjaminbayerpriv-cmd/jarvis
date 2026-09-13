#!/bin/bash
# Installs the two LaunchAgents (server + global hotkey) so Jarvis starts at
# login. The checked-in .plist files are templates (__JARVIS_ROOT__
# placeholder) rather than finished plists with a real path baked in — a
# plain `cp` would point launchd at wherever the original developer's
# machine happened to have the project (see git history), which doesn't
# exist on anyone else's Mac. This substitutes the real, current project
# path instead.
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ ! -f ".venv/bin/python3" ]; then
  echo "Bitte zuerst die Installation aus SETUP.md ausfuehren (venv anlegen, pip install)."
  exit 1
fi

mkdir -p ~/Library/LaunchAgents
for name in com.jarvis.server com.jarvis.hotkey; do
  sed "s#__JARVIS_ROOT__#${ROOT}#g" "launcher/${name}.plist" > ~/Library/LaunchAgents/"${name}".plist
  launchctl unload ~/Library/LaunchAgents/"${name}".plist 2>/dev/null || true
  launchctl load ~/Library/LaunchAgents/"${name}".plist
done

echo "Fertig. Jarvis startet ab jetzt automatisch beim Login."
echo "Deaktivieren: launchctl unload ~/Library/LaunchAgents/com.jarvis.*.plist"
