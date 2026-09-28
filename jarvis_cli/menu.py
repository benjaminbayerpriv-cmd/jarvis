"""The interactive screen: a menu that manages a running Jarvis, and
submenus for everything that needs a question answered.

`python jarvis.py` with no arguments lands here. The frame is redrawn from
scratch on every loop so the state lines (server, LM Studio, token) are never
stale, and every entry returns to the same screen instead of a stack of
sub-prompts.
"""

from __future__ import annotations

import subprocess
import time

from . import context as ctx
from . import doctor, install, lmstudio, scan, server
from .ui import ui

SETTINGS: list[tuple[str, str, str, str]] = [
    # (env key, label, hint, kind: text|secret|choice)
    ("LM_STUDIO_BASE_URL", "LM-Studio-Adresse", "http://127.0.0.1:1234/v1", "text"),
    ("LM_STUDIO_MODEL", "Chat-Modell", "siehe jarvis model", "model"),
    ("EMBEDDING_MODEL", "Embedding-Modell", "für die semantische Suche im Gedächtnis", "text"),
    ("WHISPER_MODEL", "Whisper-Modell", "tiny/base/small/medium/large", "text"),
    ("SUPERTONIC_VOICE", "Stimme (Supertonic)", "z. B. M1", "text"),
    ("SUPERTONIC_LANG", "Sprache", "de/en …", "text"),
    ("ELEVENLABS_API_KEY", "ElevenLabs-Key", "optional, sonst lokale Stimme", "secret"),
    ("ELEVENLABS_VOICE_ID", "ElevenLabs-Stimme", "Voice-ID", "text"),
    ("TAVILY_API_KEY", "Tavily-Key", "optional, für echte Web-Suche", "secret"),
    ("DEEPSEEK_API_KEY", "DeepSeek-Key", "optional, Cloud-Modell statt lokal", "secret"),
    ("DEEPSEEK_MODEL", "DeepSeek-Modell", "deepseek-chat …", "text"),
    ("DEEPSEEK_ENABLED", "DeepSeek aktiv", "true/false", "bool"),
    ("JARVIS_HOST", "Server-Adresse", "127.0.0.1", "text"),
    ("JARVIS_PORT", "Server-Port", "8000", "text"),
    ("JARVIS_MCP_PORT", "MCP-Port", "8765", "text"),
]


# ------------------------------------------------------------------ helpers
def _edit(key: str, label: str, hint: str, kind: str) -> None:
    current = ctx.env(key)
    if kind == "bool":
        value = "false" if ui.confirm(f"{label} ausschalten?", default=current != "false") else "true"
    elif kind == "model":
        chosen = lmstudio.select_model_interactively()
        if not chosen:
            return
        value = chosen
    else:
        value = ui.ask(label, default=current, hint=hint, password=kind == "secret")
    if value == current:
        ui.info("Unverändert.")
        return
    ctx.write_env({key: value})
    ui.ok(f"{key} = {ctx.secret(value) if kind == 'secret' else value}")
    ui.note("Für Einstellungen, die erst beim Start wirken: jarvis restart")


# ------------------------------------------------------------------- actions
def act_start() -> None:
    if server.is_running():
        ui.ok(f"Läuft bereits auf {server.url()}")
        return
    browser = ui.confirm("Browser mit Jarvis öffnen?", default=True)
    hotkey = not server.hotkey_running()
    if server.start(open_browser=browser):
        if hotkey and ui.confirm("Hotkey-Listener mitstarten?", default=True):
            server.hotkey_start()
        if not browser:
            ui.note(f"Im Browser öffnen: {server.url()}")


def act_stop() -> None:
    if not server.is_running():
        ui.info("Jarvis läuft nicht.")
    elif ui.confirm("Jarvis wirklich beenden?", default=True):
        server.stop()
        if server.hotkey_running() and ui.confirm("Hotkey-Listener auch beenden?", default=True):
            server.hotkey_stop()


def act_restart() -> None:
    was_running = server.is_running()
    server.restart(open_browser=False)
    if was_running:
        ui.note(f"Neu gestartet — Browser ggf. neu laden: {server.url()}")


def act_open() -> None:
    server.open_ui()


def act_logs() -> None:
    while True:
        lines = ui.ask("Wie viele Zeilen?", default="60", allow_empty=True)
        if not lines:
            return
        try:
            server.logs(int(lines))
            return
        except ValueError:
            ui.warn("Bitte eine Zahl eingeben.")


def act_ask() -> None:
    """A question straight to the running server — a sanity check that model,
    MCP tools and memory all work, without opening the browser."""
    if not server.is_running():
        ui.warn("Jarvis läuft nicht — erst starten.")
        return
    question = ui.ask("Was soll Jarvis fragen?", hint="z. B. Wie spät ist es?")
    if not question:
        return
    payload, error = ctx.http_json(
        f"{server.url()}/chat", timeout=300, method="POST",
        headers={"Content-Type": "application/json"},
        body={"message": question, "mode": "chat"},
    )
    ui.out()
    if error:
        ui.fail(f"Anfrage fehlgeschlagen: {error}")
        ui.note("Steht der Server noch?  jarvis logs")
        return
    ui.out("  " + str((payload or {}).get("reply", "")).replace("\n", "\n  "))


def act_lmstudio() -> None:
    while True:
        healthy, detail = lmstudio.health()
        entries = [
            ("health", f"Verbindung prüfen  ·  {detail}", "health"),
            ("base", f"Adresse ändern  ·  {lmstudio.base_url()}", "base"),
            ("model", f"Modell wählen  ·  {lmstudio.model()}", "model"),
            ("load", "Modell jetzt laden", "load"),
            ("unload", "Andere Modelle entladen", "unload"),
            ("scan", "Im Netzwerk suchen", "scan"),
            ("back", "Zurück", "back"),
        ]
        ui.heading("LM Studio")
        index = ui.choose("Was möchtest du?", entries)
        if index is None:
            return
        action = entries[index][0]
        if action == "health":
            good, message = lmstudio.health()
            (ui.ok if good else ui.fail)(message)
        elif action == "base":
            url = ui.ask("Neue Adresse", default=lmstudio.base_url())
            lmstudio.set_base_url(url)
            good, message = lmstudio.health()
            (ui.ok if good else ui.fail)(f"{lmstudio.base_url()} — {message}")
        elif action == "model":
            lmstudio.select_model_interactively()
        elif action == "load":
            with ui.spinner(f"{lmstudio.model()} wird geladen"):
                good, message = lmstudio.load_model(lmstudio.model())
            (ui.ok if good else ui.fail)(message)
        elif action == "unload":
            loaded = lmstudio.loaded_models()
            keep = lmstudio.model()
            choices = [(m, m) for m in loaded if m != keep]
            if not choices:
                ui.info("Neben dem aktiven Modell ist nichts geladen.")
            else:
                picked = ui.choose("Welches Modell entladen?", choices)
                if picked is not None:
                    good, message = lmstudio.unload_model(choices[picked][0])
                    (ui.ok if good else ui.fail)(message)
        elif action == "scan":
            scan.run(extended=ui.confirm("Erweiterte Suche (9 Ports)?", default=False))
        else:
            return


def act_token() -> None:
    while True:
        entries = [
            ("set", "Token einfügen (Zwischenablage oder tippen)", "set"),
            ("show", f"Gespeichertes Token anzeigen  ·  {ctx.secret(lmstudio.token(), 6)}", "show"),
            ("clear", "Token entfernen", "clear"),
            ("back", "Zurück", "back"),
        ]
        ui.heading("LM-Studio-API-Token")
        good, message = lmstudio.health()
        ui.status("ok" if good else "warn", "LM Studio", "verbunden" if good else "Probleme", message)
        index = ui.choose("Was möchtest du?", entries)
        if index is None:
            return
        action = entries[index][0]
        if action == "set":
            lmstudio.setup_token()
        elif action == "show":
            value = lmstudio.token()
            if not value:
                ui.info("Kein Token gesetzt — nicht nötig, solange LM Studio keine Auth verlangt.")
            elif ui.confirm("Token im Klartext anzeigen?", default=False):
                ui.out("  " + value)
        elif action == "clear":
            if lmstudio.token() and ui.confirm("Token wirklich löschen?", default=False):
                lmstudio.clear_token()
                ui.ok("Token entfernt.")
        else:
            return


def act_mcp() -> None:
    ui.title("MCP-Server", "Damit das Modell Jarvis' Werkzeuge benutzen kann")
    lmstudio.explain_mcp()
    ui.out()
    entries = [
        ("copy", "Block in die Zwischenablage kopieren", "copy"),
        ("install", "Direkt in eine mcp.json eintragen", "install"),
        ("manual", "Pfad zu einer mcp.json angeben", "manual"),
        ("back", "Zurück", "back"),
    ]
    index = ui.choose("Wie fortfahren?", entries)
    if index is None:
        return
    action = entries[index][0]
    if action == "copy":
        lmstudio.clipboard(lmstudio.mcp_json_text())
        ui.ok("Block liegt in der Zwischenablage.")
    elif action == "install":
        paths = lmstudio.mcp_json_paths()
        target = paths[0] if paths else None
        if target is None:
            entered = ui.ask("Pfad zur mcp.json", default=str(ctx.Path.home() / ".lmstudio" / "mcp.json"))
            target = ctx.Path(entered)
        if not target.exists():
            if not ui.confirm(f"{target} existiert nicht — neu anlegen?", default=True):
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{\n  "mcpServers": {}\n}\n', encoding="utf-8")
        good, message = lmstudio.install_mcp_entry(target)
        (ui.ok if good else ui.fail)(message)
        if good:
            ui.note("In LM Studio „Developer → Server Settings“ → „Allow calling servers "
                    "from mcp.json“ einschalten — erst dann darf LM Studio den Server aufrufen.")
    elif action == "manual":
        ui.out("  " + lmstudio.mcp_json_text().replace("\n", "\n  "))


def act_settings() -> None:
    while True:
        rows = []
        for key, label, _, kind in SETTINGS:
            value = ctx.env(key)
            shown = ctx.secret(value) if kind == "secret" else (value or "—")
            state = "ok" if value else "warn"
            rows.append((state, label, shown, ui.truncate(key, 26)))
        ui.table(("OK", "Einstellung", "Wert", "Variable"), rows, mark_col=0)
        index = ui.choose("Welche Einstellung ändern?",
                          [(k, l) for k, l, _, _ in SETTINGS] + [("--", "Zurück")])
        if index is None or index == len(SETTINGS):
            return
        key, label, hint, kind = SETTINGS[index]
        _edit(key, label, hint, kind)


def act_config_json() -> None:
    """config.json — name, personality, weather city, code agent, code dir."""
    from .configfile import read_config, write_config, describe

    while True:
        data = read_config()
        rows = [(k, str(v)) for k, v in data.items()]
        ui.heading("config.json")
        if rows:
            ui.table(("Schlüssel", "Wert"), rows)
        else:
            ui.info("config.json ist leer oder fehlt.")
        options = [("__add__", "Neuen Schlüssel setzen (z. B. name, default_city, code_agent)"),
                   ("__back__", "Zurück")]
        index = ui.choose("Was ändern?", options)
        if index is None or index == 1:
            return
        key = ui.ask("Schlüssel", default="name")
        value = ui.ask("Wert")
        if not key:
            return
        write_config({key: value})
        ui.ok(f"config.json: {key} = {value}  ({describe()})")


def act_hotkey() -> None:
    running = server.hotkey_running()
    combo = "Ctrl+Shift+J" if ctx.IS_WINDOWS else "Cmd+Shift+J"
    ui.heading("Hotkey")
    ui.status("ok" if running else "warn", "Listener", "läuft" if running else "gestoppt", combo)
    if running:
        if ui.confirm("Beenden?", default=True):
            server.hotkey_stop()
    else:
        if ui.confirm("Starten?", default=True):
            server.hotkey_start()


def act_autostart() -> None:
    installed = server.autostart_installed()
    ui.heading("Autostart")
    ui.status("ok" if installed else "warn", "Beim Anmelden",
              "aktiviert" if installed else "aus", "Server + Hotkey" if installed else "")
    if installed:
        if ui.confirm("Autostart entfernen?", default=True):
            server.autostart_disable()
    elif ui.confirm("Autostart einrichten?", default=True):
        server.autostart_enable()


def act_build() -> None:
    ui.heading("App bauen")
    if ctx.IS_WINDOWS:
        ui.note("Erzeugt launcher\\dist\\Jarvis.exe — ein Doppelklick-Programm mit eigenem Fenster.")
    else:
        ui.note("Unter macOS: launcher/build_app.sh (baut die .app).")
    if ui.confirm("Jetzt bauen?", default=False):
        server.build_exe() if ctx.IS_WINDOWS else ui.info("Bitte launcher/build_app.sh ausführen.")


def act_doctor() -> None:
    doctor.run()
    if ui.confirm("Fehlende Schritte jetzt ausführen?", default=True):
        install.wizard(interactive=True)


def act_tests() -> None:
    python = ctx.backend_python()
    if python is None:
        ui.fail("Kein .venv — erst jarvis setup.")
        return
    for script in ("test_jarvis.py", "test_features.py"):
        if not (ctx.ROOT / script).exists():
            continue
        ui.info(f"{script} …")
        started = time.time()
        with ui.spinner(f"{script} läuft"):
            result = subprocess.run([str(python), script], cwd=str(ctx.ROOT), capture_output=True,
                                    text=True, timeout=900, encoding="utf-8", errors="replace",
                                    creationflags=ctx.no_window())
        passed = result.returncode == 0
        (ui.ok if passed else ui.fail)(
            f"{script}: {'bestanden' if passed else 'fehlgeschlagen'} "
            f"({time.time() - started:.1f}s)"
        )
        if not passed:
            ui.lines("\n".join((result.stdout or "")[-2000:].splitlines()[-12:]))


def act_setup() -> None:
    install.wizard(interactive=True, extras=True)


def act_folder() -> None:
    server.open_folder()


# --------------------------------------------------------------------- menu
def entries(running: bool) -> list[tuple[str, str, str]]:
    return [
        ("stop" if running else "start",
         "Jarvis stoppen" if running else "Jarvis starten",
         f"läuft auf {server.url()}" if running else "Server, Whisper und Modell werden geladen"),
        ("restart", "Neu starten", "Konfigurationsänderungen wirksam machen"),
        ("open", "Im Browser öffnen", server.url()),
        ("ask", "Jarvis etwas fragen", "ohne Browser testen, ob Modell antwortet"),
        ("logs", "Server-Log anzeigen", str(ctx.SERVER_LOG.relative_to(ctx.ROOT))),
        ("lmstudio", "LM Studio", f"{lmstudio.base_url()} · {lmstudio.model()}"),
        ("token", "LM-Studio-Token", "aus Zwischenablage einfügen oder eintippen"),
        ("scan", "Netzwerksuche", "LM Studio im Netzwerk finden"),
        ("mcp", "MCP-Eintrag (mcp.json)", "damit das Modell Werkzeuge benutzen kann"),
        ("settings", "Einstellungen", "Modell, Stimme, Websuche, Ports, Tokens"),
        ("config", "config.json", "Name, Persönlichkeit, Wetterstadt, Code-Agent"),
        ("hotkey", "Hotkey-Listener", "läuft" if server.hotkey_running() else "gestoppt"),
        ("autostart", "Autostart", "aktiv" if server.autostart_installed() else "aus"),
        ("doctor", "Doctor", "alles prüfen und fehlende Schritte anbieten"),
        ("deps", "Pakete nachinstallieren", "behebt Import-Fehler, legt .venv ggf. neu an"),
        ("update", "Update (git pull)", "neueste Version von GitHub holen, Server neu starten"),
        ("setup", "Einrichtung (Assistent)", "Installation, Token, Modell, MCP"),
        ("tests", "Tests ausführen", "test_jarvis.py, test_features.py"),
        ("build", "App bauen", "Jarvis.exe bzw. Jarvis.app"),
        ("folder", "Projektordner öffnen", str(ctx.ROOT)),
    ]


HANDLERS = {
    "start": act_start, "stop": act_stop, "restart": act_restart, "open": act_open,
    "ask": act_ask, "logs": act_logs, "lmstudio": act_lmstudio, "token": act_token,
    "scan": lambda: scan.run(), "mcp": act_mcp, "settings": act_settings,
    "config": act_config_json, "hotkey": act_hotkey, "autostart": act_autostart,
    "doctor": act_doctor, "deps": lambda: install.ensure_deps(), "update": lambda: install.update(),
    "setup": act_setup,
    "tests": act_tests, "build": act_build,
    "folder": act_folder,
}


def frame() -> list[tuple[str, str, str]]:
    install.banner()
    ui.out()
    for kind, label, value, hint in server.summary_lines():
        ui.status(kind, label, value, hint)
    return entries(server.is_running())


def run() -> int:
    if not install.is_ready():
        install.first_run_notice()
    while True:
        ui.clear_screen()
        table = frame()
        ui.out()
        index = ui.menu(table)
        if index is None:
            ui.out()
            if server.is_running():
                ui.ok("Jarvis läuft weiter — Beenden mit  jarvis stop")
            ui.ok("Tschüss.")
            return 0
        key = table[index][0]
        try:
            HANDLERS[key]()
        except KeyboardInterrupt:
            ui.out()
            ui.info("Abgebrochen.")
        except Exception as exc:  # a broken handler must not kill the menu
            ui.fail(f"Unerwarteter Fehler: {exc.__class__.__name__}: {exc}")
            ui.note("Mit  jarvis doctor  prüfen oder  jarvis logs  ansehen.")
        ui.pause()
