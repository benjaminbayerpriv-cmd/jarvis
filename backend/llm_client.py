from __future__ import annotations

import json
import re

import requests

from . import config, memory, tools


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

# Kept deliberately short: measured against this model, a long rule-list prompt
# made it hallucinate tool results (inventing a time, claiming a note was saved)
# where a compact one keeps it actually calling the functions.
SYSTEM_PROMPT = """Du bist Jarvis, der Assistent des Nutzers auf seinem Computer. Du duzt
ihn, antwortest locker und in maximal drei Sätzen.

Du kannst seinen Computer wirklich bedienen: Programme und Webseiten öffnen, auf
den Bildschirm schauen, Shell-Befehle ausführen, Projekte programmieren und
Inhalte im Interface anzeigen.

Zum Steuern des Bildschirms nutze die passende Funktion: click_on_screen zum
direkten Anklicken, find_coordinates um nur die Position zu nennen,
look_at_display zum Beschreiben, mouse_action für bekannte Koordinaten.

Für Chrome gibt es einen Browser-Agenten: Nutze youtube_search oder web_search
für Suchen, browser_tabs für offene Tabs und open_url für konkrete Seiten. Eine
YouTube-Suche ist keine App, sondern eine Browseraktion.

Nutze dafür immer die bereitgestellten Funktionen. Erfinde niemals ein Ergebnis,
das eine Funktion liefern würde, und schreibe einen Funktionsaufruf nie als Text.

Ganz wichtig: Sage nur dann, dass etwas erledigt ist, wenn du wirklich eine
Funktion aufgerufen hast. Erfinde keine Funktionsnamen. Wenn du etwas nicht
kannst, sage das offen. Lieber ehrlich zugeben als Erfolg vortäuschen.

Deine Antwort wird vorgelesen. Bei allem, was länger als drei Sätze wäre (Code,
Listen, Erklärungen), nutze show_on_screen und sage nur einen kurzen Satz dazu.

Wenn er etwas programmiert haben will, frage zuerst, in welchen Ordner es soll."""

MAX_TOOL_ROUNDS = 4


def _post_chat(messages: list) -> dict:
    resp = requests.post(
        f"{config.LM_STUDIO_BASE_URL}/chat/completions",
        json={
            "model": config.LM_STUDIO_MODEL,
            "messages": messages,
            "tools": tools.TOOL_SCHEMAS,
            "tool_choice": "auto",
            "temperature": 0.2,
            "reasoning_effort": "none",
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("choices"):
        raise ModelError(data.get("error", {}).get("message", "LM Studio lieferte keine Antwort."))
    return data


def model_health() -> tuple[bool, str]:
    """Check that the configured single Jarvis model is loaded in LM Studio."""
    try:
        response = requests.get(f"{config.LM_STUDIO_BASE_URL}/models", timeout=5)
        response.raise_for_status()
        models = {entry.get("id") for entry in response.json().get("data", [])}
    except requests.RequestException as exc:
        return False, f"LM Studio nicht erreichbar: {exc}"
    if config.LM_STUDIO_MODEL not in models:
        return False, f"{config.LM_STUDIO_MODEL} ist in LM Studio nicht geladen."
    return True, f"Modell bereit: {config.LM_STUDIO_MODEL}"


def _clean_assistant_message(choice: dict) -> dict:
    """Strip reasoning_content before it re-enters the context window."""
    cleaned = {"role": "assistant", "content": choice.get("content", "")}
    if choice.get("tool_calls"):
        cleaned["tool_calls"] = choice["tool_calls"]
    return cleaned


def _stream_chat(messages: list):
    """Yields raw SSE JSON chunks from a streaming chat/completions call."""
    resp = requests.post(
        f"{config.LM_STUDIO_BASE_URL}/chat/completions",
        json={
            "model": config.LM_STUDIO_MODEL,
            "messages": messages,
            "tools": tools.TOOL_SCHEMAS,
            "tool_choice": "auto",
            "temperature": 0.2,
            "reasoning_effort": "none",
            "stream": True,
        },
        timeout=60,
        stream=True,
    )
    resp.raise_for_status()
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


# "Notiere: X" is unambiguous, and it is the one command this model kept
# answering conversationally ("Notiz hinzugefügt") without ever calling the
# tool — measured at roughly half the attempts, across several tool
# descriptions. A silently dropped note is worse than a missed nuance, so
# these exact imperative forms are routed straight to the tool instead of
# being put to the model. Anything less clear-cut still goes through the LLM.
_NOTE_CMD_RE = re.compile(
    r"^\s*(?:notiere|notier|merk(?:e)?\s+dir|schreib(?:e)?\s+auf|erinnere\s+mich\s+an)"
    r"\s*[:,]?\s+(?P<body>.+)$",
    re.IGNORECASE | re.DOTALL,
)

# Actions with an unambiguous grammar never need an LLM decision. Routing them
# here makes their execution deterministic: the model cannot replace a real
# side effect with a plausible success sentence.
_SCREENSHOT_CMD_RE = re.compile(
    r"\b(?:screenshot|bildschirmfoto|bildschirmaufnahme)\b", re.IGNORECASE
)
_TIME_CMD_RE = re.compile(r"\b(?:wie spät|uhrzeit|welcher wochentag|welcher tag ist heute)\b", re.IGNORECASE)
_WEATHER_CMD_RE = re.compile(r"\bwetter(?:\s+(?:gerade|heute|aktuell))?\s+(?:in|für)\s+(?P<city>[A-Za-zÄÖÜäöüß .-]+)", re.IGNORECASE)
_TYPE_CMD_RE = re.compile(
    r"^\s*(?:tippe|schreib(?:e)?)\s+(?:bitte\s+|mal\s+)?(?:den\s+)?text\s+(?P<text>.+?)\s*[.!]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_PRESS_CMD_RE = re.compile(
    r"^\s*(?:drück(?:e)?|drueck(?:e)?)\s+(?:bitte\s+|mal\s+)?(?P<key>[A-Za-z0-9+ ]+)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_CLICK_CMD_RE = re.compile(
    r"^\s*klick(?:e)?\s+(?:bitte\s+|mal\s+)?(?:auf\s+)?(?P<target>.+?)\s*[.!]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_DISPLAY_CMD_RE = re.compile(
    r"\b(?:was siehst du|was zeigt (?:mein |der )?(?:bildschirm|screen)|schau(?:e)? (?:mal )?(?:auf )?(?:meinen |den )?(?:bildschirm|screen)|guck(?:e)? (?:mal )?(?:auf )?(?:meinen |den )?(?:bildschirm|screen))\b",
    re.IGNORECASE,
)
_OPEN_CMD_RE = re.compile(
    r"^\s*(?:öffne|oeffne|mach(?:e)?\s+(?:mir\s+|mal\s+)?auf|starte)\s+(?P<target>.+?)\s*[.!]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
# "Wo ist der Button?" — return coordinates without clicking, so the user (or
# a follow-up command) can act on them.
_FIND_COORD_RE = re.compile(
    r"^\s*(?:wo\s+ist|wo\s+finde\s+ich|wo\s+liegt|finde)\s+(?:mir\s+|mal\s+)?\s*(?P<target>.+?)\s*[.!]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
# "Was ist auf dem Bildschirm klickbar?" — list interactive elements.
_LIST_ELEMENTS_RE = re.compile(
    r"^\s*(?:was\s+ist\s+(?:auf\s+dem\s+(?:bildschirm|screen)\s+)?klickbar"
    r"|liste\s+(?:mir\s+|mal\s+)?(?:alle\s+)?(?:klickbaren\s+)?elemente(?:\s+auf\s+dem\s+(?:bildschirm|screen))?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
# "Verschiebe die Datei nach Dokumente" / "in die Dokumente verschieben".
_MOVE_CMD_RE = re.compile(
    r"^\s*(?:verschiebe|verschieb|bewege|move)\s+(?P<source>.+?)\s+(?:nach|in|zu)\s+(?P<dest>.+?)\s*[.!]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_YOUTUBE_SEARCH_RE = re.compile(r"\b(?:suche|such)\s+(?:auf\s+)?youtube\s+(?:nach\s+)?(?P<query>.+)$", re.IGNORECASE)
_WEB_SEARCH_RE = re.compile(r"^\s*(?:suche|such)\s+(?:im\s+web|bei\s+google|im\s+internet)?\s*(?:nach\s+)?(?P<query>.+)$", re.IGNORECASE)
_RETRY_CMD_RE = re.compile(r"^\s*(?:mach(?:e)?(?:\s+es)?\s+richtig|versuch(?:e)?\s+(?:es\s+)?nochmal|nochmal)\s*[.!]?\s*$", re.IGNORECASE)
_WEB_ALIASES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
}


# This model intermittently writes a function call into its reply as plain
# text instead of emitting a real tool call — e.g. `show_on_screen({"title":
# ...})`. Read aloud that is gibberish, and the work never happens. When the
# whole reply is one such call to a tool we actually have, run it for real.
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
_PARTICIPLE_RE = re.compile(
    r"\b(?:geöffnet|gespeichert|erstellt|angelegt|ausgeführt|hinzugefügt|notiert|"
    r"geklickt|gestartet|getippt|gedrückt|eingerichtet|installiert|verschoben|"
    r"gelöscht|kopiert|aufgenommen|abgeschickt|gesendet)\b",
    re.IGNORECASE,
)

# Phrasings that mention an action without asserting it already happened —
# offers, questions and denials must not be mistaken for false claims.
_NOT_A_CLAIM_RE = re.compile(
    r"\b(?:möchtest du|willst du|soll ich|kann ich nicht|kann das nicht|"
    r"nicht möglich|leider nicht|konnte nicht|fehlgeschlagen|"
    r"habe ich nicht|nicht wirklich)\b",
    re.IGNORECASE,
)


def _claims_action(text: str) -> bool:
    text = text or ""
    if not _PARTICIPLE_RE.search(text):
        return False
    if _NOT_A_CLAIM_RE.search(text):
        return False
    # A bare question ("Soll das gespeichert werden?") isn't a claim either.
    stripped = text.strip()
    return not (stripped.endswith("?") and stripped.count(".") == 0)


def _looks_like_tool_text(text: str) -> bool:
    """Never show a tool call as prose, even when it is in another language."""
    names = "|".join(re.escape(name) for name in tools.DISPATCH)
    return bool(re.search(rf"\b(?:{names})\s*\(", text or "", re.IGNORECASE))


def _fast_path(user_message: str) -> str | None:
    message = user_message.strip()

    m = _NOTE_CMD_RE.match(message)
    if m:
        body = m.group("body").strip().rstrip(".")
        if body:
            return tools.call_tool("add_note", {"text": body})

    if _SCREENSHOT_CMD_RE.search(message):
        return tools.call_tool("save_screenshot", {"location": ""})

    m = _YOUTUBE_SEARCH_RE.search(message)
    if m:
        return tools.call_tool("youtube_search", {"query": m.group("query").strip().rstrip(".?!")})

    m = _WEB_SEARCH_RE.match(message)
    if m and "youtube" not in message.lower():
        return tools.call_tool("web_search", {"query": m.group("query").strip().rstrip(".?!")})

    if _TIME_CMD_RE.search(message):
        return tools.call_tool("get_time", {})

    m = _WEATHER_CMD_RE.search(message)
    if m:
        city = m.group("city").strip().rstrip(".?!")
        if city:
            return tools.call_tool("get_weather", {"city": city})

    m = _TYPE_CMD_RE.match(message)
    if m:
        return tools.call_tool("type_text", {"text": m.group("text").strip().rstrip(".")})

    m = _PRESS_CMD_RE.match(message)
    if m:
        key = re.split(r"\s+(?:zum|für|um)\b", m.group("key"), maxsplit=1, flags=re.IGNORECASE)[0]
        return tools.call_tool("press_key", {"key": key.strip().rstrip(".")})

    m = _CLICK_CMD_RE.match(message)
    if m:
        return tools.call_tool("click_on_screen", {"description": m.group("target").strip().rstrip(".")})

    if _DISPLAY_CMD_RE.search(message):
        return tools.call_tool("look_at_display", {"question": message})

    m = _FIND_COORD_RE.match(message)
    if m:
        return tools.call_tool("find_coordinates", {"description": m.group("target").strip().rstrip(".?!")})

    if _LIST_ELEMENTS_RE.match(message):
        return tools.call_tool("get_screen_elements", {})

    m = _MOVE_CMD_RE.match(message)
    if m:
        source = m.group("source").strip().rstrip(".?!")
        dest = m.group("dest").strip().rstrip(".?!")
        dest = dest.lower().removeprefix("die ").removeprefix("den ").removeprefix("das ")
        # Resolve the German names of the standard home folders.
        if dest in ("dokumente", "documents", "papiere"):
            dest = "~/Documents"
        elif dest in ("desktop", "schreibtisch"):
            dest = "~/Desktop"
        elif dest == "downloads":
            dest = "~/Downloads"
        return tools.call_tool("move_file", {"source": source, "destination": dest})

    m = _OPEN_CMD_RE.match(message)
    if m:
        target = m.group("target").strip().rstrip(".")
        lowered = target.lower().removeprefix("die ").removeprefix("den ").removeprefix("das ")
        if lowered in _WEB_ALIASES:
            return tools.call_tool("open_url", {"url": _WEB_ALIASES[lowered]})
        if re.fullmatch(r"(?:https?://)?(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?:/\S*)?", target):
            return tools.call_tool("open_url", {"url": target})
        # A direct "öffne Spotify" is equally unambiguous. If the app does
        # not exist, open_app returns an honest error instead of a claim.
        return tools.call_tool("open_app", {"name": target})

    return None


def _retry_fast_path(user_message: str, history: list | None) -> str | None:
    """Repeat the last clear command for messages such as "mach es richtig"."""
    if not _RETRY_CMD_RE.match(user_message or "") or not history:
        return None
    for item in reversed(history):
        if item.get("role") != "user" or not isinstance(item.get("content"), str):
            continue
        result = _fast_path(item["content"])
        if result:
            return result
    return None


def stream_reply(user_message: str, history: list | None = None):
    """Generator yielding {"type": "sentence", "text": ...} as soon as each
    sentence of the reply is complete, then a final {"type": "done"}.

    Tool-call rounds don't stream user-facing text (the model calls the tool
    silently), so sentences only start flowing once a round produces plain
    content — either the first round if no tool is needed, or the follow-up
    round after tool results are fed back in.
    """
    shortcut = _fast_path(user_message) or _retry_fast_path(user_message, history)
    if shortcut:
        yield {"type": "sentence", "text": shortcut}
        yield {"type": "done", "full_text": shortcut}
        return

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    remembered = memory.context_for(user_message)
    if remembered:
        messages.append({"role": "system", "content": f"Relevantes lokales Gedächtnis:\n{remembered}"})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    last_tool_result = None
    full_text_parts = []
    # Every tool that actually ran this turn. Used to catch replies that
    # claim an action was performed when nothing was.
    tools_used: list[str] = []

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
            # show_on_screen({...})") — that's invisible to the check above
            # since it only looks at the very start. So every completed
            # sentence is independently vetted too; the moment one of them
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
                                    # Hold prose until the full turn is
                                    # verified; never speak a fake success.
                                    full_text_parts.append(clean)

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
                try:
                    args = json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = tools.call_tool(c["name"], args)
                tools_used.append(c["name"])
                last_tool_result = result
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
            continue

        # A call leaked after some genuine lead-in prose (already spoken/
        # yielded above) rather than from the very start. Run it for real —
        # can't unspeak the lead-in, but the action itself still needs to
        # actually happen, which is the part that matters most.
        if trailing_suspect and trailing_suspect != "corrupt":
            recovered_trailing = _recover_leaked_call(trailing_suspect_text)
            if recovered_trailing:
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
            # than lose it.
            leftover_all = _strip_think_tags(content_acc)
            if leftover_all:
                full_text_parts.append(leftover_all)
            buffer = ""

        leftover = _strip_think_tags(buffer)
        if leftover:
            full_text_parts.append(leftover)

        if not full_text_parts and last_tool_result:
            full_text_parts.append(last_tool_result)
        elif not full_text_parts:
            yield {"type": "sentence", "text": "Alles klar."}
            full_text_parts.append("Alles klar.")

        # A tool-free success claim is never shown. The text stayed buffered,
        # so the user hears only the truthful state.
        spoken = " ".join(full_text_parts)
        if not tools_used and (_claims_action(spoken) or _looks_like_tool_text(spoken)):
            spoken = "Das habe ich nicht ausgeführt."

        yield {"type": "sentence", "text": spoken}
        yield {"type": "done", "full_text": spoken}
        return

    yield {"type": "sentence", "text": "Das dauert mir gerade zu lange, frag mich das nochmal."}
    yield {"type": "done", "full_text": "Das dauert mir gerade zu lange, frag mich das nochmal."}


def get_reply(user_message: str, history: list | None = None) -> str:
    shortcut = _fast_path(user_message) or _retry_fast_path(user_message, history)
    if shortcut:
        return shortcut

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    remembered = memory.context_for(user_message)
    if remembered:
        messages.append({"role": "system", "content": f"Relevantes lokales Gedächtnis:\n{remembered}"})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    last_tool_result = None

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
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"[Ergebnis von {name}: {result}]"})
                continue
            if content:
                if _claims_action(content) or _looks_like_tool_text(content):
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
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                }
            )

    return "Das dauert mir gerade zu lange, frag mich das nochmal."
