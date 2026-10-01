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

import shutil
import subprocess
import sys
from pathlib import Path
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


def _git_exe() -> str | None:
    """Git binary — on PATH, or known fallback homes (hermes/Git for Windows)."""
    found = shutil.which("git")
    if found:
        return found
    for cand in (
        Path.home() / "AppData" / "Local" / "hermes" / "git" / "cmd" / "git.exe",
        Path(r"C:\Program Files\Git\cmd\git.exe"),
    ):
        if cand.exists():
            return str(cand)
    return None


def update() -> bool:
    """Pull the newest version from GitHub, install any new requirements and
    restart a running server so the new code takes effect."""
    ui.heading("Update")
    git = _git_exe()
    if not git:
        ui.fail("Kein Git gefunden — Git für Windows installieren und  jarvis update  erneut.")
        return False
    if not (ctx.ROOT / ".git").exists():
        ui.fail(f"{ctx.ROOT} ist kein Git-Klons — Update geht nur in einer "
                "Kopie, die mit  git clone https://github.com/benjaminbayerpriv-cmd/jarvis  "
                "angelegt wurde.")
        return False

    def git_run(*args: str, timeout: int = 180) -> tuple[int, str]:
        return _run([git, *args], timeout=timeout)

    old = git_run("rev-parse", "HEAD")[1].strip()
    if not old:
        ui.fail("Konnte die aktuelle Revision nicht bestimmen.")
        return False
    was_running = server.is_running()

    dirty = git_run("status", "--porcelain")[1].strip()
    if dirty:
        lines = dirty.splitlines()
        ui.warn(f"{len(lines)} lokal geänderte Datei(en) — das Update holt nur die "
                "neueste Version, deine Änderungen bleiben erhalten (Fast-Forward).")
        if sys.stdin.isatty() and not ui.confirm("Weiter mit dem Update?", default=True):
            ui.info("Abgebrochen.")
            return False

    code, output = git_run("fetch", "--tags", "--prune", "origin", timeout=240)
    if code != 0:
        ui.fail("Zugriff auf GitHub fehlgeschlagen — Internet/GitHub-Login prüfen.")
        ui.lines("\n".join(_tail(output)))
        return False
    remote = git_run("rev-parse", "@{u}")[1].strip()
    if remote == old:
        ui.status("ok", "Version", "schon aktuell", old[:12])
        return True

    ui.info(f"von {old[:12]} auf die neueste Version wird geholt …")
    with ui.spinner("git pull --ff-only"):
        code, output = git_run("pull", "--ff-only")
    if code != 0:
        ui.fail("Schneller Vorlauf war nicht möglich (lokale Commits?). "
                "Kurz die Ausgabe:")
        ui.lines("\n".join(_tail(output)))
        return False
    new = git_run("rev-parse", "HEAD")[1].strip()
    log = git_run("log", "--reverse", "--oneline", "--no-decorate",
                  f"{old}..HEAD")[1].splitlines()
    ui.status("ok", "Version", f"jetzt {new[:12]}", f"vorher {old[:12]}")
    if log:
        ui.info("Neue Commits:")
        for line in log[:10]:
            ui.lines("  " + line)
        if len(log) > 10:
            ui.lines(f"  … und {len(log) - 10} weitere")

    if not ensure_deps():
        ui.note("Version ist da, aber die Paket-Prüfung war nicht grün —  jarvis deps")
        return False
    if was_running and not server.is_running():
        with ui.spinner("Server wird neu gestartet"):
            restart_ok = server.start(open_browser=False, quiet=True)
        if not restart_ok:
            ui.fail("Server konnte nicht neu starten —  jarvis start")
            return False
    elif was_running:
        # Still the old process, i.e. the new code isn't live yet. Only a
        # server started by this CLI can be restarted without pulling the
        # rug from under the app window that owns it (Jarvis.exe).
        if server.running_pid():
            with ui.spinner("Server wird neu gestartet"):
                restart_ok = server.restart(open_browser=False, quiet=True)
            if not restart_ok:
                ui.fail("Server konnte nicht neu starten —  jarvis start")
                return False
        else:
            ui.note("Der Server läuft außerhalb der CLI (z. B. Jarvis.exe) — dort neu starten, "
                    "damit die neue Version aktiv wird.")
    return True


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
        if ctx.venv_python_version() is None:
            ui.fail(".venv ist kaputt — ihr Python startet nicht (meist wurde die zugrunde liegende "
                    "Python-Installation entfernt oder aktualisiert). Den Ordner .venv löschen und "
                    "jarvis setup erneut ausführen.")
            return False
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
        ui.warn("Einige Pakete scheinen zu fehlen —  jarvis deps  installiert nach.")
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


def ensure_deps(force: bool = False) -> bool:
    """Install whatever requirements are missing — the one-command fix for
    ModuleNotFoundError and friends. Creates the .venv on the fly, stops a
    running server briefly (Windows keeps loaded .pyd files locked), pip-installs
    the full requirements.txt, and verifies with the same probe the doctor uses."""
    ui.heading("Pakete nachinstallieren")
    if not create_venv():
        return False
    python = ctx.venv_python()
    missing = ctx.missing_modules(python)
    if not missing and not force:
        ui.status("ok", "Pakete", "vollständig",
                  "alle benötigten Module sind importierbar")
        return True
    if missing:
        ui.warn(f"{len(missing)} Modul(e) fehlen: {', '.join(missing)}")

    was_running = server.is_running()
    if was_running and not ui.confirm(
            "Ein Jarvis-Server läuft und sperrt evtl. Paket-Dateien — "
            "stoppen, installieren und danach wieder starten?", default=True):
        ui.info("Abgebrochen — Pakete bleiben unverändert.")
        return False
    if was_running:
        server.stop()

    ui.info(f"Installiere in {python} …")
    try:
        with ui.spinner("pip wird aktualisiert"):
            _run([str(python), "-m", "pip", "install", "--upgrade", "pip",
                  "--disable-pip-version-check", "-q"], timeout=600)
        with ui.spinner("Pakete werden installiert (fastapi, Whisper, TTS …)"):
            code, output = _run(
                [str(python), "-m", "pip", "install", "-r", str(ctx.ROOT / "requirements.txt"),
                 "--disable-pip-version-check"],
                timeout=PIP_TIMEOUT,
            )
    except subprocess.TimeoutExpired:
        ui.fail("Die Installation brauchte über 60 Minuten und lief noch — "
                "Internetverbindung prüfen, dann  jarvis deps  erneut.")
        return False
    if code != 0:
        ui.fail("Installation fehlgeschlagen — die letzten Zeilen:")
        ui.lines("\n".join(_tail(output)))
        return False
    done = next((line for line in output.splitlines() if line.startswith("Successfully installed")), "")
    count = len(done.split()) - 2 if done else 0
    ui.ok(f"Installation erfolgreich{f' — {count} Pakete' if count else ''}.")

    still_missing = ctx.missing_modules(python)
    if still_missing:
        ui.fail(f"Immer noch nicht importierbar: {', '.join(still_missing)}")
        ui.note("Nach  jarvis logs  schauen — manche Fehler betreffen nicht fehlende Pakete, "
                "sondern native Bibliotheken (z. B. fehlende Microsoft Visual C++ Redistributable).")
        return False
    if was_running:
        if server.start(open_browser=False, quiet=True):
            ui.ok("Server wieder gestartet.")
        else:
            ui.fail("Server konnte nicht neu starten —  jarvis start")
    return True


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
