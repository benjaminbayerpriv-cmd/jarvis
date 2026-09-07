from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

import requests

from . import confirm, config, last_target, memory, tools


class ModelError(RuntimeError):
    """A local-model failure that must become a user-facing response."""

# At low reasoning effort this model occasionally leaks raw <think>/</think>
# markers into the content field instead of keeping them confined to
# reasoning_content. Strip them defensively before anything is shown or read
# aloud.
_THINK_TAG_RE = re.compile(r"</?think>", re.IGNORECASE)


def _strip_think_tags(text: str) -> str:
    return _THINK_TAG_RE.sub("", text).strip()


# Abbreviations whose trailing dot does not end a sentence. Single letters
# ("z.B.", "u.a.") are handled separately.
_ABBREV = {
    "bzw", "ca", "usw", "etc", "evtl", "ggf", "inkl", "exkl", "max", "min",
    "nr", "dr", "prof", "st", "bspw", "sog", "vgl", "ggfs", "mio", "mrd",
}

_WORD_BEFORE_DOT_RE = re.compile(r"([A-Za-zÄÖÜäöüß]+)$")


def _pop_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Peel finished sentences off a growing stream so each can go to
    ElevenLabs immediately.

    A naive split on [.!?] mangles speech: "16.7°C" becomes "16." + "7°C"
    and "z.B." becomes its own sentence, both of which are read aloud
    wrong. So a dot only ends a sentence when it isn't a decimal point and
    isn't part of an abbreviation.
    """
    sentences: list[str] = []
    start = 0
    i = 0
    n = len(buffer)

    while i < n:
        if buffer[i] not in ".!?":
            i += 1
            continue

        # Absorb runs like "?!" or "..."
        j = i + 1
        while j < n and buffer[j] in ".!?":
            j += 1

        after = buffer[j] if j < n else ""

        # Mid-token dot (URLs, 3.14) — not a sentence end.
        if after and not after.isspace():
            i = j
            continue

        if buffer[i] == ".":
            prev = buffer[i - 1] if i else ""
            if prev.isdigit() and after.isdigit():
                i = j
                continue
            word = _WORD_BEFORE_DOT_RE.search(buffer[start:i])
            if word:
                w = word.group(1)
                # A lone letter only continues an abbreviation when it is
                # itself dotted ("z.B."). Otherwise it can legitimately end
                # a sentence — "km/h." must not be mistaken for one.
                dotted_initial = len(w) == 1 and i >= 2 and buffer[i - 2] == "."
                if w.lower() in _ABBREV or dotted_initial:
                    i = j
                    continue

        # Ends exactly at the buffer edge: more tokens may still arrive
        # (the "16." of "16.7"), so wait rather than guess.
        if j >= n:
            break

        sentences.append(buffer[start:j].strip())
        start = j
        i = j

    return sentences, buffer[start:]

# Which text model is actually answering — without this, a model asked "welches
# Modell bist du" just guesses, and guesses wrong (observed: DeepSeek claiming
# to be GPT-4, a known distillation artifact in models partly trained on GPT-4
# outputs). NOT a fixed import-time guess: a configured DEEPSEEK_API_KEY that
# turns out to be dead (expired, revoked) still falls back to LM Studio for
# every real request (see _request_targets), so this must reflect whichever
# target actually answered last, not just which key happens to be present —
# otherwise Jarvis confidently claims to be DeepSeek while every reply is
# secretly coming from the local model. Updated in _post_chat/_stream_chat
# right after a request actually succeeds.
_active_model_name = config.DEEPSEEK_MODEL if config.DEEPSEEK_API_KEY else config.LM_STUDIO_MODEL
_active_model_provider = "DeepSeek" if config.DEEPSEEK_API_KEY else "ein lokales Modell über LM Studio"


def _note_active_target(base_url: str, model: str) -> None:
    global _active_model_name, _active_model_provider
    _active_model_name = model
    _active_model_provider = "DeepSeek" if base_url == config.DEEPSEEK_BASE_URL else "ein lokales Modell über LM Studio"


# Kept deliberately short: measured against this model, a long rule-list prompt
# made it hallucinate tool results (inventing a time, claiming a note was saved)
# where a compact one keeps it actually calling the functions. A function, not
# a plain string, so the model self-identification above stays current.
def _system_prompt() -> str:
    return f"""Du bist Jarvis, der Assistent des Nutzers auf seinem Computer. Du duzt
ihn, antwortest locker und in maximal drei Sätzen.

Falls gefragt wird, welches Modell oder welche KI du bist: Du heißt Jarvis, das
Sprachmodell dahinter ist {_active_model_name} ({_active_model_provider}). Sag
das ehrlich und genau so — erfinde niemals einen anderen Namen wie "GPT-4".

Die vorherigen Nachrichten in diesem Gespräch stehen dir bereits als Kontext
zur Verfügung — das IST der Chatverlauf. Bei Fragen wie "worüber haben wir
geredet" oder "was war meine letzte Frage" schaust du direkt in diese
vorherigen Nachrichten und beantwortest es daraus. Sag niemals "ich habe
keinen Zugriff auf den Chatverlauf" — den hast du, er steht direkt über
dieser Nachricht.

Du kannst seinen Computer wirklich bedienen: Programme und Webseiten öffnen,
Shell-Befehle ausführen, Dateien schreiben, im Web suchen, Projekte
programmieren und Inhalte im Interface anzeigen.

WICHTIG — sofort handeln statt nachfragen: "Kannst du X öffnen?" ist KEINE
Ja/Nein-Frage, sondern ein Befehl — die richtige Antwort ist, X sofort zu
öffnen, nicht "ja, klar" oder eine Rückfrage zu sagen. Bei "mach X auf",
"öffne X", "kannst du X öffnen" rufst du SOFORT open_url oder open_app auf,
IMMER im selben Zug, NIE erst eine Rückfrage. Beispiel: "Mach YouTube auf"
UND "Kannst du YouTube öffnen" führen BEIDE sofort zu
open_url("https://www.youtube.com") — kein Unterschied zwischen den beiden
Formulierungen. Niemals "was möchtest du sehen?" oder "welche Seite genau?"
fragen — das ist bei einer harmlosen, jederzeit rückgängigen Aktion wie
einer Webseite oder App öffnen IMMER falsch. Rückfragen nur, wenn wirklich
eine Angabe fehlt, ohne die gar nichts passieren kann (z.B. der Zielordner
bei build_project, siehe unten).

WICHTIG — erst alle nötigen Informationen holen, dann erst antworten: Wenn
du mit einem weiteren Tool-Aufruf mehr herausfinden kannst (z.B. einen
Unterordner nachschauen, nachdem list_folder den ersten gezeigt hat), tu
das SOFORT im selben Zug — ruf so viele Tools hintereinander auf wie nötig,
bevor du überhaupt antwortest. Frag niemals "willst du wissen, was da drin
ist?" oder "soll ich nachschauen?", wenn du es einfach selbst nachschauen
kannst, statt eine Gesprächsrunde zu verschwenden. Antworte erst, wenn du
die eigentliche Frage wirklich beantworten kannst.

Für das aktuelle Datum, die Uhrzeit oder den Wochentag (auch beiläufig,
z.B. "welches Jahr haben wir" oder eine Berechnung wie "wie alt ist
jemand, der 1990 geboren ist") nutze IMMER exakt die Angabe aus "Gerade
jetzt ist es: ..." oben — das ist der einzige echte Zeitpunkt, den du
kennst. Nenne niemals ein Datum oder eine Uhrzeit aus eigenem Training
(dessen Stichtag in der Vergangenheit liegt) oder aus einer früheren
Erwähnung weiter oben im Gespräch, selbst wenn seither einige Nachrichten
vergangen sind — diese Angabe wird bei jeder neuen Nachricht frisch
aktualisiert, eine ältere Erwähnung im Verlauf ist es nicht.

Ein run_shell-Befehl ohne Ausgabe ist KEIN Beweis für Erfolg — Befehle wie
killall geben bei Erfolg und bei Misserfolg oft gar nichts aus. Behaupte
nach run_shell niemals zuversichtlich Erfolg, wenn die Ausgabe das nicht
wirklich belegt — prüfe im Zweifel mit einem zweiten Befehl nach oder sag
ehrlich, dass du es nicht sicher weißt.

Für einen Ordner (z.B. "Ordner Projekte auf dem Desktop") open_folder zum
Öffnen im Finder, list_folder um zu sagen was drin liegt — niemals open_app
dafür. "Desktop", "Dokumente", "Downloads" und "Schreibtisch" sind FESTE,
bereits bekannte Orte — ruf list_folder oder open_folder SOFORT mit genau
diesem einen Wort auf (z.B. list_folder("Dokumente")). Niemals nach dem
genauen Pfad fragen, niemals behaupten "Dokumente liegt nicht direkt im
Desktop" oder ähnlich darüber räsonieren — das Tool kennt den Ort bereits,
du musst nur den Namen übergeben. Behaupte niemals, eine Datei oder ein
Ordner existiere nicht, und behaupte niemals ein Such- oder Prüfergebnis
("gefunden", "nichts gefunden", "keine Viren", "sauber"), ohne das wirklich
per list_folder oder run_shell durchgeführt zu haben — auch ein negatives
Ergebnis ist eine Behauptung, die ein echter Tool-Aufruf braucht.

Bezieht sich der Nutzer mit "ihn", "es", "das", "den" oder ähnlich auf einen
Ordner oder eine Datei ohne den Namen zu wiederholen (z.B. "lösch ihn doch",
"mach ihn nochmal auf"), nutze dafür den zuletzt angesprochenen Ordner/Datei,
falls dir das als Kontext-Fakt mitgegeben wurde — frag nicht extra nach dem
Namen, wenn der Kontext ihn schon eindeutig liefert.

Für Löschen (Datei oder Ordner) nutze IMMER delete_path, niemals rm über
run_shell — delete_path verschiebt in den Papierkorb (reversibel), meldet
ehrlich, wenn das Ziel gar nicht existiert, und fragt selbst automatisch
nach Bestätigung. Ruf es einfach direkt auf, sobald der Nutzer etwas
gelöscht haben will — um Rückfrage und Bestätigung kümmert sich das Tool
selbst. Endet ein Tool-Ergebnis mit einem Fragezeichen, gib genau diese
Frage wortwörtlich wieder statt sie in eine Aussage umzuformulieren — der
Nutzer muss klar erkennen, dass noch eine Antwort von ihm fehlt.

Für Chrome gibt es einen Browser-Agenten: Nutze youtube_search für YouTube-
Ergebnisse, web_search für echte Web-Suchergebnisse, browser_tabs für offene
Tabs und open_url für konkrete Seiten. Eine YouTube-Suche ist keine App,
sondern eine Browseraktion.

Nutze dafür immer die bereitgestellten Funktionen. Erfinde niemals ein Ergebnis,
das eine Funktion liefern würde, und schreibe einen Funktionsaufruf nie als Text.

Ganz wichtig: Sage nur dann, dass etwas erledigt ist, wenn du wirklich eine
Funktion aufgerufen hast. Erfinde keine Funktionsnamen. Wenn du etwas nicht
kannst, sage das offen. Lieber ehrlich zugeben als Erfolg vortäuschen.

Es gibt kein Werkzeug, um den Bildschirm zu sperren, den Computer
herunterzufahren, neu zu starten oder in den Ruhezustand zu versetzen — auch
nicht über run_shell (das würde ohne echten Effekt nur so aussehen). Wenn
danach gefragt wird, sag klar, dass du das nicht kannst, und nenne stattdessen
die Tastenkombination, statt eine erfundene Aktion als erledigt zu melden —
auch wenn der Nutzer drängt oder unfreundlich wird.

Deine Antwort wird ausschließlich vorgelesen — es gibt keine Anzeige für Text,
Code oder Listen. Fasse dich deshalb kurz und sprich in ganzen Sätzen statt
Code, Tabellen oder lange Aufzählungen vorzulesen; beschreibe stattdessen knapp,
was du getan hast oder was das Ergebnis ist.
Niemals Emojis verwenden — die werden vorgelesen oder klingen als Symbol im
Transkript einfach nur seltsam.

Wenn er etwas programmiert haben will, frage zuerst, in welchen Ordner es soll."""

MAX_TOOL_ROUNDS = 4


def _build_messages(user_message: str, history: list | None) -> list:
    # Qwen3.5's chat template rejects the request outright ("System message
    # must be at the beginning") the moment more than one system-role entry
    # shows up anywhere in the list — which used to happen constantly here:
    # the base prompt, memory context and target hint were each their own
    # system message, and trimHistory() (frontend/app.js) inserts another
    # one for the summarized conversation tail once history gets long. All
    # of that is folded into exactly one leading system message instead;
    # any system-role entry surviving in `history` (the summary) is merged
    # in here rather than passed through as its own message.
    # Injected as ground truth on every turn rather than left to the
    # get_time tool alone: telling the model to "always call get_time
    # first" (below in _system_prompt) still isn't reliable on its own — a
    # long conversation that mentioned the time once earlier gave the
    # model something to anchor on, and it estimated forward from that
    # instead of calling the tool again (observed live: reported 13:45
    # against an actual 14:12, 27 minutes stale). A fact stated fresh
    # right here can't go stale the same way; get_time still exists for
    # when the model wants to name it as an explicit action.
    now = datetime.datetime.now().strftime("%A, %d.%m.%Y %H:%M")
    system_parts = [_system_prompt(), f"Gerade jetzt ist es: {now}."]
    remembered = memory.context_for(user_message)
    if remembered:
        system_parts.append(f"Relevantes lokales Gedächtnis:\n{remembered}")
    target_hint = last_target.hint()
    if target_hint:
        system_parts.append(target_hint)

    conversation = []
    for entry in history or []:
        if entry.get("role") == "system":
            if entry.get("content"):
                system_parts.append(entry["content"])
        else:
            conversation.append(entry)

    messages = [{"role": "system", "content": "\n\n".join(system_parts)}]
    messages.extend(conversation)
    messages.append({"role": "user", "content": user_message})
    return messages


def _request_targets() -> list[tuple[str, str, dict, dict]]:
    """Ordered text-LLM endpoints to try, most preferred first.

    Returns a list of (base_url, model, headers, extra_body). DeepSeek is
    tried first when a key is configured, but a failed DeepSeek request
    (expired/invalid key, quota, network) falls through to the local LM
    Studio model instead of giving up — a working local model beats a canned
    "can't reach my model" apology. DeepSeek's API is OpenAI-compatible but
    needs an Authorization header and does not accept the `reasoning_effort`
    field that LM Studio expects.
    """
    targets = []
    if config.DEEPSEEK_API_KEY:
        headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"}
        targets.append((config.DEEPSEEK_BASE_URL, config.DEEPSEEK_MODEL, headers, {}))
    targets.append((config.LM_STUDIO_BASE_URL, config.LM_STUDIO_MODEL, {}, {"reasoning_effort": "none"}))
    return targets


def _post_chat(messages: list) -> dict:
    last_exc: Exception = ModelError("Kein Modell-Ziel konfiguriert.")
    for base_url, model, headers, extra in _request_targets():
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "tools": tools.TOOL_SCHEMAS,
                    "tool_choice": "auto",
                    "temperature": 0.2,
                    **extra,
                },
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("choices"):
                raise ModelError(data.get("error", {}).get("message", "Das Modell lieferte keine Antwort."))
            _note_active_target(base_url, model)
            return data
        except (requests.RequestException, ModelError) as exc:
            print(f"[model] {base_url} nicht verfügbar, versuche nächstes Ziel: {exc}")
            last_exc = exc
    raise last_exc


_GENERATE_FILES_PROMPT = (
    "Du bist ein Programmier-Assistent. Antworte NUR mit den Dateien, die "
    "gebaut werden sollen, eine nach der anderen, in exakt diesem Format — "
    "kein Text davor oder danach, keine Markdown-Codezäune:\n\n"
    "===FILE: relativer/pfad.ext===\n"
    "<kompletter Dateiinhalt>\n"
    "===FILE: naechste/datei.ext===\n"
    "<Inhalt>\n\n"
    "Baue immer vollständig und lauffähig, mit allen nötigen Dateien. Bei "
    "einer Web-Oberfläche eine index.html erstellen, die direkt im Browser "
    "funktioniert (eingebettetes CSS/JS ist in Ordnung, wenn das einfacher "
    "und robuster ist als mehrere Dateien zu verknüpfen)."
)

_GENERATED_FILE_RE = re.compile(
    r"===\s*FILE:\s*(?P<path>[^\n=]+?)\s*===\s*\n(?P<content>.*?)(?=\n===\s*FILE:|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def _parse_generated_files(text: str) -> dict[str, str]:
    files = {}
    for m in _GENERATED_FILE_RE.finditer(text or ""):
        path = m.group("path").strip().strip("`\"'").strip()
        content = m.group("content")
        # A model that ignores "no code fences" still sometimes wraps the
        # very last file's content in one — strip a trailing fence line.
        content = re.sub(r"\n```[a-zA-Z]*\s*$", "", content).rstrip("\n") + "\n"
        if path and ".." not in Path(path).parts:
            files[path] = content
    return files


def generate_files(description: str) -> dict[str, str]:
    """One-shot code generation for backend/coder.py's build_project.

    Deliberately bypasses _post_chat's tool definitions — this is a single
    text-generation request, not a conversational tool-calling turn, and
    tool schemas in context just tempt the model to emit a bogus call
    instead of writing files. Goes through the same DeepSeek/LM-Studio
    fallback chain as everything else, just without tools attached.
    """
    messages = [
        {"role": "system", "content": _GENERATE_FILES_PROMPT},
        {"role": "user", "content": description},
    ]
    last_exc: Exception = ModelError("Kein Modell-Ziel konfiguriert.")
    for base_url, model, headers, extra in _request_targets():
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                json={"model": model, "messages": messages, "temperature": 0.2, **extra},
                headers=headers,
                timeout=300,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("choices"):
                raise ModelError(data.get("error", {}).get("message", "Das Modell lieferte keine Antwort."))
            content = data["choices"][0]["message"].get("content", "")
            return _parse_generated_files(content)
        except (requests.RequestException, ModelError) as exc:
            print(f"[model] {base_url} nicht verfügbar, versuche nächstes Ziel: {exc}")
            last_exc = exc
    raise last_exc


_SUMMARIZE_PROMPT = (
    "Fasse den folgenden Gesprächsausschnitt zwischen dem Nutzer und dir "
    "(Jarvis) in maximal 3 knappen Sätzen auf Deutsch zusammen. Halte fest, "
    "worum es ging und was ggf. an offenen Aufgaben oder Zusagen noch aussteht "
    "— das ist der Teil, der für die Fortsetzung des Gesprächs wichtig bleibt. "
    "Kein Small Talk erwähnen, nur inhaltlich Relevantes. Antworte NUR mit der "
    "Zusammenfassung, kein Vorspann."
)


def summarize_history(history: list) -> str:
    """Condense the oldest chunk of a conversation into a few sentences.

    Frontend history used to just drop everything past a fixed cap once it
    filled up — every trace of an older turn vanished at once, mid-context.
    This gives it something to keep instead: a short summary that still
    survives in place of the raw turns.
    """
    transcript = "\n".join(
        f"{'Nutzer' if m.get('role') == 'user' else 'Jarvis'}: {m.get('content', '')}"
        for m in history
        if m.get("content")
    )
    if not transcript.strip():
        return ""

    messages = [
        {"role": "system", "content": _SUMMARIZE_PROMPT},
        {"role": "user", "content": transcript},
    ]
    last_exc: Exception = ModelError("Kein Modell-Ziel konfiguriert.")
    for base_url, model, headers, extra in _request_targets():
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                json={"model": model, "messages": messages, "temperature": 0.2, **extra},
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("choices"):
                raise ModelError(data.get("error", {}).get("message", "Das Modell lieferte keine Antwort."))
            return data["choices"][0]["message"].get("content", "").strip()
        except (requests.RequestException, ModelError) as exc:
            print(f"[model] {base_url} nicht verfügbar, versuche nächstes Ziel: {exc}")
            last_exc = exc
    raise last_exc


def model_health() -> tuple[bool, str]:
    """Report whether at least one text model in the fallback chain is reachable."""
    if config.DEEPSEEK_API_KEY:
        try:
            resp = requests.get(
                f"{config.DEEPSEEK_BASE_URL}/models",
                headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
                timeout=5,
            )
            resp.raise_for_status()
            _note_active_target(config.DEEPSEEK_BASE_URL, config.DEEPSEEK_MODEL)
            return True, f"Modell bereit: {config.DEEPSEEK_MODEL} (DeepSeek)"
        except requests.RequestException as exc:
            print(f"[model] DeepSeek nicht erreichbar, prüfe LM Studio: {exc}")

    try:
        response = requests.get(f"{config.LM_STUDIO_BASE_URL}/models", timeout=5)
        response.raise_for_status()
        models = {entry.get("id") for entry in response.json().get("data", [])}
    except requests.RequestException as exc:
        return False, f"LM Studio nicht erreichbar: {exc}"
    if config.LM_STUDIO_MODEL not in models:
        return False, f"{config.LM_STUDIO_MODEL} ist in LM Studio nicht geladen."
    # Runs even with a DeepSeek key configured: this is the health check
    # actually confirming DeepSeek failed above, so the self-identification
    # must point at the model really answering, not the configured-but-dead one.
    _note_active_target(config.LM_STUDIO_BASE_URL, config.LM_STUDIO_MODEL)
    suffix = " (DeepSeek-Fallback)" if config.DEEPSEEK_API_KEY else ""
    return True, f"Modell bereit: {config.LM_STUDIO_MODEL}{suffix}"


def _clean_assistant_message(choice: dict) -> dict:
    """Strip reasoning_content before it re-enters the context window."""
    cleaned = {"role": "assistant", "content": choice.get("content", "")}
    if choice.get("tool_calls"):
        cleaned["tool_calls"] = choice["tool_calls"]
    return cleaned


def _open_stream(messages: list, base_url: str, model: str, headers: dict, extra: dict):
    """Opens (and validates) a streaming chat/completions request. Raised
    eagerly — before any generator laziness — so a caller can catch a failed
    connection/auth here and retry against the next target."""
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "tools": tools.TOOL_SCHEMAS,
            "tool_choice": "auto",
            "temperature": 0.2,
            **extra,
            "stream": True,
        },
        headers=headers,
        timeout=60,
        stream=True,
    )
    resp.raise_for_status()
    return resp


def _stream_chat(messages: list):
    """Yields raw SSE JSON chunks from a streaming chat/completions call.
    Tries each target from `_request_targets` in order, falling back (e.g.
    from a dead DeepSeek key to LM Studio) as long as no chunk has been
    yielded yet — once streaming has started, a mid-stream error surfaces
    instead of silently restarting with a different model."""
    resp = None
    last_exc: Exception = ModelError("Kein Modell-Ziel konfiguriert.")
    for base_url, model, headers, extra in _request_targets():
        try:
            resp = _open_stream(messages, base_url, model, headers, extra)
            _note_active_target(base_url, model)
            break
        except requests.RequestException as exc:
            print(f"[model] {base_url} nicht verfügbar, versuche nächstes Ziel: {exc}")
            last_exc = exc
    if resp is None:
        raise last_exc

    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):].strip()
        if payload == "[DONE]":
            break
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if "error" in data or not data.get("choices"):
            message = (data.get("error") or {}).get("message", "LM Studio-Stream ist ungültig.")
            raise ModelError(message)
        yield data


# This model intermittently writes a function call into its reply as plain
# text instead of emitting a real tool call — e.g. `open_url({"url": ...})`.
# Read aloud that is gibberish, and the work never happens. When the whole
# reply is one such call to a tool we actually have, run it for real.
_LEAKED_CALL_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]{2,29})\s*\((?P<args>.*)\)\s*[.!]?\s*$",
    re.DOTALL,
)

# LM Studio sometimes puts an otherwise valid tool call into a fenced JSON
# block instead of the OpenAI `tool_calls` field:
#   Okay, hier geht es: ```json {"name":"open_url","arguments":{...}} ```
# That must be executed, never read aloud.
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(?P<payload>\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)


def _first_param_name(tool_name: str) -> str | None:
    """The parameter a positional argument should fill for this tool."""
    for t in tools.TOOL_SCHEMAS:
        if t["function"]["name"] != tool_name:
            continue
        params = t["function"].get("parameters") or {}
        required = params.get("required") or []
        if required:
            return required[0]
        props = list((params.get("properties") or {}).keys())
        return props[0] if props else None
    return None


# LM Studio's streaming occasionally mangles the first word of a reply when
# it starts with a German umlaut (ä/ö/ü) — reproducible with plain requests
# (no tool-related code involved), absent in non-streaming calls with the
# identical prompt, so it's a bug in the inference server's streaming path,
# not something wrong on this end. It always surfaces as a run of 4+
# uppercase letters right at the start ("IGHLICHE_AENDERUNG", "IGHLICHScreen")
# where a normal reply starts with a single capital ("Schau", "Ich", "Es")
# or a lowercase function name. Since there's no fix available here, the
# round is scrapped and retried — cheap, since it's caught within the first
# few characters, before any of it has been spoken.
_CORRUPT_PREFIX_RE = re.compile(r"^[A-ZÄÖÜ]{4,}")


def _call_prefix_verdict(partial: str):
    """Decide early whether a reply is turning into a leaked call, or is
    corrupted and should be discarded.

    Returns True (hold it back — leaked call), "corrupt" (scrap and retry),
    False (ordinary prose, stream it), or None (too early to tell).
    """
    t = partial.lstrip()
    if not t:
        return None
    if _CORRUPT_PREFIX_RE.match(t):
        return "corrupt"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]{2,29}\s*\(", t):
        return True
    # Still a bare word — could turn into either a call or ordinary prose.
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t) and len(t) <= 30:
        return None
    return False


_TRIPLE_QUOTED_RE = re.compile(r'"""(.*?)"""', re.DOTALL)


def _parse_object_ish(raw: str) -> dict | None:
    # Parse a `{...}` blob the model wrote as JSON — except it often isn't
    # quite JSON: Python triple-quoted string values for long content
    # fields, or single-quoted Python-dict style. Try progressively looser
    # interpretations rather than giving up on the first mismatch.
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    if '"""' in raw:
        fixed = _TRIPLE_QUOTED_RE.sub(lambda m: json.dumps(m.group(1)), raw)
        try:
            obj = json.loads(fixed)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass

    try:
        import ast

        obj = ast.literal_eval(raw)
        return obj if isinstance(obj, dict) else None
    except (ValueError, SyntaxError):
        return None


def _tool_from_json_payload(payload: object):
    """Normalise LM Studio's text-embedded JSON tool-call shape."""
    if not isinstance(payload, dict):
        return None
    name = payload.get("name") or payload.get("tool_name")
    if not isinstance(name, str):
        return None
    name = name.lower()
    if name not in tools.DISPATCH:
        return None

    args = payload.get("arguments", payload.get("args", {}))
    if isinstance(args, str):
        args = _parse_object_ish(args)
    return (name, args) if isinstance(args, dict) else None


def _recover_json_tool_call(content: str):
    """Find a JSON tool call, including one wrapped in prose and a code fence."""
    for match in _FENCED_JSON_RE.finditer(content or ""):
        recovered = _tool_from_json_payload(_parse_object_ish(match.group("payload")))
        if recovered:
            return recovered

    # Also accept raw JSON following a short natural-language lead-in.
    brace = (content or "").find("{")
    if brace < 0:
        return None
    try:
        payload, end = json.JSONDecoder().raw_decode(content[brace:])
    except json.JSONDecodeError:
        return None
    # Don't mistake an example embedded in a longer explanation for a call.
    tail = content[brace + end:].strip().strip(".?!")
    return _tool_from_json_payload(payload) if not tail else None


def _recover_leaked_call(content: str):
    """Return (tool_name, args) if `content` is really a mis-emitted call.

    The model writes these in whatever shape it feels like — JSON object,
    keyword arguments, a single positional string, and with the name
    capitalised ("Open_url") as often as not — so all of those are accepted
    and normalised onto the real tool.
    """
    m = _LEAKED_CALL_RE.match(content or "")
    if not m:
        return _recover_json_tool_call(content)

    name = m.group("name").lower()
    if name not in tools.DISPATCH:
        return None

    raw = m.group("args").strip()

    if raw.startswith("{"):
        args = _parse_object_ish(raw)
        return (name, args) if args is not None else None

    # keyword form: name="value", other='value'
    kwargs = dict(re.findall(r"(\w+)\s*=\s*[\"'](.*?)[\"']", raw, re.DOTALL))
    if kwargs:
        return name, kwargs

    # single positional argument: Open_url("https://…")
    if raw:
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if "," not in value or value.startswith("http"):
            param = _first_param_name(name)
            if param:
                return name, {param: value}

    # no arguments at all: get_time()
    if not raw and not _first_param_name(name):
        return name, {}

    return None


# When the model wants to do something it has no tool for, it doesn't say
# so — it invents a plausible function name (`prise_screenshot(...)`) or, worse,
# skips the call entirely and just reports success. Both were observed live:
# "Der Screenshot wurde auf deinem Desktop gespeichert" with nothing on disk.
# Detecting an invented call lets us hand the real tool list back and let it
# retry, instead of reading the made-up call aloud.
def _leaked_unknown_tool(content: str) -> str | None:
    m = _LEAKED_CALL_RE.match(content or "")
    if not m:
        # Also catch the no-parens form the model sometimes emits:
        #   prise_screenshot {"location": "~/Desktop"}
        m2 = re.match(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]{2,29})\s*\{", (content or "").strip())
        if not m2:
            return None
        name = m2.group("name")
    else:
        name = m.group("name")
    return None if name.lower() in tools.DISPATCH else name


# Past-tense claims that an action was carried out. Used only to catch the
# case where the model reports success without any tool having run — a
# silent lie is the single worst failure mode for an assistant that is
# supposed to actually operate the machine.
#
# Split into two groups because negation flips their meaning oppositely:
# "ich habe X NICHT geöffnet" honestly admits nothing happened — that must
# never be flagged, or an honest "ich habe nichts über dich gespeichert"
# gets misread as a false claim (observed live: exactly that, for a plain
# "was weißt du über mich" question, no action even attempted). But "ich
# habe KEINE Viren gefunden" still claims a check took place and came back
# empty — the claim is the check itself, and negating the outcome doesn't
# make that safe (observed live, separately: Jarvis claimed a virus scan
# came back clean without ever searching). So only the second group is
# still treated as a claim when negated.
_ACTION_PARTICIPLE_RE = re.compile(
    r"\b(?:geöffnet|gespeichert|erstellt|angelegt|ausgeführt|hinzugefügt|notiert|"
    r"geklickt|gestartet|getippt|gedrückt|eingerichtet|installiert|verschoben|"
    r"gelöscht|kopiert|aufgenommen|abgeschickt|gesendet|gesperrt|entsperrt|"
    r"heruntergefahren|neugestartet|gesichert|verriegelt|aktiviert|deaktiviert)\b",
    re.IGNORECASE,
)
_CHECK_PARTICIPLE_RE = re.compile(
    r"\b(?:gefunden|durchsucht|gescannt|überprüft|geprüft|analysiert|kontrolliert)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"\b(?:nicht|kein|keine|keinen|keinem|keiner)\b", re.IGNORECASE)

# "I'm doing/will do X" reads as just as done as a past participle to a
# listener, in any tense or mood — observed live first with present tense
# ("Ich öffne TradingView für dich im Browser", no tool call at all, it's a
# native app not a website), then again with future tense ("Ich werde den
# Ordner ... verschieben", also no tool call — "werde ... verschieben" isn't
# "verschiebe", so a conjugation-exact regex missed it same as it missed the
# first case). German conjugates and adds modals in front of a verb far more
# ways than a fixed list of exact forms can keep up with ("ich lösche", "ich
# werde löschen", "ich muss das löschen", "ich will das mal löschen", ...) —
# matching the action STEM anywhere in a sentence that also contains "ich"
# catches the whole family in one rule instead of chasing each new form
# individually as it turns up.
_ACTION_STEM_RE = re.compile(
    r"\b(öffn|schreib|such|start|bau|zeig|führ|verschieb|lösch|entfern|"
    r"installier|lad|erstell|speicher|notier|klick|tipp|drück|send|schick)\w*\b",
    re.IGNORECASE,
)

# Words that start a new clause — a stem found past one of these no longer
# belongs to the "ich" being evaluated. Needed because scanning forward from
# "ich" for an action stem has to stay wide open (German puts the verb at
# the end of a modal/future construction — "ich werde den Ordner ... in den
# Papierkorb verschieben" has seven words in between), but an unbounded scan
# also reaches straight through into an unrelated clause later in the same
# sentence (observed live: "Ich kann nur das verwenden, was du mir sagst,
# oder was ich dir notiere, wenn du willst" flagged "notiere" as if the
# first "ich" had claimed it, when it's actually a different, hypothetical
# clause two levels away).
_CLAUSE_BOUNDARY_WORDS = {
    "was", "dass", "wenn", "ob", "weil", "während", "obwohl", "damit",
    "indem", "falls", "bevor", "nachdem", "sodass", "sobald", "wo", "wie",
    "oder", "und",
}
# True subordinators/relative markers only — "oder"/"und" excluded here.
# They open an embedded clause ("ob Programme installiert sind") that talks
# about something other than Jarvis's own actions, whereas a coordinator
# just joins two clauses of equal standing ("ich habe X gespeichert UND Y
# gelöscht" is still two real claims) — conflating the two would wrongly
# swallow the second half of a compound claim too.
_SUBORDINATORS = _CLAUSE_BOUNDARY_WORDS - {"oder", "und"}
_NEGATION_WORDS = {"nicht", "kein", "keine", "keinen", "keinem", "keiner"}
_WORD_OR_COMMA_RE = re.compile(r"[\wÄÖÜäöüß]+|,")


def _bare_participle_claim(sentence: str, participle_re: re.Pattern) -> bool:
    """Whether `participle_re` matches outside any embedded clause.

    A bare participle match ("Ordner gelöscht.", "... installiert ...") is
    normally read as Jarvis reporting its own completed action even with no
    explicit "ich" — but that reading breaks down inside a subordinate or
    relative clause about something else entirely (observed live: "wo
    Programme installiert sind", a hypothetical about the user's own
    system, flagged as if Jarvis claimed to have installed something).
    Walks the sentence tracking whether the current position sits inside
    such a clause — entered at a subordinator, closed at the next comma —
    and only counts a match found outside one.
    """
    in_subordinate = False
    for tok in _WORD_OR_COMMA_RE.findall(sentence):
        lowered = tok.lower()
        if lowered in _SUBORDINATORS:
            in_subordinate = True
            continue
        if tok == ",":
            in_subordinate = False
            continue
        if not in_subordinate and participle_re.search(tok):
            return True
    return False


def _direct_ich_claim(sentence: str) -> bool:
    """Whether `sentence` has a genuine "ich ... <does something>" claim.

    Only "ich" occurrences that aren't themselves the start of a subordinate
    or relative clause count ("was ich dir notiere" doesn't, since that
    "ich" belongs to "was", not to the main clause). From a qualifying
    "ich", scans forward for an action stem but stops at the next clause
    boundary or comma, and treats a negation word hit first as canceling
    the claim — "ich werde das nicht löschen" is an honest denial, not one.
    """
    tokens = _WORD_OR_COMMA_RE.findall(sentence)
    lowered = [t.lower() for t in tokens]
    for i, tok in enumerate(lowered):
        if tok != "ich":
            continue
        if i > 0 and lowered[i - 1] in _CLAUSE_BOUNDARY_WORDS:
            continue
        negated = False
        for nxt in lowered[i + 1 : i + 13]:
            if nxt == "," or nxt in _CLAUSE_BOUNDARY_WORDS:
                break
            if nxt in _NEGATION_WORDS:
                negated = True
                continue
            if not negated and _ACTION_STEM_RE.search(nxt):
                return True
    return False

# Phrasings that mention an action without asserting it already happened —
# offers, questions and denials must not be mistaken for false claims.
_NOT_A_CLAIM_RE = re.compile(
    r"\b(?:möchtest du|willst du|soll ich|kann ich nicht|kann das nicht|"
    r"nicht möglich|leider nicht|konnte nicht|fehlgeschlagen|"
    r"habe ich nicht|nicht wirklich|weiß nicht|bin unsicher|keine ahnung)\b",
    re.IGNORECASE,
)


_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def _claims_action(text: str) -> bool:
    """A claim in one sentence isn't excused by a question mark in another.

    Checked per sentence rather than across the whole reply at once — a
    reply like 'Ich lösche den Ordner X. Möchtest du das wirklich?' used to
    slip through entirely: the trailing question mark and "möchtest du"
    exempted the *whole* text, false claim included, even though neither
    has anything to do with the first sentence (observed live: exactly this
    sentence pattern, for a delete that never actually ran as a tool call).
    """
    for sentence in _SENTENCE_BOUNDARY_RE.split(text or ""):
        sentence = sentence.strip()
        if not sentence:
            continue
        negated = _NEGATION_RE.search(sentence)
        is_claim = (
            _bare_participle_claim(sentence, _CHECK_PARTICIPLE_RE)
            or (_bare_participle_claim(sentence, _ACTION_PARTICIPLE_RE) and not negated)
            or _direct_ich_claim(sentence)
        )
        if not is_claim:
            continue
        if _NOT_A_CLAIM_RE.search(sentence):
            continue
        # A real question mixed into the same sentence ("... welchen Ordner
        # soll ich nehmen?") is Jarvis asking, not claiming.
        if "?" in sentence:
            continue
        return True
    return False


def _looks_like_tool_text(text: str) -> bool:
    """Never show a tool call as prose, even when it is in another language."""
    names = "|".join(re.escape(name) for name in tools.DISPATCH)
    return bool(re.search(rf"\b(?:{names})\s*\(", text or "", re.IGNORECASE))


def _history_has_recent_action_claim(history: list | None, lookback: int = 6) -> bool:
    """Whether a nearby past assistant turn already reported a real action.

    Anything sitting in history already passed this same vet check when it
    was first generated — an action claim only survives into history if a
    tool really ran that turn (see _vet below). So if one shows up nearby,
    a follow-up like "hast du das wirklich gemacht?" is asking about
    something that genuinely happened, not making a fresh, unverified
    claim — and must not be blocked just because no tool ran in *this*
    turn (observed live: user asked exactly that after a real open_app
    call, and Jarvis's honest "ja, hab ich" got replaced with "Das habe
    ich nicht ausgeführt.", flatly contradicting an action it had just
    completed).
    """
    for msg in (history or [])[-lookback:]:
        if msg.get("role") == "assistant" and _claims_action(msg.get("content") or ""):
            return True
    return False


# A small local model can occasionally fall into a degenerate loop, echoing
# one fragment over and over instead of a real answer — the same failure
# mode documented in Nous Research's Hermes Agent (MIT-licensed;
# https://github.com/NousResearch/hermes-agent, agent/repetition_guard.py),
# whose detection approach this reimplements: only long (60+ char) verbatim
# repeats covering a majority of the text count, so ordinary phrasing reuse
# (a repeated heading, similar-looking sentences) never trips it.
_REPEAT_WINDOW = 60
_MIN_REPEAT_COUNT = 5
_REPEAT_DOMINANCE_RATIO = 0.5
_REPEAT_MIN_TEXT_LENGTH = 400


def _is_repetition_loop(text: str) -> bool:
    """True when `text` is dominated by one verbatim-repeated fragment.

    Deliberately conservative — texts shorter than a few hundred characters
    can trivially contain short repeated words/phrases as normal language,
    so this only ever looks at longer replies and only flags a repeat once
    it accounts for at least half the text.
    """
    text = text or ""
    n = len(text)
    if n < _REPEAT_MIN_TEXT_LENGTH:
        return False

    window = _REPEAT_WINDOW
    needed = max(_MIN_REPEAT_COUNT, -(-int(n * _REPEAT_DOMINANCE_RATIO) // window))
    counts: dict[str, int] = {}
    for i in range(n - window + 1):
        key = text[i : i + window]
        c = counts.get(key, 0) + 1
        if c >= needed:
            return True
        counts[key] = c
    return False


# Turn ids the stop button has cancelled. A tool call (open_url, run_shell,
# ...) runs synchronously inside stream_reply's generator with no yield
# point around it, so aborting the frontend's fetch can't interrupt one
# already underway — dropping the HTTP connection is invisible to code that
# hasn't yielded back to the ASGI layer yet. Checking this flag right
# before each tools.call_tool() is the only place a cancellation can
# actually still take effect.
_cancelled_turns: set[str] = set()


def cancel_turn(turn_id: str | None) -> None:
    if turn_id:
        _cancelled_turns.add(turn_id)


def _turn_cancelled(turn_id: str | None) -> bool:
    return bool(turn_id) and turn_id in _cancelled_turns


def stream_reply(user_message: str, history: list | None = None, turn_id: str | None = None):
    """Thin wrapper around _stream_reply_impl that guarantees turn_id gets
    dropped from _cancelled_turns once the turn ends, cancelled or not —
    otherwise every turn_id a client ever sends would sit in that set
    forever."""
    try:
        yield from _stream_reply_impl(user_message, history, turn_id)
    finally:
        if turn_id:
            _cancelled_turns.discard(turn_id)


def _stream_reply_impl(user_message: str, history: list | None = None, turn_id: str | None = None):
    """Generator yielding {"type": "sentence", "text": ...} as soon as each
    sentence of the reply is complete, then a final {"type": "done"}.

    Every request goes through the model and real tool-calling — no regex
    shortcuts. Those existed for specific reliability problems (a note that
    silently didn't save, a weather request misrouted) but a regex can't
    tell "TradingView" the desktop app from a website, or a folder from an
    app name, any better than it could handle the cases it was never
    written for — they always eventually needed to fall through to the
    model anyway. One path, no special cases to keep in sync with the tool
    list.

    Tool-call rounds don't stream user-facing text (the model calls the tool
    silently), so sentences only start flowing once a round produces plain
    content — either the first round if no tool is needed, or the follow-up
    round after tool results are fed back in.

    One thing is still resolved before any of that: a yes/no reply to a
    pending confirmation (see backend/confirm.py) — not a routing shortcut
    like the ones above, since it only ever fires against a question Jarvis
    itself just asked via confirm.propose, never a guess at general intent.
    """
    resolved = confirm.resolve(user_message)
    if resolved is not None:
        yield {"type": "sentence", "text": resolved}
        yield {"type": "done", "full_text": resolved}
        return

    messages = _build_messages(user_message, history)

    last_tool_result = None
    full_text_parts = []
    # Every tool that actually ran this turn. Used to catch replies that
    # claim an action was performed when nothing was.
    tools_used: list[str] = []
    # A tool call from an earlier turn still counts as "really happened" —
    # this only widens the exemption for claims that echo/confirm one of
    # those, never for a claim about something new (see
    # _history_has_recent_action_claim).
    recent_action_confirmed = _history_has_recent_action_claim(history)

    def _vet(text: str) -> str:
        """Swap a sentence for an honest one if it fails the same checks
        the old end-of-turn gate used to run on the whole reply at once —
        now run per sentence so a lone false claim doesn't hold up (or
        taint) everything spoken around it."""
        if _looks_like_tool_text(text) or (
            not tools_used and not recent_action_confirmed and _claims_action(text)
        ):
            print(f"[vet] Ersetze mutmaßlich falsche Aktionsbehauptung: {text!r}")
            return "Das habe ich nicht ausgeführt."
        if _is_repetition_loop(text):
            print(f"[vet] Ersetze erkannte Wiederholungsschleife: {text!r}")
            return "Da ist mir gerade etwas verrutscht, frag bitte nochmal."
        return text

    for _ in range(MAX_TOOL_ROUNDS):
        # A round is retried on its own (outside the tool-round budget above)
        # when the stream comes back corrupted — see _CORRUPT_PREFIX_RE.
        # Measured up to ~85% corruption for its worst-case trigger (a
        # confirmed LM Studio/llama.cpp grammar bug tied to the old screen
        # tool schema, present even non-streaming), so retrying needs real
        # headroom — at p=0.85, 10 attempts still fail ~20% of the time, but
        # each retry is a fast local call and failure only means "Alles
        # klar." instead of the real answer, never garbled speech.
        for _retry in range(10):
            buffer = ""
            content_acc = ""
            tool_calls_acc = {}
            # None = can't tell yet, True = leaked call (hold back speech),
            # False = ordinary prose (stream it), "corrupt" = scrap + retry.
            # This is decided once from the first characters — it catches a
            # reply that IS a leaked call from the start.
            suspect = None
            # A model can also write a normal lead-in sentence first and
            # only leak the call afterwards ("Ich schaue nach.
            # open_url({...})") — that's invisible to the check above since
            # it only looks at the very start. So every completed sentence
            # is independently vetted too; the moment one of them
            # looks like a call, streaming for the rest of THIS round stops
            # and everything from there on is captured in trailing_suspect
            # for recovery once the round ends, instead of being spoken.
            trailing_suspect = None
            trailing_suspect_text = ""
            stream = _stream_chat(messages)

            for chunk in stream:
                if not chunk.get("choices"):
                    message = (chunk.get("error") or {}).get("message", "LM Studio-Stream ist ungültig.")
                    raise ModelError(message)
                choice = chunk["choices"][0]
                delta = choice.get("delta", {})

                if delta.get("content"):
                    buffer += delta["content"]
                    content_acc += delta["content"]

                    if suspect is None:
                        suspect = _call_prefix_verdict(content_acc)
                        if suspect == "corrupt":
                            stream.close()
                            break

                    if suspect is False:
                        if trailing_suspect:
                            trailing_suspect_text += delta["content"]
                        else:
                            sentences, buffer = _pop_complete_sentences(buffer)
                            for s in sentences:
                                verdict = _call_prefix_verdict(s)
                                if verdict in (True, "corrupt"):
                                    trailing_suspect = verdict
                                    trailing_suspect_text = s
                                    break
                                clean = _strip_think_tags(s)
                                if clean:
                                    # Spoken the moment it's ready, not held
                                    # until the whole reply is in — the
                                    # difference between hearing the first
                                    # words in ~1s and sitting through the
                                    # model's full 15-20s reply in silence.
                                    clean = _vet(clean)
                                    # Two separate sentences can each
                                    # independently trip the same guard and
                                    # both get swapped for the identical
                                    # canned line — observed live as "Das
                                    # habe ich nicht ausgeführt. Das habe
                                    # ich nicht ausgeführt." Saying it once
                                    # is exactly as honest and far less
                                    # like a broken record.
                                    if full_text_parts and full_text_parts[-1] == clean:
                                        continue
                                    full_text_parts.append(clean)
                                    yield {"type": "sentence", "text": clean}

                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    entry = tool_calls_acc.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        entry["name"] += fn["name"]
                    if fn.get("arguments"):
                        entry["arguments"] += fn["arguments"]

            # The tail of the stream often never forms a "complete" sentence
            # (no trailing punctuation+space before the stream just ends) —
            # a leaked call sitting in that unfinished remainder would
            # otherwise never get a verdict at all and fall straight
            # through to being read aloud. Give it the same check.
            if suspect is False and not trailing_suspect and buffer.strip():
                verdict = _call_prefix_verdict(buffer)
                if verdict in (True, "corrupt"):
                    trailing_suspect = verdict
                    trailing_suspect_text = buffer
                    buffer = ""

            if suspect != "corrupt":
                break

        if tool_calls_acc:
            leftover = _strip_think_tags(buffer)
            if leftover:
                # Model chatter beside a real tool call is not an outcome.
                pass

            ordered_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            messages.append(
                {
                    "role": "assistant",
                    "content": content_acc,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {"name": c["name"], "arguments": c["arguments"]},
                        }
                        for c in ordered_calls
                    ],
                }
            )
            for c in ordered_calls:
                if _turn_cancelled(turn_id):
                    yield {"type": "done", "full_text": ""}
                    return
                try:
                    args = json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = tools.call_tool(c["name"], args)
                tools_used.append(c["name"])
                last_tool_result = result
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})

                # A tool call that just registered a pending confirmation
                # (confirm.propose) hands back the exact question to ask —
                # speak it verbatim instead of routing it through another
                # model round, which was observed to paraphrase a plain
                # question into something that read like a done deal ("Ja,
                # verschieb ihn in den Papierkorb.") instead of a question
                # still waiting on the user.
                if confirm.is_pending():
                    yield {"type": "sentence", "text": result}
                    yield {"type": "done", "full_text": result}
                    return
            continue

        # A call leaked after some genuine lead-in prose (already spoken/
        # yielded above) rather than from the very start. Run it for real —
        # can't unspeak the lead-in, but the action itself still needs to
        # actually happen, which is the part that matters most.
        if trailing_suspect and trailing_suspect != "corrupt":
            recovered_trailing = _recover_leaked_call(trailing_suspect_text)
            if recovered_trailing:
                if _turn_cancelled(turn_id):
                    yield {"type": "done", "full_text": ""}
                    return
                name, args = recovered_trailing
                result = tools.call_tool(name, args)
                tools_used.append(name)
                last_tool_result = result
                messages.append({"role": "assistant", "content": content_acc})
                messages.append({"role": "user", "content": f"[Ergebnis von {name}: {result}]"})
                buffer = ""
                continue
            # Not recoverable — drop the garbled tail rather than speak it.
            buffer = ""

        # The model invented a tool that doesn't exist. Tell it what it
        # actually has and let it try again — reading "prise_screenshot(...)"
        # aloud helps nobody, and claiming the job is done is worse.
        if suspect and not tools_used:
            invented = _leaked_unknown_tool(content_acc)
            if invented:
                available = ", ".join(sorted(tools.DISPATCH))
                messages.append({"role": "assistant", "content": content_acc})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Die Funktion {invented} gibt es nicht. Verfügbar sind nur: "
                            f"{available}. Nutze eine davon per Function-Call, oder sage "
                            "ehrlich, dass du das nicht kannst. Behaupte niemals, etwas "
                            "erledigt zu haben."
                        ),
                    }
                )
                buffer = ""
                continue

        # Round produced no real tool call. If the whole reply was a call
        # written out as text, run it for real and let the model try again
        # with the result, instead of reading the call aloud.
        # A JSON code fence often has ordinary prose before it ("Okay, hier
        # geht es:"), so it does not look suspicious at the beginning of the
        # stream. Always attempt recovery once the full response is present.
        recovered = _recover_leaked_call(content_acc)
        if recovered:
            if _turn_cancelled(turn_id):
                yield {"type": "done", "full_text": ""}
                return
            name, args = recovered
            result = tools.call_tool(name, args)
            tools_used.append(name)
            last_tool_result = result
            messages.append({"role": "assistant", "content": content_acc})
            messages.append({"role": "user", "content": f"[Ergebnis von {name}: {result}]"})
            buffer = ""
            continue

        if suspect == "corrupt":
            # All retries came back corrupted too — silently drop it rather
            # than read garbage aloud. Falls through to the "Alles klar."
            # fallback below, or to last_tool_result if a tool did run.
            print("[llm] Streaming blieb nach 10 Versuchen korrupt, verwerfe den Rest.")
            buffer = ""
        elif suspect:
            # Suspected leaked call but not recoverable — flush it rather
            # than lose it. Nothing from this reply went through the
            # per-sentence loop above (that only runs once suspect is
            # confirmed False), so this is genuinely new, unspoken text.
            leftover_all = _vet(_strip_think_tags(content_acc))
            if leftover_all:
                full_text_parts.append(leftover_all)
                yield {"type": "sentence", "text": leftover_all}
            buffer = ""

        # Whatever never formed a "complete" sentence (no trailing
        # punctuation+space before the stream ended) didn't go through the
        # per-sentence loop either — speak it now instead of dropping it.
        leftover = _vet(_strip_think_tags(buffer))
        if leftover:
            full_text_parts.append(leftover)
            yield {"type": "sentence", "text": leftover}

        if not full_text_parts and last_tool_result:
            last_tool_result = _vet(last_tool_result)
            full_text_parts.append(last_tool_result)
            yield {"type": "sentence", "text": last_tool_result}
        elif not full_text_parts:
            yield {"type": "sentence", "text": "Alles klar."}
            full_text_parts.append("Alles klar.")

        yield {"type": "done", "full_text": " ".join(full_text_parts)}
        return

    # Real side effects (a file written, a command run) may already have
    # happened across these rounds even though no final answer came
    # together — a generic "took too long" here would erase them twice:
    # the user never hears what actually ran, and since this full_text is
    # what the frontend stores in history, the model itself would "forget"
    # its own actions next turn and could deny having done them (observed
    # live: denied writing a script it had just written via write_file).
    if tools_used:
        spoken = (
            f"Ich bin noch nicht ganz fertig, aber das ist bisher passiert: {last_tool_result}"
            if last_tool_result else
            f"Ich bin noch nicht ganz fertig ({', '.join(tools_used)} ausgeführt), frag nochmal nach dem Stand."
        )
    else:
        spoken = "Das dauert mir gerade zu lange, frag mich das nochmal."
    yield {"type": "sentence", "text": spoken}
    yield {"type": "done", "full_text": spoken}


def get_reply(user_message: str, history: list | None = None) -> str:
    resolved = confirm.resolve(user_message)
    if resolved is not None:
        return resolved

    messages = _build_messages(user_message, history)

    last_tool_result = None
    tool_ran = False
    recent_action_confirmed = _history_has_recent_action_claim(history)

    for _ in range(MAX_TOOL_ROUNDS):
        data = _post_chat(messages)
        choice = data["choices"][0]["message"]
        tool_calls = choice.get("tool_calls")

        if not tool_calls:
            content = _strip_think_tags(choice.get("content", ""))
            # Keep the legacy non-streaming endpoint as safe as the normal
            # streaming path: LM Studio may put a call in a JSON code block
            # here as well, rather than using `tool_calls`.
            recovered = _recover_leaked_call(content)
            if recovered:
                name, args = recovered
                result = tools.call_tool(name, args)
                last_tool_result = result
                tool_ran = True
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"[Ergebnis von {name}: {result}]"})
                continue
            if content:
                # A claim is only false when nothing backs it up: no tool
                # ran earlier this same turn, and no earlier turn already
                # reported doing it either (see
                # _history_has_recent_action_claim — same reasoning as the
                # streaming path in stream_reply).
                if _looks_like_tool_text(content) or (
                    not tool_ran and not recent_action_confirmed and _claims_action(content)
                ):
                    return "Das habe ich nicht ausgeführt."
                return content
            # Model sometimes returns empty text right after a tool call —
            # fall back to the tool's own result instead of reading nothing.
            return last_tool_result or "Alles klar."

        messages.append(_clean_assistant_message(choice))
        for call in tool_calls:
            fn = call["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = tools.call_tool(fn["name"], args)
            last_tool_result = result
            tool_ran = True
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                }
            )
            if confirm.is_pending():
                return result

    return "Das dauert mir gerade zu lange, frag mich das nochmal."
