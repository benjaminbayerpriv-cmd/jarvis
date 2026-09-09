# Jarvis

Ein lokaler, sprachgesteuerter KI-Assistent für den Desktop — läuft auf
**macOS** und **Windows**, spricht mit dir in Deutsch und erledigt echte
Aufgaben am Rechner: Programme öffnen, Dateien schreiben und verschieben,
im Web suchen, Projekte bauen, Notizen führen und Dinge merken. Das Modell
kommt aus **LM Studio** (OpenAI-kompatibel, läuft komplett lokal) — optional
lässt sich die Text-Generierung auf DeepSeek Cloud umstellen.

Alles Persönliche bleibt standardmäßig auf dem eigenen Rechner: Sprache,
Erkennung, Modelle, Gedächtnis. Nur die optionalen Bausteine (ElevenLabs,
DeepSeek, Tavily, experimentelles Gemini) verlassen die Maschine.

---

## Überblick

```
┌──────────────────────────  Browser-UI (Frontend)  ──────────────────────────┐
│ • Chat + Sidebar mit Konversationen (Chat/Code-Modus, persistent)          │
│ • Sprachmodus: Orb-Animation, Live-Transkription, TTS-Ausgabe               │
│ • Diktat direkt ins Eingabefeld                                             │
│ • Fortschrittspanel für Hintergrund-Aufgaben (Builds, Dateien, Shell)       │
└──────────────┬──────────────────────────────────────┬───────────────────────┘
               │ SSE (Streaming) / WS                  │ Web Speech API (STT)
┌──────────────▼───────────────  Backend (FastAPI)  ──▼───────────────────────┐
│ • Chat-Streaming, Turn-Abbruch, Konversations-Speicher                      │
│ • Tools: Programme, Dateien, Shell, Web-Suche, Projekt-Build, Memory        │
│ • TTS: Supertonic (lokal) → ElevenLabs (optional) → Systemstimme (Fallback)│
│ • Browser-Agent via Chrome-Erweiterung (WebSocket)                          │
│ • Ernste Antworten als Markdown-/Code-Blöcke im Interface, kurzer Satz      │
│   wird gesprochen                                                           │
└──────────────┬──────────────────────────────────────────────────────────────┘
               │
      LM Studio (OpenAI-kompatible API, lokal) — Modell + Embeddings
      optional: DeepSeek Cloud · Tavily Search · ElevenLabs · Gemini (experimentell)
```

## Features

- **Sprachgesteuert** — Globaler Hotkey (`Cmd+Shift+J` auf macOS,
  `Ctrl+Shift+J` auf Windows) holt Jarvis aus dem Hintergrund. Spracherkennung
  läuft über die browsereigene **Web Speech API** (`de-DE`, kontinuierlich,
  Live-Zwischenergebnisse), Ausgabe über eine lokale Supertonic-Stimme.
- **Talk-Modus** — Antworten werden gesprochen (sequenzielle Audio-Queue),
  ein animierter Punktorb pulsiert mit der eigenen Stimme. Barge-in: ein
  anhaltender Satz unterbricht Jarvis mitten in der Antwort.
- **Diktat** — Sprache direkt ins Eingabefeld transkribieren, Zwischenergeb-
  nisse erscheinen live.
- **Chat & Code** — Zwei getrennte Modi mit eigenen Konversationen; alles
  wird als Datei auf dem Rechner gespeichert und in der Sidebar verwaltet.
- **Programme & Seiten öffnen** — deutsche Namen („Rechner“, „Notizen“) wer-
  den auf macOS über Spotlight, unter Windows über `App Paths`/PATH aufgelöst.
- **Dateien & Ordner** — `open_folder`, `list_folder`, `write_file`,
  `move_file`; **Löschen geht immer in den Papierkorb** (`send2trash`,
  reversibel) und fragt vorher nach Bestätigung.
- **Shell** — Befehle werden ausgeführt, Ausgaben über 400 Zeichen landen im
  Interface statt im Sprachkanal. Eine Sperrliste blockiert systemzerstörende
  Befehle (`sudo`, `rm -rf /`, `mkfs`, Fork-Bomben …) auf beiden Plattformen.
- **Web suchen** — echte Suchergebnisse zum Zusammenfassen/Vorlesen über die
  Tavily-API (kostenlos, ohne Kreditkarte) oder über den verbundenen Browser.
- **Projekte programmieren** — Jarvis fragt nach dem Ordner und baut das
  Projekt mit dem lokalen Modell selbst; Fortschritt erscheint im Interface,
  Meldung kommt per Sprache.
- **Gedächtnis** — Ein Obsidian-Vault (`Jarvis/`-Ordner) mit Profil,
  Aufgaben, Wissen, Notizen und Tages-Zusammenfassungen als Markdown.
  Semantische Suche über lokale Embeddings im LM Studio (ohne Modell fällt
  sie auf Keyword-Suche zurück).
- **Browser-Agent** — Die Chrome-Erweiterung steuert deine Tabs: Tabs lesen,
  URLs öffnen, suchen, Tab aktivieren, Seitenelemente bedienen.
- **Lokale Spracherkennung / keine Cloud nötig** — Für den Grundbetrieb sind
  nur LM Studio auf `127.0.0.1:1234` und ein Browser nötig.

## Schnellstart

1. **LM Studio** starten, ein Chat-Modell laden, unter *Developer → Start
   Server* den Server auf `http://127.0.0.1:1234` laufen lassen.
2. Projekt einrichten (venv + Abhängigkeiten):

   ```bash
   python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. `.env` vorbereiten (`.env.example` als Vorlage, mindestens
   `LM_STUDIO_MODEL` anpassen):

   ```bash
   cp .env.example .env
   ```

4. Server starten und `http://localhost:8000` öffnen:

   ```bash
   python3 -m backend.main
   ```

5. (Optional) Globalen Hotkey aktivieren:

   ```bash
   python3 launcher/hotkey_listener.py
   ```

   macOS fragt beim ersten Start nach **Input Monitoring**-Berechtigung.

Ausführlicher (inkl. Windows-.exe, Autostart bei Login, Browser-Agent,
Obsidian-Vault): [SETUP.md](SETUP.md).

## Konfiguration

| Einstellung | Beschreibung |
|---|---|
| `LM_STUDIO_BASE_URL` / `LM_STUDIO_MODEL` | Lokales Modell (LM Studio, `127.0.0.1:1234`), Name muss exakt dem in LM Studio entsprechen. |
| `EMBEDDING_MODEL` | Lokales Embedding-Modell für die semantische Gedächtnis-Suche; ohne fällt es auf Keyword-Suche zurück. |
| `DEEPSEEK_API_KEY` | (optional) OpenAI-kompatible Cloud-LLM; sobald gesetzt, läuft die Text-Generierung darüber. |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | (optional) Bessere Cloud-Stimme; ohne Key spricht Supertonic lokal. |
| `TAVILY_API_KEY` | (optional, kostenlos) Echte Web-Suchergebnisse; ohne Key öffnet `web_search` die Suche im Browser. |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Nur für das experimentelle `backend/live_voice_test.py`, nicht Teil der normalen Pipeline. |
| `JARVIS_HOST` / `JARVIS_PORT` | Bind-Adresse und Port des Servers. |
| `config.json` | Name, Persönlichkeit (`locker_direkt`), Standard-Stadt für „Wetter“. |

## Komponenten

| Verzeichnis | Inhalt |
|---|---|
| `backend/` | FastAPI-Server: `main.py` (Endpoints, SSE-Streaming), `llm_client.py`, `tools.py`, `tts.py`, `stt.py`, `memory.py` + `vector_memory.py`, `conversations.py`, `browser_agent.py`, `coder.py`, `panel.py`, `confirm.py` |
| `frontend/` | UI: `index.html`/`app.js` (legacy), `claude.html`/`claude-app.js` (aktive UI), `style.css` |
| `launcher/` | Globaler Hotkey, Server-Start, macOS-Login-Plist, Windows-`.bat`/`.exe`-Build |
| `chrome-extension/` | Browser-Agent-Erweiterung (Tabs lesen/öffnen/suchen) |
| `Jarvis/` | Obsidian-Vault / Gedächtnis (wird beim ersten Start angelegt) |

## Sprachausgabe & Spracherkennung

**Sprachausgabe (Fallback-Kette):** Supertonic (lokal, offline, ohne Limit)
→ ElevenLabs (optional, kontingentiert) → Systemstimme (`say` unter macOS,
SAPI unter Windows). Große Zahlen werden mit `num2words` ausgesprochen statt
Ziffern-für-Ziffern gelesen.

**Spracherkennung (STT):** browserbasierte **Web Speech API** (`de-DE`,
kontinuierlich, Zwischenergebnisse) — funktioniert ohne lokales STT-Modell
und ohne CPU-Last. Es gibt weiterhin ein experimentelles Whisper-Backend
(`backend/stt.py`, Endpoint `/stt`), das derzeit im Frontend nicht mehr
aufgerufen wird.

## Rechte & Sicherheit

Siehe [SECURITY.md](SECURITY.md) und die Sperrliste in `backend/tools.py`.
Löschaktionen gehen immer in den Papierkorb, Shell-Ausführungen werden gegen
eine Blacklist geprüft, und konfigurierbare Bestätigungen (`confirm.py`)
sichern kritische Aktionen ab.

## Tests

```bash
python test_jarvis.py
python test_features.py
```

## Projekt-Struktur-Hinweise

- Persönlichkeit/Prompt: `backend/llm_client.py` → `_system_prompt()`
- Neue Tools: Funktion + Eintrag in `TOOL_SCHEMAS`/`DISPATCH` in `backend/tools.py`
- Notizen landen in `jarvis_notes.md` im Projektordner.