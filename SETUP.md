# Jarvis — Setup & Start (macOS und Windows)

## 1. Voraussetzungen

- **LM Studio** läuft lokal mit geladenem Modell `qwen2.5-7b-instruct` (Server
  unter `http://localhost:1234`, in LM Studio unter "Developer" -> "Start
  Server"). Bewusst kein Reasoning-Modell (wie z.B. Qwen3.5) — die denken vor
  jeder Antwort erst mehrere Sekunden nach, was sich in der Sprachassistenz
  wie eine Verzögerung/Blockade anfühlt. Qwen2.5-7B antwortet ohne
  Denkschritt direkt und ruft Tools trotzdem zuverlässig auf.
- ElevenLabs API-Key ist bereits in `.env` hinterlegt.

## 2. Installation

macOS:

```bash
cd /Pfad/zu/JARVIS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
cd C:\Pfad\zu\JARVIS
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. Server starten

macOS: `source .venv/bin/activate && python3 -m backend.main`

Windows: `.\.venv\Scripts\python.exe -m backend.main`

Dann im Browser (Chrome empfohlen, wegen Web Speech API) öffnen:

```
http://localhost:8000
```

Einmal auf "Mic-Zugriff erlauben" klicken und die Berechtigung im Browser
bestätigen. Danach den Tab offen lassen — er reagiert auch im Hintergrund
auf den Hotkey.

## 4. Hotkey aktivieren

In einem zweiten Terminal (mit aktivierter venv):

macOS: `python3 launcher/hotkey_listener.py`

Windows: `.\.venv\Scripts\python.exe launcher\hotkey_listener.py`

Beim ersten Start fragt macOS nach **Input Monitoring**-Berechtigung
(Systemeinstellungen -> Datenschutz & Sicherheit -> Eingabeüberwachung) —
das Terminal (oder python3) dort erlauben, sonst funktioniert der
globale Hotkey `Cmd+Shift+J` nicht. Unter Windows lautet der Hotkey
`Ctrl+Shift+J`; beim ersten Zugriff eventuelle Berechtigungs- oder
Firewall-Dialoge bestätigen.

Unter Windows startet [start_jarvis_windows.cmd](launcher/start_jarvis_windows.cmd)
Server und Hotkey zusammen.

## 5. Chrome-Browser-Agent einrichten (macOS und Windows)

1. In Chrome `chrome://extensions` öffnen und den **Entwicklermodus** aktivieren.
2. Auf **Entpackte Erweiterung laden** klicken.
3. Den Ordner `chrome-extension` aus diesem Projekt auswählen.

Die Erweiterung verbindet sich lokal mit Jarvis. Sie steuert deine bestehenden
Chrome-Tabs für Suchen, Navigation und Seitenelemente. Das funktioniert auf
macOS und Windows identisch.

## 6. Obsidian-Gedächtnis

Beim ersten Start legt Jarvis im Projektordner den Unterordner `Jarvis/` an.
Öffne den Projektordner einmal als Vault in Obsidian. Darin liegen Profil,
Aufgaben, Wissen, Notizen und tägliche Zusammenfassungen als normale Markdown-
Dateien mit YAML-Metadaten und Wikilinks.

## 7. Autostart beim Login einrichten (optional, macOS)

```bash
cp launcher/com.jarvis.server.plist ~/Library/LaunchAgents/
cp launcher/com.jarvis.hotkey.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jarvis.server.plist
launchctl load ~/Library/LaunchAgents/com.jarvis.hotkey.plist
```

Zum Deaktivieren: `launchctl unload ~/Library/LaunchAgents/com.jarvis.*.plist`

Die Plists verweisen auf `.venv/bin/python3` — Schritt 2 muss also vorher
durchgelaufen sein.

## Was Jarvis kann

- **Programme & Webseiten öffnen** — auf macOS über Spotlight/App-Bundles,
  auf Windows über den Programmnamen (`Rechner`, `Notizen` etc.).
- **Shell-Befehle ausführen** — Ausgaben über 400 Zeichen gehen ins Interface
  statt vorgelesen zu werden. Eine Sperrliste verhindert systemzerstörende
  Befehle (`sudo`, `rm -rf /`, `mkfs`, Fork-Bombs …).
- **Dateien schreiben** — direkt per `write_file`, ohne Shell-Umweg.
- **Im Web suchen** — mit `TAVILY_API_KEY` echte Ergebnisse, sonst öffnet
  es die Suche im verbundenen Browser.
- **Projekte programmieren** — Jarvis fragt nach dem Ordner und baut das
  Projekt mit seinem eigenen Modell selbst (kein externes Tool). Läuft im
  Hintergrund und meldet sich per Sprache, wenn es fertig ist. Ein kleines
  lokales Modell liefert dabei spürbar schwächere Ergebnisse als ein
  dediziertes Coding-Tool — für ernsthafte Projekte eher als Ausgangspunkt
  zu verstehen.
- **Inhalte anzeigen** — alles Längere (Code, Erklärungen, Listen) geht ins
  Interface, gesprochen wird nur ein kurzer Satz dazu.

## Anpassen

- **Persönlichkeit/Prompt:** `backend/llm_client.py` -> `SYSTEM_PROMPT`
- **Tools:** `backend/tools.py` (Wetter, Uhrzeit, Notizen, URL öffnen — neue
  Tools als Funktion + Eintrag in `TOOL_SCHEMAS` + `DISPATCH` ergänzen)
- **Stimme:** `.env` -> `ELEVENLABS_VOICE_ID` (Voice-IDs unter
  elevenlabs.io -> Voice Library)
- **Modell:** `.env` -> `LM_STUDIO_MODEL` / `LM_STUDIO_BASE_URL`
- **Notizen** landen in `jarvis_notes.md` im Projektordner.
