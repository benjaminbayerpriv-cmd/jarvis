"""Real coding, delegated to the Claude Code CLI.

A local 7B model can hold a conversation but it cannot reliably build a
working project. Rather than pretend otherwise, Jarvis hands coding work to
the `claude` CLI that's already installed on this machine: it gets a
directory and a description, works there with full file access, and Jarvis
reports back and opens the result.

Builds run on a background thread — they take minutes, and blocking the
voice loop that long would make Jarvis feel dead.
"""

import os
import shutil
import subprocess
import threading
from pathlib import Path

from . import panel, platform_utils

CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
BUILD_TIMEOUT_S = 1800  # 30 min

# Interesting files to surface in the panel once a build finishes.
_CODE_SUFFIXES = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
                  ".md", ".sh", ".go", ".rs", ".java", ".rb", ".swift", ".c", ".cpp"}


def expand(location: str) -> Path:
    """Turn what someone says out loud into a real path.

    Voice input arrives as "Desktop/Rechner", "~/Projekte/foo" or just
    "rechner", rarely as a clean absolute path. A leading folder that
    already exists in the home directory is anchored there — otherwise
    "Desktop/rechner" would land in ~/Desktop/Desktop/rechner. Anything
    else is treated as a project name and put on the Desktop.
    """
    location = (location or "").strip().strip("\"'")
    p = Path(os.path.expanduser(location))
    if p.is_absolute():
        return p

    parts = p.parts
    if parts:
        head = parts[0]
        for candidate in (head, head.capitalize()):
            if (Path.home() / candidate).is_dir():
                return Path.home() / candidate / Path(*parts[1:]) if len(parts) > 1 else Path.home() / candidate
    return Path.home() / "Desktop" / p


def open_path(path: Path) -> None:
    """Show the result: editor for the folder, browser for a web page."""
    try:
        if shutil.which("code"):
            subprocess.run(["code", str(path)], timeout=30, capture_output=True)
        elif platform_utils.is_windows():
            os.startfile(str(path))
        else:
            subprocess.run(["open", str(path)], timeout=30, capture_output=True)
    except Exception:
        pass

    index = path / "index.html"
    if index.exists():
        try:
            if platform_utils.is_windows():
                os.startfile(str(index))
            else:
                subprocess.run(["open", str(index)], timeout=30, capture_output=True)
        except Exception:
            pass


def _summarize_result(path: Path) -> None:
    files = []
    for f in sorted(path.rglob("*")):
        if f.is_dir() or any(part.startswith(".") for part in f.parts):
            continue
        if "node_modules" in f.parts or "__pycache__" in f.parts:
            continue
        files.append(str(f.relative_to(path)))
        if len(files) >= 60:
            break

    panel.push("files", title=f"Gebaut in {path}", path=str(path), files=files)

    # Preview the most likely entry point so there's something to look at.
    for candidate in ("index.html", "main.py", "app.py", "app.js", "main.js", "README.md"):
        f = path / candidate
        if f.exists() and f.suffix in _CODE_SUFFIXES:
            try:
                text = f.read_text(errors="replace")[:6000]
                panel.push("code", title=candidate, language=f.suffix.lstrip("."), text=text)
            except Exception:
                pass
            break


def _run_build(path: Path, description: str) -> None:
    path.mkdir(parents=True, exist_ok=True)

    prompt = (
        f"{description}\n\n"
        "Baue das vollständig und lauffähig in diesem Verzeichnis. "
        "Erstelle alle nötigen Dateien. Wenn es eine Web-Oberfläche ist, "
        "erstelle eine index.html, die direkt im Browser funktioniert. "
        "Antworte am Ende mit maximal zwei Sätzen, was du gebaut hast."
    )

    before = {p for p in path.rglob("*") if p.is_file()}

    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--dangerously-skip-permissions"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        panel.push("notify", text="Der Build hat zu lange gedauert und wurde abgebrochen.")
        return
    except Exception as exc:
        panel.push("notify", text=f"Build fehlgeschlagen: {exc}")
        return

    summary = (proc.stdout or "").strip()

    # A non-zero exit means it failed even when something was printed — the
    # auth-failure message arrives on stdout, and reporting "fertig" over an
    # empty folder is the worst possible outcome.
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or summary or "Unbekannter Fehler"
        panel.push("markdown", title="Build fehlgeschlagen", text=detail[:1500])
        spoken = "Der Build ist fehlgeschlagen, Details stehen im Interface."
        if "authenticate" in detail.lower() or "oauth" in detail.lower():
            spoken = ("Ich komme nicht an Claude Code ran, die Anmeldung ist abgelaufen. "
                      "Melde dich im Terminal mit claude einmal neu an.")
        panel.push("notify", text=spoken)
        return

    # Exit 0 but nothing written is still a failure worth admitting.
    created = {p for p in path.rglob("*") if p.is_file()} - before
    if not created:
        panel.push("markdown", title="Nichts gebaut", text=summary[:1500] or "Keine Ausgabe.")
        panel.push("notify", text="Es wurden keine Dateien erstellt. Schau ins Interface.")
        return

    _summarize_result(path)
    if summary:
        panel.push("markdown", title="Claude Code", text=summary[:4000])

    open_path(path)
    panel.push("notify", text=f"Fertig. Ich hab es in {path.name} gebaut und dir geöffnet.")


def start_build(location: str, description: str) -> str:
    """Kick off a build in the background; returns what Jarvis should say now."""
    if not location.strip():
        return "Ich brauche noch einen Ordner, wo ich das bauen soll."

    path = expand(location)
    threading.Thread(target=_run_build, args=(path, description), daemon=True).start()
    return (
        f"Alles klar, ich baue das in {path}. "
        "Das dauert ein paar Minuten, ich sag Bescheid wenn es fertig ist."
    )
