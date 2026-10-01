#!/usr/bin/env bash
# Jarvis fuer macOS: im Finder doppelklicken (oeffnet das Terminal) oder
# im Terminal "./jarvis.command" aufrufen. Startet jarvis.py, argumente werden
# durchgereicht (z.B. "./jarvis.command --help").
#
# Der macOS-Standard-Python (/usr/bin/python3) ist oft 3.9 und damit zu alt
# (jarvis.py braucht 3.10+), deshalb wird erst die Projekt-Umgebung (.venv)
# genommen und sonst ein passender Python gesucht. Beim Start per Doppelklick
# kennt das Terminal nicht den PATH der Shell, daher die Zusatzpfade.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

pause_on_error() {
  echo
  echo "Zum Schliessen eine Taste druecken ..."
  read -r -n 1
}

for candidate in .venv/bin/python python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 \
     && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    "$candidate" jarvis.py "$@"
    status=$?
    # Fehler sichtbar lassen, statt dass sich das Fenster sofort schliesst.
    if [ "$status" -ne 0 ] && [ "$status" -ne 130 ]; then
      echo
      echo "Jarvis wurde mit Fehlercode $status beendet."
      pause_on_error
    fi
    exit "$status"
  fi
done

echo "Python 3.10 oder neuer wird benoetigt und wurde nicht gefunden."
echo "Installieren, z.B. mit:  brew install python"
pause_on_error
exit 1
