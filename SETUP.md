# Jarvis — Setup & Start (macOS und Windows)

Jarvis läuft auf **macOS** und **Windows**. Der Code erkennt beim Start
selbst, auf welcher Plattform er läuft (`platform.system()`), und wählt
automatisch die passende Variante für Sprachausgabe und Programme öffnen —
es gibt keine Einstellung, die man dafür umschalten müsste. Wo die Schritte
unten unterschiedlich sind, ist es gekennzeichnet.

## 1. Voraussetzungen

- **LM Studio** läuft lokal mit geladenem Modell (Server unter
  `http://localhost:1234`, in LM Studio unter "Developer" -> "Start
  Server"). Der Modellname in `.env` (`LM_STUDIO_MODEL`) muss exakt zu dem
  passen, was LM Studio anzeigt.
- ElevenLabs API-Key in `.env` ist optional — ohne Key (oder wenn das
  Kontingent aufgebraucht ist) spricht Jarvis automatisch mit der lokalen
  Supertonic-Stimme weiter, siehe unten.
- Python 3.12+ ist installiert (`python3 --version` bzw. unter Windows
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

`requirements.txt` enthält keine plattformspezifischen Pakete — dieselbe
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

Dann im Browser öffnen:

```
http://localhost:8000
```

Einmal auf "Mikrofon freigeben" klicken und die Berechtigung im Browser
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
das Terminal (oder python3) dort erlauben, sonst funktioniert der globale
Hotkey `Cmd+Shift+J` nicht.

**Windows:**

```powershell
python launcher\hotkey_listener.py
```

Keine besondere Berechtigung nötig. Windows hat keine Cmd-Taste, daher ist
der Hotkey hier `Ctrl+Shift+J` — der Listener erkennt die Plattform selbst
und wählt automatisch die richtige Kombination. `start_jarvis_windows.cmd`
startet Server und Hotkey zusammen.

### Als startbare .exe verpacken (optional, Windows)

Statt jedes Mal ein Terminal zu öffnen, lässt sich der Server als
Doppelklick-App verpacken: `launcher\build_exe.bat` einmal ausführen (nach
Schritt 2, venv muss stehen). Das erzeugt `launcher\dist\Jarvis.exe` — ein
schlanker Launcher, der den bestehenden `.venv`-Server startet und ein
eigenes, normales App-Fenster mit dem Orb öffnet (kein Browsertab, kein
Terminal-Fenster). Bei einem Fehlschlag kommt eine Fehlermeldung statt
eines stillen Abbruchs.

Das ist bewusst kein vollständiges PyInstaller-Freeze des ganzen Backends —
`faster-whisper`/`ctranslate2` und Supertonic bringen native Bibliotheken
mit, die sich dabei erfahrungsgemäß schlecht einfrieren lassen. Der
Launcher ruft stattdessen einfach das bereits funktionierende `.venv` auf,
genau wie `start_jarvis_windows.cmd`.

## 5. Chrome-Browser-Agent einrichten (optional, macOS und Windows)

1. In Chrome `chrome://extensions` öffnen und den **Entwicklermodus** aktivieren.
2. Auf **Entpackte Erweiterung laden** klicken.
3. Den Ordner `chrome-extension` aus diesem Projekt auswählen.

Die Erweiterung verbindet sich lokal mit Jarvis und steuert deine
bestehenden Chrome-Tabs für Websuche, YouTube-Suche und offene Tabs. Ohne
sie fällt `web_search` auf die Tavily-API zurück (siehe unten) bzw. öffnet
ohne `TAVILY_API_KEY` nur eine Suchseite.

## 6. Obsidian-Gedächtnis

Beim ersten Start legt Jarvis im Projektordner den Unterordner `Jarvis/` an.
Öffne den Projektordner einmal als Vault in Obsidian. Darin liegen Profil,
Aufgaben, Wissen, Notizen und tägliche Zusammenfassungen als normale Markdown-
Dateien mit YAML-Metadaten und Wikilinks.

## 7. Autostart beim Login einrichten (optional)

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
- **Ordner öffnen/auflisten** — `open_folder` zeigt einen Ordner im
  Finder/Explorer, `list_folder` sagt nur, was drin liegt, ohne etwas zu
  öffnen. "Desktop", "Dokumente", "Downloads" sind feste, bereits bekannte
  Orte.
- **Dateien schreiben** — direkt per `write_file`, ohne Shell-Umweg.
- **Löschen** — `delete_path` verschiebt in den Papierkorb (reversibel,
  nie ein endgültiges `rm`), fragt selbst nach Bestätigung und meldet
  ehrlich, wenn das Ziel gar nicht existiert.
- **Verschieben** — `move_file` für Dateien/Ordner zwischen zwei Orten.
- **Shell-Befehle ausführen** — Ausgaben über 400 Zeichen landen im
  Interface statt vorgelesen zu werden. Eine Sperrliste verhindert
  systemzerstörende Befehle (`sudo`, `rm -rf /`, `mkfs`, `format`,
  Fork-Bomben …) auf beiden Plattformen.
- **Im Web suchen** — mit `TAVILY_API_KEY` (kostenlos, tavily.com) echte
  Ergebnisse zum Vorlesen/Zusammenfassen; ohne Key öffnet es stattdessen
  die Suche im verbundenen Browser.
- **Projekte programmieren** — Jarvis fragt nach dem Ordner und baut das
  Projekt mit seinem eigenen Modell selbst, ganz ohne externes Tool. Läuft
  im Hintergrund (dabei erscheint eine kleine zweite "arbeitet"-Kugel im
  Interface) und meldet sich per Sprache, wenn es fertig ist. Ein kleines
  lokales Modell liefert dabei spürbar schwächere Ergebnisse als ein
  dediziertes Coding-Tool — für ernsthafte Projekte eher ein Ausgangspunkt.
- **Inhalte anzeigen** — alles Längere (Code, Erklärungen, Listen) geht ins
  Interface, gesprochen wird nur ein kurzer Satz dazu.

## Spracherkennung (STT)

Jarvis nutzt lokales, offline laufendes Whisper (`faster-whisper`) statt der
browsereigenen Spracherkennung — funktioniert dadurch in jedem Browser,
nicht nur in Chrome, und ist bei Deutsch deutlich zuverlässiger. Das Modell
lädt beim Serverstart einmal (`WHISPER_MODEL` in `.env`, Standard
`medium` — `small` ist schneller, aber ungenauer).

## Sprachausgabe

Primär spricht Jarvis mit **Supertonic**, einer lokalen, offline laufenden
Stimme ohne Zeichenlimit oder Kosten. Ist ElevenLabs konfiguriert
(`ELEVENLABS_API_KEY` in `.env`) und Supertonic aus irgendeinem Grund nicht
verfügbar, springt ElevenLabs als bessere, aber kontingentierte Stimme ein.
Schlägt auch das fehl (Kontingent, kein Netz), spricht die eingebaute
Systemstimme weiter — geringere Qualität, dafür kostenlos, offline und
unbegrenzt:

- **macOS:** die eingebaute `say`-Stimme (`Anna`).
- **Windows:** der eingebaute SAPI-Sprachsynthesizer, angesteuert über
  PowerShell — keine zusätzliche Installation nötig.

## Anpassen

- **Persönlichkeit/Prompt:** `backend/llm_client.py` -> `_system_prompt()`
- **Tools:** `backend/tools.py` (Wetter, Uhrzeit, Notizen, URL öffnen — neue
  Tools als Funktion + Eintrag in `TOOL_SCHEMAS` + `DISPATCH` ergänzen)
- **Stimme:** `.env` -> `ELEVENLABS_VOICE_ID` (Voice-IDs unter
  elevenlabs.io -> Voice Library) bzw. `SUPERTONIC_VOICE`/`SUPERTONIC_LANG`
- **Modell:** `.env` -> `LM_STUDIO_MODEL` / `LM_STUDIO_BASE_URL`
- **Notizen** landen in `jarvis_notes.md` im Projektordner.
