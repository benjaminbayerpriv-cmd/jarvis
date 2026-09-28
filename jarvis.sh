#!/usr/bin/env bash
# Jarvis CLI fuer macOS/Linux. Benoetigt nur Python 3.10+ ohne Pakete —
# die virtuelle Umgebung und alle Abhaengigkeiten legt die CLI selbst an.
set -euo pipefail
cd "$(dirname "$0")"
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    exec "$candidate" jarvis.py "$@"
  fi
done
echo "Python 3.10 oder neuer wird benoetigt und wurde nicht gefunden." >&2
exit 1
