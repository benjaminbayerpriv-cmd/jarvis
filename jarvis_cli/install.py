"""The guided installation.

Runs from a freshly unpacked ZIP, where there is no virtualenv, no .env and
no dependencies — so it works in stages that can each be re-run on their own,
and every stage is skippable:

  1. Python prüfen       2. .venv anlegen        3. Abhängigkeiten installieren
  4. .env anlegen        5. LM Studio verbinden 6. Modell wählen
  7. Token einfügen      8. MCP-Eintrag          9. Autostart / Hotkey

Long steps run behind a spinner with the raw output kept for the error path,
so the terminal shows one line at a time instead of pip's 200 progress lines.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Callable

from . import context as ctx
from . import lmstudio, scan, server
from .ui import ui

MIN_PYTHON = (3, 10)
RECOMMENDED_PYTHON = (3, 12)
PIP_TIMEOUT = 3600


def needs_setup() -> list[str]:
    """What is still missing — drives the first-run screen."""
    missing = []
    if not ctx.system_python_ok():
        missing.append("Python-Version")
    if not ctx.venv_python():
        missing.append(".venv")
    if not ctx.ENV_FILE.exists():
        missing.append(".env")
    if not lmstudio.token():
        missing.append("LM-Studio-Token")
    if not ctx.env("JARVIS_MCP_TOKEN"):
        missing.append("MCP-Eintrag")
    return missing


def is_ready() -> bool:
    return bool(ctx.venv_python()) and ctx.ENV_FILE.exists()


def _run(args: list[str], timeout: int = 600) -> tuple[int, str]:
    result = subprocess.run(args, cwd=str(ctx.ROOT), capture_output=True, text=True,
                            timeout=timeout, encoding="utf-8", errors="replace",
                            creationflags=ctx.no_window())
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _tail(output: str, lines: int = 18) -> list[str]:
    return [line for line in output.splitlines() if line.strip()][-lines:]


# ------------------------------------------------------------------- stages
def check_python() -> bool:
    ui.heading("Python")
    current = sys.version_info[:3]
    version = f"{current[0]}.{current[1]}.{current[2]}"
    if current[:2] >= MIN_PYTHON:
        ui.status("ok", "Interpreter", f"Python {version}", sys.executable)
    else:
        ui.status("fail", "Interpreter", f"Python {version}",
                  f"es braucht mindestens {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
        ui.fail(f"Bitte Python {RECOMMENDED_PYTHON[0]}.{RECOMMENDED_PYTHON[1]}+ von python.org "
                "installieren und die CLI neu öffnen.")
        return False
    if current[:2] < RECOMMENDED_PYTHON:
        ui.warn(f"Python {version} läuft, {RECOMMENDED_PYTHON[0]}.{RECOMMENDED_PYTHON[1]}+ "
                "ist aber die erprobte Version (siehe SETUP.md).")
    return True


def create_venv() -> bool:
    ui.heading("Python-Umgebung (.venv)")
    if ctx.venv_python():
        ui.status("ok", ".venv", "vorhanden", str(ctx.venv_python()))
        return True
    ui.info("Lege .venv an …")
    try:
        with ui.spinner("python -m venv .venv"):
            code, output = _run([sys.executable, "-m", "venv", str(ctx.ROOT / ".venv")], timeout=300)
    except subprocess.TimeoutExpired:
        ui.fail("Das Anlegen von .venv hat zu lange gedauert.")
        return False
    if code != 0 or not ctx.venv_python():
        ui.fail("Konnte .venv nicht anlegen:")
        ui.lines("\n".join(_tail(output)))
        return False
    ui.ok(f".venv angelegt ({ctx.venv_python()})")
    return True


def install_dependencies(force: bool = False) -> bool:
    ui.heading("Abhängigkeiten")
    python = ctx.venv_python()
    if python is None:
        ui.fail("Kein .venv vorhanden.")
        return False
    if ctx.deps_ok() and not force:
        ui.status("ok", "Pakete", "vollständig", "alle Importpfade funktionieren")
        if not ui.confirm("Trotzdem neu installieren?", default=False):
            return True
    ui.info("Das dauert je nach Internetverbindung einige Minuten.")
    try:
        with ui.spinner("pip wird aktualisiert"):
            _run([str(python), "-m", "pip", "install", "--upgrade", "pip",
                  "--disable-pip-version-check", "-q"], timeout=600)
        with ui.spinner("Pakete werden installiert (fastapi, Whisper, TTS …)"):
            code, output = _run(
                [str(python), "-m", "pip", "install", "-r", "requirements.txt",
                 "--disable-pip-version-check"],
                timeout=PIP_TIMEOUT,
            )
    except subprocess.TimeoutExpired:
        ui.fail("Die Installation hat nach 60 Minuten noch nicht aufgehört — "
                "Internetverbindung prüfen und erneut versuchen.")
        return False
    if code != 0:
        ui.fail("Installation fehlgeschlagen — die letzten Zeilen:")
        ui.lines("\n".join(_tail(output)))
        return False
    done = next((line for line in output.splitlines() if line.startswith("Successfully installed")), "")
    count = len(done.split()) - 2 if done else 0
    ui.ok(f"Installation erfolgreich{f' — {count} Pakete' if count else ''}.")
    if not ctx.deps_ok():
        ui.warn("Einige Pakete scheinen zu fehlen — jarvis doctor zeigt, was fehlt.")
        return False
    return True


def create_env_file() -> bool:
    ui.heading("Konfiguration (.env)")
    if ctx.ENV_FILE.exists():
        ui.status("ok", ctx.ENV_FILE.name, "vorhanden", str(ctx.ENV_FILE))
        return True
    ctx.write_env({})
    ui.ok(f"{ctx.ENV_FILE.name} aus {ctx.ENV_EXAMPLE.name} erzeugt — Platzhalterwerte geleert.")
    ui.note("Zeilen mit # sind Kommentare; alle Werte kannst du jederzeit anpassen.")
    return True


def connect_lm_studio() -> bool:
    ui.heading("LM Studio")
    ui.note("Voraussetzung: LM Studio gestartet, ein Modell geladen, unter "
            "„Developer → Start Server“ der Server läuft (Standard 127.0.0.1:1234).")
    healthy, detail = lmstudio.health()
    if healthy:
        ui.ok(detail)
        return True
    ui.fail(detail)

    # 401 first: the address is fine in that case, and sending the user off to
    # hunt for a different one would be exactly the wrong advice.
    if lmstudio.requires_auth():
        if ui.confirm("LM Studio verlangt ein Token — jetzt einfügen?", default=True):
            if lmstudio.setup_token() and lmstudio.health()[0]:
                ui.ok(lmstudio.health()[1])
                return True

    if not ui.confirm("Adresse eingeben oder im Netzwerk suchen?", default=True):
        return False
    if ui.confirm("Im Netzwerk nach LM Studio suchen?", default=True):
        if scan.run(extended=False, apply=True) and lmstudio.health()[0]:
            ui.ok(lmstudio.health()[1])
            return True
    address = ui.ask("LM-Studio-Adresse", default=lmstudio.base_url(),
                     hint="http://127.0.0.1:1234/v1")
    lmstudio.set_base_url(address)
    healthy, detail = lmstudio.health()
    (ui.ok if healthy else ui.fail)(detail)
    return healthy


def choose_model() -> bool:
    ui.heading("Modell")
    chosen = lmstudio.select_model_interactively()
    if not chosen:
        ui.warn("Kein Modell gesetzt. In LM Studio unter „My Models“ ein Modell laden, "
                "dann hier erneut wählen — sonst startet Jarvis zwar, findet aber keins.")
        return False
    ui.ok(f"Modell: {chosen}  (LM_STUDIO_MODEL in {ctx.ENV_FILE.name})")
    return True


def setup_token() -> bool:
    ui.heading("LM-Studio-Token")
    if lmstudio.token():
        good, message = lmstudio.verify_token(lmstudio.token())
        if good:
            ui.status("ok", "Token", "vorhanden und gültig", message)
            return True
        ui.warn(f"Das gespeicherte Token wird abgelehnt: {message}")
    if not ui.confirm("Jetzt ein Token einfügen?", default=True):
        return False
    return lmstudio.setup_token()


def setup_mcp() -> bool:
    lmstudio.ensure_mcp_token()
    lmstudio.explain_mcp()
    paths = lmstudio.mcp_json_paths()
    if paths:
        if ui.confirm(f"Jarvis-Eintrag direkt in {paths[0]} eintragen?", default=True):
            good, message = lmstudio.install_mcp_entry(paths[0])
            (ui.ok if good else ui.fail)(message)
            return good
        if ui.confirm("Stattdessen den Block in die Zwischenablage kopieren?", default=True):
            lmstudio.clipboard(lmstudio.mcp_json_text())
            ui.ok("Block liegt in der Zwischenablage.")
        return False
    ui.note("Keine mcp.json im Benutzerprofil gefunden — den Block oben in LM Studio "
            "unter „Program“ → „Install“ → „Edit mcp.json“ einfügen.")
    if ui.confirm("Block trotzdem in die Zwischenablage kopieren?", default=True):
        lmstudio.clipboard(lmstudio.mcp_json_text())
        ui.ok("Block liegt in der Zwischenablage.")
    return False


def setup_extras() -> None:
    ui.heading("Optional")
    if ui.confirm("Hotkey-Listener starten?", default=True):
        server.hotkey_start()
    if ui.confirm("Autostart beim Anmelden einrichten?", default=False):
        server.autostart_enable()
    ui.note("Browser-Agent: den Ordner chrome-extension in Chrome über chrome://extensions "
            "als entpackte Erweiterung laden — nur für die Tab-Steuerung nötig.")


# --------------------------------------------------------------------- runs
def wizard(interactive: bool = True, extras: bool = False) -> bool:
    ui.title("Jarvis einrichten",
             "Installation · LM Studio · Token · Netzwerk — Schritt für Schritt")
    stages: list[tuple[str, Callable[[], bool]]] = [
        ("Python prüfen", check_python),
        (".venv anlegen", create_venv),
        ("Pakete installieren", install_dependencies),
        (".env anlegen", create_env_file),
    ]
    if interactive:
        stages += [
            ("LM Studio verbinden", connect_lm_studio),
            ("Modell wählen", choose_model),
            ("LM-Studio-Token", setup_token),
            ("MCP-Eintrag", setup_mcp),
        ]
    results: list[tuple[str, bool]] = []
    for name, stage in stages:
        results.append((name, stage()))
    if interactive and extras:
        setup_extras()

    ui.heading("Zusammenfassung")
    for name, ok in results:
        ui.status("ok" if ok else "warn", name, "erledigt" if ok else "offen")
    ui.out()
    if all(ok for _, ok in results):
        ui.ok("Fertig. Als Nächstes:  jarvis start")
        return True
    ui.warn("Einige Schritte sind offen — jarvis setup wiederholt sie, jarvis doctor zeigt Details.")
    return False


def quick_install(force: bool = False) -> bool:
    """Non-interactive: only what needs no question answered."""
    ui.title("Jarvis installieren", "venv, Pakete, .env, MCP-Token")
    results = [check_python(), create_venv(), install_dependencies(force=force), create_env_file()]
    lmstudio.ensure_mcp_token()
    ui.out()
    if all(results):
        ui.ok("Fertig — als Nächstes:  jarvis token   und   jarvis model")
        return True
    ui.fail("Installation unvollständig — jarvis setup für den interaktiven Weg.")
    return False


def first_run_notice() -> None:
    """Shown by the bare `jarvis` command when the project isn't set up yet."""
    missing = needs_setup()
    ui.title("Willkommen bei Jarvis", "Die Installation ist noch nicht abgeschlossen")
    ui.status("warn", "Fehlt noch", ", ".join(missing) if missing else "nichts")
    ui.out()
    ui.note("Der Assistent prüft Python, legt .venv an, installiert die Pakete, "
            "erzeugt die .env, verbindet LM Studio und trägt Token und MCP-Eintrag ein.")
    ui.out()
    if ui.confirm("Jetzt einrichten?", default=True):
        wizard()
    else:
        ui.note("Später:  jarvis setup")


def banner() -> None:
    ui.title("Jarvis", "Lokaler Sprachassistent — verwalten, einrichten, verbinden")
    ui.status("info", "Projektordner", str(ctx.ROOT))
    ui.status("info", "LM Studio", lmstudio.base_url())
    ui.status("info", "Modell", lmstudio.model())
    ui.status("info", "Netz", scan.describe())
