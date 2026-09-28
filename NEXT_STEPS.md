# Übergabe: natives LM-Studio-Tool-Calling + Live-Fortschritt (MCP)

Stand: 2026-09-28, von Claude Code.

## Kurzfassung für die nächste Session

Der Umbau steht, mit einem wichtigen Kurswechsel gegenüber der ersten
Fassung: **nicht mehr `ephemeral_mcp`, sondern LM Studios `mcp.json`.**
Grund und Belege unten unter "Warum `ephemeral_mcp` verworfen wurde".

**Live gegen echtes LM Studio bestätigt** (2026-09-28, separat von
Christoph getestet, siehe `main`-Commit `349b287`): eine echte
Chat-Anfrage mit `{"type": "plugin", "id": "mcp/jarvis"}` erreicht LM
Studio korrekt und bekommt eine präzise, LM-Studio-eigene Antwort zurück
— *"Permission denied to use plugin 'mcp/jarvis' … 'Allow calling servers
from mcp.json' einschalten"* — statt eines Absturzes oder einer
kryptischen Meldung. Das bestätigt: das Request-Format wird richtig
geparst, der Plugin-Id `mcp/jarvis` korrekt erkannt. Getestet wurde
bewusst OHNE den `mcp.json`-Eintrag wirklich zu registrieren — der letzte
Schritt (Eintrag wirklich eintragen, "Allow calling servers from
mcp.json" + "Require Authentication" einschalten, dann ein Tool
tatsächlich aufrufen lassen) ist der eine verbleibende Punkt vor
"fertig", siehe Offene Punkte unten.

## Was jetzt so läuft

- **LM Studio → `/api/v1/chat`** (nativer Endpunkt, Streaming). Die
  Werkzeuge bekommt das Modell über `backend/mcp_server.py`, das Jarvis
  einmalig in LM Studios `mcp.json` einträgt (Konsolen-Ausgabe beim
  Start, siehe SETUP.md) — nicht mehr dynamisch pro Chat-Anfrage.
- **DeepSeek** unverändert über den alten OpenAI-kompatiblen Pfad.
- Eine gemeinsame Antwort-Pipeline für beide (normalisierte
  Runden-Events, siehe Kommentar über `_openai_round` in
  `backend/llm_client.py`).
- Live-Status mit echten Prozenten beim Modell-Laden/Prompt-Verarbeiten;
  Ladeanzeige beim Modellwechsel.
- **Neu seit dem Kurswechsel:** LM Studios `mcp.json`-Weg braucht
  „Require Authentication“ an — dafür kann jetzt in Jarvis unter
  Einstellungen -> LM Studio ein `LM_STUDIO_API_TOKEN` hinterlegt werden,
  das bei jeder Anfrage an LM Studio mitgeschickt wird (überall: Chat,
  Modell-Liste, Laden/Entladen, auch OpenCodes eigene LM-Studio-Anbindung).

## Warum `ephemeral_mcp` verworfen wurde

Die erste Fassung dieses Umbaus (Commit `9d502de`) nutzte LM Studios
`ephemeral_mcp`-Integration: der MCP-Server wurde bei JEDER Chat-Anfrage
neu mit seiner Adresse mitgeschickt. Eine andere Session hat das ungetestet
gebaut UND danach gegen echtes LM Studio getestet und zwei Blocker
gemeldet — mit der Schlussfolgerung, den ganzen Ansatz zu verwerfen.
Beide Behauptungen wurden nachgeprüft, bevor irgendwas verworfen wurde
(siehe Nutzerpräferenz: erst Beweise sammeln, dann handeln):

1. **"Abhängigkeitskonflikt, App stürzt beim Start ab"** — **widerlegt.**
   Frisches Venv, `pip install -r requirements.txt` wortwörtlich, danach
   `from backend import main`: läuft sauber durch (nur eine normale
   `on_event`-Deprecation-Warnung), zweimal unabhängig reproduziert. Die
   andere Session hat das vermutlich in einer nicht sauberen Umgebung
   getestet.
2. **"LM Studio lehnt private/LAN-Adressen für `ephemeral_mcp` ab"** —
   **bestätigt, über LM Studios eigenen Bug-Tracker, mit identischem
   Fehlertext:**
   - [lmstudio-ai/lms#574](https://github.com/lmstudio-ai/lms/issues/574):
     *"URL resolves to a non-public address. We only allow public
     addresses for dynamic remote MCP connections."* — betraf sogar
     `127.0.0.1` auf demselben Rechner.
   - [lmstudio-ai/lmstudio-bug-tracker#2027](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/2027):
     dieselbe Sperre für `192.168.x.x`, seit LM Studio 0.4.15/0.4.16.
   - Das ist ein bewusster SSRF-Schutz: eine dynamisch aus einer
     Chat-Anfrage stammende Adresse darf LM Studio nicht mehr anfragen.

   `ephemeral_mcp` ist damit für jedes lokale Setup tot, nicht nur für
   LAN — Punkt 2 alleine hätte gereicht, den Ansatz zu kippen, aber eben
   nur `ephemeral_mcp`, nicht MCP als Ganzes.

**Der Ausweg:** LM Studio kennt einen zweiten, unabhängigen Weg,
MCP-Server bekanntzumachen — vorkonfiguriert in `mcp.json`
(rechte Seitenleiste -> "Program" -> "Install" -> "Edit mcp.json"), statt
dynamisch pro Anfrage. Diese SSRF-Sperre betrifft laut LM Studios eigener
Doku nur den dynamischen Weg; ein einmalig von Hand eingetragener
`http://127.0.0.1:...`-Server ist eine andere Vertrauensstufe (die
Adresse kommt vom Nutzer selbst, nicht aus einer möglicherweise fremden
Chat-Anfrage). **Live bestätigt** (siehe Kurzfassung oben): eine
Chat-Anfrage mit dem `mcp.json`-Integrationstyp wird von echtem LM Studio
angenommen und korrekt verarbeitet, nicht von derselben SSRF-Sperre
abgewiesen.

## Was inzwischen umgebaut wurde

- `backend/mcp_server.py`: `request_scope()` liefert jetzt
  `{"type": "plugin", "id": "mcp/jarvis"}` statt `ephemeral_mcp` mit
  `server_url`/`headers`. Token ist jetzt **persistiert**
  (`config.JARVIS_MCP_TOKEN`, einmalig erzeugt, nicht mehr pro Start neu)
  — ein `mcp.json`-Eintrag ist ja einmalig von Hand gemacht, ein bei
  jedem Neustart wechselndes Token hätte ihn sofort ungültig gemacht.
  Der Abbruch-Guard ist vereinfacht auf einen einzelnen "aktive Runde
  erlaubt das gerade?"-Slot statt einer Registry pro Anfrage-Schlüssel —
  geht, weil LM Studio ohnehin nur eine Chat-Anfrage gleichzeitig
  verarbeitet (an mehreren Stellen im Code schon vorausgesetzt) UND weil
  `mcp.json`-Header statisch sind, also gar keinen Platz für einen
  Anfrage-Schlüssel mehr bieten. `mcp_json_snippet()` gibt den fertigen
  Block für die Datei aus, `ensure_started()` loggt ihn beim ersten Start.
- `backend/config.py`: `JARVIS_MCP_TOKEN` (persistiert) und
  `LM_STUDIO_API_TOKEN` (für LM Studios eigenes „Require Authentication“,
  Setting-UI unter `_SIMPLE_SETTINGS`) neu; `lm_studio_headers()` als
  gemeinsamer Helfer.
- `backend/llm_client.py`, `hardware.py`, `opencode_agent.py`,
  `vector_memory.py`, `main.py`: jede Anfrage an LM Studio schickt jetzt
  `config.lm_studio_headers()` mit. Fehlertexte (`_native_rejection`,
  `_native_error`) auf den neuen Weg umgeschrieben, inkl. eines eigenen
  Hinweises für 401/403 ("Require Authentication" vs. mcp.json-Berechtigung
  — Reihenfolge der Prüfung ist bewusst: Nachrichteninhalt vor Statuscode,
  siehe Kommentar in `_native_rejection`).
- Frontend: neues Einstellungsfeld "LM-Studio-API-Token".
- Alle E2E-Tests (`fake_lmstudio.py` + `e2e_native.py`/`e2e_main.py`) auf
  den neuen Integrationstyp umgestellt, plus neue Fälle: Token wird
  mitgeschickt, falsches Token löst den richtigen Hinweis aus,
  mcp.json-Fehler vs. Auth-Fehler werden nicht verwechselt (das war ein
  echter Bug, den der Test gefunden hat — Status 403 alleine reichte
  nicht, um zwischen beidem zu unterscheiden, jetzt zählt zuerst der
  Nachrichtentext).

## Chatforken (`previous_response_id`) — neu, noch NICHT live getestet

Auf Benjamins Wunsch zusätzlich gebaut: `/api/v1/chat` ist laut LM Studios
Doku standardmäßig zustandsbehaftet (`store: true`, jede Antwort bekommt
eine `response_id`) — ein Folge-Turn kann per `previous_response_id` daran
anknüpfen, statt den ganzen bisherigen Verlauf als Text erneut zu
schicken. Vorher schickte Jarvis bei jedem Turn `store: false` und den
kompletten Verlauf als beschriftetes Transkript im `input`-Feld
(`_native_input`) — das ist jetzt der Fallback-Weg, nicht mehr der einzige.

**Wichtige Erkenntnis vor dem Bauen recherchiert** (nicht angenommen):
`system_prompt`/`integrations` werden von LM Studio NICHT automatisch über
`previous_response_id` mitgeführt — genau wie bei OpenAIs Responses API,
die dieser Endpunkt nachbildet (belegt u.a. durch
[vllm-project/vllm#37697](https://github.com/vllm-project/vllm/issues/37697),
ein als Bug gemeldetes Leck genau dieses Verhaltens). Jarvis schickt beide
deshalb bei JEDER Anfrage weiterhin frisch mit, verkettet wird nur der
`input`-Teil (die neue Nachricht statt des ganzen Verlaufs).

**Design** (`backend/llm_client.py`):
- Ein `conversation_id -> {response_id, expect_history_len}`-Speicher
  (`_response_chains`, nur im Speicher — ein Neustart von Jarvis oder LM
  Studio macht eine Kette ohnehin ungültig, der Fallback ist immer
  korrekt, nur nicht maximal günstig).
- Verkettet wird NUR die erste Runde eines Turns (`is_first_round`) — eine
  Recovery-Runde (geleakter Aufruf, erfundenes Tool) fällt für den Rest
  des Turns auf vollen Transkript-Aufbau zurück, statt eine zweite,
  schwerer nachvollziehbare Verkettungs-Ebene einzuziehen.
- `expect_history_len` verhindert eine falsch passende Kette: weicht die
  vom Frontend geschickte `history`-Länge beim nächsten Turn ab (Verlauf
  kompaktiert/bearbeitet/verzweigt), wird automatisch neu aufgebaut statt
  eine möglicherweise falsche Kette zu verwenden.
- Lehnt LM Studio eine verkettete Anfrage ab (z.B. nach einem eigenen
  Neustart, `response_id` vergessen), fängt Jarvis das ab, löscht die
  Kette für diese Konversation und wiederholt DENSELBEN Versuch einmal
  ohne Verkettung — der Nutzer merkt vom Ausfall nichts, und am Ende des
  Turns steht wieder eine frische, gültige Kette.
- `warm_system_prompt()` bleibt bei `store: false` (Wegwerf-Ping, soll
  nicht im gespeicherten Antwort-Graphen von LM Studio landen).

**Getestet:** ausführlich gegen `fake_lmstudio.py` (frischer Turn ohne
Kette, Folge-Turn verkettet mit kurzem `input` + weiterhin vollem
`system_prompt`/`integrations`, Verlaufs-Mismatch fällt zurück,
Mehrrunden-Turn verkettet nur Runde 1, abgelehnte Kette heilt sich selbst
und baut am Ende wieder eine gültige Kette auf) — **noch nicht gegen
echtes LM Studio**. Insbesondere unbestätigt: ob LM Studio bei einer
abgelehnten `previous_response_id` wirklich mit einem sofortigen
HTTP-Fehler antwortet (das fängt Jarvis' Selbstheilung ab) oder anders
(z.B. als gestreamtes Fehler-Event mitten im Stream — dafür gibt es aktuell
KEINE Selbstheilung, nur den bestehenden generischen Fehlerpfad).

## Offene Punkte für die nächste Session

1. **Zuerst das hier, bevor irgendwas anderes:** den vollen Kreislauf auf
   dem echten Windows-Rechner einmal komplett durchspielen — die SSRF-
   Kernfrage ist geklärt (siehe oben), es fehlt nur noch der manuelle
   Teil: Jarvis einmal starten (gibt den `mcp.json`-Block mit der
   aktuellen Adresse + Token in der Konsole aus), den Block wirklich in
   LM Studios `mcp.json` einfügen, "Allow calling servers from mcp.json"
   + "Require Authentication" einschalten, das Token in Jarvis unter
   Einstellungen -> LM Studio eintragen, dann eine normale
   Chat-Nachricht schicken, die ein Werkzeug braucht (z.B. "wie spät ist
   es"). Klappt der Tool-Aufruf, ist der Branch aus fachlicher Sicht
   mergebereit (nach normalem Code-Review).
2. **Direkt im selben Durchlauf: Chatforken live prüfen.** Nach dem
   ersten erfolgreichen Tool-Aufruf aus Punkt 1 eine ZWEITE Nachricht im
   selben Gespräch schicken (z.B. „und jetzt?" oder eine Rückfrage). In
   Jarvis' eigener Konsolen-/Log-Ausgabe (oder per Mitschnitt der Anfrage
   an LM Studio) prüfen, ob die zweite Anfrage `previous_response_id`
   enthält und `input` dabei kurz bleibt (nur die neue Nachricht, kein
   komplettes Transkript mehr — siehe `_native_input`/`_chain_lookup` in
   `backend/llm_client.py`). Zusätzlich beobachten, WIE LM Studio auf eine
   ungültige/vergessene `response_id` reagiert (sofortiger HTTP-Fehler vs.
   gestreamtes Fehler-Event), siehe die offene Frage im Abschnitt
   „Chatforken" oben. Kein Blocker, falls das nicht wie erwartet greift —
   der Fallback (voller Verlauf) bleibt korrekt — aber unbedingt
   vermerken.
3. Welche LM-Studio-Version aktuell läuft, unklar (muss ≥ 0.4.0 für den
   `/api/v1/chat`-Endpunkt sein, und die `mcp.json`-Rechte brauchen
   vermutlich auch eine halbwegs aktuelle Version — noch nicht geprüft,
   ab welcher genau "Allow calling servers from mcp.json" existiert).
4. Format von `tool_call.success.output`: angenommen ist die MCP-Content-
   Liste als JSON-String (wie im Doku-Beispiel); `mcp_server.output_text`
   nimmt sonst den Rohtext. Noch nicht live beobachtet.
5. Verlauf: `/api/v1/chat` kennt nur EINE User-Nachricht. Der Verlauf geht
   deshalb als beschriftetes Transkript in diese Nachricht
   (`_native_input`), nicht in den System-Prompt (sonst fiele der
   Tool-Teil jedes Mal aus LM Studios Prompt-Cache). Live beobachten, ob
   kleine Modelle damit genauso gut umgehen wie mit echten Rollen.
6. Nebenbefund, nicht angefasst: die „Trotzdem laden"-Box
   (`#jsModelFitNotice`) fehlt auf der Sichtbarkeits-Whitelist in
   `frontend/claude-app.js` (Regel `body.js-app-active > :not(...)`) und
   ist dadurch vermutlich nie sichtbar (`#jsModelLoad`, die neue
   Ladeanzeige, hatte exakt dasselbe Problem — schon behoben, dort als
   Referenz für den Fix).

## Was schon vorher erledigt war (NICHT nochmal bauen)

- **Live-Status statt starrem "Denkt nach…"** (PR #92, `main`):
  `status`-Events über den OpenAI-kompatiblen Stream — der pragmatische
  Ersatz, falls der native Weg am Ende doch nicht tragfähig ist.
- **Buchstaben-Unschärfe-Einblendung** beim Streamen (auch PR #92).
- **`warm_system_prompt()`-Fix**: wärmt den Prompt-Cache auch nach
  Titel-Generierung/History-Zusammenfassung neu vor.

## Warum das kein kleiner Tweak war

`_stream_reply_impl` (`backend/llm_client.py`) ist eine ausgereifte,
mehrfach gehärtete Pipeline: Korruptions-Erkennung, Behauptungs-Prüfung,
`<think>`-Filterung, Wiederholungs-Schleifen-Erkennung, Satz-für-Satz-
Streaming — all das hing an inkrementellen Content-STRINGS
(OpenAI-Delta-Format). Umgesetzt als ein gemeinsamer Satz normalisierter
Events, auf dem dieselbe Pipeline unverändert für beide Backends läuft
(siehe Kommentar über `_openai_round`) — nicht ersetzt, nur der Eingang
umgebaut.
