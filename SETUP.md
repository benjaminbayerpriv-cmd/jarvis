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

## 5. Autostart beim Login einrichten (optional, macOS)

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
- **Auf den Bildschirm schauen** — Screenshot via `screencapture` (macOS)
  beziehungsweise Windows PowerShell, Analyse
  durch das lokale Vision-Modell `google/gemma-4-e2b`. Muss in LM Studio
  geladen sein, sonst schlägt nur dieses eine Tool fehl.
- **Shell-Befehle ausführen** — Ausgaben über 400 Zeichen landen in der
  Werkbank statt vorgelesen zu werden. Eine Sperrliste verhindert
  systemzerstörende Befehle (`sudo`, `rm -rf /`, `mkfs`, Fork-Bombs …).
- **Projekte programmieren** — Jarvis fragt nach dem Ordner und übergibt die
  Arbeit an die **Claude Code CLI**, die dort wirklich Dateien schreibt.
  Läuft im Hintergrund und meldet sich per Sprache, wenn es fertig ist.
- **Inhalte anzeigen** — alles Längere (Code, Erklärungen, Listen) geht in
  die Werkbank rechts, gesprochen wird nur ein kurzer Satz dazu.

### Voraussetzung fürs Programmieren

`build_project` braucht eine angemeldete Claude Code CLI. Falls Jarvis sagt,
die Anmeldung sei abgelaufen, einmal im Terminal anmelden:

```bash
claude
```

Alternativ einen API-Key setzen (die CLI nimmt ihn automatisch):

```bash
export ANTHROPIC_API_KEY=dein-key
```

## Anpassen

- **Persönlichkeit/Prompt:** `backend/llm_client.py` -> `SYSTEM_PROMPT`
- **Tools:** `backend/tools.py` (Wetter, Uhrzeit, Notizen, URL öffnen — neue
  Tools als Funktion + Eintrag in `TOOL_SCHEMAS` + `DISPATCH` ergänzen)
- **Stimme:** `.env` -> `ELEVENLABS_VOICE_ID` (Voice-IDs unter
  elevenlabs.io -> Voice Library)
- **Modell:** `.env` -> `LM_STUDIO_MODEL` / `LM_STUDIO_BASE_URL`
- **Notizen** landen in `jarvis_notes.md` im Projektordner.
