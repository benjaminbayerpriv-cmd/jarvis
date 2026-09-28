"""Command line parsing and dispatch.

`python jarvis.py` with no arguments opens the interactive menu; every menu
entry also exists as a subcommand so the CLI can be scripted (start it at
login, read the token from the clipboard, scan on a schedule, …).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import configfile, context as ctx
from . import doctor, install, lmstudio, menu, scan, server
from .ui import ui

EPILOG = """Beispiele:
  jarvis                     Interaktives Menü (ohne Argumente)
  jarvis setup               Einrichtungs-Assistent für eine frische Installation
  jarvis install             Installation ohne Rückfragen
  jarvis deps                Fehlende Pakete nachinstallieren (bei Import-Fehlern)
  jarvis token               LM-Studio-Token aus der Zwischenablage einfügen
  jarvis scan --extended     Netzwerksuche über alle üblichen LLM-Ports
  jarvis start --no-browser  Server im Hintergrund starten
  jarvis stop                Server beenden
  jarvis doctor              Alles prüfen
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="Jarvis verwalten: installieren, starten, stoppen, LM Studio verbinden.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("menu", help="Interaktives Menü (Standard)")

    setup = sub.add_parser("setup", help="Einrichtungs-Assistent (Python, venv, Pakete, LM Studio, Token)")
    setup.add_argument("--extras", action="store_true", help="auch Hotkey/Autostart anbieten")

    install_parser = sub.add_parser("install", help="Installation ohne Rückfragen")
    install_parser.add_argument("--force", action="store_true", help="Pakete neu installieren")

    deps = sub.add_parser("deps", help="Fehlende Pakete installieren (behebt Import-Fehler)")
    deps.add_argument("--force", action="store_true", help="alles neu installieren, nicht nur Fehlendes")

    sub.add_parser("doctor", help="Alles prüfen und Probleme anzeigen")

    status = sub.add_parser("status", help="Kurzstatus (für Skripte: exit 0 = läuft)")
    status.add_argument("--quiet", action="store_true", help="nur das Wort running/stopped")

    start = sub.add_parser("start", help="Server starten")
    start.add_argument("--no-browser", action="store_true", help="Browser nicht öffnen")
    start.add_argument("--no-wait", action="store_true", help="nicht auf Bereitschaft warten")
    start.add_argument("--hotkey", action="store_true", help="Hotkey-Listener mitstarten")

    sub.add_parser("stop", help="Server beenden")
    restart = sub.add_parser("restart", help="Server neu starten")
    restart.add_argument("--no-browser", action="store_true", help="Browser nicht öffnen")
    sub.add_parser("open", help="Jarvis im Browser öffnen")

    logs = sub.add_parser("logs", help="Server-Log anzeigen")
    logs.add_argument("-n", "--lines", type=int, default=60, help="Anzahl Zeilen (Standard 60)")
    logs.add_argument("-f", "--follow", action="store_true", help="mitlesen, bis Strg+C")

    token = sub.add_parser("token", help="LM-Studio-API-Token einfügen/entfernen")
    token.add_argument("--set", dest="value", metavar="TOKEN", help="Token direkt angeben")
    token.add_argument("--clipboard", action="store_true", help="Nur aus der Zwischenablage (kein Dialog)")
    token.add_argument("--show", action="store_true", help="gespeichertes Token anzeigen")
    token.add_argument("--clear", action="store_true", help="Token entfernen")

    scan_parser = sub.add_parser("scan", help="Netzwerksuche nach LM Studio")
    scan_parser.add_argument("--extended", "-e", action="store_true",
                             help="alle üblichen LLM-Ports statt nur 1234")
    scan_parser.add_argument("--no-apply", action="store_true", help="nur anzeigen, nichts speichern")

    model = sub.add_parser("model", help="Modell wählen")
    model.add_argument("name", nargs="?", help="Modellname; ohne Angabe Liste der geladenen Modelle")

    sub.add_parser("models", help="Modelle in LM Studio anzeigen")

    mcp = sub.add_parser("mcp", help="mcp.json-Eintrag für LM Studio anzeigen")
    mcp.add_argument("--copy", action="store_true", help="in die Zwischenablage kopieren")
    mcp.add_argument("--install", metavar="PATH", nargs="?", const="", help="in eine mcp.json eintragen")

    hotkey = sub.add_parser("hotkey", help="Hotkey-Listener")
    hotkey.add_argument("action", nargs="?", choices=["start", "stop", "status"], default="status")

    auto = sub.add_parser("autostart", help="Autostart beim Anmelden")
    auto.add_argument("action", nargs="?", choices=["on", "off", "status"], default="status")

    sub.add_parser("build", help="Jarvis.exe bzw. Jarvis.app bauen")
    sub.add_parser("folder", help="Projektordner im Explorer/Finder öffnen")

    ask = sub.add_parser("ask", help="Jarvis eine Frage stellen (Server muss laufen)")
    ask.add_argument("question", nargs="*", help="Frage; ohne Angabe interaktiv")
    ask.add_argument("--mode", choices=["chat", "code"], default="chat")

    tests = sub.add_parser("test", help="test_jarvis.py und test_features.py ausführen")
    tests.add_argument("--script", choices=["test_jarvis.py", "test_features.py"], help="nur dieses")

    sub.add_parser("config", help="config.json anzeigen")
    config_set = sub.add_parser("set", help="Einstellung in .env setzen (KEY=VALUE)")
    config_set.add_argument("pairs", nargs="+", metavar="KEY=WERT")
    return parser


def cmd_status(args) -> int:
    running = server.is_running()
    if getattr(args, "quiet", False):
        ui.out("running" if running else "stopped")
        return 0 if running else 1
    install.banner()
    ui.out()
    for kind, label, value, hint in server.summary_lines():
        ui.status(kind, label, value, hint)
    return 0 if running else 1


def cmd_token(args) -> int:
    if args.show:
        value = lmstudio.token()
        if not value:
            ui.info("Kein Token gesetzt.")
            return 1
        ui.out(value)
        return 0
    if args.clear:
        if not lmstudio.token():
            ui.info("Kein Token gesetzt.")
            return 0
        lmstudio.clear_token()
        ui.ok("Token entfernt.")
        return 0
    if args.value:
        good, message = lmstudio.verify_token(args.value)
        if not good and not ui.confirm("Trotzdem speichern?", default=False):
            ui.fail(message)
            return 1
        lmstudio.set_token(args.value)
        ui.ok(f"Token gespeichert. {message}")
        return 0
    if args.clipboard:
        return 0 if lmstudio.setup_token(interactive=False) else 1
    return 0 if lmstudio.setup_token(interactive=True) else 1


def cmd_scan(args) -> int:
    found = scan.run(extended=args.extended, apply=not args.no_apply)
    return 0 if found else 1


def cmd_model(args) -> int:
    if args.name:
        lmstudio.set_model(args.name)
        ui.ok(f"LM_STUDIO_MODEL = {args.name}")
        ui.note("Wirkt ab dem nächsten Chat — die laufende Sitzung behält ihr Modell "
                "bis zu einem jarvis restart.")
        return 0
    if not ctx.ENV_FILE.exists():
        ui.warn("Keine .env vorhanden — bitte zuerst jarvis setup.")
        return 1
    loaded = lmstudio.loaded_models()
    all_models = lmstudio.all_models()
    if not loaded and not all_models:
        ui.fail("LM Studio meldet keine Modelle — erst dort eines laden.")
        return 1
    ui.heading("Modelle")
    rows = []
    for entry in all_models:
        identifier = entry["id"]
        state = "ok" if identifier in loaded else "warn"
        if identifier == lmstudio.model():
            state = "info"
        size = f"{entry['size'] / 1024 ** 3:.1f} GB" if entry["size"] else "?"
        rows.append((state, identifier, size, "geladen" if identifier in loaded else "auf Platte"))
    ui.table(("OK", "Modell", "Größe", "Status"), rows, mark_col=0)
    ui.out()
    ui.note(f"Aktiv für Jarvis: {lmstudio.model()}")
    ui.note("Wechseln:  jarvis model <name>   oder im Menü: LM Studio → Modell wählen")
    return 0


def cmd_models(args) -> int:
    return cmd_model(argparse.Namespace(name=None))


def cmd_mcp(args) -> int:
    lmstudio.explain_mcp()
    if args.copy:
        lmstudio.clipboard(lmstudio.mcp_json_text())
        ui.ok("Block liegt in der Zwischenablage.")
    if args.install is not None:
        if args.install == "":
            paths = lmstudio.mcp_json_paths()
            if not paths:
                ui.fail("Keine mcp.json gefunden — Pfad angeben: jarvis mcp --install PFAD")
                return 1
            target = paths[0]
        else:
            target = ctx.Path(args.install)
        if not target.exists():
            ui.fail(f"{target} existiert nicht.")
            return 1
        good, message = lmstudio.install_mcp_entry(target)
        (ui.ok if good else ui.fail)(message)
        return 0 if good else 1
    return 0


def cmd_hotkey(args) -> int:
    if args.action == "start":
        return 0 if server.hotkey_start() else 1
    if args.action == "stop":
        server.hotkey_stop()
        return 0
    running = server.hotkey_running()
    ui.out("running" if running else "stopped")
    return 0 if running else 1


def cmd_autostart(args) -> int:
    if args.action == "on":
        return 0 if server.autostart_enable() else 1
    if args.action == "off":
        return 0 if server.autostart_disable() else 1
    installed = server.autostart_installed()
    ui.out("on" if installed else "off")
    return 0 if installed else 1


def cmd_ask(args) -> int:
    question = " ".join(args.question).strip()
    if not question:
        question = ui.ask("Was soll Jarvis fragen?")
    if not question:
        return 1
    if not server.is_running():
        ui.fail("Jarvis läuft nicht — erst  jarvis start")
        return 1
    payload, error = ctx.http_json(
        f"{server.url()}/chat", timeout=300, method="POST",
        headers={"Content-Type": "application/json"},
        body={"message": question, "mode": args.mode},
    )
    ui.out()
    if error:
        ui.fail(error)
        return 1
    ui.out(str((payload or {}).get("reply", "")))
    return 0


def cmd_set(args) -> int:
    updates = {}
    for pair in args.pairs:
        key, _, value = pair.partition("=")
        if not key or not _:
            ui.fail(f"Ungültiges Paar: {pair} (erwartet KEY=WERT)")
            return 1
        updates[key.strip()] = value
    ctx.write_env(updates)
    ui.heading("Gespeichert")
    for key, value in updates.items():
        ui.status("ok", key, ctx.secret(value) if "KEY" in key or "TOKEN" in key else value, "")
    ui.note("Einige Werte liest Jarvis erst beim nächsten Start —  jarvis restart")
    return 0


def cmd_test(args) -> int:
    python = ctx.backend_python()
    if python is None:
        ui.fail("Kein .venv — erst  jarvis setup")
        return 1
    # The tests boot the backend in-process, which needs the MCP port for
    # itself — a running server would collide with it.
    was_running = server.is_running()
    if was_running and not ui.confirm(
            "Ein Jarvis-Server läuft und belegt den Test-Port 8765 — "
            "stoppen und nach dem Test wieder starten?", default=True):
        ui.info("Test abgebrochen.")
        return 1
    if was_running:
        server.stop()
    scripts = [args.script] if args.script else ["test_jarvis.py", "test_features.py"]
    failed = 0
    for script in scripts:
        if not (ctx.ROOT / script).exists():
            continue
        with ui.spinner(f"{script} läuft"):
            result = subprocess.run([str(python), script], cwd=str(ctx.ROOT),
                                    capture_output=True, text=True, timeout=900,
                                    encoding="utf-8", errors="replace",
                                    creationflags=ctx.no_window())
        if result.returncode == 0:
            ui.ok(f"{script} bestanden")
        else:
            failed += 1
            ui.fail(f"{script} fehlgeschlagen")
            ui.lines("\n".join((result.stdout or result.stderr or "").splitlines()[-12:]))
    if was_running:
        if server.start(open_browser=False, quiet=True):
            ui.ok("Server wieder gestartet.")
        else:
            ui.fail("Server konnte nach dem Test nicht gestartet werden —  jarvis start")
    return 1 if failed else 0


def cmd_doctor(args) -> int:
    _, warns, fails = doctor.run()
    return 1 if fails else 0


def cmd_config(args) -> int:
    data = configfile.read_config()
    ui.heading("config.json")
    if data:
        ui.table(("Schlüssel", "Wert"), [(k, str(v)) for k, v in data.items()])
    else:
        ui.info("leer oder nicht vorhanden")
    ui.out()
    ui.note("Ändern:  jarvis set name=…  (alle übrigen Werte stecken in .env) "
            "oder im Menü: config.json")
    ui.out(ui.paint(json.dumps(data, indent=2, ensure_ascii=False), "grey"))
    return 0


COMMANDS = {
    "menu": lambda args: menu.run(),
    "setup": lambda args: install.wizard(interactive=True, extras=args.extras),
    "install": lambda args: install.quick_install(force=args.force),
    "deps": lambda args: install.ensure_deps(force=args.force),
    "doctor": cmd_doctor,
    "status": cmd_status,
    "start": lambda args: (server.start(not args.no_browser, not args.no_wait)
                           and (server.hotkey_start() if args.hotkey else True)),
    "stop": lambda args: (server.stop(), True)[1],
    "restart": lambda args: server.restart(open_browser=not args.no_browser),
    "open": lambda args: (server.open_ui(), True)[1],
    "logs": lambda args: server.logs(args.lines, args.follow),
    "token": cmd_token,
    "scan": cmd_scan,
    "model": cmd_model,
    "models": cmd_models,
    "mcp": cmd_mcp,
    "hotkey": cmd_hotkey,
    "autostart": cmd_autostart,
    "ask": cmd_ask,
    "set": cmd_set,
    "config": cmd_config,
    "test": cmd_test,
    "build": lambda args: (server.build_exe(), True)[1],
    "folder": lambda args: (server.open_folder(), True)[1],
}


def _to_exit(result: object) -> int:
    """Unify whatever a handler returned into a process exit code: None or
    True mean success (0), False means failure (1), tuples follow their error
    count, integers pass straight through."""
    if result is None:
        return 0
    if isinstance(result, bool):
        return 0 if result else 1
    if isinstance(result, tuple):
        return 0 if len(result) < 3 or not result[-1] else 1
    try:
        return int(result)
    except (TypeError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        return menu.run()
    args = parser.parse_args(argv)
    command = args.command or "menu"
    handler = COMMANDS.get(command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        result = handler(args)
    except KeyboardInterrupt:
        ui.out()
        ui.info("Abgebrochen.")
        return 130
    except Exception as exc:
        ui.fail(f"{exc.__class__.__name__}: {exc}")
        if "--debug" in argv:
            raise
        ui.note("Mehr Details:  jarvis doctor  oder  jarvis logs")
        return 1
    return _to_exit(result)
