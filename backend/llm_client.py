from __future__ import annotations

import json
import platform
import re
import subprocess
import threading
import time
from typing import Callable

import requests

from . import confirm, config, hardware, last_target, mcp_server, memory, tools


class ModelError(RuntimeError):
    """A local-model failure that must become a user-facing response."""


class ModelTooLargeError(ModelError):
    """The configured model doesn't fit into this PC's memory; the message
    is meant to be shown/spoken to the user as-is."""


class LmStudioError(ModelError):
    """LM Studio refused or aborted a native chat request (too old, per-request
    MCPs switched off, tool server unreachable, …); the message says why and
    is meant to be shown/spoken to the user as-is."""

# Some local reasoning models (observed with VibeThinker-3B) put their
# entire chain-of-thought inline as ordinary `content` wrapped in
# <think>...</think>, instead of a separate reasoning_content field the way
# e.g. DeepSeek-R1-style APIs do. The previous version of this only deleted
# the bare tag markers and left the reasoning prose itself fully visible —
# it showed up verbatim as sidebar chat titles ("<think>The user gave a
# meta-instruction...") and inside summarized history. This removes the
# whole block, content included, for any call site that has the complete
# text in hand at once (non-streaming replies, titles, summaries).
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
# A block that never closed (model ran out of tokens mid-thought, or got
# cut off) — drop everything from the opening tag onward rather than show a
# half-finished reasoning trace.
_THINK_UNCLOSED_RE = re.compile(r"<think>.*", re.IGNORECASE | re.DOTALL)


def _strip_think_tags(text: str) -> str:
    text = _THINK_BLOCK_RE.sub("", text)
    text = _THINK_UNCLOSED_RE.sub("", text)
    return text.strip()


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _new_think_filter_state() -> dict:
    return {"in_think": False, "carry": ""}


def _filter_think(state: dict, text: str) -> str:
    """Stateful counterpart to _strip_think_tags for the streaming path,
    where a <think>...</think> block (and even its individual tags) can
    arrive split across several chunks, and sentence-popping downstream
    would otherwise treat un-tagged reasoning prose (the tag itself already
    consumed by an earlier chunk) as ordinary output. Feed each new chunk
    of raw model text through this and only ever pass its return value
    further into the pipeline (buffer/content_acc) — never the raw chunk.
    `state` is one _new_think_filter_state() dict per streaming turn/retry.
    """
    state["carry"] += text
    out_parts = []
    while True:
        marker = _THINK_CLOSE if state["in_think"] else _THINK_OPEN
        idx = state["carry"].lower().find(marker)
        if idx == -1:
            break
        if not state["in_think"]:
            out_parts.append(state["carry"][:idx])
        state["carry"] = state["carry"][idx + len(marker):]
        state["in_think"] = not state["in_think"]
    hold_back = len(_THINK_CLOSE) - 1  # enough to catch a tag split across chunks
    if state["in_think"]:
        # Reasoning text is never shown; just cap unbounded growth if the
        # model never closes the block at all.
        if len(state["carry"]) > 8000:
            state["carry"] = state["carry"][-hold_back:]
    elif len(state["carry"]) > hold_back:
        out_parts.append(state["carry"][:-hold_back])
        state["carry"] = state["carry"][-hold_back:]
    return "".join(out_parts)


# Abbreviations whose trailing dot does not end a sentence. Single letters
# ("z.B.", "u.a.") are handled separately.
_ABBREV = {
    "bzw", "ca", "usw", "etc", "evtl", "ggf", "inkl", "exkl", "max", "min",
    "nr", "dr", "prof", "st", "bspw", "sog", "vgl", "ggfs", "mio", "mrd",
}

_WORD_BEFORE_DOT_RE = re.compile(r"([A-Za-zÄÖÜäöüß]+)$")

# A bare digit followed by ". <Monatsname>" is a German date's day-of-month
# ordinal ("der 8. September", "den 08. September 2026"), never a sentence
# end — unlike a plain digit before ANY dot (see _pop_complete_sentences),
# which can't be treated as always-non-terminal without also swallowing
# genuinely sentence-final numbers ("Das Jahr ist 2026." must still split).
# Restricting to a month name right after keeps this to the one case that
# actually needs it.
_MONTH_AFTER_DOT_RE = re.compile(
    r"^\s+(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\b"
)


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
            # Same idea, for the date-ordinal case specifically (see
            # _MONTH_AFTER_DOT_RE) — without this, a streamed date got
            # mis-split mid-date ("... den 08." / "September 2026." as two
            # separate TTS calls), which also broke tts.py's date-to-words
            # expansion (it needs the day and month name in the same
            # chunk) and read the day as a cardinal instead of an ordinal.
            if prev.isdigit() and _MONTH_AFTER_DOT_RE.match(buffer[j:]):
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
# secretly coming from the local model. Updated in _open_round right after
# a request actually succeeds.
_active_model_name = config.DEEPSEEK_MODEL if (config.DEEPSEEK_API_KEY and config.DEEPSEEK_ENABLED) else config.LM_STUDIO_MODEL
_active_model_provider = "DeepSeek" if (config.DEEPSEEK_API_KEY and config.DEEPSEEK_ENABLED) else "ein lokales Modell über LM Studio"


def _note_active_target(base_url: str, model: str) -> None:
    global _active_model_name, _active_model_provider
    _active_model_name = model
    _active_model_provider = "DeepSeek" if base_url == config.DEEPSEEK_BASE_URL else "ein lokales Modell über LM Studio"


# (connect, read). The read timeout covers the silence while LM Studio
# prefills the prompt before the first token — with the full system prompt
# plus every tool schema (~6k tokens) that took 94 s cold on a model larger
# than VRAM. A 60 s limit aborted it, LM Studio threw the half-built prompt
# cache away with the dropped connection, and every retry started cold
# again: Jarvis could never answer until something else warmed the cache.
_CHAT_TIMEOUT = (10, 300)


# (Modell, System-Prompt) -> response_id einer gespeicherten "Basis"-Antwort:
# ein Chat, in dem der System-Prompt samt Werkzeug-Definitionen schon
# verarbeitet ist. Jeder NEUE Chat startet als Fork davon (siehe
# _native_round), statt den ganzen System-Prompt (~3000 Token) neu zu
# verarbeiten — live gemessen: 20-38 s bei kaltem Cache gegen unter 1 s im
# Fork, auch wenn der Prefix-Cache zwischendurch (z.B. durch die
# Titel-Generierung) verdrängt wurde. Nur im Speicher: nach einem Neustart
# legt warm_system_prompt sie neu an; ist eine Basis bei LM Studio nicht mehr
# auffindbar, fällt _native_round auf den normalen Weg zurück.
_fork_bases: dict[tuple[str, str], str] = {}
_FORK_BASES_MAX = 6


def _fork_base_lookup(model: str, system_prompt: str) -> str | None:
    return _fork_bases.get((model, system_prompt))


def _fork_base_store(model: str, system_prompt: str, response_id: str) -> None:
    if len(_fork_bases) >= _FORK_BASES_MAX:
        _fork_bases.clear()
    _fork_bases[(model, system_prompt)] = response_id


def _fork_base_forget(model: str, system_prompt: str) -> None:
    _fork_bases.pop((model, system_prompt), None)


def warm_system_prompt(model: str, on_load_progress: Callable[[float], None] | None = None) -> bool:
    """Throwaway native chat request carrying the real system prompt and the
    real tool integration, so LM Studio loads the model (just-in-time, if it
    isn't yet) and processes those tokens ahead of time. Returns whether that
    worked.

    Observed live: with a big model (Qwen3.6 35B A3B), the FIRST real message
    after a (re)load took noticeably longer than every one after it — because
    that first request pays for prefilling the whole system prompt (a few
    thousand tokens) from scratch, while later ones reuse the server's
    prompt-prefix cache from the previous turn. Sending that same prefix here
    ahead of time moves that one-time cost off the user's first real message.
    Goes through the same /api/v1/chat + MCP path as a real turn: the tool
    definitions LM Studio renders from the MCP server belong to the cached
    prefix too.

    Where no stored base exists yet for a system-prompt variant (text and
    speech mode differ), this request is also kept (store=True) and its
    response_id registered as that variant's fork base — see _fork_bases.
    `on_load_progress` gets LM Studio's model-load progress (0..1) while the
    model is being loaded. Never raises — this must never block startup or a
    model switch.
    """
    try:
        for speech in (False, True):
            system_prompt = _system_prompt(speech)
            is_new_base = _fork_base_lookup(model, system_prompt) is None
            body = {
                **_native_body(model, system_prompt, "hi", mcp_server.warm_integration(), store=is_new_base),
                # A few tokens for a new base so the stored exchange is a
                # complete one; one is enough for a pure cache refresh.
                "max_output_tokens": 16 if is_new_base else 1,
            }
            for data in _native_events(body):
                kind = data.get("type")
                if kind == "model_load.progress" and on_load_progress:
                    on_load_progress(data.get("progress", 0.0))
                elif kind == "error":
                    raise _native_error(data.get("error") or {})
                elif kind == "chat.end" and is_new_base:
                    rid = (data.get("result") or {}).get("response_id")
                    if rid:
                        _fork_base_store(model, system_prompt, rid)
        return True
    except (requests.RequestException, ModelError, RuntimeError) as exc:
        print(f"[model] Vorwärmen des System-Prompts für {model} fehlgeschlagen: {exc}")
        return False


# model -> system prompt of the most recent real native round, so a cache
# refresh can target the prompt actually in use (text and speech differ).
_last_chat_system: dict[str, str] = {}


def refresh_prompt_cache(model: str) -> None:
    """Re-prime LM Studio's prompt-prefix cache for the system prompt the last
    real chat used — after a side call (title, summary) with its own short
    system prompt pushed it out, so the NEXT message of that chat doesn't pay
    the full prefill again. Only that one prompt, not every variant (each
    costs a cold prefill and LM Studio handles one request at a time).
    Fork-started chats don't need it for their first turn (their base
    survives eviction); this is for the turns after. Never raises."""
    system_prompt = _last_chat_system.get(model)
    if not system_prompt:
        return
    try:
        body = {**_native_body(model, system_prompt, "hi", mcp_server.warm_integration(), store=False), "max_output_tokens": 1}
        for data in _native_events(body):
            if data.get("type") == "error":
                raise _native_error(data.get("error") or {})
    except (requests.RequestException, ModelError, RuntimeError) as exc:
        print(f"[model] Cache-Auffrischung für {model} fehlgeschlagen: {exc}")


def _platform_note() -> str:
    # Without this the model assumed macOS/Linux (the prompt used to mention
    # only Finder/killall): benchmarked on Windows it ran `free -h` and
    # `sysctl` via run_shell and gave Mac-only instructions.
    system = platform.system()
    if system == "Windows":
        return ("Der Computer läuft unter Windows. run_shell nutzt cmd.exe — verwende Windows-"
                "Befehle (z.B. powershell -Command \"...\", tasklist, systeminfo), niemals "
                "Linux/macOS-Befehle wie free, top, sysctl, killall, pmset. Tastenkürzel und "
                "Anleitungen gibst du für Windows an.")
    if system == "Darwin":
        return "Der Computer läuft unter macOS. Verwende macOS-Befehle und -Tastenkürzel."
    return "Der Computer läuft unter Linux. Verwende Linux-Befehle."


# Kept deliberately short: measured against this model, a long rule-list prompt
# made it hallucinate tool results (inventing a time, claiming a note was saved)
# where a compact one keeps it actually calling the functions. A function, not
# a plain string, so the model self-identification above stays current.
def _system_prompt(is_speech: bool = False) -> str:
    intro_style = (
        "Du duzt ihn, antwortest locker und in maximal drei Sätzen."
        if is_speech else
        "Du duzt ihn und antwortest locker — im Textchat darf eine Antwort so lang sein, "
        "wie die Frage es braucht, auch mit Code-Blöcken, Listen oder mehreren Absätzen, "
        "wenn das dem Nutzer wirklich hilft. Kurz wo eine kurze Antwort reicht, ausführlich "
        "wo Details gefragt sind — nicht künstlich aufblähen, aber auch nicht künstlich kürzen."
    )
    output_note = (
        "Deine Antwort wird ausschließlich vorgelesen — es gibt keine Anzeige für Text,\n"
        "Code oder Listen. Fasse dich deshalb kurz und sprich in ganzen Sätzen statt\n"
        "Code, Tabellen oder lange Aufzählungen vorzulesen; beschreibe stattdessen knapp,\n"
        "was du getan hast oder was das Ergebnis ist."
        if is_speech else
        "Deine Antwort wird als Text angezeigt (Markdown wird gerendert) — Code-Blöcke,\n"
        "Listen und Tabellen sind hier sinnvoll und werden ordentlich dargestellt, nutze sie,\n"
        "wo sie die Antwort klarer machen."
    )
    return f"""Du bist Jarvis, der Assistent des Nutzers auf seinem Computer. {intro_style}

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

{_platform_note()}

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
eine Angabe fehlt, ohne die gar nichts passieren kann.

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
jemand, der 1990 geboren ist") rufe IMMER zuerst get_time auf und nutze
exakt dessen Ergebnis — das ist der einzige echte Zeitpunkt, den du
kennst. Nenne niemals ein Datum oder eine Uhrzeit aus eigenem Training
(dessen Stichtag in der Vergangenheit liegt) oder aus einer früheren
Erwähnung weiter oben im Gespräch, selbst wenn seither einige Nachrichten
vergangen sind — ruf get_time bei jeder neuen Frage danach frisch erneut
auf, statt dich auf eine ältere Erwähnung im Verlauf zu verlassen.

Bei JEDER Rechnung, egal wie einfach — Addition, Subtraktion, Multiplikation,
vor allem Division ("acht geteilt durch zwei", "was ist 17 mal 23") — rufst
du IMMER calculate auf, statt das Ergebnis selbst im Kopf auszurechnen. Du
rechnest sonst zuverlässig falsch, besonders bei Division. Wandle dabei
Zahlwörter in Ziffern um und gib calculate einen reinen Rechenausdruck wie
"8/2".

Ein run_shell-Befehl ohne Ausgabe ist KEIN Beweis für Erfolg — Befehle wie
taskkill oder killall geben bei Erfolg und bei Misserfolg oft gar nichts aus. Behaupte
nach run_shell niemals zuversichtlich Erfolg, wenn die Ausgabe das nicht
wirklich belegt — prüfe im Zweifel mit einem zweiten Befehl nach oder sag
ehrlich, dass du es nicht sicher weißt.

Für einen Ordner (z.B. "Ordner Projekte auf dem Desktop") open_folder zum
Öffnen im Explorer/Finder, list_folder um zu sagen was drin liegt — niemals open_app
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

Wünscht der Nutzer ein Diagramm, eine Grafik, einen Verlauf oder etwas auf dem Raster, rufst du IMMER visualize auf — sag nie "hier ist es", ohne die Funktion aufgerufen zu haben.

Soll am Code gearbeitet werden — programmieren, ändern, refactoren, einen Bug
fixen, Tests schreiben, eine Datei im Projekt umbauen — rufst du IMMER opencode
auf und gibst den Auftrag als klaren, vollständigen Satz weiter. OpenCode ist
der Coding-Agent, der das wirklich umsetzt; du schreibst den Code NICHT selbst
und zeigst ihn auch nicht als Text. Der Nutzer spricht dabei weiter mit dir,
nicht mit OpenCode: Du nimmst seinen Wunsch entgegen und tippst ihn dort ein.
Formuliere den Auftrag dabei ruhig aus, statt nur "mach das" weiterzureichen —
OpenCode kennt euer Gespräch nicht. Danach sagst du in einem kurzen Satz, was
du weitergegeben hast.

Will der Nutzer das Modell des Coding-Agenten wechseln ("nimm das Devstral",
"wechsel bei OpenCode auf das große Modell", "benutz Sonnet", "nimm Opus",
"switch das Modell zu X"), rufst du SOFORT opencode_model mit genau dem vom
Nutzer genannten Namen auf — auch wenn dir der Name selbst nichts sagt oder
exotisch/erfunden klingt ("Big Pickle" zum Beispiel ist ein echtes,
existierendes OpenCode-Modell). Du kennst OpenCodes Modell-Katalog NICHT
auswendig, also darfst du niemals von dir aus behaupten, ein Modellname sei
"unbekannt" oder frag nie von dir aus nach, welches Modell gemeint ist, bevor
du opencode_model überhaupt aufgerufen hast — nur das Tool weiß, ob der Name
existiert, und liefert bei einem echten Nichttreffer selbst schon die Liste
der verfügbaren Modelle sowie eine passende Rückfrage zurück, die du dann
unverändert weitergibst. Behaupte den Wechsel aber auch nie einfach, ohne
die Funktion aufgerufen zu haben. Gemeint ist damit NICHT dein eigenes
Chat-Modell. Das gilt für ALLE drei Coding-Agenten, nicht nur OpenCode:
opencode_model wechselt immer das Modell des gerade AKTIVEN Agenten (siehe
set_code_agent).

Will der Nutzer stattdessen WELCHEN Coding-Agenten benutzen ("nimm Claude
Code zum Programmieren", "wechsel auf Codex", "benutz wieder OpenCode"),
rufst du IMMER set_code_agent auf — das ist etwas anderes als opencode_model
(hier wechselt der ganze Agent, dort nur dessen Modell).

set_code_agent kennt GENAU drei gültige Namen: OpenCode, Claude Code, Codex —
sonst nichts. Jeder andere Name in einem "nimm/wechsel/switch"-Satz ist ein
MODELLNAME, kein Agent, und gehört zu opencode_model — auch wenn er wie ein
Eigenname oder ein zweites Wort wie "Coder"/"Code" klingt (z.B. "Qwen Coder",
"Muse Spark", "Space Bunny" sind allesamt Modelle aus OpenCodes Katalog,
keine Agenten). Ruf set_code_agent NIEMALS mit einem Namen auf, der nicht
wortwörtlich einer der drei obigen ist — im Zweifel ist es opencode_model.

Programmiert wird AUSNAHMSLOS über opencode — jede Größe, jede Aufgabe, auch
wenn der Nutzer einen eigenen Zielordner nennt oder eine komplett neue App
will. Du schreibst nie selbst Code, weder als Text in der Antwort noch über
write_file. Nennt der Nutzer dabei KEINEN Ordner, ist das kein Hindernis —
opencode arbeitet im aktuellen Projektordner und braucht keinen Ort; frag
also nicht nach einem Speicherort, sondern gib den Auftrag sofort weiter.
Beantwortet der Nutzer gerade eine Rückfrage von dir ("Hallo Welt", nachdem
du gefragt hast, was das Programm tun soll), setzt du seine Antwort mit
deiner Frage zusammen und handelst sofort — frag nicht dasselbe noch einmal
anders. Geöffnet wird dagegen nie vom Coding-Agenten: eine Datei öffnest du
mit open_file, auch eine, die er gerade erstellt hat.

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

{output_note}
Harte Regel, keine Ausnahme: Verwende NIEMALS Emojis oder Emoji-Symbole (🚀⭐❌
⚠❤ etc.) — weder im Fließtext noch in Code-Ausgaben. Auch nicht wenn der Nutzer
danach fragt oder es "freundlicher" machen soll. Emojis werden ohnehin entfernt,
also lass sie ganz weg.

Ganz wichtig für Programmier-Aufträge ("code eine Website", "bau eine Demo"):
Die rufst du SOFORT mit opencode auf — ohne Rückfrage, auch ohne genannten
Ordner. opencode arbeitet im Hintergrund: sag knapp "ich gebe es weiter", die
Fortschritte erscheinen automatisch im Interface, du musst sie nicht erfinden.
Behaupte niemals "wird gerade gebaut" oder "ist fertig", bevor du die echte
Rückmeldung hast, und widersprich dir nie: Was du einmal gesagt hast (z.B.
"fertig"), bleibt gesagt und gilt weiter."""

MAX_TOOL_ROUNDS = 4
# LM Studio runs the tool loop itself on the native path, so rounds alone
# don't bound it there (see _stream_reply_impl).
MAX_NATIVE_TOOL_CALLS = 8


# Chat|Code-Modus: bei mode=="code" wird dieser Zusatz in den System-Prompt
# gemischt. Er lenkt die Antwort in Richtung konkreter, technischer Hilfe mit
# Code statt in lockere Umgangssprache — der Frontend-Umschalter reicht einen
# mode-Wert mit, das Backend entscheidet hier über den Ton.
_CODE_MODE_PROMPT = """Der Nutzer hat den Code-Modus gewählt. Antworte deshalb jetzt
technischer und konkreter: wo es passt, gib echten Code (in Code-Blöcken),
zeige Differenzen oder genaue Schritte und bleibe knapp. Soll etwas
programmiert werden, gib den Auftrag wie immer sofort per opencode weiter —
ohne nach einem Zielordner zu fragen.

Redet der Nutzer hier im Code-Modus von "das Modell wechseln"/"switch das
Modell" o.ä., OHNE dabei ausdrücklich dein eigenes Chat-/Sprachmodell zu
meinen, ist damit IMMER das Modell des gerade aktiven Coding-Agenten gemeint
(OpenCode, Claude Code oder Codex) — ruf sofort opencode_model auf, ganz
gleich ob der Nutzer den Agenten beim Namen nennt oder nicht. Frag nicht erst
nach, ob er den Coding-Agenten oder dein eigenes Modell meint; im Code-Modus
ist das keine echte Mehrdeutigkeit."""


def _user_content(user_message: str, images: list[str] | None):
    """Plain string for a text-only turn, or an OpenAI vision-style content
    array (text + one or more image_url parts) when images are attached —
    LM Studio's OpenAI-compatible endpoint accepts this shape for any
    "vlm"-typed model (see list_model_capabilities). Each image is a data
    URL ("data:image/jpeg;base64,...") straight from the frontend's
    FileReader — nothing server-side re-encodes or validates it beyond
    LM Studio's own request handling."""
    if not images:
        return user_message
    for img in images:
        header = img[:32] if isinstance(img, str) else "<non-string>"
        size = len(img) if isinstance(img, str) else 0
        print(f"[vision] Bild angehängt: {size} Zeichen, Header: {header!r}")
    content = [{"type": "text", "text": user_message}]
    content.extend({"type": "image_url", "image_url": {"url": img}} for img in images)
    return content


def _build_messages(user_message: str, history: list | None, mode: str | None = None, images: list[str] | None = None, is_speech: bool = False) -> list:
    # Qwen3.5's chat template rejects the request outright ("System message
    # must be at the beginning") the moment more than one system-role entry
    # shows up anywhere in the list — which used to happen constantly here:
    # the base prompt, memory context and target hint were each their own
    # system message, and trimHistory() (frontend/app.js) inserts another
    # one for the summarized conversation tail once history gets long. All
    # of that is folded into exactly one leading system message instead;
    # any system-role entry surviving in `history` (the summary) is merged
    # in here rather than passed through as its own message.
    system_parts = [_system_prompt(is_speech)]
    if mode == "code":
        system_parts.append(_CODE_MODE_PROMPT)
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
    messages.append({"role": "user", "content": _user_content(user_message, images)})
    return messages


def _request_targets() -> list[tuple[str, str, dict, dict]]:
    """Ordered text-LLM endpoints to try, most preferred first.

    Returns a list of (base_url, model, headers, extra_body). Which one goes
    first is controlled by config.ACTIVE_PROVIDER: "auto" (default, legacy
    behaviour) always prefers DeepSeek when a key is configured, "deepseek"/
    "lmstudio" pin it explicitly — set via the frontend's model picker (see
    main.py select_model) picking the synthetic "deepseek:..." entry or a
    real LM Studio one. Without this pin, picking an LM Studio model in the
    picker had no effect at all whenever a DeepSeek key existed: DeepSeek
    kept answering regardless, which is what "Modellauswahl funktioniert mit
    Deepseek nicht" turned out to mean. Either way, a failed DeepSeek request
    (expired/invalid key, quota, network) still falls through to the other
    target instead of giving up — a working model beats a canned "can't
    reach my model" apology. DeepSeek's API is OpenAI-compatible but needs an
    Authorization header and does not accept the `reasoning_effort` field
    that LM Studio expects.
    """
    deepseek_target = None
    if config.DEEPSEEK_API_KEY and config.DEEPSEEK_ENABLED:
        headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"}
        deepseek_target = (config.DEEPSEEK_BASE_URL, config.DEEPSEEK_MODEL, headers, {})

    # LM Studio loads a model just-in-time on the first request for it — so
    # a model too big for this PC must never be requested at all, or that
    # request is what triggers the crash.
    too_large = hardware.blocked_reason(config.LM_STUDIO_MODEL)
    if too_large:
        # A block set once (typically at startup, before LM Studio had even
        # finished reporting its own state) must never stick around forever
        # — re-verify right now instead of trusting a stale verdict. Live
        # observed: the model was already loaded seconds later (LM Studio's
        # /api/v0/models just hadn't answered yet at boot), but every
        # request kept getting the boot-time "not enough memory" message
        # since nothing ever re-checked or cleared it.
        fit = hardware.check_model(config.LM_STUDIO_MODEL)
        if fit["fits"]:
            hardware.unblock_all()
            too_large = None
        else:
            too_large = fit.get("message", too_large)
    lmstudio_target = None
    if not too_large:
        lmstudio_target = (config.LM_STUDIO_BASE_URL, config.LM_STUDIO_MODEL, config.lm_studio_headers(), {"reasoning_effort": "none"})

    if config.ACTIVE_PROVIDER == "lmstudio":
        ordered = [lmstudio_target, deepseek_target]
    else:
        # "deepseek" (explicit) and "auto" (legacy default) both prefer
        # DeepSeek first when it's available.
        ordered = [deepseek_target, lmstudio_target]
    targets = [t for t in ordered if t is not None]
    if not targets:
        raise ModelTooLargeError(too_large or "Kein Modell verfügbar.")
    return targets


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
            return _strip_think_tags(data["choices"][0]["message"].get("content", ""))
        except (requests.RequestException, ModelError) as exc:
            print(f"[model] {base_url} nicht verfügbar, versuche nächstes Ziel: {exc}")
            last_exc = exc
    raise last_exc


_TITLE_PROMPT = (
    "Gib dem folgenden Gesprächsanfang zwischen dem Nutzer und dir (Jarvis) "
    "einen kurzen Titel auf Deutsch: maximal 4 Wörter, keine Anführungszeichen, "
    "kein Punkt am Ende, keine Emojis. Antworte NUR mit dem Titel, sonst nichts."
)


def generate_title(user_text: str, assistant_text: str) -> str:
    """A short sidebar label for a new conversation (Claude-style, e.g.
    "Claude Skill Installation Setup") — generated once, right after the
    first exchange, from just that first turn. Returns "" on failure so the
    caller can fall back to a generic label instead of blocking on it."""
    transcript = f"Nutzer: {user_text}\nJarvis: {assistant_text}"
    messages = [
        {"role": "system", "content": _TITLE_PROMPT},
        {"role": "user", "content": transcript},
    ]
    for base_url, model, headers, extra in _request_targets():
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                json={"model": model, "messages": messages, "temperature": 0.2, **extra},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("choices"):
                continue
            title = _strip_think_tags(data["choices"][0]["message"].get("content", ""))
            return title.strip("\"'").strip()[:60]
        except (requests.RequestException, ModelError) as exc:
            print(f"[model] {base_url} nicht verfügbar, versuche nächstes Ziel: {exc}")
    return ""


# Prefix marking a synthetic model-picker entry as "DeepSeek", not an LM
# Studio model id — LM Studio ids never contain a colon, so this can't
# collide with a real one. See list_models()/select_model() in main.py.
DEEPSEEK_MODEL_ID_PREFIX = "deepseek:"


def is_deepseek_model_id(model_id: str) -> bool:
    return str(model_id or "").startswith(DEEPSEEK_MODEL_ID_PREFIX)


def is_embedding_model_id(model_id: str) -> bool:
    return "embed" in str(model_id or "").lower()


def list_models() -> list[str]:
    """Every model LM Studio currently reports via its OpenAI-compatible
    /models endpoint, plus a synthetic "deepseek:<model>" entry when a
    DeepSeek key is configured — used by the frontend's model-picker
    dropdown. Without this, DeepSeek never showed up there at all, and
    picking an LM Studio model had no effect anyway (see
    _request_targets(): a configured DeepSeek key always won, regardless of
    what was picked) — the picker looked broken specifically for DeepSeek."""
    try:
        response = requests.get(f"{config.LM_STUDIO_BASE_URL}/models", headers=config.lm_studio_headers(), timeout=5)
        response.raise_for_status()
        # Embedding models can't chat — picking one in the model menu used
        # to break every following message.
        models = sorted(
            entry.get("id") for entry in response.json().get("data", [])
            if entry.get("id") and not is_embedding_model_id(entry["id"])
        )
    except requests.RequestException:
        # LM Studio unreachable must not hide DeepSeek from the picker too —
        # DeepSeek can be perfectly healthy while LM Studio is down.
        models = []
    if config.DEEPSEEK_API_KEY and config.DEEPSEEK_ENABLED:
        models.insert(0, f"{DEEPSEEK_MODEL_ID_PREFIX}{config.DEEPSEEK_MODEL}")
    return models


# Substring fingerprint for vision-capable models. LM Studio doesn't guarantee
# a `vision`/`capabilities` field in its /models metadata, so this is the
# reliable fallback: match a model id / architecture string against the common
# naming conventions. `(?<![a-z])vl(?![a-z])` catches a bare "vl" token (e.g.
# "qwen2-vl") without matching random "vl" substrings inside other words.
_VISION_RE = re.compile(
    r"vision|visual|multimodal|llava|internvl|pixtral|moondream|molmo|"
    r"qwen[0-9.-]*-vl|qwen[^ ]*vision|deepseek[-_]vl|phi[-_]?vision|"
    r"gemini|claude|gpt-?4[ot]?-?vision|minicpm[-_]?v|bakllava|(?<![a-z])vl(?![a-z])",
    re.IGNORECASE,
)


def _native_model_meta() -> dict[str, dict]:
    """Best-effort per-model metadata from LM Studio's *native* /api/v0/models
    endpoint, which exposes richer fields (architecture, path, quant) than the
    OpenAI-compatible /v1/models one. The root is the base URL with any trailing
    /v1 stripped; a failure just falls back to the id heuristic."""
    base = config.LM_STUDIO_BASE_URL
    root = base[: base.rfind("/v1")].rstrip("/") if base.endswith("/v1") else base.rstrip("/")
    try:
        response = requests.get(f"{root}/api/v0/models", headers=config.lm_studio_headers(), timeout=4)
        response.raise_for_status()
        return {
            entry.get("id"): entry
            for entry in response.json().get("data", []) if entry.get("id")
        }
    except requests.RequestException:
        return {}


def _detect_capabilities(model_id: str, meta: dict) -> list[str]:
    """Given a model id and whatever metadata happened to come back, return
    the capability tags (e.g. ["vision"]). Evidence is preferred in order:
    explicit `vision`/`capabilities` fields, then the architecture string,
    then a substring match over the id + architecture."""
    hay = [model_id or ""]
    for key in ("owned_by", "architecture", "arch", "model_type"):
        if isinstance(meta.get(key), str):
            hay.append(meta[key])
    cfg = meta.get("config")
    if isinstance(cfg, dict):
        for key in ("arch", "model_type"):
            if isinstance(cfg.get(key), str):
                hay.append(cfg[key])

    caps: list[str] = []
    # LM Studio's native /api/v0/models marks every vision-capable model
    # with `"type": "vlm"` — by far the most reliable signal available
    # (it's LM Studio's own classification, not a guess from the id/arch
    # string), but wasn't being read at all: only "owned_by", "architecture",
    # "arch", "model_type" were ever added to `hay` above, never "type".
    # Observed live: google/gemma-4-e4b, qwen3.5-9b, qwen3.8-27b and
    # devstral-small-2-24b-instruct-2512 are all real "vlm" models that
    # this endpoint reported as having zero capabilities. Note: this
    # endpoint's "capabilities" list only ever contains things like
    # "tool_use" in this LM Studio version — it never lists "vision" even
    # for models that demonstrably do vision inference correctly (confirmed
    # live: gemma-4-e4b correctly described a synthetic test image) — so
    # "type":"vlm" is the only usable vision signal here, not "capabilities".
    if meta.get("type") == "vlm":
        caps.append("vision")
    if isinstance(meta.get("vision"), bool) and meta["vision"]:
        caps.append("vision")
    if isinstance(meta.get("capabilities"), (list, tuple)):
        for cap in meta["capabilities"]:
            if isinstance(cap, str) and cap.lower() in ("vision", "multimodal", "image"):
                caps.append("vision")
    if not caps and _VISION_RE.search(" ".join(hay)):
        caps.append("vision")
    return sorted(set(caps))


def list_model_capabilities() -> dict[str, list[str]]:
    """model id -> capability tags, for the frontend's per-model badge. Tolerant
    of unknown metadata formats: prefers the native endpoint's architecture
    string, and always has the id/arch substring heuristic as a guaranteed
    fallback so a metadata quirk never breaks the endpoint."""
    native = _native_model_meta()
    try:
        response = requests.get(f"{config.LM_STUDIO_BASE_URL}/models", headers=config.lm_studio_headers(), timeout=5)
        response.raise_for_status()
        data = response.json().get("data", [])
    except requests.RequestException:
        data = []

    caps: dict[str, list[str]] = {}
    seen: set[str] = set()
    for entry in data:
        model_id = entry.get("id")
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        caps[model_id] = _detect_capabilities(model_id, native.get(model_id, entry))
    return caps


def eject_model(model_id: str) -> None:
    """Unloads a model so switching models actually replaces the one in VRAM
    instead of leaving both loaded at once (just-in-time loading alone was
    observed to leave a previous model resident).

    Tries LM Studio's own REST API first (POST /api/v1/models/unload, LM
    Studio >= 0.4.0) — a plain HTTP call to the same origin Jarvis already
    chats with, so it works exactly as well when LM Studio runs on a
    different machine on the network. Falls back to the local `lms unload`
    CLI (only ever effective when LM Studio runs on THIS machine) for older
    LM Studio versions that don't have the v1 API yet.
    """
    try:
        resp = requests.post(
            f"{hardware.lm_studio_root()}/api/v1/models/unload",
            json={"instance_id": model_id}, headers=config.lm_studio_headers(), timeout=10,
        )
        if resp.status_code < 400:
            return
        print(f"[model] POST /api/v1/models/unload für {model_id} lieferte {resp.status_code}, versuche 'lms unload'.")
    except requests.RequestException as exc:
        print(f"[model] /api/v1/models/unload nicht erreichbar ({exc}), versuche lokales 'lms unload'.")

    lms = hardware.find_lms_cli()
    if not lms:
        print(
            f"[model] Weder die v1-REST-API noch das 'lms'-CLI konnten {model_id} entladen "
            "— es bleibt in LM Studio geladen. Läuft LM Studio auf diesem Rechner, einmalig "
            "'lms bootstrap' ausführen; läuft es entfernt, prüfen, ob es auf Version >= 0.4.0 ist."
        )
        return
    try:
        result = subprocess.run(
            [lms, "unload", model_id], capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"[model] 'lms unload {model_id}' fehlgeschlagen: {result.stderr.strip()}")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[model] Konnte {model_id} nicht entladen: {exc}")


def model_health() -> tuple[bool, str]:
    """Report whether at least one text model in the fallback chain is
    reachable. Skips DeepSeek entirely (no network call at all, not even the
    free /models listing) when config.DEEPSEEK_ENABLED is off — the whole
    point of the toggle is that nothing gets sent to DeepSeek while it's
    switched off, not just that its reply gets discarded."""
    if config.DEEPSEEK_API_KEY and config.DEEPSEEK_ENABLED:
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
        response = requests.get(f"{config.LM_STUDIO_BASE_URL}/models", headers=config.lm_studio_headers(), timeout=5)
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
    suffix = " (DeepSeek-Fallback)" if config.DEEPSEEK_API_KEY and config.DEEPSEEK_ENABLED else ""
    return True, f"Modell bereit: {config.LM_STUDIO_MODEL}{suffix}"


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
        timeout=_CHAT_TIMEOUT,
        stream=True,
    )
    resp.raise_for_status()
    return resp


# One model round, from either backend, as the same small set of events —
# so the whole reply pipeline in _stream_reply_impl (think filtering, leak
# and corruption detection, claim vetting, sentence streaming) runs
# unchanged on top of both:
#   {"kind": "text", "text": str}           reply text as it arrives
#   {"kind": "reasoning"}                   the model is thinking
#   {"kind": "progress", "phase": "loading"|"prompt", "progress": 0..1}
#   {"kind": "tool_call_delta", "delta": …} OpenAI-style call fragment, run
#                                           by Jarvis after the round
#   {"kind": "tool_started", "tool": str}   LM Studio is calling a tool
#   {"kind": "tool_ran", "tool": str, "output": str}
#                                           …and it ran (via mcp_server)
# Each round generator first yields None once its connection is accepted
# (see _open_round), and closing it closes the HTTP connection — which is
# what actually makes the server stop generating (Stop button).


def _openai_round(messages: list, base_url: str, model: str, headers: dict, extra: dict):
    """A round against an OpenAI-compatible endpoint (DeepSeek)."""
    resp = _open_stream(messages, base_url, model, headers, extra)
    try:
        yield None
        for line in resp.iter_lines():
            if not line.startswith(b"data: "):
                continue
            payload = line[len(b"data: "):].strip()
            if payload == b"[DONE]":
                return
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if "error" in data or not data.get("choices"):
                raise ModelError((data.get("error") or {}).get("message", "Der Modell-Stream ist ungültig."))
            delta = data["choices"][0].get("delta", {})
            if delta.get("reasoning_content"):
                yield {"kind": "reasoning"}
            if delta.get("content"):
                yield {"kind": "text", "text": delta["content"]}
            for tc in delta.get("tool_calls") or []:
                yield {"kind": "tool_call_delta", "delta": tc}
    finally:
        resp.close()


# Per model: which `reasoning` values LM Studio accepts ("off", "on", …).
# Sending one the model doesn't support fails the whole request.
_reasoning_options_cache: dict[str, list[str]] = {}


def _reasoning_options(model: str) -> list[str]:
    if model not in _reasoning_options_cache:
        resp = requests.get(f"{hardware.lm_studio_root()}/api/v1/models", headers=config.lm_studio_headers(), timeout=5)
        if resp.status_code >= 400:
            raise _native_rejection(resp)
        for entry in resp.json().get("models", []):
            ids = {entry.get("key")} | {inst.get("id") for inst in entry.get("loaded_instances") or []}
            if model in ids:
                reasoning = (entry.get("capabilities") or {}).get("reasoning") or {}
                _reasoning_options_cache[model] = list(reasoning.get("allowed_options") or [])
                break
        else:
            return []
    return _reasoning_options_cache[model]


def _native_body(model: str, system_prompt: str, user_input, integration: dict, *, store: bool = True) -> dict:
    body = {
        "model": model,
        "system_prompt": system_prompt,
        "input": user_input,
        "integrations": [integration],
        "temperature": 0.2,
        # Stored by default so a later round/turn can chain off this one's
        # response_id (see _native_round, _chain_lookup/_chain_store) —
        # only the one-off warm-up ping opts out, see warm_system_prompt.
        "store": store,
    }
    # Same intent as `reasoning_effort: none` on the OpenAI path: answer
    # directly instead of thinking first — only where the model allows it.
    if "off" in _reasoning_options(model):
        body["reasoning"] = "off"
    return body


def _native_rejection(resp: requests.Response) -> LmStudioError:
    try:
        err = resp.json().get("error")
        detail = err.get("message", "") if isinstance(err, dict) else str(err or "")
    except ValueError:
        detail = ""
    detail = detail or resp.text.strip() or f"HTTP {resp.status_code}"
    hint = ""
    # Message content decides first — a 403 specifically about mcp.json
    # permissions needs the mcp.json hint, not the generic auth one, even
    # though both surface as 401/403.
    if "mcp" in detail.lower():
        hint = (
            " In LM Studio unter Developer → Server Settings „Allow calling servers from mcp.json“ "
            "einschalten und Jarvis' Eintrag in mcp.json prüfen."
        )
    elif resp.status_code in (401, 403):
        hint = (
            " Hat LM Studio „Require Authentication“ an? Dann muss das passende Token auch in "
            "Jarvis unter Einstellungen -> LM-Studio-API-Token eingetragen sein."
        )
    elif resp.status_code == 404:
        hint = " Jarvis braucht LM Studio 0.4.0 oder neuer."
    return LmStudioError(f"LM Studio hat die Anfrage abgelehnt: {detail}.{hint}")


def _native_error(err: dict) -> LmStudioError:
    message = err.get("message") or "unbekannter Fehler"
    if err.get("type") == "mcp_connection_error":
        return LmStudioError(
            f"LM Studio erreicht Jarvis' Werkzeuge nicht ({message}). Ist Jarvis' Eintrag in LM "
            f"Studios mcp.json vorhanden, „Allow calling servers from mcp.json“ eingeschaltet, "
            f"und lässt die Firewall Port {config.JARVIS_MCP_PORT} zu?"
        )
    return LmStudioError(f"LM Studio meldet einen Fehler: {message}")


def _native_events(body: dict):
    """Opens a streaming POST /api/v1/chat — raising right away if LM Studio
    refuses it — and returns an iterator over its SSE event payloads."""
    resp = requests.post(
        f"{hardware.lm_studio_root()}/api/v1/chat",
        json={**body, "stream": True},
        headers=config.lm_studio_headers(),
        timeout=_CHAT_TIMEOUT,
        stream=True,
    )
    if resp.status_code >= 400:
        raise _native_rejection(resp)
    return _sse_payloads(resp)


# Events that only exist once the prompt is prefilled and the model is
# actually answering.
_ANSWER_EVENTS = ("reasoning.", "message.", "tool_call.", "chat.end", "error")
# How long an abandoned prefill may keep running in the background.
_PREFILL_DRAIN_SECONDS = 900


def _drain_prefill(resp: requests.Response, lines) -> None:
    """Read an abandoned stream up to the end of its prompt prefill, then
    drop it. Closing the connection mid-prefill makes LM Studio throw the
    half-built prompt cache away, so every retry (a second message, the stop
    button, a barge-in) restarted a minutes-long prefill from zero and Jarvis
    never answered. Finishing the prefill keeps the cache for the next turn."""
    deadline = time.monotonic() + _PREFILL_DRAIN_SECONDS
    try:
        for line in lines:
            if time.monotonic() > deadline:
                break
            if not line.startswith(b"data:"):
                continue
            try:
                kind = json.loads(line[len(b"data:"):]).get("type", "")
            except (json.JSONDecodeError, AttributeError):
                continue
            if kind.startswith(_ANSWER_EVENTS):
                break
    except requests.RequestException:
        pass
    finally:
        resp.close()


def _sse_payloads(resp: requests.Response):
    lines = resp.iter_lines()
    answering = False
    try:
        for line in lines:
            if not line.startswith(b"data:"):
                continue
            try:
                payload = json.loads(line[len(b"data:"):])
            except json.JSONDecodeError:
                continue
            if str(payload.get("type", "")).startswith(_ANSWER_EVENTS):
                answering = True
            yield payload
    except GeneratorExit:
        if not answering:
            threading.Thread(target=_drain_prefill, args=(resp, lines), daemon=True).start()
            resp = None
        raise
    finally:
        if resp is not None:
            resp.close()


def _content_text(content) -> str:
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if part.get("type") == "text")
    return content or ""


def _native_input(messages: list):
    """(system_prompt, input) for /api/v1/chat, built from the same message
    list the OpenAI path sends.

    That endpoint takes one system prompt and ONE user message — no
    role-based history. Earlier turns therefore go into that message as a
    labeled transcript ahead of the new one, not into the system prompt:
    chat templates render the tool definitions right after the system
    prompt, so a growing history there would push them out of LM Studio's
    prompt cache every turn. This way each turn's transcript extends the
    previous one's.

    Called with the FULL `messages` list when there's no response_id to
    chain off of (see _native_round); called with just `[messages[0],
    messages[-1]]` for a chained round, where `earlier` then comes out
    empty and this naturally returns just the newest message with no
    transcript prefix — LM Studio already has everything before that
    stored server-side (see _chain_lookup/_chain_store)."""
    system_prompt = messages[0]["content"]
    *earlier, current = messages[1:]
    text = _content_text(current["content"])
    lines = [
        f"{'Nutzer' if m['role'] == 'user' else 'Jarvis'}: {_content_text(m.get('content')).strip()}"
        for m in earlier
        if _content_text(m.get("content")).strip()
    ]
    if lines:
        text = "Bisheriger Chatverlauf:\n" + "\n".join(lines) + "\n\nNeue Nachricht des Nutzers:\n" + text
    images = [
        part["image_url"]["url"]
        for part in current["content"] if part.get("type") == "image_url"
    ] if isinstance(current["content"], list) else []
    if not images:
        return system_prompt, text
    return system_prompt, [{"type": "text", "content": text}, *({"type": "image", "data_url": url} for url in images)]


def _native_round(messages: list, model: str, turn_id: str | None, previous_response_id: str | None = None):
    """A round against LM Studio's native /api/v1/chat. LM Studio runs the
    tool loop itself through mcp_server, so one round can already contain
    several tool calls and the text before and after them.

    `previous_response_id`, when given, chains off an earlier round/turn's
    stored response instead of resending the whole transcript (see
    _native_input). `system_prompt`/`integrations` are sent fresh either
    way — like the OpenAI Responses API LM Studio mirrors here, those do
    NOT automatically carry over via previous_response_id (confirmed:
    https://github.com/vllm-project/vllm/issues/37697, an instructions-
    leak reported as a bug precisely because that's not the intended
    behaviour), only the conversation-so-far does."""
    if previous_response_id:
        system_prompt, user_input = _native_input([messages[0], messages[-1]])
    else:
        system_prompt, user_input = _native_input(messages)
    # A brand-new chat (system prompt + first message, no history) whose
    # system prompt is exactly the one a stored base was made with starts as a
    # fork of that base: the base already carries the processed system prompt,
    # so it must NOT be sent again (LM Studio answers a re-sent one with a 500
    # "System message must be at the beginning" — verified live), while the
    # tool integration has to be (without it the model only writes the call as
    # text — also verified). Every other case takes the normal path.
    _last_chat_system[model] = system_prompt
    base_id = None
    if not previous_response_id and len(messages) == 2:
        base_id = _fork_base_lookup(model, system_prompt)
    with mcp_server.request_scope(lambda: not _turn_cancelled(turn_id)) as integration:
        body = _native_body(model, system_prompt, user_input, integration)
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        events = None
        if base_id:
            fork_body = {k: v for k, v in body.items() if k != "system_prompt"}
            fork_body["previous_response_id"] = base_id
            try:
                events = _native_events(fork_body)
            except LmStudioError as exc:
                print(f"[model] Fork der Basis nicht möglich, normaler Weg: {exc}")
                if "previous_response_id" in str(exc):
                    # Base gone on LM Studio's side — make a fresh one in the
                    # background for the next new chat.
                    _fork_base_forget(model, system_prompt)
                    threading.Thread(target=warm_system_prompt, args=(model,), daemon=True).start()
        if events is None:
            events = _native_events(body)
        try:
            yield None
            for data in events:
                kind = data.get("type")
                if kind in ("model_load.start", "model_load.progress"):
                    yield {"kind": "progress", "phase": "loading", "progress": data.get("progress", 0.0)}
                elif kind in ("prompt_processing.start", "prompt_processing.progress"):
                    yield {"kind": "progress", "phase": "prompt", "progress": data.get("progress", 0.0)}
                elif kind == "reasoning.delta":
                    yield {"kind": "reasoning"}
                elif kind == "message.start":
                    # A message after a tool call continues the reply —
                    # without a break, "Ich schaue nach." + "Es ist 12 Uhr."
                    # would glue into one unsplittable "nach.Es" sentence.
                    yield {"kind": "text", "text": "\n\n"}
                elif kind == "message.delta":
                    yield {"kind": "text", "text": data.get("content", "")}
                elif kind == "tool_call.start":
                    yield {"kind": "tool_started", "tool": data.get("tool", "")}
                elif kind == "tool_call.success":
                    yield {"kind": "tool_ran", "tool": data.get("tool", ""), "output": mcp_server.output_text(data.get("output", ""))}
                elif kind == "tool_call.failure":
                    # LM Studio hands the failure back to the model itself,
                    # which then retries or answers — nothing ran.
                    print(f"[mcp] Tool-Aufruf fehlgeschlagen: {data.get('reason')}")
                elif kind == "error":
                    raise _native_error(data.get("error") or {})
                elif kind == "chat.end":
                    rid = (data.get("result") or {}).get("response_id")
                    if rid:
                        yield {"kind": "response_id", "id": rid}
                    return
        finally:
            events.close()


# conversation_id -> {"response_id", "expect_history_len"}, for LM Studio's
# native response-chaining (see _native_round's previous_response_id).
# AKTUELL DEAKTIVIERT — kein Aufrufer setzt previous_response_id mehr (siehe
# Kommentar in stream_reply): Bei diesem LM-Studio-Build kippt ein chained
# Request auf zwei Arten (live per Probe verifiziert) — die erneut
# mitgeschickte system_prompt landet beim Ketten an falscher Position
# (leere Antwort / 500 "System message must be at the beginning"), und
# MCP-Tool-Aufrufe werden storniert ("Werkzeug wurde nicht ausgeführt"),
# weil das Plugin im chained Kontext nicht mehr live verbunden ist. Die
# Helfer bleiben nur als Anknüpfpunkt stehen, falls LM Studio den
# Chained-Pfad repariert; bis dahin schickt jede Runde den vollen
# Transcript. NACHTRAG: Ein Gegentest ohne Jarvis-Anfrage-Scope (Fork ohne
# system_prompt, MIT Integration) führte get_time in einem Fork sehr wohl aus
# — die zweite Beobachtung (stornierte Tool-Aufrufe) war vermutlich Jarvis'
# eigene Ablehnung außerhalb eines aktiven request_scope. Der Fork von der
# Basis (_fork_bases) nutzt deshalb genau diese Kombination.
# Transcript. In-memory only, Neustarts von Jarvis oder LM Studio
# invalidieren eine Kette ohnehin.
_response_chains: dict[str, dict] = {}


def _chain_lookup(conversation_id: str | None, history: list | None) -> str | None:
    if not conversation_id:
        return None
    state = _response_chains.get(conversation_id)
    if not state or state["expect_history_len"] != len(history or []):
        return None
    return state["response_id"]


def _chain_store(conversation_id: str | None, history: list | None, response_id: str | None) -> None:
    if not conversation_id or not response_id:
        return
    _response_chains[conversation_id] = {
        "response_id": response_id,
        "expect_history_len": len(history or []) + 2,
    }


def _chain_clear(conversation_id: str | None) -> None:
    if conversation_id:
        _response_chains.pop(conversation_id, None)


def _open_round(messages: list, turn_id: str | None, previous_response_id: str | None = None):
    """The event stream (see above) for one model round, from the first
    target in `_request_targets` that accepts the connection — falling back
    (e.g. from a dead DeepSeek key to LM Studio) only as long as nothing has
    streamed yet; once it has, a mid-stream error surfaces instead of
    silently restarting with a different model. LM Studio goes through its
    native /api/v1/chat, DeepSeek through its OpenAI-compatible endpoint.
    `previous_response_id` only ever applies to the LM Studio target —
    DeepSeek has no such feature."""
    last_exc: Exception = ModelError("Kein Modell-Ziel konfiguriert.")
    for base_url, model, headers, extra in _request_targets():
        if base_url == config.DEEPSEEK_BASE_URL:
            stream = _openai_round(messages, base_url, model, headers, extra)
        else:
            stream = _native_round(messages, model, turn_id, previous_response_id)
        try:
            next(stream)
        except requests.RequestException as exc:
            print(f"[model] {base_url} nicht verfügbar, versuche nächstes Ziel: {exc}")
            last_exc = exc
            continue
        _note_active_target(base_url, model)
        return stream
    raise last_exc


def _round_transcript(content: str, round_tools: list[tuple[str, str]]) -> str:
    """What a finished round said and did, for the context of the next
    round — on the native path LM Studio's own tool calls and results are
    otherwise gone once its request ends."""
    ran = "".join(f"[{name} ausgeführt, Ergebnis: {output}]\n" for name, output in round_tools)
    return ran + content


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
# The capital run must be glued to more word characters ("_", or a lowercase
# letter right after the caps) — a bare `^[A-ZÄÖÜ]{4,}` also matched every
# ordinary answer starting with an acronym ("HTML (HyperText …", "JSON ist …",
# "WLAN", "NVIDIA"): benchmarked 6/6 such answers were retried ten times and
# then replaced by "Alles klar.".
_CORRUPT_PREFIX_RE = re.compile(r"^[A-ZÄÖÜ]{4,}(?:[a-zäöüß]{2}|[A-ZÄÖÜ0-9]*_)")


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
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]{2,29})\s*\(", t)
    if m and _looks_like_call_name(m.group(1)):
        return True
    # Still a bare word — could turn into either a call or ordinary prose.
    # (Or an acronym still growing, e.g. "HTM" -> "HTMLi…": wait for more.)
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t) and len(t) <= 30:
        return None
    return False


def _looks_like_call_name(name: str) -> bool:
    """A leaked call is a real tool name (any case) or a snake_case
    identifier (an invented tool) — not prose like "HTML (HyperText …)"
    or "Python (die Sprache)", which also starts with word + "("."""
    return name.lower() in tools.DISPATCH or "_" in name or name[:1].islower()


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
    r"heruntergefahren|neugestartet|gesichert|verriegelt|aktiviert|deaktiviert|"
    r"weitergegeben|weitergeleitet)\b",
    re.IGNORECASE,
)
# Handing a coding task to the opencode tool has its own characteristic
# phrasing ("Ich habe den Auftrag ... gegeben") that the participle list
# above doesn't fully cover — a bare "gegeben" is too generic on its own
# (also shows up in plenty of unrelated honest sentences), but "gegeben"
# right after "Auftrag" specifically is not (observed live, five times
# over five otherwise-identical requests: the model claimed exactly this
# without ever calling opencode, and neither this word nor
# "weitergegeben" above existed anywhere in this file's claim detection —
# it was built up for the older open/save/delete/click tools and never
# extended when opencode was added).
_TASK_HANDOFF_RE = re.compile(
    r"\bauftrag\b[^.!?]{0,60}\b(?:weitergegeben|weitergeleitet|übergeben|gegeben)\b",
    re.IGNORECASE,
)
_CHECK_PARTICIPLE_RE = re.compile(
    r"\b(?:gefunden|durchsucht|gescannt|überprüft|geprüft|analysiert|kontrolliert)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"\b(?:nicht|nichts|kein|keine|keinen|keinem|keiner)\b", re.IGNORECASE)
# A statement about whether a file/folder exists or was already removed is a
# check result, so negation doesn't excuse it either — observed live: after an
# unrecognized "Ja bitte" to a delete confirmation, the model claimed "Die
# Datei wurde bereits gelöscht oder existiert gar nicht mehr" while the file
# was still there.
_FS_STATE_CLAIM_RE = re.compile(
    r"\b(?:datei|ordner|verzeichnis)\w*\b[^.!?]{0,80}\b(?:existiert|existieren|vorhanden|gelöscht|entfernt)\b",
    re.IGNORECASE,
)
# The model rejecting a requested code-agent model switch as "unknown" from
# its own (non-)knowledge, without ever having called opencode_model to find
# out — observed live: "Auch 'Big Pickle' ist mir als Modellname unbekannt.
# Kannst du mir sagen, ...?" for a model that genuinely exists in OpenCode's
# catalog. Only opencode_model actually knows the catalog; a refusal that
# skips it is exactly as unbacked as claiming a file was deleted without
# checking (see _FS_STATE_CLAIM_RE above).
_MODEL_UNKNOWN_CLAIM_RE = re.compile(
    r"\bmodell\w*\b[^.!?]{0,60}\b(?:unbekannt|nicht bekannt|nicht verfügbar|"
    r"existiert nicht|gibt es nicht|kenne ich nicht|kenn ich nicht)\b",
    re.IGNORECASE,
)
# The opposite failure of the one above: claiming the switch WORKED without
# ever calling opencode_model — observed live, switching A -> B -> back to A
# again: the second switch was never actually applied (get_selected_model
# still showed B), yet the reply confidently said the model was back to A.
# None of the existing participle/stem lists caught this (they were built for
# open/save/delete/click, never extended for "wechseln"/"umstellen") so the
# claim sailed through unvetted. Order-independent (lookaheads) since the verb
# and "Modell" can appear in either order ("Modell gewechselt" vs. "Big
# Pickle ist jetzt aktiv") — deliberately also matches opencode_model's own
# genuine return text ("OpenCode arbeitet ab jetzt mit X"), which is fine:
# when the tool really ran, the requirement below is already satisfied.
_MODEL_SWITCH_CLAIM_RE = re.compile(
    r"(?=.*\b(?:modell\w*|coding-agent)\b)"
    r"(?=.*\b(?:gewechselt|wechselt|zurückgewechselt|umgestellt|umgeschaltet|"
    r"eingestellt|gesetzt|aktiviert|arbeitet\s+(?:ab\s+)?jetzt\s+mit|"
    r"läuft\s+(?:ab\s+)?jetzt\s+mit|ist\s+(?:jetzt\s+)?wieder)\b)",
    re.IGNORECASE,
)

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
_NEGATION_WORDS = {"nicht", "nichts", "kein", "keine", "keinen", "keinem", "keiner"}
# "ich KANN X" states general capability/ability, not that X is happening or
# will happen — unlike "ich werde/muss/will X", which _ACTION_STEM_RE's own
# comment deliberately treats as committing to the action. Cancels a match
# the same way negation does (observed live: "Ich kann zum Beispiel
# Webseiten öffnen, ... suchen oder ... programmieren" — a capability
# listing in answer to "was kannst du?", not a claim any of that just ran).
_CAPABILITY_WORDS = {"kann", "könnte"}
_WORD_OR_COMMA_RE = re.compile(r"[\wÄÖÜäöüß]+|,")


# A participle alone ("ausgeführt", "gespeichert", "gefunden") is just as
# common in explanations ("JavaScript wird im Browser ausgeführt", "Die Mauer
# wurde 1989 geöffnet", "Penicillin wurde 1928 gefunden") as in a report of
# Jarvis's own action — benchmarked, such sentences made up most of what the
# filter replaced with "Das habe ich nicht ausgeführt.". It only reads as a
# self-report when the sentence is about Jarvis/the user right now, or is a
# terse status line ("Ordner gelöscht.", "Spotify ist geöffnet.").
_SELF_REPORT_RE = re.compile(
    r"\b(?:ich|hab|habe|habs|hab's|mir|jetzt|gerade|soeben|eben|nun|erfolgreich|erledigt|dir|dich|deine[mnrs]?|dein)\b",
    re.IGNORECASE,
)


def _self_report_context(sentence: str) -> bool:
    words = [t for t in _WORD_OR_COMMA_RE.findall(sentence) if t != ","]
    return len(words) <= 5 or bool(_SELF_REPORT_RE.search(sentence))


# "Ich zeige dir ein Beispiel", "ich schreibe dir das als Liste auf", "ich
# starte mit den Grundlagen" describe the reply itself, not an action on the
# computer — unless a real target (file, app, browser …) is named.
_CONVERSATIONAL_ICH_RE = re.compile(
    r"\bich\s+(?:zeige|schreibe|erkläre|erstelle|suche|fasse|liste|gebe|starte|beginne|lade)\s+"
    r"(?:dir|euch|dich|mal|kurz|gern|gerne|mit|zusammen|hier|ein|eine|einen)\b",
    re.IGNORECASE,
)
_REAL_OBJECT_RE = re.compile(
    r"\b(?:datei\w*|ordner\w*|verzeichnis\w*|programm\w*|apps?|browser|terminal|notiz\w*|desktop|"
    r"schreibtisch|webseite\w*|website\w*|youtube|spotify|tabs?|fenster|screenshot\w*|papierkorb|"
    r"downloads?|dokumente|e-?mails?|opencode|codex|coding-agent\w*|internet|web|google|netz)\b"
    r"|\w\.(?:txt|py|md|js|json|csv|pdf)\b",
    re.IGNORECASE,
)
# A sentence opening with a condition is an offer or hypothetical ("Wenn du
# mir das sagst, kann ich es mir notieren"), not a report.
_CONDITIONAL_START_RE = re.compile(r"^\s*(?:wenn|falls|sobald|sofern)\b", re.IGNORECASE)
# "kann ich", "könnte ich", "würde ich" — capability/offer, same as "ich kann".
_MODAL_BEFORE_ICH = {"kann", "könnte", "könnten", "würde", "würden", "möchte", "darf", "soll", "sollte"}


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
    if not _self_report_context(sentence):
        return False
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
    if _CONVERSATIONAL_ICH_RE.search(sentence) and not _REAL_OBJECT_RE.search(sentence):
        return False
    tokens = _WORD_OR_COMMA_RE.findall(sentence)
    lowered = [t.lower() for t in tokens]
    for i, tok in enumerate(lowered):
        if tok != "ich":
            continue
        if i > 0 and (lowered[i - 1] in _CLAUSE_BOUNDARY_WORDS or lowered[i - 1] in _MODAL_BEFORE_ICH):
            continue
        negated = False
        capability = False
        for j in range(i + 1, min(i + 13, len(tokens))):
            nxt = lowered[j]
            if nxt == "," or nxt in _CLAUSE_BOUNDARY_WORDS:
                break
            if nxt in _NEGATION_WORDS:
                negated = True
                continue
            if nxt in _CAPABILITY_WORDS:
                capability = True
                continue
            # German capitalizes every noun but never a mid-sentence finite
            # verb — a capitalized hit here is almost always the NOUN form
            # ("eine Web-Suche", "der erste Klick"), not the verb "ich
            # suche"/"ich klicke". Checked against the ORIGINAL token, since
            # `lowered` (used for every other comparison here) already threw
            # that signal away (observed live: "ich brauche dafür eine
            # Web-Suche" — no action taken or even offered, just naming a
            # noun — flagged as if it had said "ich suche").
            if tokens[j][:1].isupper():
                continue
            if not negated and not capability and _ACTION_STEM_RE.search(nxt):
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


def _sentence_is_claim(sentence: str) -> bool:
    if _CONDITIONAL_START_RE.match(sentence):
        return False
    negated = _NEGATION_RE.search(sentence)
    is_claim = (
        _bare_participle_claim(sentence, _CHECK_PARTICIPLE_RE)
        or (_bare_participle_claim(sentence, _ACTION_PARTICIPLE_RE) and not negated)
        or _direct_ich_claim(sentence)
        or (bool(_TASK_HANDOFF_RE.search(sentence)) and not negated)
        or bool(_FS_STATE_CLAIM_RE.search(sentence))
        or bool(_MODEL_UNKNOWN_CLAIM_RE.search(sentence))
        or bool(_MODEL_SWITCH_CLAIM_RE.search(sentence))
    )
    if not is_claim:
        return False
    if _NOT_A_CLAIM_RE.search(sentence):
        return False
    # A real question mixed into the same sentence ("... welchen Ordner
    # soll ich nehmen?") is Jarvis asking, not claiming.
    if "?" in sentence:
        return False
    return True


def _claims_action(text: str) -> bool:
    """A claim in one sentence isn't excused by a question mark in another.

    Checked per sentence rather than across the whole reply at once — a
    reply like 'Ich lösche den Ordner X. Möchtest du das wirklich?' used to
    slip through entirely: the trailing question mark and "möchtest du"
    exempted the *whole* text, false claim included, even though neither
    has anything to do with the first sentence (observed live: exactly this
    sentence pattern, for a delete that never actually ran as a tool call).
    """
    return any(
        _sentence_is_claim(s.strip())
        for s in _SENTENCE_BOUNDARY_RE.split(text or "")
        if s.strip()
    )


# Most claim wording (the participle/stem lists above) is shared across many
# tools, so "some tool ran this turn" was a reasonable proxy for "this claim
# is backed" — until it wasn't: observed live, a real set_code_agent call
# was enough to wave through a completely unrelated, unbacked claim "Ich
# habe den Auftrag an Claude Code weitergegeben" the very next turn, because
# opencode itself never ran. The task-handoff phrasing is distinctive enough
# to map to its one real backing tool; extending this table to every other
# participle would need a similarly tight, verified mapping for each one
# (risking newly flagging genuine claims from a wrong guess) and hasn't been
# done — this stays scoped to the one gap actually observed.
_CLAIM_TOOL_REQUIREMENTS: tuple[tuple[re.Pattern, frozenset[str]], ...] = (
    (_TASK_HANDOFF_RE, frozenset({"opencode"})),
    (_MODEL_UNKNOWN_CLAIM_RE, frozenset({"opencode_model"})),
    (_MODEL_SWITCH_CLAIM_RE, frozenset({"opencode_model"})),
)


def _required_tools_for_claim(sentence: str) -> frozenset[str] | None:
    """Which specific tool(s) would back this sentence's claim, or None to
    fall back to the old, coarser "some tool ran this turn" rule."""
    for pattern, required in _CLAIM_TOOL_REQUIREMENTS:
        if pattern.search(sentence):
            return required
    return None


def _unbacked_claim(text: str, tools_used, recent_action_confirmed: bool) -> bool:
    """Whether `text` contains a claim not backed by what actually ran.

    A specifically-mapped claim (see _CLAIM_TOOL_REQUIREMENTS) needs its own
    named tool in `tools_used`; every other claim keeps the old, coarser
    rule of needing just some tool to have run this turn.
    """
    if recent_action_confirmed:
        return False
    used = set(tools_used)
    for sentence in _SENTENCE_BOUNDARY_RE.split(text or ""):
        sentence = sentence.strip()
        if not sentence or not _sentence_is_claim(sentence):
            continue
        required = _required_tools_for_claim(sentence)
        if required is not None:
            if not (required & used):
                return True
        elif not used:
            return True
    return False


def _looks_like_tool_text(text: str) -> bool:
    """Never show a tool call as prose, even when it is in another language."""
    names = "|".join(re.escape(name) for name in tools.DISPATCH)
    return bool(re.search(rf"\b(?:{names})\s*\(", text or "", re.IGNORECASE))


_FOLLOWUP_ACTION_RE = re.compile(
    r"\b(wirklich|tats(?:ä|ae)chlich|hast du|hat es|ist es|ist er|ist sie|"
    r"schon fertig|erledigt|geklappt|funktioniert(?:\s+hat)?|sicher)\b",
    re.IGNORECASE,
)


def _looks_like_followup_question(user_message: str) -> bool:
    """A short back-reference to what just happened ("hast du das wirklich
    gemacht?", "ist es fertig?"), not a fresh request. Deliberately cheap:
    a question mark or one of a handful of confirmation words — good enough
    to separate "did that thing you said happen" from a new imperative."""
    t = (user_message or "").strip()
    if not t:
        return False
    return "?" in t or bool(_FOLLOWUP_ACTION_RE.search(t))


def _history_has_recent_action_claim(user_message: str, history: list | None, lookback: int = 6) -> bool:
    """Whether the user is asking about a real action a nearby past turn
    already reported, rather than making a fresh request this turn.

    Anything sitting in history already passed this same vet check when it
    was first generated — an action claim only survives into history if a
    tool really ran that turn (see _vet below). So if one shows up nearby
    AND the user's current message reads like a follow-up about it ("hast
    du das wirklich gemacht?"), that's asking about something that
    genuinely happened, not making a fresh, unverified claim — and must
    not be blocked just because no tool ran in *this* turn (observed live:
    user asked exactly that after a real open_app call, and Jarvis's
    honest "ja, hab ich" got replaced with "Das habe ich nicht
    ausgeführt.", flatly contradicting an action it had just completed).

    The follow-up check matters: without it, ANY nearby real action —
    regardless of what the new message actually asks for — exempted the
    whole turn from the check, letting an unrelated fresh claim slip
    through unverified (observed live: a real set_code_agent call one turn,
    then "Ich gebe den Auftrag an Claude Code weiter" the next with no
    opencode call behind it at all, waved through only because
    set_code_agent still counted as "recent").
    """
    if not _looks_like_followup_question(user_message):
        return False
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


def stream_reply(user_message: str, history: list | None = None, turn_id: str | None = None, mode: str | None = None, images: list[str] | None = None, is_speech: bool = False, conversation_id: str | None = None):
    """Thin wrapper around _stream_reply_impl that guarantees turn_id gets
    dropped from _cancelled_turns once the turn ends, cancelled or not —
    otherwise every turn_id a client ever sends would sit in that set
    forever."""
    try:
        yield from _stream_reply_impl(user_message, history, turn_id, mode, images, is_speech, conversation_id)
    finally:
        if turn_id:
            _cancelled_turns.discard(turn_id)


def _stream_reply_impl(user_message: str, history: list | None = None, turn_id: str | None = None, mode: str | None = None, images: list[str] | None = None, is_speech: bool = False, conversation_id: str | None = None):
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

    messages = _build_messages(user_message, history, mode, images, is_speech)
    # Chaining per LM Studios previous_response_id ist deaktiviert: ein
    # chained /api/v1/chat-Request (nur neue Nachricht + previous_response_id)
    # bricht bei diesem LM-Studio-Build doppelt (live per Probe verifiziert):
    #  - Wird system_prompt trotzdem frisch mitgeschickt, kommt eine leere
    #    Antwort bzw. 500 "Jinja Exception: System message must be at the
    #    beginning" — LM Studio schiebt die erneute System-Message beim
    #    Ketten an falscher Position ein (qwen-Template verlangt sie an
    #    Position 0).
    #  - Wird system_prompt weggelassen, läuft die Antwort zwar (die
    #    gespeicherte Conversation trägt die System-Message weiter), aber
    #    MCP-Tool-Aufrufe werden von LM Studio storniert ("Werkzeug wurde
    #    nicht ausgeführt") — das Plugin ist im chained Kontext nicht mehr
    #    live verbunden, get_time/open_url/… funktionieren gar nicht.
    # Deshalb schickt JEDE Runde wieder den vollen Transcript (system_prompt +
    # "Bisheriger Chatverlauf…" im input), status quo ante Chaining. Die
    # _chain_*-Helfer und der previous_response_id-Parameter in
    # _native_round/_open_round bleiben nur als Anknüpfpunkt stehen, falls
    # LM Studio den Chained-Pfad irgendwann repariert — verwenden darf sie
    # hier aber nichts mehr.

    last_tool_result = None
    full_text_parts = []
    # Every tool that actually ran this turn. Used to catch replies that
    # claim an action was performed when nothing was.
    tools_used: list[str] = []
    # A tool call from an earlier turn still counts as "really happened" —
    # this only widens the exemption for claims that echo/confirm one of
    # those, never for a claim about something new (see
    # _history_has_recent_action_claim).
    recent_action_confirmed = _history_has_recent_action_claim(user_message, history)
    # Statt der immer gleichen "Denkt nach…"-Anzeige im Frontend: einmalige
    # Status-Events ("thinking"/"answering"/"tool"), sobald der jeweilige
    # Zustand tatsächlich zum ersten Mal eintritt — siehe deren Yield-Stellen
    # unten. Ein Set statt einzelner Bools, weil "tool" pro Turn mehrfach
    # (mit wechselndem Werkzeugnamen) auftreten kann, "thinking"/"answering"
    # aber jeweils nur einmal.
    status_sent: set[str] = set()
    # Last whole percent sent per progress phase ("loading"/"prompt") — LM
    # Studio reports far finer steps than a status line can show.
    progress_sent: dict[str, int] = {}
    # Tool calls LM Studio started this turn (native path). It runs the tool
    # loop itself, so this is the only bound on a model stuck calling tools.
    native_tool_calls = 0
    tool_budget_exhausted = False

    def _vet(text: str) -> str:
        """Swap a sentence for an honest one if it fails the same checks
        the old end-of-turn gate used to run on the whole reply at once —
        now run per sentence so a lone false claim doesn't hold up (or
        taint) everything spoken around it."""
        if _looks_like_tool_text(text) or _unbacked_claim(text, tools_used, recent_action_confirmed):
            print(f"[vet] Ersetze mutmaßlich falsche Aktionsbehauptung: {text!r}")
            return "Das habe ich nicht ausgeführt."
        if _is_repetition_loop(text):
            print(f"[vet] Ersetze erkannte Wiederholungsschleife: {text!r}")
            return "Da ist mir gerade etwas verrutscht, frag bitte nochmal."
        return text

    # Sentences that read as an action claim with nothing backing them up
    # YET this round — but the model can still emit a real tool_calls delta
    # moments later in the very same response (observed live: "Ich öffne
    # die YouTube-Ergebnisse für ..." immediately followed by the actual
    # youtube_search call in the same round). Vetting a sentence the instant
    # it completes can't see that still-arriving tool call, so a genuine
    # claim got branded a lie every time the model announced the action
    # before the structured call for it. Held here instead and resolved
    # once the round's outcome is known — see _flush_pending_claims.
    pending_claims: list[str] = []

    def _is_pending_claim_risk(text: str) -> bool:
        return not _looks_like_tool_text(text) and _unbacked_claim(text, tools_used, recent_action_confirmed)

    def _flush_pending_claims():
        nonlocal pending_claims
        for s in pending_claims:
            vetted = _vet(s)
            if full_text_parts and full_text_parts[-1] == vetted:
                continue
            full_text_parts.append(vetted)
            yield {"type": "sentence", "text": vetted}
        pending_claims = []

    for _ in range(MAX_TOOL_ROUNDS):
        # Chaining deaktiviert (siehe Kommentar oben) — jede Runde schickt
        # den vollen Transcript, previous_response_id wird nie gesetzt.
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
            pending_claims = []
            think_state = _new_think_filter_state()
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
            # Tools LM Studio already ran within this round (native path) —
            # (name, output) in order, for the next round's context.
            round_tools: list[tuple[str, str]] = []
            stream = _open_round(messages, turn_id)

            for event in stream:
                # The Stop button (chat/cancel) used to only be checked
                # between tool-call rounds — while the model was still
                # generating plain text, nothing here ever looked at the
                # flag, so Stop neither ended the reply nor (since the
                # connection to LM Studio stayed open) actually interrupted
                # LM Studio's own generation. Checked on every event now, and
                # stream.close() really closes that connection instead of
                # just abandoning the generator.
                if _turn_cancelled(turn_id):
                    stream.close()
                    yield {"type": "done", "full_text": "".join(full_text_parts)}
                    return
                kind = event["kind"]

                if kind == "response_id":
                    # _native_round meldet die chat.end-response_id noch,
                    # aber Chaining ist deaktiviert — schlicht überspringen.
                    continue

                if kind == "progress":
                    percent = int(event["progress"] * 100)
                    if progress_sent.get(event["phase"]) != percent:
                        progress_sent[event["phase"]] = percent
                        yield {"type": "status", "phase": event["phase"], "progress": percent}
                    continue

                if kind == "tool_call_delta":
                    tc = event["delta"]
                    idx = tc.get("index", 0)
                    entry = tool_calls_acc.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        entry["name"] += fn["name"]
                    if fn.get("arguments"):
                        entry["arguments"] += fn["arguments"]
                    continue

                if kind == "tool_started":
                    native_tool_calls += 1
                    if native_tool_calls > MAX_NATIVE_TOOL_CALLS:
                        print(f"[llm] Mehr als {MAX_NATIVE_TOOL_CALLS} Tool-Aufrufe in einem Turn, breche ab.")
                        stream.close()
                        tool_budget_exhausted = True
                        break
                    yield {"type": "status", "phase": "tool", "tool": event["tool"]}
                    continue

                if kind == "tool_ran":
                    tools_used.append(event["tool"])
                    last_tool_result = event["output"]
                    round_tools.append((event["tool"], event["output"]))
                    # Same as after an OpenAI-path tool call below: a pending
                    # confirmation's question is spoken verbatim, and the
                    # model must not get to paraphrase it.
                    if confirm.is_pending():
                        stream.close()
                        yield {"type": "sentence", "text": event["output"]}
                        yield {"type": "done", "full_text": event["output"]}
                        return
                    # Claims held earlier this round are backed now.
                    yield from _flush_pending_claims()
                    continue

                # Modelle, die Reasoning getrennt vom Antworttext senden
                # (reasoning_content bzw. reasoning.delta, statt es als
                # <think>-Text in den Inhalt zu leaken — siehe
                # _filter_think), sagen uns hierüber trotzdem, dass gerade
                # nachgedacht wird — reicht für den Status, auch wenn der
                # Inhalt selbst nirgends angezeigt wird.
                if kind == "reasoning" and "thinking" not in status_sent:
                    status_sent.add("thinking")
                    yield {"type": "status", "phase": "thinking"}
                if think_state["in_think"] and "thinking" not in status_sent:
                    status_sent.add("thinking")
                    yield {"type": "status", "phase": "thinking"}

                # Reasoning text (<think>...</think>) is filtered out right
                # here, before anything downstream ever sees it — see
                # _filter_think for why that has to happen at this exact
                # point rather than later on individual sentences.
                visible = _filter_think(think_state, event["text"]) if kind == "text" else ""
                if visible:
                    if "answering" not in status_sent:
                        status_sent.add("answering")
                        yield {"type": "status", "phase": "answering"}
                    buffer += visible
                    content_acc += visible

                    if suspect is None:
                        suspect = _call_prefix_verdict(content_acc)
                        if suspect == "corrupt":
                            stream.close()
                            break

                    if suspect is False:
                        if trailing_suspect:
                            trailing_suspect_text += visible
                        else:
                            sentences, buffer = _pop_complete_sentences(buffer)
                            for s in sentences:
                                verdict = _call_prefix_verdict(s)
                                if verdict in (True, "corrupt"):
                                    trailing_suspect = verdict
                                    trailing_suspect_text = s
                                    break
                                clean = _strip_think_tags(s)
                                # Once a sentence is held, everything after it
                                # waits too — otherwise later sentences overtook
                                # it and the reply came out of order.
                                if clean and (pending_claims or _is_pending_claim_risk(clean)):
                                    # Might still be backed by a tool_calls
                                    # delta arriving later in this very
                                    # round — held instead of vetted now,
                                    # see _flush_pending_claims.
                                    pending_claims.append(clean)
                                elif clean:
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

                            # Live, word-by-word: während das Modell schreibt, den
                            # gerade entstehenden (noch unfertigen) Satz anzeigen,
                            # statt den Nutzer 20s auf's erste Wort starren zu lassen.
                            # Denk-/Code-Fragmente im Zwischenpuffer wegstreifen.
                            if buffer and not trailing_suspect:
                                partial = _strip_think_tags(buffer)
                                yield {"type": "partial", "text": partial}

                    else:
                        if buffer:
                            partial = _strip_think_tags(buffer)
                            yield {"type": "partial", "text": partial}

            # _filter_think always withholds a short tail (long enough to
            # catch a </think> split across two chunks) — once the stream is
            # actually done, that tail can never turn out to be a tag after
            # all, so release it now instead of silently swallowing the last
            # few characters of every reply.
            if not think_state["in_think"] and think_state["carry"]:
                buffer += think_state["carry"]
                content_acc += think_state["carry"]
                think_state["carry"] = ""

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

            # A retry repeats the whole request — never once LM Studio already
            # ran a tool in it, or that tool's side effect happens twice.
            # The garbage is dropped below instead, like after the last retry.
            if suspect != "corrupt" or round_tools:
                break

        if tool_budget_exhausted:
            yield from _flush_pending_claims()
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
                yield {"type": "status", "phase": "tool", "tool": c["name"]}
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
            yield from _flush_pending_claims()
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
                yield {"type": "status", "phase": "tool", "tool": name}
                result = tools.call_tool(name, args)
                tools_used.append(name)
                last_tool_result = result
                messages.append({"role": "assistant", "content": _round_transcript(content_acc, round_tools)})
                messages.append({"role": "user", "content": f"[Ergebnis von {name}: {result}]"})
                buffer = ""
                yield from _flush_pending_claims()
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
                messages.append({"role": "assistant", "content": _round_transcript(content_acc, round_tools)})
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
                yield from _flush_pending_claims()
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
            yield {"type": "status", "phase": "tool", "tool": name}
            result = tools.call_tool(name, args)
            tools_used.append(name)
            last_tool_result = result
            messages.append({"role": "assistant", "content": _round_transcript(content_acc, round_tools)})
            messages.append({"role": "user", "content": f"[Ergebnis von {name}: {result}]"})
            buffer = ""
            yield from _flush_pending_claims()
            continue

        # No tool ran this round after all (every recovery path above was
        # ruled out) — resolve any held claims now, same rules as _vet
        # would have applied at the time, since nothing arrived to back
        # them up.
        yield from _flush_pending_claims()

        if suspect == "corrupt":
            # All retries came back corrupted too — silently drop it rather
            # than read garbage aloud. Falls through to the empty-reply
            # fallback below, or to last_tool_result if a tool did run.
            print("[llm] Streaming blieb korrupt, verwerfe den Rest.")
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
            # Nothing ran and nothing was said — "Alles klar." here read like
            # a confirmation of something that never happened.
            empty = "Da ist bei mir gerade keine Antwort zustande gekommen, frag bitte nochmal."
            yield {"type": "sentence", "text": empty}
            full_text_parts.append(empty)

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


def get_reply(user_message: str, history: list | None = None, mode: str | None = None) -> str:
    """The whole reply at once, for the non-streaming /chat endpoint — the
    same pipeline as stream_reply, just collected."""
    return next(e["full_text"] for e in stream_reply(user_message, history, mode=mode) if e["type"] == "done")
