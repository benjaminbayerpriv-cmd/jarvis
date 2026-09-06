# Jarvis — Setup & Start

Jarvis läuft auf **macOS** und **Windows**. Der Code erkennt beim Start
selbst, auf welcher Plattform er läuft (`platform.system()`), und wählt
automatisch die passende Variante für Sprachausgabe, Bildschirmzugriff,
Mausteuerung und Programme öffnen — es gibt keine Einstellung, die man dafür
umschalten müsste. Wo die Schritte unten unterschiedlich sind, ist es
gekennzeichnet.

## 1. Voraussetzungen

- **LM Studio** läuft lokal mit geladenem Modell `qwen2.5-7b-instruct` (Server
  unter `http://localhost:1234`, in LM Studio unter "Developer" -> "Start
  Server"). Bewusst kein Reasoning-Modell (wie z.B. Qwen3.5) — die denken vor
  jeder Antwort erst mehrere Sekunden nach, was sich in der Sprachassistenz
  wie eine Verzögerung/Blockade anfühlt. Qwen2.5-7B antwortet ohne
  Denkschritt direkt und ruft Tools trotzdem zuverlässig auf.
- ElevenLabs API-Key ist bereits in `.env` hinterlegt (optional — ohne Key
  fällt Jarvis automatisch auf die lokale Systemstimme zurück, siehe unten).
- Python 3.11+ ist installiert (`python3 --version` bzw. unter Windows
  `python --version`).

## 2. Installation

**macOS:**

```bash
cd /pfad/zu/jarvis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell oder cmd):**

```powershell
cd C:\pfad\zu\jarvis
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` enthält keine plattformspezifischen Pakete mehr — dieselbe
Datei installiert auf beiden Systemen alles Nötige.

## 3. Server starten

**macOS:**

```bash
source .venv/bin/activate
python3 -m backend.main
```

**Windows:**

```powershell
.venv\Scripts\activate
python -m backend.main
```

Dann im Browser (Chrome empfohlen, wegen Web Speech API) öffnen:

```
http://localhost:8000
```

Einmal auf "Mic-Zugriff erlauben" klicken und die Berechtigung im Browser
bestätigen. Danach den Tab offen lassen — er reagiert auch im Hintergrund
auf den Hotkey.

## 4. Hotkey aktivieren

In einem zweiten Terminal (mit aktivierter venv):

**macOS:**

```bash
python3 launcher/hotkey_listener.py
```

Beim ersten Start fragt macOS nach **Input Monitoring**-Berechtigung
(Systemeinstellungen -> Datenschutz & Sicherheit -> Eingabeüberwachung) —
das Terminal (oder python3) dort erlauben, sonst funktioniert der
globale Hotkey `Cmd+Shift+J` nicht.

**Windows:**

```powershell
python launcher\hotkey_listener.py
```

Keine besondere Berechtigung nötig. Windows hat keine Cmd-Taste, daher ist
der Hotkey hier `Ctrl+Shift+J` — der Listener erkennt die Plattform selbst
und wählt automatisch die richtige Kombination.

## 5. Autostart beim Login einrichten (optional)

**macOS** — LaunchAgents:

```bash
cp launcher/com.jarvis.server.plist ~/Library/LaunchAgents/
cp launcher/com.jarvis.hotkey.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jarvis.server.plist
launchctl load ~/Library/LaunchAgents/com.jarvis.hotkey.plist
```

Zum Deaktivieren: `launchctl unload ~/Library/LaunchAgents/com.jarvis.*.plist`

Die Plists verweisen auf `.venv/bin/python3` — Schritt 2 muss also vorher
durchgelaufen sein.

**Windows** — geplante Aufgaben (Task Scheduler), starten die mitgelieferten
`launcher\start_server.bat` / `launcher\start_hotkey.bat` bei jeder Anmeldung:

```powershell
schtasks /create /tn "Jarvis Server" /tr "\"%CD%\launcher\start_server.bat\"" /sc onlogon /rl highest
schtasks /create /tn "Jarvis Hotkey" /tr "\"%CD%\launcher\start_hotkey.bat\"" /sc onlogon /rl highest
```

Zum Deaktivieren:

```powershell
schtasks /delete /tn "Jarvis Server" /f
schtasks /delete /tn "Jarvis Hotkey" /f
```

Die `.bat`-Dateien aktivieren `.venv` selbst — Schritt 2 muss vorher
durchgelaufen sein, und der Ordnername `.venv` darf nicht verändert werden.

## Was Jarvis kann

- **Programme & Webseiten öffnen** — deutsche Namen ("Rechner", "Notizen")
  werden auf macOS über Spotlight, unter Windows über `App Paths`/PATH und
  die Start-Menü-Verknüpfungen auf das echte Programm aufgelöst.
- **Auf den Bildschirm schauen** — Screenshot per Pillow (plattformunabhängig
  auf macOS und Windows), Analyse durch das lokale Vision-Modell
  `google/gemma-4-e2b`. Muss in LM Studio geladen sein, sonst schlägt nur
  dieses eine Tool fehl.
- **Shell-Befehle ausführen** — Ausgaben über 400 Zeichen landen in der
  Werkbank statt vorgelesen zu werden. Eine Sperrliste verhindert
  systemzerstörende Befehle (`sudo`, `rm -rf /`, `mkfs`, `format`, Fork-Bomben …)
  auf beiden Plattformen.
- **Projekte programmieren** — Jarvis fragt nach dem Ordner und übergibt die
  Arbeit an die **Claude Code CLI**, die dort wirklich Dateien schreibt.
  Läuft im Hintergrund und meldet sich per Sprache, wenn es fertig ist.
- **Inhalte anzeigen** — alles Längere (Code, Erklärungen, Listen) geht in
  die Werkbank rechts, gesprochen wird nur ein kurzer Satz dazu.
- **Maus steuern** — Klicken, Ziehen, Scrollen über `pynput`, das auf beiden
  Plattformen direkt mit dem jeweiligen Betriebssystem spricht. Auf macOS
  muss der Prozess dafür unter Systemeinstellungen -> Datenschutz &
  Sicherheit -> Bedienungshilfen freigegeben sein; unter Windows ist keine
  zusätzliche Freigabe nötig.

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

Unter Windows (PowerShell): `$env:ANTHROPIC_API_KEY = "dein-key"`

## Sprachausgabe ohne ElevenLabs

Läuft der ElevenLabs-Kontingent aus oder ist kein Key gesetzt, spricht
Jarvis automatisch mit der Systemstimme weiter — Qualität ist geringer,
dafür kostenlos, offline und unbegrenzt:

- **macOS:** die eingebaute `say`-Stimme (`Anna`).
- **Windows:** der eingebaute SAPI-Sprachsynthesizer, angesteuert über
  PowerShell — keine zusätzliche Installation nötig.

## Anpassen

- **Persönlichkeit/Prompt:** `backend/llm_client.py` -> `SYSTEM_PROMPT`
- **Tools:** `backend/tools.py` (Wetter, Uhrzeit, Notizen, URL öffnen — neue
  Tools als Funktion + Eintrag in `TOOL_SCHEMAS` + `DISPATCH` ergänzen)
- **Stimme:** `.env` -> `ELEVENLABS_VOICE_ID` (Voice-IDs unter
  elevenlabs.io -> Voice Library)
- **Modell:** `.env` -> `LM_STUDIO_MODEL` / `LM_STUDIO_BASE_URL`
- **Notizen** landen in `jarvis_notes.md` im Projektordner.
