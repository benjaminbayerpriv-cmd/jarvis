"""Real coding, done by Jarvis's own model — no external CLI involved.

Asks the active text model (DeepSeek/LM Studio, same fallback chain as the
voice loop — see llm_client.generate_files) to write out every file for the
project as plain text, then writes them to disk itself. A small local model
won't match a dedicated coding agent, but Jarvis builds it itself rather
than delegating to another program.

Builds run on a background thread — they can take a while, and blocking the
voice loop that long would make Jarvis feel dead.
"""

import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from . import llm_client, panel, platform_utils

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


def _run_build(task_id: str, path: Path, description: str) -> None:
    path.mkdir(parents=True, exist_ok=True)

    try:
        files = llm_client.generate_files(description)
    except Exception as exc:
        panel.push("task", id=task_id, status="failed")
        panel.push("notify", text=f"Build fehlgeschlagen, konnte kein Modell erreichen: {exc}")
        return

    if not files:
        panel.push("task", id=task_id, status="failed")
        panel.push("markdown", title="Nichts gebaut", text="Das Modell hat keine Dateien im erwarteten Format geliefert.")
        panel.push("notify", text="Es wurden keine Dateien erstellt. Schau ins Interface.")
        return

    written = []
    for rel_path, content in files.items():
        try:
            target = path / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            written.append(rel_path)
        except Exception as exc:
            panel.push("notify", text=f"Konnte '{rel_path}' nicht schreiben: {exc}")

    if not written:
        panel.push("task", id=task_id, status="failed")
        panel.push("notify", text="Es wurden keine Dateien erstellt. Schau ins Interface.")
        return

    _summarize_result(path)
    open_path(path)
    panel.push("task", id=task_id, status="done")
    panel.push(
        "notify",
        text=f"Fertig. Ich hab {len(written)} Datei(en) in {path.name} gebaut und dir geöffnet.",
    )


def start_build(location: str, description: str) -> str:
    """Kick off a build in the background; returns what Jarvis should say now."""
    if not location.strip():
        return "Ich brauche noch einen Ordner, wo ich das bauen soll."

    path = expand(location)
    task_id = uuid.uuid4().hex[:8]
    # Announced immediately so the UI can show a second, small "working"
    # orb for the duration of the build — the voice reply below moves on
    # right away, but the build itself keeps running on this thread.
    panel.push("task", id=task_id, status="started", label=f"Baut {path.name}")
    threading.Thread(target=_run_build, args=(task_id, path, description), daemon=True).start()
    return (
        f"Alles klar, ich baue das in {path}. "
        "Das dauert einen Moment, ich sag Bescheid wenn es fertig ist."
    )
