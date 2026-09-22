from __future__ import annotations

import datetime
import os
import platform
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path

import requests

from . import browser_agent, config, confirm, last_target, memory, opencode_agent, panel, platform_utils

IS_WINDOWS = platform.system() == "Windows"

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
            "name": "visualize",
            "description": "PFLICHT bei Bitte um Diagramm, Grafik, Verlauf oder Anzeige auf dem Raster (nie nur behaupten). bars = Balken, line = Verlauf, text = ein großer Wert, list = kurze Liste.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["bars", "line", "text", "list"]},
                    "title": {"type": "string"},
                    "data": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "bars/line: \"Label=Zahl\" (z.B. \"Mo=21\"); text: ein Element; list: Zeilen (max 6)",
                    },
                },
                "required": ["type", "data"],
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
            "description": "Web-Suche mit echten Ergebnissen (Titel, Kurzbeschreibung, URL). Nur für Aktuelles oder Unsicheres (Preise, News, Öffnungszeiten); Allgemeinwissen beantwortest du selbst.",
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
            "description": "Ein Programm öffnen, z.B. Spotify, Obsidian, Terminal, Rechner, Notizen.",
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
            "name": "open_folder",
            "description": "Öffnet einen Ordner sichtbar im Finder/Explorer — nur wenn der Nutzer ihn selbst sehen will (sonst list_folder).",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Ordnername und Ort, wie gesagt",
                    }
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_folder",
            "description": "Sagt, was in einem Ordner liegt (Dateinamen als Text), ohne etwas zu öffnen. Für Dokumente, Desktop, Downloads reicht der Name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Ordnername und Ort, wie gesagt",
                    }
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Führt einen Shell-Befehl aus und liefert die Ausgabe (Systeminfos, Dateien suchen, git, Prozesse). Nicht zum Programmieren und nicht zum Bauen von Projekten — dafür opencode.",
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
            "name": "move_file",
            "description": "Verschiebt eine Datei oder einen Ordner. source = voller Pfad, destination = Zielordner oder Zielpfad.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Der vollständige Pfad der Datei, z.B. ~/Desktop/bild.png"},
                    "destination": {"type": "string", "description": "Der Zielordner, z.B. ~/Documents oder ein Zielpfad"},
                },
                "required": ["source", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Schreibt Text in eine Datei (neu oder überschrieben, fehlende Ordner werden angelegt). Für Notizen, Listen, Textdokumente — NICHT für Quellcode, den schreibt ausschließlich opencode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Zielpfad, z.B. ~/Desktop/notiz.txt"},
                    "content": {"type": "string", "description": "Der zu schreibende Inhalt"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": "Verschiebt in den Papierkorb (reversibel) — für jede Lösch-Anfrage, nie rm. Fragt selbst nach Bestätigung, ruf es direkt auf.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Datei oder Ordner, z.B. 'notiz.txt in Dokumente'",
                    },
                },
                "required": ["description"],
            },
        },
    },
    # build_project (der alte, eingebaute Bau-Durchlauf) wird dem Modell
    # bewusst NICHT mehr angeboten: Programmiert wird ausschließlich über
    # opencode, mit dem dort gewählten Modell. Solange es zwei Wege gab, hat
    # das kleine lokale Modell bei gleichem Satz mal den einen, mal den
    # anderen genommen. Der Dispatch-Eintrag unten bleibt und leitet einen
    # trotzdem erfolgenden Aufruf auf opencode um.
    {
        "type": "function",
        "function": {
            "name": "opencode",
            "description": (
                "Gibt einen Programmier-Auftrag an den lokalen Coding-Agenten "
                "weiter, der im Terminal am Projekt des Nutzers arbeitet — "
                "standardmäßig OpenCode, oder Claude Code bzw. Codex, falls der "
                "Nutzer per set_code_agent umgestellt hat. PFLICHT, sobald am "
                "Code gearbeitet werden soll: etwas programmieren, ändern, "
                "refactoren, einen Bug fixen, Tests schreiben, eine Datei im "
                "Projekt umbauen, eine komplett neue App bauen — AUSNAHMSLOS, "
                "auch ein eigener Zielordner ändert daran nichts. Der Auftrag "
                "wird wortwörtlich als Prompt eingetippt, das Terminal öffnet "
                "sich dabei automatisch. Schreib niemals selbst Code als Text "
                "oder über write_file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "Der vollständige Auftrag als klarer Satz, so wie ihn ein "
                            "Entwickler bekommen würde (z.B. 'Füge in main.py eine "
                            "Funktion hinzu, die die Konfiguration validiert')"
                        ),
                    },
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opencode_model",
            "description": (
                "Wechselt das Modell, mit dem OpenCode arbeitet (z.B. 'nimm das "
                "große Coder-Modell', 'wechsel auf GPT OSS'). EIN Aufruf genügt: "
                "gib direkt das vom Nutzer genannte Modell mit, frag die Liste "
                "nicht vorher ab. Passt der Name zu keinem Modell, bekommst du die "
                "verfügbaren zurück. Das Terminal startet dabei neu, damit die "
                "Wahl greift."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Modellname so, wie der Nutzer ihn gesagt hat (z.B. 'Devstral', 'GPT OSS')",
                    },
                },
                "required": ["model"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_code_agent",
            "description": (
                "Wechselt, WELCHER Coding-Agent Programmieraufträge (opencode-"
                "Tool) bearbeitet: OpenCode, Claude Code oder Codex ('nimm "
                "Claude Code zum Programmieren', 'wechsel auf Codex', 'benutz "
                "wieder OpenCode'). EIN Aufruf genügt: gib direkt den vom "
                "Nutzer genannten Namen mit. Ist der Agent nicht installiert, "
                "bekommst du das gesagt statt eines stillen Fehlschlags. Ein "
                "offenes Terminal startet dabei neu, damit die Wahl greift."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "description": "Agentenname so, wie der Nutzer ihn gesagt hat (z.B. 'Claude Code', 'Codex', 'OpenCode')",
                    },
                },
                "required": ["agent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_file",
            "description": (
                "Öffnet eine einzelne Datei mit dem passenden Programm — auch eine, "
                "die der Coding-Agent gerade angelegt hat (der Arbeitsordner wird "
                "mitdurchsucht). Fürs ANSCHAUEN/Öffnen zuständig, nicht opencode: "
                "das programmiert nur. Für einen Ordner open_folder, für eine "
                "Webseite open_url."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Dateiname oder Pfad, z.B. 'signal2.txt' oder '~/Desktop/notiz.txt'"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opencode_status",
            "description": (
                "Liest, was im Terminal des Coding-Agenten zuletzt passiert ist. "
                "PFLICHT, sobald der Nutzer nach dem Stand fragt ('wie weit ist "
                "er', 'ist es fertig', 'was macht er gerade') — rate den "
                "Fortschritt niemals, sondern schau nach und fasse zusammen, was "
                "dort steht."
            ),
            "parameters": {"type": "object", "properties": {}},
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
    # Windows equivalents of the above.
    r"\bformat\s+[a-z]:",
    r"\bdel\s+/[a-z]*\s+.*[a-z]:\\\\?\s*$",
    r"remove-item\s+.*-recurse\b.*[a-z]:\\\\?\s*$",
    r"\bvssadmin\s+delete\b",
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
    """Real search when a Tavily key is configured; otherwise the old
    behaviour (open a results page in the connected browser) so this still
    works, just without spoken answers, when nobody has set up a key."""
    if not config.TAVILY_API_KEY:
        return browser_agent.agent.web_search(query)

    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {config.TAVILY_API_KEY}", "Content-Type": "application/json"},
            json={"query": query, "max_results": 5, "include_answer": True},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("answer"):
            return data["answer"]
        results = data.get("results", [])
        if not results:
            return f"Keine Suchergebnisse für '{query}' gefunden."
        lines = [
            f"{r.get('title', '')}: {r.get('content', '')} ({r.get('url', '')})"
            for r in results[:5]
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"Suche fehlgeschlagen: {exc}"


def _browser_tabs() -> str:
    return browser_agent.agent.command("list_tabs", {})


def _resolve_app_macos(name: str) -> str | None:
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


def _open_app_macos(name: str) -> str:
    # _open_app below routes to _open_app_windows on Windows and never
    # reaches this function there — this is macOS-only, unconditionally.
    try:
        proc = subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=20)
        if proc.returncode == 0:
            return f"{name} geöffnet."

        resolved = _resolve_app_macos(name)
        if resolved:
            proc = subprocess.run(["open", resolved], capture_output=True, text=True, timeout=20)
            if proc.returncode == 0:
                return f"{name} geöffnet."
        return f"Konnte '{name}' nicht finden. Heißt das Programm vielleicht anders?"
    except Exception as exc:
        return f"Konnte '{name}' nicht öffnen: {exc}"


def _find_start_menu_shortcut(name: str) -> str | None:
    """Windows has no Spotlight, but every installed program gets a .lnk
    shortcut in one of the (per-user or all-users) Start Menu folders —
    close enough to a name lookup."""
    roots = [
        Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    name_lower = name.lower()
    hits = []
    for root in roots:
        if not root.is_dir():
            continue
        for f in root.rglob("*.lnk"):
            if name_lower in f.stem.lower():
                hits.append(f)
    if not hits:
        return None
    hits.sort(key=lambda p: len(p.stem))
    return str(hits[0])


def _open_app_windows(name: str) -> str:
    # os.startfile resolves anything Windows itself would know how to run:
    # an exe on PATH, a registered "App Path", a URL, a document.
    try:
        os.startfile(name)  # noqa: S606 - name comes from the LLM's tool call, not raw shell input
        return f"{name} geöffnet."
    except OSError:
        pass

    resolved = _find_start_menu_shortcut(name)
    if resolved:
        try:
            os.startfile(resolved)
            return f"{name} geöffnet."
        except OSError:
            pass

    return f"Konnte '{name}' nicht finden. Heißt das Programm vielleicht anders?"


def _open_app(name: str) -> str:
    name = name.strip()
    if not name:
        return "Welches Programm soll ich öffnen?"
    try:
        return _open_app_windows(name) if IS_WINDOWS else _open_app_macos(name)
    except Exception as exc:
        return f"Konnte '{name}' nicht öffnen: {exc}"


# Common macOS home folders, keyed by every German/English word a spoken
# request might use for them.
_LOCATION_ALIASES = {
    "desktop": "~/Desktop", "schreibtisch": "~/Desktop",
    "dokumente": "~/Documents", "documents": "~/Documents", "papiere": "~/Documents",
    "downloads": "~/Downloads",
}

# Filler words stripped out to isolate the actual folder name from a spoken
# request like "den Ordner Projekte auf dem Desktop".
_FOLDER_STOPWORDS = {
    "den", "die", "das", "der", "dem", "einen", "ordner", "order", "verzeichnis",
    "folder", "auf", "im", "in", "vom", "von", "meinem", "meiner", "mir",
    *_LOCATION_ALIASES.keys(),
}


def _resolve_fs_path(description: str, *, require_dir: bool) -> tuple[Path | None, str]:
    """Resolve a spoken file/folder reference to a real path deterministically.

    Vision-based clicking is approximate and struggles with small desktop
    icons; a named request ("Ordner Projekte auf dem Desktop") has an exact
    answer on disk, so this resolves it directly instead of guessing pixel
    coordinates. Returns (path or None, the resolved/attempted name) —
    shared by every tool that takes a spoken folder/file reference, so they
    all fail the same way.
    """
    text = (description or "").strip()
    if not text:
        return None, ""

    lowered = text.lower()
    base = Path.home() / "Desktop"
    for word, path in _LOCATION_ALIASES.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            base = Path(os.path.expanduser(path))
            break

    # "." kept so a spoken filename with an extension ("notiz.txt") survives
    # as one token instead of splitting into "notiz" + "txt".
    words = [w for w in re.findall(r"[\wÄÖÜäöüß.-]+", text) if w.lower() not in _FOLDER_STOPWORDS]
    name = " ".join(words).strip()

    target = base if not name else base / name
    if not target.exists() and base.is_dir():
        matches = [p for p in base.iterdir() if p.name.lower() == name.lower()]
        if matches:
            target = matches[0]

    if not target.exists() or (require_dir and not target.is_dir()):
        return None, name or base.name
    last_target.remember(target)
    return target, target.name


def _resolve_folder_path(description: str) -> tuple[Path | None, str]:
    return _resolve_fs_path(description, require_dir=True)


def _open_folder(description: str) -> str:
    target, name = _resolve_folder_path(description)
    if not (description or "").strip():
        return "Welchen Ordner soll ich öffnen?"
    if target is None:
        return f"Konnte den Ordner '{name}' nicht finden."

    try:
        if platform_utils.is_windows():
            subprocess.run(["explorer", str(target)], timeout=10)
        elif platform_utils.is_macos():
            subprocess.run(["open", str(target)], check=True, timeout=10)
        else:
            subprocess.run(["xdg-open", str(target)], timeout=10)
    except Exception as exc:
        return f"Konnte '{target.name}' nicht öffnen: {exc}"
    return f"Ordner '{target.name}' geöffnet."


def _list_folder(description: str) -> str:
    """Return a folder's contents as text, without opening anything.

    Answers "was liegt in Ordner X" honestly — open_folder only opens
    Finder/Explorer and tells Jarvis nothing back, which was leading to
    hallucinated "der Ordner existiert nicht" claims for folders that were
    never actually checked.
    """
    if not (description or "").strip():
        return "Welchen Ordner soll ich mir ansehen?"
    target, name = _resolve_folder_path(description)
    if target is None:
        return f"Konnte den Ordner '{name}' nicht finden."

    entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
    if not entries:
        return f"'{target.name}' ist leer."
    shown = [f"{p.name}/" if p.is_dir() else p.name for p in entries[:40]]
    listing = ", ".join(shown)
    if len(entries) > 40:
        listing += f", … und {len(entries) - 40} weitere"
    return f"Inhalt von '{target.name}': {listing}"


def _run_shell(command: str) -> str:
    if _is_blocked(command):
        return "Diesen Befehl führe ich nicht aus, der könnte das System beschädigen."
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            # subprocess with text=True decodes the child's output using
            # the OS locale's preferred encoding by default — cp1252 on
            # German Windows — which either mangles or (for a genuinely
            # invalid byte sequence) raises on any UTF-8 output, and a lot
            # of modern CLI tools (git, npm, python itself) default to
            # UTF-8 regardless of the console's codepage.
            encoding="utf-8",
            errors="replace",
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
    """Wird dem Modell nicht mehr angeboten (siehe TOOL_SCHEMAS), kann aber
    weiterhin aus einem halluzinierten Namen heraus ankommen. Programmiert
    wird ausschließlich über opencode, also landet auch das dort — mit dem
    Ort im Auftragstext, damit die Angabe nicht verloren geht."""
    task = str(description or "").strip()
    where = str(location or "").strip()
    if where:
        task = f"{task} (im Ordner {where})" if task else f"Arbeite im Ordner {where}"
    return _opencode(task)


def _move_file(source: str, destination: str) -> str:
    """Move a file or folder; safer than a raw `mv` via run_shell."""
    import shutil

    src = Path(os.path.expanduser((source or "").strip().strip("\"'")))
    dst = Path(os.path.expanduser((destination or "").strip().strip("\"'")))

    if not src.exists():
        return f"Konnte '{source}' nicht finden."

    # "in die Dokumente" → move into the folder, keeping the filename.
    if dst.is_dir():
        dst = dst / src.name
    else:
        # A destination like "~/Documents" that doesn't exist yet is almost
        # always meant as the Documents folder, not a renamed file.
        if dst.suffix == "" and not dst.exists():
            dst = dst / src.name

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"'{src.name}' nach '{dst.parent}' verschoben."


def _delete_path(description: str) -> str:
    """Ask for confirmation, then move a file or folder to the Trash.

    Two things that used to go wrong here: a raw `rm -rf` run through
    run_shell silently no-ops on a missing target (that's what -f means),
    with the exact same empty output and exit code as a real deletion —
    Jarvis once confidently claimed to have deleted a folder that was never
    there. And the confirm/execute split used to be pure prose: the model
    asked "Soll ich das löschen?" in plain text, then had to correctly
    remember and re-resolve what "das" meant when the user said "ja" a turn
    later — which a small local model reliably failed at.

    Both are fixed the same way: nothing here is inferred from conversation
    text. send2trash raises for a path that doesn't exist (existence is
    checked again after, too), and the confirmation itself is registered as
    real state via confirm.propose — resolved deterministically in code the
    moment the user answers, never re-derived by the model.
    """
    if not (description or "").strip():
        return "Was genau soll ich löschen?"

    target, name = _resolve_fs_path(description, require_dir=False)
    if target is None:
        return f"Konnte '{name}' nicht finden — da ist nichts zu löschen."

    def _do_delete() -> str:
        try:
            from send2trash import send2trash
            send2trash(str(target))
        except Exception as exc:
            return f"Konnte '{target.name}' nicht löschen: {exc}"
        if target.exists():
            return f"'{target.name}' konnte nicht in den Papierkorb verschoben werden."
        return f"'{target.name}' wurde in den Papierkorb verschoben."

    return confirm.propose(f"Soll ich '{target.name}' wirklich in den Papierkorb verschieben?", _do_delete)


# Dateiendungen, hinter denen Quellcode steckt. Der Nutzer will, dass
# programmiert ausschließlich über opencode wird — ohne diese Sperre schrieb
# das Modell den Code trotz gegenteiliger Beschreibung einfach selbst per
# write_file (live beobachtet: ~/Desktop/zahlen.py).
_CODE_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css",
    ".scss", ".java", ".kt", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs",
    ".rb", ".php", ".swift", ".sh", ".bat", ".ps1", ".sql", ".vue", ".svelte",
}


def _write_file(path: str, content: str) -> str:
    target = Path(os.path.expanduser((path or "").strip().strip("\"'")))
    if not str(target):
        return "Welche Datei soll ich schreiben?"
    if target.suffix.lower() in _CODE_SUFFIXES:
        # Ein bloßes Verweigern reichte nicht: das Modell meldete danach
        # trotzdem Vollzug und rief opencode NICHT auf — die Datei entstand
        # nirgends (live beobachtet). Also hier direkt weiterreichen, damit
        # die Arbeit wirklich in opencode und bei dessen Modell landet; der
        # mitgelieferte Entwurf geht nur als Beschreibung mit, nicht als
        # fertige Datei.
        draft = (content or "").strip()
        task = f"Schreibe die Datei {target}."
        if draft:
            task += " Sie soll das hier leisten:\n\n" + draft
        return _opencode(task)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Same cp1252-vs-UTF-8 trap as elsewhere in this file (see coder.py):
    # without an explicit encoding, any character outside the Windows
    # locale's codepage — an emoji, a checkmark, non-Latin text — raises
    # UnicodeEncodeError instead of writing.
    target.write_text(content or "", encoding="utf-8")
    return f"Datei geschrieben: {target} ({len(content or '')} Zeichen)."


def _visualize(vtype: str, title: str, data) -> str:
    """Schickt eine Grafik an den Sprachmodus (frontend zeichnet sie auf das
    Raster). Die Daten werden hier bereinigt, damit das Frontend nur
    saubere, begrenzte Werte bekommt — die Eingabe kommt vom Modell."""
    if vtype not in ("bars", "line", "text", "list"):
        return "Unbekannter Typ. Erlaubt: bars, line, text, list."
    items = [str(x).strip() for x in (data if isinstance(data, list) else [data]) if str(x).strip()]
    if not items:
        return "Keine Daten zum Anzeigen."
    if vtype in ("bars", "line"):
        points = []
        for i, raw in enumerate(items[:12]):
            label, _, num = raw.rpartition("=")
            if not label and not _:
                label, num = str(i + 1), raw
            try:
                points.append({"label": label.strip()[:14] or str(i + 1), "value": float(num.replace(",", ".").strip())})
            except ValueError:
                return f'"{raw}" ist keine Zahl. Format: "Label=Zahl".'
        payload = points
    elif vtype == "text":
        payload = items[0][:40]
    else:
        payload = [x[:60] for x in items[:6]]
    panel.push("viz", vtype=vtype, title=(title or "")[:60], data=payload)
    return "Auf dem Raster angezeigt."


def _opencode(task: str) -> str:
    """Reicht einen Programmier-Auftrag an die OpenCode-TUI weiter. Getippt
    wird im Frontend (das Terminal ist ein xterm im Sprachmodus, der PTY
    hängt am Browser-Socket) — hier wird der Auftrag nur sauber normalisiert
    und über den Panel-Kanal dorthin geschickt."""
    task = " ".join(str(task or "").split())
    if not task:
        return "Kein Auftrag angegeben."
    # Zeilenumbrüche sind oben schon weg: ein "\n" im PTY wäre ein Absenden
    # mitten im Satz, OpenCode bekäme nur das erste Fragment.
    panel.push("opencode", task=task[:2000])
    return f"An OpenCode weitergegeben: {task}"


# Dateien, die das Betriebssystem beim Öffnen AUSFÜHREN würde. "Zeig mir die
# Datei" darf kein Skript starten, also gehen die in den Editor.
_RUNNABLE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ps1", ".bat", ".cmd", ".sh", ".vbs", ".jar"}


def _open_in_editor(target: Path) -> None:
    if shutil.which("code"):
        subprocess.run(["code", str(target)], timeout=30, capture_output=True)
    elif platform_utils.is_windows():
        subprocess.run(["notepad", str(target)], timeout=30, capture_output=True)
    elif platform_utils.is_macos():
        subprocess.run(["open", "-t", str(target)], timeout=30, capture_output=True)
    else:
        subprocess.run(["xdg-open", str(target)], timeout=30, capture_output=True)


def _open_file(path: str) -> str:
    """Öffnet eine Datei mit dem Standardprogramm. Eigenes Tool, weil es nur
    open_url/open_app/open_folder gab — eine einzelne Datei konnte Jarvis gar
    nicht öffnen und reichte die Bitte deshalb an opencode weiter, das sie
    nicht öffnet."""
    raw = (path or "").strip().strip("\"'")
    if not raw:
        return "Welche Datei soll ich öffnen?"
    target = Path(os.path.expanduser(raw))
    if not target.is_absolute() or not target.exists():
        # Dateien, die opencode gerade angelegt hat, liegen in dessen
        # Arbeitsordner — dort zuerst nachsehen, bevor aufgegeben wird.
        for base in (Path.cwd(), Path(opencode_agent.get_code_dir()), platform_utils.desktop_dir(), Path.home()):
            candidate = base / raw
            if candidate.exists():
                target = candidate
                break
    if not target.exists():
        return f"Die Datei {raw} finde ich nicht."
    try:
        if target.suffix.lower() in _RUNNABLE_SUFFIXES:
            # "Öffne zahlen.py" darf das Skript NICHT ausführen: unter Windows
            # startet os.startfile eine .py/.bat/.ps1 einfach, statt sie zu
            # zeigen. Solche Dateien landen deshalb im Editor.
            _open_in_editor(target)
        elif platform_utils.is_windows():
            os.startfile(str(target))  # noqa: S606 - genau dafür gedacht
        elif platform_utils.is_macos():
            subprocess.run(["open", str(target)], timeout=30, capture_output=True)
        else:
            subprocess.run(["xdg-open", str(target)], timeout=30, capture_output=True)
    except Exception as exc:  # noqa: BLE001 - Öffnen kann am OS scheitern
        return f"Konnte {target} nicht öffnen: {exc}"
    last_target.remember(target)
    return f"Geöffnet: {target}"


def _opencode_status() -> str:
    text = opencode_agent.recent_output(1800)
    if not text:
        return "Im Coding-Terminal ist noch nichts passiert (es läuft gerade keins)."
    return "Letzte Ausgabe im Coding-Terminal:\n" + text


def _opencode_model(name: str) -> str:
    """Stellt das Modell um, mit dem opencode arbeitet. Die Wahl landet in der
    opencode-Konfiguration, die nur beim Start der TUI gelesen wird — deshalb
    schickt der Panel-Push das Frontend dazu, das Terminal neu zu starten."""
    # Alle Modelle, die opencode kennt — auch seine eigenen kostenlosen
    # (opencode/big-pickle und Co.), nicht nur die aus LM Studio.
    available = opencode_agent.list_all_models()
    if not available:
        return "OpenCode meldet gerade keine Modelle."
    chosen = opencode_agent.resolve_model(name, available)
    if not chosen:
        return f'Kein Modell gefunden, das zu "{name}" passt. Verfügbar: ' + ", ".join(available[:10])
    opencode_agent.set_selected_model(chosen)
    lm_models = opencode_agent.list_models()
    if lm_models:
        opencode_agent.ensure_provider_config(lm_models, chosen)
    panel.push("opencode_model", model=chosen)
    return f"OpenCode arbeitet ab jetzt mit {chosen}."


def _set_code_agent(name: str) -> str:
    """Stellt um, welcher Coding-Agent das opencode-Tool bedient. Landet in
    derselben Konfiguration, die start_tty() beim Start der PTY-TUI liest —
    ein offenes Terminal muss also neu starten, damit die Wahl greift
    (genau wie beim Modellwechsel oben, siehe _opencode_model)."""
    chosen = opencode_agent.resolve_agent(name)
    if not chosen:
        available = ", ".join(a["name"] for a in opencode_agent.list_code_agents())
        return f'Kein Coding-Agent gefunden, der zu "{name}" passt. Verfügbar: {available}.'
    display_name = opencode_agent.CODE_AGENTS[chosen]
    if not opencode_agent.agent_available(chosen):
        return f"{display_name} ist auf diesem Rechner nicht installiert oder nicht im PATH."
    opencode_agent.set_code_agent(chosen)
    panel.push("code_agent", agent=chosen, name=display_name)
    return f"Programmieraufträge gehen ab jetzt an {display_name}."


DISPATCH = {
    "get_weather": lambda a: _get_weather(a.get("city", "")),
    "get_time": lambda a: _get_time(),
    "add_note": lambda a: _add_note(a.get("text", "")),
    "visualize": lambda a: _visualize(a.get("type", ""), a.get("title", ""), a.get("data", [])),
    "opencode": lambda a: _opencode(a.get("task", "")),
    "opencode_model": lambda a: _opencode_model(a.get("model", "")),
    "set_code_agent": lambda a: _set_code_agent(a.get("agent", "")),
    "opencode_status": lambda a: _opencode_status(),
    "open_file": lambda a: _open_file(a.get("path", "")),
    "open_url": lambda a: _open_url(a.get("url", "")),
    "youtube_search": lambda a: _youtube_search(a.get("query", "")),
    "web_search": lambda a: _web_search(a.get("query", "")),
    "browser_tabs": lambda a: _browser_tabs(),
    "open_app": lambda a: _open_app(a.get("name", "")),
    "open_folder": lambda a: _open_folder(a.get("description", "")),
    "list_folder": lambda a: _list_folder(a.get("description", "")),
    "run_shell": lambda a: _run_shell(a.get("command", "")),
    "build_project": lambda a: _build_project(a.get("location", ""), a.get("description", "")),
    "move_file": lambda a: _move_file(a.get("source", ""), a.get("destination", "")),
    "write_file": lambda a: _write_file(a.get("path", ""), a.get("content", "")),
    "delete_path": lambda a: _delete_path(a.get("description", "")),
}


def call_tool(name: str, arguments: dict) -> str:
    handler = DISPATCH.get(name)
    if handler is None:
        return f"Unbekanntes Tool: {name}"
    action_id = f"tool-{datetime.datetime.now().strftime('%H%M%S%f')}"
    panel.push("action", id=action_id, action=name, status="läuft", target=arguments)
    try:
        result = handler(arguments)
        failed = result.lower().startswith(("fehler", "konnte", "unbekannt", "browser-agent nicht verbunden", "browser-aktion fehlgeschlagen"))
        panel.push("action", id=action_id, action=name, status="fehlgeschlagen" if failed else "erfolgreich", detail=result)
        return result
    except Exception as exc:
        result = f"Fehler beim Ausführen von {name}: {exc}"
        panel.push("action", id=action_id, action=name, status="fehlgeschlagen", detail=result)
        return result
