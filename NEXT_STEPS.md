# Übergabe: natives LM-Studio-Tool-Calling + Live-Fortschritt (MCP)

## ERGEBNIS (2026-09-28, zweimal überprüft): Ansatz sieht jetzt tragfähig aus

Eine andere Session (Branch `claude/nice-archimedes-jxyh6q`) hat den
kompletten Umbau bereits gebaut (MCP-Server, `llm_client.py` auf
normalisierte Runden-Events umgestellt) — **bevor** der unten
beschriebene Testschritt 0 durchlief. Claude Code hat das in einem
isolierten Worktree gegen echtes LM Studio getestet, BEVOR es auf einem
echten Rechner ausprobiert wurde. Verlauf über zwei Runden:

**Runde 1 (Commit `9d502de`):** zwei vermeintliche Blocker gefunden —
(a) `mcp==2.2.0` zieht angeblich ein inkompatibles `starlette`, die App
stürze beim Start ab; (b) LM Studio lehnt `ephemeral_mcp` mit
privaten/LAN-Adressen grundsätzlich ab (Fehlermeldung: "We only allow
public addresses for dynamic remote MCP connections").

**Runde 2 (Commit `dd21ab0`):** die andere Session hat (a) selbst
gegengeprüft und **widerlegt**, und für (b) den MCP-Weg auf LM Studios
statische `mcp.json`-Registrierung umgestellt (statt `ephemeral_mcp` pro
Anfrage). Claude Code hat BEIDES unabhängig nachgeprüft, mit korrigierter
Methode:

1. **Abhängigkeitskonflikt — zurückgezogen, war ein eigener Testfehler.**
   Der erste Test hatte `mcp` nachträglich in ein bereits gefülltes venv
   installiert statt alles zusammen neu aufzulösen — dabei wählte pip ein
   zu neues `starlette`. Mit einem echten frischen venv (Python 3.12,
   `pip install -r requirements.txt` in einem Rutsch) löst pip automatisch
   kompatible Versionen auf (`starlette==0.41.3`, `sse-starlette==3.0.3`,
   beide mit `fastapi==0.115.6` verträglich) — App startet sauber, kein
   Absturz. **Diese Sorge ist vom Tisch.**

2. **Private Adressen — bestätigt, UND korrekt gelöst.** Live gegen
   echtes LM Studio (Modell `qwen/qwen3.6-35b-a3b`) getestet: Jarvis
   druckt beim ersten Kontakt den fertigen `mcp.json`-Eintrag
   (LAN-Adresse + generiertes Bearer-Token) in die Konsole. Eine echte
   Chat-Anfrage, die ein Tool braucht, erreicht LM Studio korrekt und
   bekommt (weil der Eintrag bei diesem Test absichtlich nicht in einem
   echten LM Studio registriert war) eine klare, verständliche
   Fehlermeldung zurück ("Permission denied to use plugin 'mcp/jarvis'
   … 'Allow calling servers from mcp.json' einschalten") statt eines
   Absturzes oder einer kryptischen Meldung.

**Offen, NICHT mehr von hier aus testbar:** ob der volle Kreislauf
(Eintrag wirklich in LM Studios `mcp.json` einfügen, "Allow calling
servers from mcp.json" + "Require Authentication" aktivieren, Jarvis'
Token dort hinterlegen) tatsächlich zu einem erfolgreichen Tool-Aufruf
führt. Das braucht manuelles Handeln auf dem Windows-Rechner selbst
(Datei bearbeiten, Einstellungen umschalten) — Anleitung dafür steht in
`SETUP.md`. Das ist der nächste, tatsächlich noch offene Schritt.

**Einschätzung:** kein Grund mehr, den Branch zu verwerfen. Empfehlung:
Christoph/Benjamin lassen den `mcp.json`-Eintrag einmal echt eintragen
und testen den zweiten curl-Befehl aus `SETUP.md` — klappt der, ist der
Branch mergebereit (nach normalem Code-Review, ~740 Zeilen Diff).

---

Stand: 2026-09-27, von Claude Code. Grund für diese Datei: Benjamins
Wochenlimit war fast aufgebraucht, Untersuchung wurde bewusst NICHT
begonnen, nur recherchiert. Der oben stehende Test wurde am 2026-09-28
trotzdem nachgeholt, weil ein anderer Branch den Umbau schon ungetestet
gebaut hatte.

## Ziel

Zwei Dinge, die Benjamin sich wünscht, hängen technisch zusammen:

1. **Granularer Live-Status** statt "Denkt nach…" — z.B. echte
   Ladefortschritts-Prozente beim Modell-Swap, "verarbeitet Prompt X%".
   (Ein einfacherer Ersatz dafür ist bereits gebaut und gemerged — siehe
   "Was schon erledigt ist" unten. Das hier ist die "richtige", native
   Variante.)
2. **Echtes Tool-Calling über LM Studios nativen `/api/v1/chat`-Endpunkt**,
   der diese granularen Events (`model_load.progress`,
   `prompt_processing.progress`, `tool_call.start/arguments/success/failure`,
   `reasoning.delta`, `message.delta`, …) überhaupt erst liefert.

Das Problem: dieser native Endpunkt hat **kein** `tools`-Feld wie OpenAIs
API, über das man eigene Funktionsdefinitionen mitgibt (bestätigt live
gegen die LM-Studio-Doku geprüft). Er akzeptiert Tools nur über
`integrations` — entweder LM-Studio-eigene **Plugins** oder einen
**`ephemeral_mcp`**-Server (Model Context Protocol). Jarvis' ~20 Tools
(opencode, run_shell, get_time, calculate, …) sind aktuell simple
Python-Funktionen mit OpenAI-Style-JSON-Schema (`backend/tools.py`,
`TOOL_SCHEMAS`/`DISPATCH`), kein MCP-Server.

## Der Plan (mit Benjamin abgestimmt: NIEDRIGES RISIKO, kein großer Umbau
sofort)

**Schritt 0 — ZUERST das hier, bevor irgendwas anderes:** rein empirisch
testen, ob `ephemeral_mcp` überhaupt mit einer lokalen/LAN-Adresse
funktioniert. Die Doku zeigt nur ein Beispiel mit einer öffentlichen
HTTPS-URL (`https://huggingface.co/mcp`), keine Bestätigung für
`http://<lan-ip>:<port>/...`. Wenn das nicht geht, ist das ganze Vorhaben
tot, bevor Zeit in einen Umbau fließt.

Konkret:
1. Winzigen MCP-Server bauen (Python-Paket `mcp`, Transport
   "streamable-http" oder SSE — beides remote-fähig, nicht stdio) mit
   GENAU EINEM Test-Tool (z.B. "sag einen festen String zurück").
2. Benjamin aktiviert einmalig **"Allow per-request MCPs"** in LM Studios
   Server Settings (braucht LM Studio ≥ 0.4.0 — Version vorher prüfen).
3. Testanfrage an `POST /api/v1/chat` mit
   ```json
   {
     "model": "<aktuelles modell>",
     "input": "Nutze das test_tool.",
     "integrations": [{
       "type": "ephemeral_mcp",
       "server_label": "jarvis_test",
       "server_url": "http://<lan-ip-dieses-macs>:<port>/mcp",
       "allowed_tools": ["test_tool"]
     }]
   }
   ```
   und schauen, ob im Response/Stream ein `tool_call.*`-Event für
   `test_tool` auftaucht.

**Erst wenn Schritt 0 klappt**, den großen Teil angehen:

4. Echten MCP-Server bauen, der ALLE bestehenden Tools aus
   `backend/tools.py` spiegelt (Schema-Übersetzung OpenAI→MCP ist
   mechanisch, beide nutzen JSON-Schema — die eigentliche Ausführung bleibt
   `tools.call_tool()`, nur der Transport/die Anmeldung ändert sich).
5. **NICHT den bestehenden Pfad ersetzen.** Als komplett separater,
   opt-in/experimenteller Pfad bauen (z.B. Settings-Schalter "Erweiterten
   Live-Status verwenden (experimentell)"). Der jetzige, gut getestete
   `_stream_reply_impl`-Pfad (OpenAI-kompatibel, `/v1/chat/completions`)
   bleibt Standard und unangetastet — der neue Pfad ist eigener Code, der
   bei Problemen einfach wieder ausgeschaltet werden kann.
6. DeepSeek (Cloud-Fallback) kann kein MCP über LM Studio — muss weiterhin
   über den alten Pfad laufen. Beide Pfade müssen sauber nebeneinander
   existieren können (Provider-Auswahl entscheidet, welcher greift).

## Warum das kein kleiner Tweak ist

`_stream_reply_impl` (backend/llm_client.py) ist eine ausgereifte,
mehrfach gehärtete Pipeline: Korruptions-Erkennung
(`_call_prefix_verdict`, siehe Kommentare zu einem bekannten
LM-Studio/llama.cpp-Grammar-Bug), Behauptungs-Prüfung (`_vet`,
`_unbacked_claim`), `<think>`-Filterung (`_filter_think`,
`_new_think_filter_state`), Wiederholungs-Schleifen-Erkennung
(`_is_repetition_loop`), Satz-für-Satz-Streaming (`_pop_complete_sentences`).
All das hängt an inkrementellen Content-STRINGS (OpenAI-Delta-Format).
Ein Event-basierter Stream (`message.delta`/`reasoning.delta`/`tool_call.*`)
bedeutet nicht "ein paar Zeilen ändern", sondern diese ganze Logik auf ein
anderes Eingabeformat zu übertragen — mit echtem Risiko, etwas davon
kaputt zu machen, das aktuell zuverlässig läuft.

## Was schon erledigt ist (NICHT nochmal bauen)

- **Live-Status statt starrem "Denkt nach…"** ist bereits gemerged (PR #92,
  jetzt in `main`): `status`-Events (`thinking`/`answering`/`tool` mit
  Werkzeugname) über den BESTEHENDEN OpenAI-kompatiblen Stream, ohne den
  großen Umbau. Zeigt z.B. "Rechnet …", "Programmiert gerade …". Das ist
  der pragmatische Ersatz, bis (falls) der native Weg steht.
- **Buchstaben-Unschärfe-Einblendung** beim Streamen (auch PR #92,
  gemerged): jeder neu gestreamte Buchstabe blendet unscharf→scharf ein,
  ohne Staffelung (mehrere Zeichen gleichzeitig), kurze Animationsdauer
  (0.18s), damit sie den häufigen kompletten DOM-Neuaufbau pro
  Stream-Update übersteht.
- **`warm_system_prompt()`-Fix**: wärmt den LM-Studio-Prompt-Cache jetzt
  auch nach Titel-Generierung/History-Zusammenfassung neu vor (vorher nur
  einmal beim Start/Modellwechsel — der Cache wurde durch diese
  Zwischen-Aufrufe mit eigenem, kürzerem System-Prompt ständig verdrängt).

## Offene Fragen für die nächste Session

- Welche LM-Studio-Version läuft aktuell auf Christophs/Benjamins
  Windows-Rechner (Bild vom Server-Log zeigte `192.168.56.1`/
  `10.111.148.251:1234` als wechselnde LAN-Adressen — Rechner wechselt
  offenbar zwischen Netzwerken)? Muss ≥ 0.4.0 für MCP-Support sein.
- Funktioniert `ephemeral_mcp` mit `server_url` = lokale LAN-IP, oder nur
  mit öffentlich erreichbaren HTTPS-URLs? (Kern-Unsicherheit, siehe oben.)
- Falls Schritt 0 scheitert: einfach bei der jetzigen Lösung (status-Events
  über den normalen Pfad) bleiben, kein weiterer Aufwand nötig.
