from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path

import requests

from . import browser_agent, coder, config, keyboard, memory, mouse, panel, platform_utils, vision

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Aktuelles Wetter für eine Stadt abrufen.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "Stadtname, z.B. Hamburg"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": (
                "Aktuelles Datum, Uhrzeit UND Wochentag abrufen. Auch bei 'welcher Tag "
                "ist heute', 'welcher Wochentag' nutzen — nicht den Kalender öffnen."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_note",
            "description": (
                "Schreibt eine Notiz dauerhaft in die Notizdatei. Nutze das immer, wenn "
                "der Nutzer 'notiere', 'merk dir', 'schreib auf' oder 'erinnere mich' "
                "sagt. Ohne diesen Aufruf wird nichts gespeichert."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Der Notiztext"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Eine Webseite im Browser öffnen.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Vollständige URL oder Domain"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_search",
            "description": "Öffnet die YouTube-Ergebnisliste für eine Suchanfrage im verbundenen Chrome.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Öffnet eine Web-Ergebnisliste für eine Suchanfrage im verbundenen Chrome.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_tabs",
            "description": "Listet die offenen Chrome-Tabs des verbundenen Browser-Agenten auf.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": (
                "Ein Programm auf dem Computer öffnen, z.B. Spotify, Obsidian, Terminal, "
                "Visual Studio Code, Discord, Rechner, Notizen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Der Programmname exakt so, wie der Nutzer ihn gesagt hat. "
                            "Übersetze ihn nicht und rate keinen englischen Namen — "
                            "deutsche Namen wie 'Rechner' werden automatisch aufgelöst."
                        ),
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            # NOT named see_screen. Under that name this schema tripped a
            # real LM Studio bug: the reply's first tokens came back mangled
            # ("IGHLICHScreen...") for 10 out of 10 attempts on its own
            # trigger phrases, with no tool call. Measured cause was the tool
            # NAME itself, not the description or parameters — renaming it
            # dropped the failure rate to 0 out of 30. Keep the name free of
            # "screen" unless you re-measure.
            "name": "look_at_display",
            "description": (
                "Schaut auf den Bildschirm des Nutzers und beschreibt oder analysiert was "
                "dort zu sehen ist. Nutze dieses Tool bei jeder Frage zum aktuellen "
                "Bildschirminhalt, zum Beispiel schau mal, guck mal, was siehst du, was "
                "zeigt der Bildschirm, oder bei Hilfe zu einem sichtbaren Fehler."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Was am Bildschirm herausgefunden werden soll",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Einen Shell-Befehl auf dem Computer ausführen und die Ausgabe bekommen. "
                "Für Systeminfos, Dateien suchen, Ordner anlegen, git, Prozesse prüfen. "
                "NICHT für das Bauen von Projekten — dafür build_project nutzen."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Der Shell-Befehl"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_project",
            "description": (
                "Etwas programmieren: eine App, Website, ein Skript oder Tool. Baut das "
                "vollständig in einem Ordner auf dem Computer und öffnet es danach. "
                "WICHTIG: 'location' musst du vorher beim Nutzer erfragen — rate den "
                "Ordner niemals selbst."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Ordner, z.B. 'Desktop/Rechner' oder '~/Projekte/todo-app'",
                    },
                    "description": {
                        "type": "string",
                        "description": "Ausführliche Beschreibung, was gebaut werden soll",
                    },
                },
                "required": ["location", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_on_screen",
            "description": (
                "Zeigt längeren Text im Interface an, damit der Nutzer ihn lesen kann: "
                "Erklärungen, Code, Listen, Tabellen, Vergleiche. Nutze das immer bei "
                "'erklär mir', 'zeig mir', 'wie funktioniert', 'schreib mir', wenn die "
                "Antwort länger als drei Sätze wäre. Der Nutzer bekommt deine Antwort "
                "nur vorgelesen — langen Text sieht er ausschließlich über dieses Tool. "
                "Den ganzen Inhalt in 'content' übergeben, nicht in die Sprachantwort."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Überschrift"},
                    "content": {"type": "string", "description": "Der Inhalt (Markdown erlaubt)"},
                    "language": {
                        "type": "string",
                        "description": "Bei Code die Sprache, z.B. python. Sonst weglassen.",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_screenshot",
            "description": (
                "Macht ein Bildschirmfoto und speichert es als Datei. Nutze das immer, "
                "wenn der Nutzer einen Screenshot machen oder speichern will. Nicht "
                "verwechseln mit look_at_display, das nur anschaut ohne zu speichern."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Zielordner, zum Beispiel Desktop. Leer lassen fuer Desktop.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": (
                "Tippt Text auf der Tastatur in das gerade aktive Fenster. Nutze das, "
                "wenn der Nutzer etwas schreiben oder eingeben lassen will."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Der zu tippende Text"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": (
                "Drueckt eine Taste oder Tastenkombination, zum Beispiel Enter, Escape, "
                "cmd+s zum Speichern oder cmd+w zum Schliessen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Die Taste, zum Beispiel enter, escape, cmd+s",
                    }
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_on_screen",
            "description": (
                "Schaut auf den Bildschirm, findet ein sichtbares Element anhand seiner "
                "Beschreibung und klickt darauf — z.B. 'den Speichern-Button', 'das "
                "Suchfeld', 'den ersten Link'. Nutze das, wenn der Nutzer dich bittet, "
                "etwas auf dem Bildschirm anzuklicken. Die Zielerkennung ist ungefähr, "
                "nicht pixelgenau — bei kleinen oder dicht beieinanderliegenden "
                "Elementen kann es danebengehen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Was angeklickt werden soll, so wie der Nutzer es beschrieben hat",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["click", "double_click", "right_click", "move"],
                        "description": "Standardmäßig 'click'",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_action",
            "description": (
                "Bewegt die Maus zu exakten Bildschirm-Koordinaten oder zieht von einer "
                "Koordinate zu einer anderen. Nur nutzen, wenn die Koordinaten bereits "
                "bekannt sind (z.B. aus einer vorherigen click_on_screen-Antwort) — sonst "
                "click_on_screen verwenden, das die Position selbst herausfindet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["move", "click", "drag", "scroll"]},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "x2": {"type": "number", "description": "Zielpunkt, nur für 'drag'"},
                    "y2": {"type": "number", "description": "Zielpunkt, nur für 'drag'"},
                    "button": {"type": "string", "enum": ["left", "right"]},
                },
                "required": ["action"],
            },
        },
    },
]

# ---------------------------------------------------------------------------

# Commands that could wipe the machine or hand over the whole box. Jarvis is
# voice-driven and the model behind it is small, so a misheard sentence must
# not be able to turn into a destructive command. Everything else is allowed
# — this is the user's own machine and the point is to be useful.
_BLOCKED = [
    r"\brm\s+(-[a-z]*\s+)*-?[a-z]*[rf][a-z]*\s+/(\s|$)",
    r"\bmkfs\b",
    r"\bdd\s+.*of=/dev/",
    r":\(\)\s*\{.*\}\s*;\s*:",          # fork bomb
    r"\bshutdown\b|\breboot\b",
    r"\bsudo\b",
    r">\s*/dev/(disk|sd)",
    r"\bdiskutil\s+(erase|reformat)",
    r"\bchmod\s+-R\s+777\s+/(\s|$)",
]


def _is_blocked(command: str) -> bool:
    lowered = command.lower()
    return any(re.search(p, lowered) for p in _BLOCKED)


def _get_weather(city: str) -> str:
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "de"},
            timeout=10,
        ).json()
        results = geo.get("results")
        if not results:
            return f"Konnte die Stadt '{city}' nicht finden."
        lat, lon = results[0]["latitude"], results[0]["longitude"]
        resolved_name = results[0]["name"]

        weather = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            },
            timeout=10,
        ).json()
        current = weather.get("current", {})
        return (
            f"In {resolved_name} sind es aktuell {current.get('temperature_2m')}°C, "
            f"gefühlt {current.get('apparent_temperature')}°C, "
            f"bei {current.get('wind_speed_10m')} km/h Wind."
        )
    except Exception as exc:
        return f"Wetterabfrage fehlgeschlagen: {exc}"


def _get_time() -> str:
    return datetime.datetime.now().strftime("%A, %d.%m.%Y %H:%M")


def _add_note(text: str) -> str:
    return memory.add_note(text)


def _open_url(url: str) -> str:
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    if browser_agent.agent.connected():
        result = browser_agent.agent.command("open_url", {"url": url})
        if not result.startswith("Browser-Agent nicht verbunden"):
            return result
    webbrowser.open(url)
    panel.push("link", title="Geöffnet", url=url)
    return f"{url} geöffnet."


def _youtube_search(query: str) -> str:
    return browser_agent.agent.youtube_search(query)


def _web_search(query: str) -> str:
    return browser_agent.agent.web_search(query)


def _browser_tabs() -> str:
    return browser_agent.agent.command("list_tabs", {})


def _resolve_app(name: str) -> str | None:
    """Find an app bundle by the name a German speaker would actually say.

    `open -a Rechner` fails because the bundle is Calculator.app — the German
    name only exists as a localized display name. Spotlight indexes those, so
    it can map what the user said onto the real bundle.
    """
    if not platform_utils.is_macos():
        return None
    query = (
        "kMDItemContentType == 'com.apple.application-bundle' && "
        f"kMDItemDisplayName == '{name}*'c"
    )
    try:
        proc = subprocess.run(["mdfind", query], capture_output=True, text=True, timeout=15)
        hits = [h for h in proc.stdout.strip().split("\n") if h.strip()]
        if not hits:
            return None
        # Prefer real install locations over caches and app translocations.
        hits.sort(key=lambda p: (not p.startswith(("/Applications", "/System/Applications")), len(p)))
        return hits[0]
    except Exception:
        return None


def _open_app(name: str) -> str:
    name = name.strip()
    if not name:
        return "Welches Programm soll ich öffnen?"

    try:
        if platform_utils.is_windows():
            aliases = {
                "rechner": "calc.exe", "taschenrechner": "calc.exe", "notizen": "notepad.exe",
                "editor": "notepad.exe", "explorer": "explorer.exe", "datei explorer": "explorer.exe",
            }
            target = aliases.get(name.lower(), name)
            # A PowerShell single-quoted literal keeps a spoken app name from
            # becoming PowerShell syntax.
            safe_target = "'" + target.replace("'", "''") + "'"
            proc = subprocess.run(
                platform_utils.powershell(f"Start-Process -FilePath {safe_target}"),
                capture_output=True, text=True, timeout=20,
            )
            if proc.returncode == 0:
                return f"{name} geöffnet."
            return f"Konnte '{name}' nicht finden. Heißt das Programm vielleicht anders?"

        proc = subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=20)
        if proc.returncode == 0:
            return f"{name} geöffnet."

        resolved = _resolve_app(name)
        if resolved:
            proc = subprocess.run(["open", resolved], capture_output=True, text=True, timeout=20)
            if proc.returncode == 0:
                return f"{name} geöffnet."
        return f"Konnte '{name}' nicht finden. Heißt das Programm vielleicht anders?"
    except Exception as exc:
        return f"Konnte '{name}' nicht öffnen: {exc}"


def _run_shell(command: str) -> str:
    if _is_blocked(command):
        return "Diesen Befehl führe ich nicht aus, der könnte das System beschädigen."
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(Path.home()),
        )
    except subprocess.TimeoutExpired:
        return "Der Befehl hat zu lange gedauert und wurde abgebrochen."
    except Exception as exc:
        return f"Befehl fehlgeschlagen: {exc}"

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    combined = out or err or "(keine Ausgabe)"

    # Long output belongs on screen, not in Jarvis's mouth.
    if len(combined) > 400:
        panel.push("code", title=f"$ {command}", language="text", text=combined[:20000])
        head = combined[:300].replace("\n", " ")
        return f"Ausgabe ist lang, ich hab sie dir angezeigt. Anfang: {head}"
    return combined


def _build_project(location: str, description: str) -> str:
    return coder.start_build(location, description)


def _show_on_screen(title: str, content: str, language: str = "") -> str:
    if language:
        panel.push("code", title=title, language=language, text=content)
    else:
        panel.push("markdown", title=title, text=content)
    return f"Ich hab '{title}' im Interface angezeigt."


def _click_on_screen(description: str, action: str = "click") -> str:
    if not description.strip():
        return "Was soll ich anklicken?"
    return mouse.click_on_screen(description, action or "click")


def _mouse_action(a: dict) -> str:
    action = a.get("action", "")
    w, h = mouse.screen_size()

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    x = clamp(float(a.get("x", 0)), 0, w)
    y = clamp(float(a.get("y", 0)), 0, h)

    if action == "move":
        # osascript's "click at" is the only reliable primitive here (see
        # mouse.py), so a bare hover-move isn't available — approximate
        # with a click, which is what the user almost always actually wants.
        mouse.click(x, y)
        return f"Bei ({int(x)}, {int(y)}) geklickt (reines Bewegen wird nicht unterstützt)."
    if action == "click":
        mouse.click(x, y, button=a.get("button", "left"))
        return f"Bei ({int(x)}, {int(y)}) geklickt."
    if action == "drag":
        x2 = clamp(float(a.get("x2", x)), 0, w)
        y2 = clamp(float(a.get("y2", y)), 0, h)
        mouse.drag(x, y, x2, y2)
        return f"Von ({int(x)}, {int(y)}) nach ({int(x2)}, {int(y2)}) gezogen."
    if action == "scroll":
        mouse.scroll(dy=int(a.get("y", 0)))
        return "Gescrollt."
    return f"Unbekannte Mausaktion: {action}"


DISPATCH = {
    "get_weather": lambda a: _get_weather(a.get("city", "")),
    "get_time": lambda a: _get_time(),
    "add_note": lambda a: _add_note(a.get("text", "")),
    "open_url": lambda a: _open_url(a.get("url", "")),
    "youtube_search": lambda a: _youtube_search(a.get("query", "")),
    "web_search": lambda a: _web_search(a.get("query", "")),
    "browser_tabs": lambda a: _browser_tabs(),
    "open_app": lambda a: _open_app(a.get("name", "")),
    "look_at_display": lambda a: vision.look_at_screen(a.get("question", "")),
    "run_shell": lambda a: _run_shell(a.get("command", "")),
    "build_project": lambda a: _build_project(a.get("location", ""), a.get("description", "")),
    "show_on_screen": lambda a: _show_on_screen(
        a.get("title", "Info"), a.get("content", ""), a.get("language", "")
    ),
    "click_on_screen": lambda a: _click_on_screen(a.get("description", ""), a.get("action", "click")),
    "mouse_action": _mouse_action,
    "save_screenshot": lambda a: vision.save_screenshot(a.get("location", "")),
    "type_text": lambda a: keyboard.type_text(a.get("text", "")),
    "press_key": lambda a: keyboard.press_key(a.get("key", ""), a.get("modifiers")),
}


def call_tool(name: str, arguments: dict) -> str:
    handler = DISPATCH.get(name)
    if handler is None:
        return f"Unbekanntes Tool: {name}"
    action_id = f"tool-{datetime.datetime.now().strftime('%H%M%S%f')}"
    panel.push("action", id=action_id, action=name, status="läuft", target=arguments)
    try:
        result = handler(arguments)
        failed = result.lower().startswith(("fehler", "konnte", "unbekannt", "browser-aktion fehlgeschlagen", "screenshot fehlgeschlagen", "tastendruck fehlgeschlagen", "tippen fehlgeschlagen"))
        panel.push("action", id=action_id, action=name, status="fehlgeschlagen" if failed else "erfolgreich", detail=result)
        return result
    except Exception as exc:
        result = f"Fehler beim Ausführen von {name}: {exc}"
        panel.push("action", id=action_id, action=name, status="fehlgeschlagen", detail=result)
        return result
