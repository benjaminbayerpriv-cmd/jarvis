from __future__ import annotations

import ast
import datetime
import json
import math
import operator
import os
import platform
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

import requests

from . import alpaca_client, browser_agent, config, confirm, jarvis_browser, last_target, memory, opencode_agent, panel, platform_utils

IS_WINDOWS = platform.system() == "Windows"
_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Aktuelles Wetter abrufen. Ohne genannte Stadt sofort ohne city aufrufen — dann gilt der Wohnort des Nutzers, nicht nachfragen.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "Stadtname, z.B. Hamburg; weglassen, wenn keine Stadt genannt wurde"}},
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
            "name": "calculate",
            "description": (
                "Berechnet einen mathematischen Ausdruck exakt (+, -, *, /, ^, Klammern, "
                "Prozent). Nutze das IMMER bei jeder Rechnung, egal wie einfach — auch "
                "'acht geteilt durch zwei' oder Kopfrechnen —, statt das Ergebnis selbst "
                "zu erfinden. Ein Sprachmodell rechnet unzuverlässig, besonders bei "
                "Division; nur dieses Tool liefert das echte Ergebnis. Wandle Zahlwörter "
                "in Ziffern und 'geteilt durch'/'durch' in '/', 'mal' in '*', 'hoch' in "
                "'^' um, z.B. 'acht geteilt durch zwei' -> '8/2'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Reiner Rechenausdruck, z.B. '8/2' oder '(3+4)*2'",
                    }
                },
                "required": ["expression"],
            },
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
            "name": "browser_open",
            "description": (
                "Öffnet eine Seite in Jarvis' EIGENEM Browser (nicht im Chrome des Nutzers) und liefert die nummerierte "
                "Elementliste. Für Recherche und Bedienen von Webseiten; open_url nur, wenn der Nutzer die Seite selbst sehen will."
            ),
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_look",
            "description": "Aktuelle Seite im Jarvis-Browser: nummerierte Liste der sichtbaren Buttons, Links und Felder. Immer zuerst aufrufen, bevor du klickst oder tippst.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Klickt das Element mit dieser Nummer aus der letzten Elementliste (browser_look/browser_open). Nie Koordinaten raten.",
            "parameters": {"type": "object", "properties": {"nr": {"type": "integer"}}, "required": ["nr"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Tippt Text in das Feld mit dieser Nummer. enter=true schickt danach Enter (Suche absenden). Passwort- und Zahlungsfelder fasst Jarvis nie an.",
            "parameters": {
                "type": "object",
                "properties": {"nr": {"type": "integer"}, "text": {"type": "string"}, "enter": {"type": "boolean"}},
                "required": ["nr", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_select",
            "description": "Wählt in der Auswahlliste mit dieser Nummer eine Option (Text oder Wert).",
            "parameters": {
                "type": "object",
                "properties": {"nr": {"type": "integer"}, "value": {"type": "string"}},
                "required": ["nr", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scrollt die Seite im Jarvis-Browser: unten, oben, anfang oder ende. Danach neue Elementliste.",
            "parameters": {"type": "object", "properties": {"direction": {"type": "string"}}, "required": ["direction"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_read",
            "description": "Liest den Text der aktuellen Seite im Jarvis-Browser (Artikel, Ergebnisse), um daraus zu antworten.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_back",
            "description": "Geht im Jarvis-Browser eine Seite zurück.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "alpaca_data",
            "description": "Echte Börsendaten von Alpaca: Kurs, Kerzen, Tagesübersicht, Nachrichten, Gewinner/Verlierer, meistgehandelte Aktien, Optionen, Krypto (Symbol wie BTC/USD). Für jede Frage nach Kursen oder Marktdaten — nie schätzen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["quote", "snapshot", "bars", "trades", "news", "movers", "most_active", "option_chain"],
                        "description": "quote = aktueller Kurs, snapshot = Tagesübersicht, bars = Kursverlauf",
                    },
                    "symbols": {"type": "string", "description": "Ticker, mehrere mit Komma, z.B. 'NVDA,AAPL'"},
                    "timeframe": {"type": "string", "description": "Nur bars: 1Min, 5Min, 15Min, 1Hour, 1Day, 1Week, 1Month"},
                    "start": {"type": "string", "description": "Nur bars: Beginn, z.B. 2026-01-01"},
                    "end": {"type": "string", "description": "Nur bars: Ende, z.B. 2026-02-01"},
                    "limit": {"type": "string", "description": "Anzahl Einträge"},
                },
                "required": ["kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "alpaca_account",
            "description": "Liest das Alpaca-Depot: Kontostand, Positionen, Orders, Kontobewegungen, Depotverlauf, ob die Börse offen ist, Handelstage, Infos zu einem Wertpapier, Watchlists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "what": {
                        "type": "string",
                        "enum": ["account", "positions", "orders", "activities", "portfolio_history", "clock", "calendar", "asset", "watchlists"],
                    },
                    "symbol": {"type": "string", "description": "Nur für asset"},
                    "status": {"type": "string", "description": "Nur für orders: open, closed oder all"},
                },
                "required": ["what"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "alpaca_order",
            "description": "Kauft, verkauft, ändert oder storniert bei Alpaca und schließt Positionen. Fragt selbst nach Bestätigung — ruf es direkt auf, sobald der Nutzer handeln will.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["buy", "sell", "replace", "cancel", "cancel_all", "close_position", "close_all"],
                    },
                    "symbol": {"type": "string", "description": "Ticker, z.B. NVDA oder BTC/USD"},
                    "qty": {"type": "string", "description": "Stückzahl"},
                    "notional": {"type": "string", "description": "Betrag in Dollar statt Stückzahl"},
                    "type": {"type": "string", "enum": ["market", "limit", "stop", "stop_limit", "trailing_stop"]},
                    "limit_price": {"type": "string"},
                    "stop_price": {"type": "string"},
                    "trail_percent": {"type": "string", "description": "Nur trailing_stop"},
                    "time_in_force": {"type": "string", "enum": ["day", "gtc", "opg", "cls", "ioc", "fok"]},
                    "take_profit": {"type": "string", "description": "Zielkurs einer Bracket-Order"},
                    "stop_loss": {"type": "string", "description": "Stoppkurs einer Bracket-Order"},
                    "order_id": {"type": "string", "description": "Für replace und cancel"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "alpaca_request",
            "description": "Beliebiger Aufruf der Alpaca-REST-API für alles, was alpaca_data, alpaca_account und alpaca_order nicht abdecken (z.B. Watchlist anlegen, Optionskontrakte, Corporate Actions). Verändernde Aufrufe fragen selbst nach Bestätigung.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                    "path": {"type": "string", "description": "Pfad wie /v2/watchlists, keine ganze URL"},
                    "params": {"type": "string", "description": "Query-Parameter als JSON-Objekt"},
                    "body": {"type": "string", "description": "Request-Body als JSON-Objekt"},
                },
                "required": ["method", "path"],
            },
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
                "Ein Programm öffnen, z.B. Spotify, Obsidian, Terminal, Rechner, "
                "Notizen. NICHT für OpenCode, Claude Code oder Codex — das sind "
                "keine eigenständigen Apps, sondern Terminal-Coding-Agenten, "
                "dafür set_code_agent bzw. das opencode-Tool verwenden."
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
                "Wechselt das Modell des AKTUELL gewählten Coding-Agenten "
                "(OpenCode, Claude Code oder Codex — siehe set_code_agent), "
                "z.B. 'nimm das große Coder-Modell', 'wechsel auf GPT OSS', "
                "'benutz Sonnet', 'nimm Opus'. EIN Aufruf genügt: gib direkt "
                "das vom Nutzer genannte Modell mit, frag die Liste nicht "
                "vorher ab. Bei OpenCode bekommst du bei einem unbekannten "
                "Namen die verfügbaren zurück; Claude Code und Codex haben "
                "keinen abfragbaren lokalen Katalog, ihr Name wird direkt "
                "übernommen. Das Terminal startet dabei neu, damit die Wahl "
                "greift."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Modellname so, wie der Nutzer ihn gesagt hat (z.B. 'Devstral', 'GPT OSS', 'Sonnet', 'Opus')",
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
                "wieder OpenCode', aber genauso 'öffne Claude Code', 'kannst du "
                "Codex öffnen', 'starte OpenCode' — auch bei 'öffnen' geht es "
                "hier NICHT um open_app, diese drei sind Terminal-Coding-"
                "Agenten, keine eigenständigen Apps). EIN Aufruf genügt: gib "
                "direkt den vom Nutzer genannten Namen mit. Ist der Agent "
                "nicht installiert, bekommst du das gesagt statt eines stillen "
                "Fehlschlags. Ein offenes Terminal startet dabei neu, damit "
                "die Wahl greift."
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
    # rm on the root, root/*, a top-level directory, ~ or $HOME — with any
    # flags in between (the old pattern needed whitespace right after the
    # "/" and so let "rm -rf /*", "rm -rf ~" and "--no-preserve-root /"
    # straight through).
    r"\brm\s+(?:-\S+\s+)*[\"']?(?:/|/\*|/[a-z]+/?\*?|~|~/|~/\*|\$home|\$\{home\}|\$home/\*?)[\"']?(?:\s|$)",
    r"--no-preserve-root",
    r"\bfind\s+/\s.*-delete\b",
    r"\bmkfs\b",
    r"\bdd\s+.*of=/dev/",
    r":\(\)\s*\{.*\}\s*;\s*:",          # fork bomb
    # Only in command position — "echo shutdown notes" must stay allowed.
    r"(?:^|[;&|(]|\bcmd(?:\.exe)?\s+/[ck]|\bpowershell(?:\.exe)?(?:\s+-\w+)*)\s*[\"']?(?:sudo\s+)?(?:shutdown|reboot|halt|poweroff)(?:\.exe)?\b",
    r"\b(?:stop|restart)-computer\b",
    r"\bsudo\b",
    r">\s*/dev/(disk|sd)",
    r"\bdiskutil\s+(erase|reformat)",
    r"\bchmod\s+-R\s+777\s+/(\s|$)",
    # Windows equivalents of the above.
    r"\bformat\s+[a-z]:",
    # Deleting a drive root, everything on it, or the Windows/Users/Program
    # Files trees — via cmd (rd/rmdir/del/erase) or PowerShell (Remove-Item
    # and its ri/rm/del aliases).
    r"\b(?:rd|rmdir|del|erase|remove-item|ri|rm)\b.*\b[a-z]:[\\/]+"
    r"(?:\*(?:\.\*)?|windows|users|program files(?: \(x86\))?)?[\\/]*[\"']?\s*$",
    r"\bvssadmin\s+delete\b",
]


def _is_blocked(command: str) -> bool:
    lowered = command.lower()
    return any(re.search(p, lowered) for p in _BLOCKED)


def _get_weather(city: str) -> str:
    # "Wie ist das Wetter?" without a place: the model passes "" and the
    # geocoder found nothing — the configured home city is what was meant.
    city = (city or "").strip() or str(config.load_config().get("default_city") or "").strip()
    if not city:
        return "Für welche Stadt soll ich das Wetter abfragen?"
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


_WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def _get_time() -> str:
    # %A follows the process locale (English on a default Python install),
    # not the German the rest of Jarvis speaks.
    now = datetime.datetime.now()
    return f"{_WEEKDAYS_DE[now.weekday()]}, {now:%d.%m.%Y %H:%M}"


# A model asked about something it doesn't know ("was hab ich dir über
# meinen Urlaub erzählt?") was observed saving a template instead of an
# answer: "Urlaub: [Details aus dem Chatverlauf]". Such a note is pure
# invention and, once indexed, gets fed back as "memory" on every turn.
_NOTE_PLACEHOLDER = re.compile(r"\[[^\]]*\b(details?|platzhalter|inhalt|text|hier|einfügen|todo|xxx)\b[^\]]*\]|<[^>]*(details?|platzhalter|einfügen)[^>]*>", re.IGNORECASE)


def _add_note(text: str) -> str:
    if _NOTE_PLACEHOLDER.search(text or ""):
        return ("Nicht gespeichert: Die Notiz enthält einen Platzhalter statt echtem Inhalt. "
                "Nur speichern, was der Nutzer wirklich gesagt hat — sonst nachfragen.")
    return memory.add_note(text)


# Restricted to arithmetic only — no names, no calls, no subscripts — so this
# can safely evaluate whatever expression the model hands over without
# risking arbitrary code execution the way a bare eval() would.
_CALC_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval_calc_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        left, right = _eval_calc_node(node.left), _eval_calc_node(node.right)
        # Integer powers never overflow in Python, they just keep computing —
        # "9 hoch 9 hoch 9" would pin the server for hours.
        if isinstance(node.op, ast.Pow):
            if abs(right) > 1000 and abs(left) > 1:
                raise OverflowError("exponent too large")
            # A small exponent on an already huge base is the same trap one
            # level down: ((9**999)**999)**999 passed the check above three
            # times and then tried to build a number with a billion digits.
            if isinstance(left, int) and isinstance(right, int) and left.bit_length() * right > 100_000:
                raise OverflowError("result too large")
        return _CALC_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_eval_calc_node(node.operand))
    raise ValueError("unsupported expression")


def _format_calc_result(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = f"{value:.10f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    return text.replace(".", ",")


def _calculate(expression: str) -> str:
    # "geteilt durch"/"durch" -> "/", "mal" -> "*", "hoch" -> "**", "%" as a
    # trailing percent -> "/100" — a small safety net in case the model
    # passes the words through instead of converting them itself, since
    # that conversion is exactly the step this tool exists to not trust it
    # blindly with (see the tool description).
    expr = expression.strip().lower()
    expr = re.sub(r"geteilt\s+durch|:", "/", expr)
    expr = re.sub(r"\bdurch\b", "/", expr)
    expr = re.sub(r"÷", "/", expr)
    expr = re.sub(r"\bmal\b|×|·", "*", expr)
    expr = re.sub(r"\bhoch\b|\^", "**", expr)
    expr = re.sub(r"\bplus\b", "+", expr)
    expr = re.sub(r"\bminus\b|[−–]", "-", expr)
    expr = re.sub(r"\bmodulo\b", "%", expr)
    expr = re.sub(r"(?<=\d),(?=\d)", ".", expr)
    # A trailing "%" is a percentage ("20% * 50"); one between two operands is
    # modulo ("10 % 3").
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%(?!\s*[\d(])", r"(\1/100)", expr)
    if not re.fullmatch(r"[\d\s+\-*/().%]*", expr):
        return f"'{expression}' ist kein Rechenausdruck, den ich auswerten kann."
    try:
        # mode="eval" only parses expr into an AST — nothing here calls the
        # eval() builtin. _eval_calc_node then walks that AST itself and
        # only ever executes the whitelisted arithmetic ops in _CALC_OPS,
        # rejecting names/calls/attributes/subscripts outright.
        tree = ast.parse(expr, mode="eval")
        result = _eval_calc_node(tree.body)
    except ZeroDivisionError:
        return "Division durch null ist nicht definiert."
    except OverflowError:
        return f"Das Ergebnis von '{expression}' ist zu groß, um es auszurechnen."
    except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
        # RecursionError/MemoryError: hundreds of nested brackets.
        return f"'{expression}' ist kein Rechenausdruck, den ich auswerten kann."
    if isinstance(result, complex):
        # e.g. (-8)**(1/3): Python returns a complex number, which used to be
        # printed raw as "(1.0000000000000002+1.7320508075688772j)".
        return f"'{expression}' hat kein reelles Ergebnis."
    if isinstance(result, int) and result.bit_length() > 13000:
        # str() refuses ints this long (Python's int-to-str digit limit).
        digits = int(result.bit_length() * math.log10(2)) + 1
        return f"{expression} ergibt eine Zahl mit rund {digits} Stellen — zu lang zum Ausgeben."
    return f"{expression} = {_format_calc_result(result)}"


def _open_url(url: str) -> str:
    url = (url or "").strip()
    # An empty address used to become "https://" and open a browser error page.
    if not url or url.lower() in ("http://", "https://"):
        return "Welche Adresse soll ich öffnen?"
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    if browser_agent.agent.connected():
        result = browser_agent.agent.command("open_url", {"url": url})
        if not result.startswith("Browser-Agent nicht verbunden"):
            return result
    webbrowser.open(url)
    panel.push("link", title="Geöffnet", url=url)
    return f"{url} geöffnet."


def _open_in_browser(url: str, via_agent) -> str:
    """Use the Chrome extension when it's connected, otherwise the default
    browser — like _open_url. Without this fallback YouTube/web searches
    simply failed on every machine without the extension installed."""
    if browser_agent.agent.connected():
        result = via_agent()
        if not result.startswith("Browser-Agent nicht verbunden"):
            return result
    webbrowser.open(url)
    panel.push("link", title="Geöffnet", url=url)
    return f"{url} im Standardbrowser geöffnet (die Jarvis-Chrome-Erweiterung ist nicht verbunden)."


def _youtube_search(query: str) -> str:
    query = (query or "").strip()
    if not query:
        # "Öffne YouTube" regularly arrives here with an empty query.
        return _open_url("https://www.youtube.com")
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    return _open_in_browser(url, lambda: browser_agent.agent.youtube_search(query))


def _web_search(query: str) -> str:
    """Real search when a Tavily key is configured; otherwise open a results
    page in the browser — and say plainly that no results came back, so the
    model doesn't make some up."""
    if not config.TAVILY_API_KEY:
        url = f"https://www.google.com/search?q={quote_plus(query or '')}"
        opened = _open_in_browser(url, lambda: browser_agent.agent.web_search(query))
        return (
            f"{opened} Ich habe keine Suchergebnisse zurückbekommen (kein Tavily-API-Key "
            "eingerichtet) — die Ergebnisse stehen nur im Browser."
        )

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


def _jb_page_number(raw) -> int | None:
    try:
        return int(float(str(raw).strip().lstrip("#")))
    except (TypeError, ValueError):
        return None


def _jb_fail(res: dict) -> str:
    message = res.get("message") or "Unbekannter Fehler."
    # "nicht verbunden" erklärt sich selbst; alles andere als Fehler kennzeichnen,
    # damit das Panel den Aufruf als fehlgeschlagen zeigt.
    return message if message.startswith("Jarvis-Browser nicht verbunden") else f"Konnte das im Jarvis-Browser nicht tun: {message}"


def _jb_view(res: dict, previous: dict | None = None) -> str:
    data = res.get("data") or {}
    jarvis_browser.agent.remember(data)
    return jarvis_browser.agent.render(data, previous)


def _browser_open(url: str) -> str:
    url = (url or "").strip()
    if not url or url.lower() in ("http://", "https://"):
        return "Welche Adresse soll ich im Jarvis-Browser öffnen?"
    # Nur Webseiten: javascript:/file:/data:/chrome: & Co. würden Skripte
    # ausführen oder lokale Dateien lesen.
    if re.match(r"^(javascript|file|data|vbscript|blob|about|chrome|edge|view-source|ftp)\s*:", url, re.IGNORECASE):
        return "Konnte das nicht tun: Der Jarvis-Browser öffnet nur http- und https-Adressen."
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    res = jarvis_browser.agent.command("open", {"url": url}, timeout=50)
    return _jb_view(res) if res["ok"] else _jb_fail(res)


def _browser_look() -> str:
    res = jarvis_browser.agent.command("look", {})
    return _jb_view(res) if res["ok"] else _jb_fail(res)


def _jb_target(raw_nr) -> tuple[int, dict, int] | str:
    """Prüft Nummer, Schalter und letzte Elementliste. Gibt (nr, element, epoch)
    oder eine Fehlermeldung für das Modell zurück."""
    if not jarvis_browser.agent.actions_enabled():
        return "Konnte das nicht tun: Klicken und Tippen im Jarvis-Browser ist ausgeschaltet (config.json: jarvis_browser_actions)."
    nr = _jb_page_number(raw_nr)
    if nr is None:
        return "Konnte das nicht tun: Welche Nummer aus der Elementliste?"
    last = jarvis_browser.agent.last
    element = jarvis_browser.agent.element(nr)
    if element is None or last.get("epoch") is None:
        return f"Konnte das nicht tun: Es gibt kein Element Nr. {nr} in der letzten Liste. Bitte erst browser_look aufrufen."
    return nr, element, int(last["epoch"])


def _browser_click(nr_raw) -> str:
    target = _jb_target(nr_raw)
    if isinstance(target, str):
        return target
    nr, element, epoch = target
    name = element.get("name") or element.get("role", "Element")
    url = jarvis_browser.agent.last.get("url", "")
    previous = dict(jarvis_browser.agent.last)

    def _do_click(after_confirm: bool) -> str:
        res = jarvis_browser.agent.command("click", {"nr": nr, "epoch": epoch}, timeout=45)
        if not res["ok"]:
            return _jb_fail(res)
        if after_confirm:
            # Nach "Ja" ist das hier die ganze Antwort an den Nutzer (das Modell
            # wird übersprungen, siehe confirm.resolve) — also ein lesbarer Satz.
            data = res.get("data") or {}
            jarvis_browser.agent.remember(data)
            return f"Erledigt: \u201e{name}\u201c angeklickt. Die Seite ist jetzt \u201e{data.get('title') or ''}\u201c."
        return _jb_view(res, previous)

    if jarvis_browser.RISKY_RE.search(name):
        # Kauf/Senden/Löschen/Zustimmen: nie ohne ausdrückliches Ja des Nutzers.
        what = "dem Link" if element.get("role") == "Link" else "auf"
        return confirm.propose(
            f"Soll ich im Jarvis-Browser {what} \u201e{name}\u201c klicken (Seite: {url[:60]})?", lambda: _do_click(True)
        )
    return _do_click(False)


def _browser_type(nr_raw, text: str, enter) -> str:
    target = _jb_target(nr_raw)
    if isinstance(target, str):
        return target
    nr, element, epoch = target
    if element.get("role") in jarvis_browser.SECRET_ROLES:
        return "Konnte das nicht tun: In Passwort- und Zahlungsfelder tippe ich nicht. Das musst du selbst eingeben."
    previous = dict(jarvis_browser.agent.last)
    submit = str(enter).strip().lower() in ("true", "1", "ja", "yes")
    res = jarvis_browser.agent.command("type", {"nr": nr, "epoch": epoch, "text": str(text or ""), "enter": submit}, timeout=45)
    return _jb_view(res, previous) if res["ok"] else _jb_fail(res)


def _browser_select(nr_raw, value: str) -> str:
    target = _jb_target(nr_raw)
    if isinstance(target, str):
        return target
    nr, _element, epoch = target
    previous = dict(jarvis_browser.agent.last)
    res = jarvis_browser.agent.command("select", {"nr": nr, "epoch": epoch, "value": str(value or "")}, timeout=30)
    return _jb_view(res, previous) if res["ok"] else _jb_fail(res)


def _browser_scroll(direction: str) -> str:
    res = jarvis_browser.agent.command("scroll", {"direction": str(direction or "unten")})
    return _jb_view(res) if res["ok"] else _jb_fail(res)


def _browser_read() -> str:
    res = jarvis_browser.agent.command("read", {"max_chars": 5000}, timeout=30)
    if not res["ok"]:
        return _jb_fail(res)
    data = res.get("data") or {}
    text = str(data.get("text") or "").strip()
    head = f'{jarvis_browser.PAGE_DATA_NOTE}\nSeite: "{data.get("title", "")}" ({data.get("url", "")})'
    if not text:
        return head + "\nAuf der Seite steht kein lesbarer Text."
    tail = f"\n[gekürzt, die Seite hat {data.get('length')} Zeichen]" if data.get("truncated") else ""
    return f"{head}\n{text}{tail}"


def _browser_back() -> str:
    previous = dict(jarvis_browser.agent.last)
    res = jarvis_browser.agent.command("back", {}, timeout=40)
    return _jb_view(res, previous) if res["ok"] else _jb_fail(res)


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


def _find_start_app(name: str) -> str | None:
    """AppUserModelID of an app by the name the Start menu shows for it.

    Microsoft Store apps (Spotify from the Store, Rechner, Terminal, ...) have
    neither an exe on PATH nor a .lnk in the Start Menu folders, so the two
    lookups in _open_app_windows never find them. Get-StartApps lists
    everything the Start menu shows, with its localized display name —
    `shell:AppsFolder\\<AppID>` then launches it."""
    script = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
    try:
        proc = subprocess.run(
            platform_utils.powershell(script),
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=20, creationflags=_NO_WINDOW,
        )
        apps = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if isinstance(apps, dict):  # ConvertTo-Json writes a single app as a bare object
        apps = [apps]

    wanted = re.sub(r"\.exe$", "", name.strip(), flags=re.IGNORECASE).lower()
    word_start = re.compile(r"\b" + re.escape(wanted))
    best: tuple[tuple[int, int], str] | None = None
    for app in apps:
        app_name, app_id = str(app.get("Name") or ""), app.get("AppID")
        shown = app_name.lower()
        if not app_id or not wanted:
            continue
        if shown == wanted:
            rank = 0
        elif shown.startswith(wanted):
            rank = 1
        elif word_start.search(shown):
            rank = 2
        else:
            continue
        key = (rank, len(app_name))  # exact > prefix > word inside the name, shorter name wins ties
        if best is None or key < best[0]:
            best = (key, str(app_id))
    return best[1] if best else None


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

    app_id = _find_start_app(name)
    if app_id:
        try:
            os.startfile(f"shell:AppsFolder\\{app_id}")  # noqa: S606 - AppID comes from Get-StartApps
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
    text = (description or "").strip().strip("\"'")
    if not text:
        return None, ""

    # A real path ("C:\Users\me\Desktop\x", "~/Downloads/a.txt",
    # "Projekte/alt") — the word-based lookup below would shred it into
    # "C Users me Desktop x". Tried as-is first, then relative to home and
    # Desktop.
    if "/" in text or "\\" in text:
        raw = Path(os.path.expanduser(text))
        candidates = [raw] if raw.is_absolute() else [Path.home() / raw, Path.home() / "Desktop" / raw]
        for candidate in candidates:
            if candidate.exists() and (not require_dir or candidate.is_dir()):
                last_target.remember(candidate)
                return candidate, candidate.name
        if raw.is_absolute():
            # A full path that doesn't exist IS the answer — the word lookup
            # below only shredded it ("Konnte den Ordner 'C Users mimet
            # gibtsnicht' nicht finden").
            return None, str(raw)

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

    try:
        entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return f"Konnte '{target.name or target}' nicht lesen: {exc.strerror or exc}"
    if not entries:
        return f"'{target.name}' ist leer."
    shown = [f"{p.name}/" if p.is_dir() else p.name for p in entries[:40]]
    listing = ", ".join(shown)
    if len(entries) > 40:
        listing += f", … und {len(entries) - 40} weitere"
    # Small models miscount long listings ("19 Python-Dateien" for 22 —
    # observed in the benchmark), so the counts come pre-computed.
    folders = sum(1 for p in entries if p.is_dir())
    by_ext: dict[str, int] = {}
    for p in entries:
        if p.is_file():
            ext = p.suffix.lower() or "(ohne Endung)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
    counts = ", ".join(f"{n}× {ext}" for ext, n in sorted(by_ext.items(), key=lambda kv: -kv[1]))
    summary = f"{len(entries) - folders} Dateien ({counts}), {folders} Ordner" if counts else f"{folders} Ordner"
    return f"Inhalt von '{target.name}' — {summary}: {listing}"


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


def _spoken_location(raw: str) -> Path:
    """A destination as the model passes it: an absolute path, a known place
    ("Dokumente", "Desktop") or a name relative to the Desktop — never
    relative to the server's working directory, which is the Jarvis repo."""
    path = Path(os.path.expanduser(raw))
    if path.is_absolute():
        return path
    alias = _LOCATION_ALIASES.get(raw.strip().lower())
    if alias:
        return Path(os.path.expanduser(alias))
    return platform_utils.desktop_dir() / path


def _move_file(source: str, destination: str) -> str:
    """Move a file or folder; safer than a raw `mv` via run_shell."""
    source = (source or "").strip().strip("\"'")
    destination = (destination or "").strip().strip("\"'")
    if not source:
        return "Was soll ich verschieben?"
    if not destination:
        # Path("") is "." — the Jarvis repo the server runs in.
        return "Wohin soll ich es verschieben?"
    src, _name = _resolve_fs_path(source, require_dir=False)
    if src is None:
        return f"Konnte '{source}' nicht finden."
    if _is_protected_location(src):
        return f"'{src}' ist ein geschützter Haupt- oder Systemordner (oder liegt in einem) — das verschiebe ich nicht."
    dst = _spoken_location(destination)

    # "in die Dokumente" → move into the folder, keeping the filename.
    if dst.is_dir():
        dst = dst / src.name
    else:
        # A destination like "~/Documents" that doesn't exist yet is almost
        # always meant as the Documents folder, not a renamed file.
        if dst.suffix == "" and not dst.exists():
            dst = dst / src.name

    if dst.exists():
        # shutil.move silently replaces an existing file at the destination.
        return f"Am Ziel gibt es '{dst.name}' schon ({dst.parent}) — ich überschreibe nichts. Nenn mir einen anderen Zielnamen oder -ordner."

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"'{src.name}' nach '{dst.parent}' verschoben."


def _system_roots() -> list[Path]:
    """Folders whose contents belong to the operating system or installed
    programs — nothing in there is ever the user's "that file over there"."""
    if IS_WINDOWS:
        raw = [os.environ.get(var) for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
    else:
        raw = ["/System", "/usr", "/bin", "/sbin", "/etc", "/var", "/private", "/Library"]
    return [Path(p).resolve() for p in raw if p]


def _is_protected_location(target: Path) -> bool:
    resolved = target.resolve()
    home = Path.home().resolve()
    protected = {home, *(Path(os.path.expanduser(p)).resolve() for p in _LOCATION_ALIASES.values())}
    if resolved in protected or resolved == Path(resolved.anchor) or resolved in home.parents:
        return True
    # Moving or trashing C:\Windows, a program folder or anything inside them
    # was not refused before — move_file has no confirmation step at all, and
    # across drives shutil.move copies first and deletes after.
    if any(resolved == root or root in resolved.parents for root in _system_roots()):
        return True
    # Jarvis itself, and every folder it lives in.
    jarvis = config.ROOT_DIR.resolve()
    return resolved == jarvis or resolved in jarvis.parents


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
    if _is_protected_location(target):
        # A description made only of filler/location words ("den Ordner auf
        # dem Schreibtisch") resolves to the base folder itself.
        return f"'{target}' ist ein geschützter Haupt- oder Systemordner (oder liegt in einem) — das lösche ich nicht. Welche eigene Datei oder welchen eigenen Ordner meinst du?"

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
    raw = (path or "").strip().strip("\"'")
    if not raw:
        return "Welche Datei soll ich schreiben?"
    target = Path(os.path.expanduser(raw))
    if not target.is_absolute():
        # A bare "einkauf.txt" used to land in the backend's working
        # directory — the Jarvis repo itself.
        target = platform_utils.desktop_dir() / target
    if target.suffix.lower() not in _CODE_SUFFIXES and target.exists():
        # write_text replaced an existing file without a word — one misheard
        # "schreib eine Datei notizen.txt" wiped the real notes. move_file
        # refuses to overwrite for the same reason.
        return (f"'{target.name}' gibt es schon ({target.parent}) — ich überschreibe keine bestehende "
                "Datei. Nenn mir einen anderen Namen oder lösch die alte zuerst.")
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
    # Same cp1252-vs-UTF-8 trap as elsewhere in this file:
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
    items = [str(x).strip() for x in (data if isinstance(data, list) else [data]) if x is not None and str(x).strip()]
    if not items:
        return "Keine Daten zum Anzeigen."
    if vtype in ("bars", "line"):
        points = []
        for i, raw in enumerate(items[:12]):
            label, _, num = raw.rpartition("=")
            if not label and not _:
                label, num = str(i + 1), raw
            try:
                value = float(num.replace(",", ".").strip())
                if not math.isfinite(value):
                    raise ValueError(raw)
                points.append({"label": label.strip()[:14] or str(i + 1), "value": value})
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
    agent_id = opencode_agent.get_code_agent()
    if not opencode_agent.agent_available(agent_id):
        # Used to report "weitergegeben" regardless — with the binary missing
        # the task silently went nowhere.
        name = opencode_agent.CODE_AGENTS.get(agent_id, agent_id)
        return (
            f"Konnte den Auftrag nicht weitergeben: {name} ist auf diesem Rechner nicht installiert "
            "bzw. nicht gebaut (siehe SETUP.md). Mit set_code_agent kann auf einen installierten "
            "Coding-Agenten umgestellt werden."
        )
    # Zeilenumbrüche sind oben schon weg: ein "\n" im PTY wäre ein Absenden
    # mitten im Satz, OpenCode bekäme nur das erste Fragment.
    panel.push("opencode", task=task[:2000])
    name = opencode_agent.CODE_AGENTS.get(opencode_agent.get_code_agent(), "den Coding-Agenten")
    return f"An {name} weitergegeben: {task}"


# Dateien, die das Betriebssystem beim Öffnen AUSFÜHREN würde. "Zeig mir die
# Datei" darf kein Skript starten, also gehen die in den Editor.
_RUNNABLE_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ps1", ".psm1", ".bat", ".cmd", ".sh", ".vbs", ".vbe",
    ".jse", ".wsf", ".wsh", ".hta", ".reg", ".jar",
}
# Programs/installers: "opening" them means running them, which is open_app's
# job, not a request to look at a file.
_EXECUTABLE_SUFFIXES = {".exe", ".msi", ".msix", ".appx", ".scr", ".com", ".cpl", ".pif", ".lnk"}


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
    if target.suffix.lower() in _EXECUTABLE_SUFFIXES:
        return f"{target.name} ist ein Programm bzw. Installer — das starte ich nicht einfach beim Öffnen. Soll es wirklich ausgeführt werden, sag es ausdrücklich."
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
    """Stellt das Modell um, mit dem der AKTUELL gewählte Coding-Agent
    arbeitet (opencode, Claude Code oder Codex — siehe set_code_agent). Die
    Wahl landet in einer pro Agent getrennten Konfiguration (siehe
    opencode_agent.get_selected_model), die erst beim nächsten Start der TUI
    gelesen wird — deshalb schickt der Panel-Push das Frontend dazu, das
    Terminal neu zu starten.

    Früher lief das immer gegen OpenCodes eigenen Modellkatalog, auch wenn
    gerade Claude Code oder Codex aktiv war — "Sonnet" landete dann live
    beobachtet bei einem irrelevanten OpenRouter-Modell aus OpenCodes Liste.
    Claude Code und Codex haben eigene, disjunkte Kataloge, gegen die
    OpenCodes Liste nichts hergibt.
    """
    agent = opencode_agent.get_code_agent()

    if agent == "claude":
        chosen = opencode_agent.resolve_claude_model(name)
        if not chosen:
            return "Welches Modell soll Claude Code benutzen?"
        opencode_agent.set_selected_model(chosen, "claude")
        panel.push("opencode_model", model=chosen)
        return f"Claude Code arbeitet ab jetzt mit {chosen}. Ein gerade offenes Terminal wird dafür neu gestartet, sonst gilt es ab dem nächsten Start."

    if agent == "codex":
        chosen = opencode_agent.resolve_codex_model(name)
        if not chosen:
            return "Welches Modell soll Codex benutzen?"
        opencode_agent.set_selected_model(chosen, "codex")
        panel.push("opencode_model", model=chosen)
        return f"Codex arbeitet ab jetzt mit {chosen}. Ein gerade offenes Terminal wird dafür neu gestartet, sonst gilt es ab dem nächsten Start."

    # opencode (Standard) — hier gibt es einen echten lokalen Katalog
    # (LM Studio + OpenCodes eigene kostenlose Modelle), gegen den sich der
    # gesprochene Name sinnvoll fuzzy matchen lässt.
    available = opencode_agent.list_all_models()
    if not available:
        return "OpenCode meldet gerade keine Modelle."
    chosen = opencode_agent.resolve_model(name, available)
    if not chosen:
        return f'Kein Modell gefunden, das zu "{name}" passt. Verfügbar: ' + ", ".join(available[:10])
    opencode_agent.set_selected_model(chosen, "opencode")
    lm_models = opencode_agent.list_models()
    if lm_models:
        opencode_agent.ensure_provider_config(lm_models, chosen)
    panel.push("opencode_model", model=chosen)
    return f"OpenCode arbeitet ab jetzt mit {chosen}. Ein gerade offenes Terminal wird dafür neu gestartet, sonst gilt es ab dem nächsten Start."


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


def _alpaca_guarded(run) -> str:
    """Runs an Alpaca call; a failure becomes a sentence instead of a trace."""
    try:
        return run()
    except alpaca_client.AlpacaError as exc:
        return f"Fehler bei Alpaca: {exc}"
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return f"Fehler bei Alpaca: unerwartete Antwort ({exc})."


def _alpaca_data(a: dict) -> str:
    return _alpaca_guarded(lambda: alpaca_client.market_data(
        a.get("kind", ""), a.get("symbols", "") or a.get("symbol", ""), a.get("timeframe", ""),
        a.get("start", ""), a.get("end", ""), a.get("limit", ""),
    ))


def _alpaca_account(a: dict) -> str:
    return _alpaca_guarded(lambda: alpaca_client.account_info(a.get("what", ""), a.get("symbol", ""), a.get("status", "")))


def _alpaca_number(value: str) -> str:
    """'10', '10,5', '$1.200' -> a plain decimal string, '' if not a positive number."""
    text = str(value or "").strip().replace("$", "").replace("€", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return text if float(text) > 0 else ""
    except ValueError:
        return ""


# The paper account is shared with the analyst app on the tower.
_ALPACA_SHARED_NOTE = " Das betrifft auch Positionen und Orders anderer Programme auf diesem Konto."


def _alpaca_confirm(question: str, method: str, path: str, params: dict | None, body: dict | None, done) -> str:
    """Every account-changing Alpaca call goes through here: nothing is sent
    until the user's next message is a plain yes (see confirm.propose)."""
    hint = alpaca_client.missing_keys_hint()
    if hint:
        return hint

    def _send() -> str:
        return _alpaca_guarded(lambda: done(alpaca_client.request(method, path, params, body, data=False)))

    return confirm.propose(question, _send)


def _alpaca_order(a: dict) -> str:
    action = (a.get("action") or "").strip().lower()
    label = alpaca_client.account_label()
    syms = alpaca_client.symbols(a.get("symbol", ""))
    symbol = syms[0] if syms else ""
    order_id = (a.get("order_id") or "").strip()

    if action == "cancel_all":
        return _alpaca_confirm(
            f"Soll ich wirklich ALLE offenen Orders stornieren ({label})?{_ALPACA_SHARED_NOTE}",
            "DELETE", "/v2/orders", None, None, lambda r: "Alle offenen Orders wurden storniert.",
        )
    if action == "close_all":
        return _alpaca_confirm(
            f"Soll ich wirklich ALLE Positionen zum Marktpreis schließen und alle Orders stornieren ({label})?{_ALPACA_SHARED_NOTE}",
            "DELETE", "/v2/positions", {"cancel_orders": "true"}, None,
            lambda r: f"Schließen von {len(r or [])} Positionen wurde beauftragt.",
        )
    if action == "cancel":
        if not order_id:
            return "Welche Order soll ich stornieren? Ich brauche die Order-ID (siehe alpaca_account mit what=orders)."
        return _alpaca_confirm(
            f"Soll ich die Order {order_id} stornieren ({label})?",
            "DELETE", f"/v2/orders/{quote_plus(order_id)}", None, None, lambda r: f"Order {order_id} wurde storniert.",
        )
    if action == "close_position":
        if not symbol:
            return "Welche Position soll ich schließen?"
        return _alpaca_confirm(
            f"Soll ich die gesamte Position {symbol} zum Marktpreis schließen ({label})?",
            "DELETE", f"/v2/positions/{quote_plus(symbol)}", None, None,
            lambda r: f"Schließen der Position {symbol} wurde beauftragt (Order {(r or {}).get('id', '?')}).",
        )
    if action == "replace":
        if not order_id:
            return "Welche Order soll ich ändern? Ich brauche die Order-ID."
        changes = {
            key: _alpaca_number(a.get(src, "")) for key, src in
            (("qty", "qty"), ("limit_price", "limit_price"), ("stop_price", "stop_price"), ("trail", "trail_percent"))
        }
        changes = {k: v for k, v in changes.items() if v}
        if a.get("time_in_force"):
            changes["time_in_force"] = a["time_in_force"].lower()
        if not changes:
            return "Was soll ich an der Order ändern (Stückzahl, Limit- oder Stoppkurs)?"
        text = ", ".join(f"{k} {v}" for k, v in changes.items())
        return _alpaca_confirm(
            f"Soll ich die Order {order_id} ändern auf {text} ({label})?",
            "PATCH", f"/v2/orders/{quote_plus(order_id)}", None, changes,
            lambda r: f"Order geändert, neue ID {(r or {}).get('id', '?')}, Status {(r or {}).get('status', '?')}.",
        )
    if action not in ("buy", "sell"):
        return "Unbekannte Order-Aktion. Möglich: buy, sell, replace, cancel, cancel_all, close_position, close_all."

    if not symbol:
        return "Welches Wertpapier soll ich handeln?"
    qty, notional = _alpaca_number(a.get("qty", "")), _alpaca_number(a.get("notional", ""))
    if not qty and not notional:
        return f"Wie viele Stück {symbol} (oder für welchen Betrag) soll ich {'kaufen' if action == 'buy' else 'verkaufen'}?"
    limit_price, stop_price = _alpaca_number(a.get("limit_price", "")), _alpaca_number(a.get("stop_price", ""))
    trail = _alpaca_number(a.get("trail_percent", ""))
    take_profit, stop_loss = _alpaca_number(a.get("take_profit", "")), _alpaca_number(a.get("stop_loss", ""))
    order_type = (a.get("type") or "").strip().lower() or (
        "stop_limit" if limit_price and stop_price else "limit" if limit_price else "stop" if stop_price
        else "trailing_stop" if trail else "market"
    )
    needs = {"limit": [("Limitkurs", limit_price)], "stop": [("Stoppkurs", stop_price)],
             "stop_limit": [("Limitkurs", limit_price), ("Stoppkurs", stop_price)],
             "trailing_stop": [("Abstand in Prozent", trail)], "market": []}
    if order_type not in needs:
        return f"Unbekannter Ordertyp '{order_type}'. Möglich: market, limit, stop, stop_limit, trailing_stop."
    missing = [name for name, value in needs[order_type] if not value]
    if missing:
        return f"Für eine {order_type}-Order fehlt noch: {', '.join(missing)}."

    crypto = "/" in symbol
    body = {
        "symbol": symbol, "side": action, "type": order_type,
        "time_in_force": (a.get("time_in_force") or ("gtc" if crypto else "day")).lower(),
    }
    body["qty" if qty else "notional"] = qty or notional
    if order_type in ("limit", "stop_limit"):
        body["limit_price"] = limit_price
    if order_type in ("stop", "stop_limit"):
        body["stop_price"] = stop_price
    if order_type == "trailing_stop":
        body["trail_percent"] = trail
    if take_profit or stop_loss:
        body["order_class"] = "bracket" if take_profit and stop_loss else "oto"
        if take_profit:
            body["take_profit"] = {"limit_price": take_profit}
        if stop_loss:
            body["stop_loss"] = {"stop_price": stop_loss}

    verb = "kaufen" if action == "buy" else "verkaufen"
    amount = f"{qty} Stück {symbol}" if qty else f"{symbol} für {notional} $"
    details = [f"Ordertyp {order_type}"]
    details += [f"{name} {value} $" for name, value in (("Limit", body.get("limit_price")), ("Stopp", body.get("stop_price"))) if value]
    if trail and order_type == "trailing_stop":
        details.append(f"Abstand {trail} %")
    if take_profit:
        details.append(f"Ziel {take_profit} $")
    if stop_loss:
        details.append(f"Stop-Loss {stop_loss} $")
    details.append(f"gültig {body['time_in_force']}")
    if qty:
        price = float(limit_price) if limit_price else alpaca_client.latest_price(symbol)
        if price:
            details.append(f"Gegenwert etwa {float(qty) * price:,.0f} $".replace(",", "."))
    return _alpaca_confirm(
        f"Soll ich wirklich {amount} {verb}? {', '.join(details)}. Konto: {label}.",
        "POST", "/v2/orders", None, body,
        lambda r: f"Order aufgegeben ({label}): {amount} {verb}, Status {(r or {}).get('status', '?')}, ID {(r or {}).get('id', '?')}.",
    )


def _alpaca_request(a: dict) -> str:
    method = (a.get("method") or "GET").strip().upper()
    path = (a.get("path") or "").strip()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        return f"Unbekannte Methode '{method}'."
    parsed = {}
    for field in ("params", "body"):
        raw = (a.get(field) or "").strip()
        try:
            parsed[field] = json.loads(raw) if raw else None
        except ValueError:
            return f"Konnte '{field}' nicht als JSON lesen."
        if parsed[field] is not None and not isinstance(parsed[field], dict):
            return f"'{field}' muss ein JSON-Objekt sein."
    if method == "GET":
        return _alpaca_guarded(lambda: alpaca_client.compact(alpaca_client.request("GET", path, parsed["params"])))
    if alpaca_client.is_data_path(path):
        return "Die Marktdaten-API von Alpaca kennt nur lesende Aufrufe (GET)."
    body_text = f" mit {alpaca_client.compact(parsed['body'], 300)}" if parsed["body"] else ""
    return _alpaca_confirm(
        f"Soll ich wirklich {method} {path}{body_text} an Alpaca senden ({alpaca_client.account_label()})?",
        method, path, parsed["params"], parsed["body"],
        lambda r: "Erledigt. Antwort von Alpaca: " + (alpaca_client.compact(r, 600) if r is not None else "leer"),
    )


DISPATCH = {
    "alpaca_data": _alpaca_data,
    "alpaca_account": _alpaca_account,
    "alpaca_order": _alpaca_order,
    "alpaca_request": _alpaca_request,
    "get_weather": lambda a: _get_weather(a.get("city", "")),
    "get_time": lambda a: _get_time(),
    "add_note": lambda a: _add_note(a.get("text", "")),
    "calculate": lambda a: _calculate(a.get("expression", "")),
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
    "browser_open": lambda a: _browser_open(a.get("url", "")),
    "browser_look": lambda a: _browser_look(),
    "browser_click": lambda a: _browser_click(a.get("nr", "")),
    "browser_type": lambda a: _browser_type(a.get("nr", ""), a.get("text", ""), a.get("enter", "")),
    "browser_select": lambda a: _browser_select(a.get("nr", ""), a.get("value", "")),
    "browser_scroll": lambda a: _browser_scroll(a.get("direction", "")),
    "browser_read": lambda a: _browser_read(),
    "browser_back": lambda a: _browser_back(),
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
    # The arguments come from the model: a number or null where a string
    # belongs used to surface as "'int' object has no attribute 'strip'".
    if not isinstance(arguments, dict):
        arguments = {}
    arguments = {
        key: value if key == "data" or isinstance(value, str)
        else "" if value is None
        else " ".join(map(str, value)) if isinstance(value, (list, tuple))
        else str(value)
        for key, value in arguments.items()
    }
    action_id = f"tool-{datetime.datetime.now().strftime('%H%M%S%f')}"
    panel.push("action", id=action_id, action=name, status="läuft", target=arguments)
    try:
        result = handler(arguments)
        failed = result.lower().startswith(("fehler", "konnte", "unbekannt", "browser-agent nicht verbunden", "browser-aktion fehlgeschlagen", "jarvis-browser nicht verbunden"))
        panel.push("action", id=action_id, action=name, status="fehlgeschlagen" if failed else "erfolgreich", detail=result)
        return result
    except Exception as exc:
        result = f"Fehler beim Ausführen von {name}: {exc}"
        panel.push("action", id=action_id, action=name, status="fehlgeschlagen", detail=result)
        return result
