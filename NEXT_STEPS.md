# Übergabe: natives LM-Studio-Tool-Calling + Live-Fortschritt (MCP)

## ERGEBNIS (2026-09-28): Ansatz verworfen — zwei harte Blocker

Eine andere Session (Branch `claude/nice-archimedes-jxyh6q`, Commit
`9d502de`) hat den kompletten Umbau bereits gebaut (MCP-Server,
`llm_client.py` auf normalisierte Runden-Events umgestellt, ~740 Zeilen
Diff) — **bevor** der in diesem Dokument unten beschriebene Testschritt 0
durchlief. Claude Code hat das nachträglich in einem isolierten Worktree
gegen echtes LM Studio getestet, BEVOR es auf einem echten Rechner
ausprobiert wurde. Ergebnis: zwei voneinander unabhängige, harte Blocker.

1. **Abhängigkeitskonflikt:** `mcp==2.2.0` (aus requirements.txt in diesem
   Branch) zieht eine `starlette`-Version, die mit dem im Projekt
   gepinnten `fastapi==0.115.6` inkompatibel ist. Ergebnis: die App
   **stürzt beim Start komplett ab** (`TypeError: Router.__init__() got an
   unexpected keyword argument 'on_startup'`), nicht nur das neue Feature.
   Ein Downgrade von `starlette` auf eine mit fastapi kompatible Version
   bringt die App zwar wieder zum Laufen, kollidiert dann aber mit `mcp`s
   eigener Abhängigkeit `sse-starlette` (die eine neuere `starlette`
   braucht) — ungelöst, vermutlich nur durch ein größeres fastapi-Upgrade
   im ganzen Projekt behebbar (eigenes Risiko, nicht klein).

2. **LM Studio lehnt private/LAN-Adressen für MCP grundsätzlich ab.** Live
   getestet: eine echte Chat-Anfrage mit `ephemeral_mcp` gegen
   `http://192.168.5.29:8766/mcp` (Jarvis' eigener MCP-Server, LAN-Adresse
   dieses Macs) wurde von LM Studio mit dieser Fehlermeldung abgelehnt:
   > "Unable to connect to remote MCP server 'jarvis' … URL resolves to a
   > non-public address. We only allow public addresses for dynamic
   > remote MCP connections."

   Das ist keine Einstellung ("Allow per-request MCPs" war aktiv, Version
   war neu genug), sondern eine feste Sicherheitsregel von LM Studio.
   Benjamins/Christophs Setup (Jarvis und LM Studio beide im privaten
   Heimnetz, keine öffentliche Adresse) kann `ephemeral_mcp` damit
   grundsätzlich nicht nutzen — außer man hängt Jarvis' MCP-Server über
   einen öffentlichen Tunnel (ngrok, Cloudflare Tunnel o.ä.) ins Internet,
   was NICHT empfohlen wird: `run_shell` und die anderen Tools wären dann
   (auch wenn token-geschützt) einem öffentlich erreichbaren Endpunkt
   ausgesetzt.

**Empfehlung: diesen Ansatz nicht weiterverfolgen.** Bei der bereits
gemergten, pragmatischen Lösung bleiben (Live-Status über den normalen
OpenAI-kompatiblen Pfad, siehe "Was schon erledigt ist" unten). Der Branch
`claude/nice-archimedes-jxyh6q` sollte NICHT gemerged werden.

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
