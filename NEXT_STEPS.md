# Übergabe: natives LM-Studio-Tool-Calling + Live-Fortschritt (MCP)

Stand: 2026-09-27, von Claude Code. Der Umbau ist **gebaut**, auf Benjamins
Wunsch ohne vorherigen Einzeltest (Schritt 0 der alten Notiz) und nicht als
opt-in, sondern als der eine Weg für LM Studio. Getestet ist er gegen ein
nachgebautes LM Studio (siehe unten) — **noch nicht gegen ein echtes**.

## Was jetzt so läuft

- **LM Studio → nur noch `/api/v1/chat`** (nativer Endpunkt, Streaming).
  Jarvis' Werkzeuge bekommt das Modell über einen eigenen MCP-Server
  (`backend/mcp_server.py`), den Jarvis pro Anfrage als `ephemeral_mcp`
  mitschickt. LM Studio führt die Tool-Schleife selbst aus: ruft den
  MCP-Server, der ruft wie bisher `tools.call_tool()`.
- **DeepSeek → unverändert** über den OpenAI-kompatiblen Pfad
  (`/chat/completions`, Tools lokal ausgeführt). Der Fallback DeepSeek ↔ LM
  Studio funktioniert wie vorher.
- **Eine Pipeline für beide**: `_stream_reply_impl` konsumiert jetzt
  normalisierte Runden-Events (`_openai_round` / `_native_round`, Format
  im Kommentar über `_openai_round`). Think-Filter, Korruptions- und
  Leak-Erkennung, Behauptungs-Prüfung, Satz-Streaming sind derselbe Code
  wie vorher.
- **Live-Status mit echten Prozenten**: im Chat „Lädt das Modell … 45 %“
  und „Liest die Anfrage … 70 %“ (aus `model_load.progress` /
  `prompt_processing.progress`), dazu wie bisher Denkt nach / Schreibt /
  Werkzeugname. Beim Modellwechsel und Kaltstart eine Ladeanzeige mit
  Balken oben (Panel-Item `model_load`), weil der Warm-up-Request jetzt
  selbst gestreamt über `/api/v1/chat` lädt.
- `get_reply` (`POST /chat`) läuft jetzt über `stream_reply`; `_post_chat`
  ist weg. Titel/Zusammenfassung laufen weiter über `/chat/completions`
  (keine Tools nötig).

## Wie der MCP-Server abgesichert ist

- Lauscht auf `0.0.0.0:JARVIS_MCP_PORT` (Standard 8765), weil LM Studio auf
  einem anderen Rechner laufen kann. Adresse, die LM Studio bekommt: pro
  Anfrage die Schnittstelle, die zu LM Studios Host routet (Loopback, wenn
  lokal) — übersteht also Netzwechsel.
- Zufälliges Bearer-Token pro Jarvis-Start (über die `headers` der
  Integration), ohne Token 401.
- Jeder Tool-Aufruf braucht zusätzlich einen Request-Key, der nur lebt,
  solange Jarvis den zugehörigen Stream liest und der Turn nicht per Stop
  abgebrochen wurde. Warm-up-Anfragen dürfen gar keine Tools ausführen.
- Maximal `MAX_NATIVE_TOOL_CALLS` (8) Tool-Aufrufe pro Turn, weil LM Studio
  die Schleife selbst dreht.

## Was Benjamin einmalig tun muss

1. `pip install -r requirements.txt` (neu: `mcp==2.2.0`).
2. LM Studio **0.4.0 oder neuer**.
3. In LM Studio unter Developer → Server Settings **„Allow per-request
   MCPs“** einschalten.
4. Läuft LM Studio auf einem anderen Rechner: Firewall-Abfrage für Python
   beim ersten Jarvis-Start zulassen (eingehend Port 8765).

Fehlt davon etwas, sagt Jarvis das wörtlich (eigene Fehlerklasse
`LmStudioError`, wird statt „Ich erreiche mein Sprachmodell nicht“
angezeigt/gesprochen).

## Wie getestet (alles gegen Nachbauten, nicht live)

- MCP-Server mit dem offiziellen MCP-Client (so wie LM Studio ihn nutzt):
  21 Tools gelistet, Aufrufe landen in `tools.call_tool`, falsches Token
  401, nach Stop/Ende abgelehnt.
- Fake-LM-Studio, das `/api/v1/chat` mit echten SSE-Events spielt und
  über den MCP-Client Jarvis' Tools aufruft: normaler Tool-Aufruf mit Lade-
  und Prompt-Fortschritt, Behauptung vor Tool-Aufruf, unbelegte
  Behauptung, als Text geleakter Aufruf (zweite Runde bekommt das
  Ergebnis), Bestätigungsfrage wortwörtlich, Verlauf + Bilder, Korruption
  mit/ohne vorherigen Tool-Aufruf, MCP-Verbindungsfehler, abgelehnte
  Anfrage, altes LM Studio, Tool-Budget, Stop mitten im Stream, Modell ohne
  `reasoning: off`, Warm-up, `/chat`, `/chat/stream`, DeepSeek-Pfad und
  Fallback. Im Browser (Chromium) die Status-Zeile und die Ladeanzeige.

## Offene Punkte / was live zu prüfen ist

- **Kern-Unsicherheit bleibt**: ob echtes LM Studio `ephemeral_mcp` mit
  einer `http://<LAN-IP>`-Adresse annimmt (Doku zeigt nur HTTPS-Beispiele).
  Falls nicht, kommt eine klare Fehlermeldung — dann wäre der Weg ein
  mcp.json-Eintrag in LM Studio (`integrations: ["mcp/jarvis"]`), braucht
  aber „Require Authentication“ + API-Token.
- Format von `tool_call.success.output`: angenommen ist die MCP-Content-
  Liste als JSON-String (wie im Doku-Beispiel); `mcp_server.output_text`
  nimmt sonst den Rohtext.
- Wie lange LM Studio auf ein langsames Tool wartet (Timeout seines
  MCP-Clients), ist unbekannt.
- Verlauf: `/api/v1/chat` kennt nur EINE User-Nachricht. Der Verlauf geht
  deshalb als beschriftetes Transkript in diese Nachricht
  (`_native_input`), nicht in den System-Prompt (sonst fiele der
  Tool-Teil jedes Mal aus LM Studios Prompt-Cache). Live beobachten, ob
  kleine Modelle damit genauso gut umgehen wie mit echten Rollen.
- Nebenbefund, nicht angefasst: die „Trotzdem laden“-Box
  (`#jsModelFitNotice`) fehlt auf der Sichtbarkeits-Whitelist in
  `frontend/claude-app.js` (Regel `body.js-app-active > :not(...)`) und
  ist dadurch vermutlich nie sichtbar.
