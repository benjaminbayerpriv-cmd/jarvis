"""Fehlerprotokoll: sammelt Fehler aus Oberfläche und Backend in einer Datei.

Gedacht für die Fehlersuche ohne Zutun des Nutzers: Jeder JavaScript-Fehler
der Oberfläche (POST /errors/client), jede unbehandelte Ausnahme eines
Endpunkts, jeder abgestürzte Tool-Aufruf und jede leere Modellantwort landet
als eine JSON-Zeile in logs/errors.jsonl. `python jarvis.py errors` zeigt sie
zusammengefasst an.

Bewusst robust und sparsam: Schreiben darf nie selbst einen Fehler werfen,
gleiche Meldungen werden innerhalb kurzer Zeit nur gezählt statt
wiederholt geschrieben, und die Datei wird bei 2 MB rotiert.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "errors.jsonl"
MAX_BYTES = 2 * 1024 * 1024
# Dieselbe Meldung (Quelle + Text + erste Stack-Zeile) höchstens einmal pro
# Zeitfenster schreiben — eine Fehlerschleife im Frontend soll die Platte
# nicht mit tausend gleichen Zeilen füllen.
DEDUPE_WINDOW_S = 60
MAX_FIELD = 4000

_lock = threading.Lock()
_recent: dict[str, list] = {}  # key -> [erstes Mal, Anzahl unterdrückt]


def _clip(value, n: int = MAX_FIELD) -> str:
    text = str(value if value is not None else "")
    return text if len(text) <= n else text[: n - 1] + "…"


def _rotate() -> None:
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
            old = LOG_FILE.with_suffix(".jsonl.1")
            old.unlink(missing_ok=True)
            LOG_FILE.replace(old)
    except OSError:
        pass


def record(source: str, kind: str, message: str, *, stack: str = "", context: dict | None = None) -> None:
    """Einen Fehler festhalten. Wirft nie."""
    try:
        message = _clip(message, 1000)
        stack = _clip(stack)
        first_frame = next((line.strip() for line in stack.splitlines() if line.strip()), "")
        key = f"{source}|{kind}|{message}|{first_frame}"
        now = time.time()
        with _lock:
            seen = _recent.get(key)
            if seen and now - seen[0] < DEDUPE_WINDOW_S:
                seen[1] += 1
                return
            repeats = seen[1] if seen else 0
            _recent[key] = [now, 0]
            if len(_recent) > 500:  # alte Schlüssel wegräumen
                for k in [k for k, v in _recent.items() if now - v[0] > DEDUPE_WINDOW_S]:
                    _recent.pop(k, None)
            entry = {
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                "source": _clip(source, 40),
                "kind": _clip(kind, 80),
                "message": message,
            }
            if stack:
                entry["stack"] = stack
            if context:
                entry["context"] = {str(k)[:60]: _clip(v, 500) for k, v in list(context.items())[:20]}
            if repeats:
                entry["repeated_before"] = repeats
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            _rotate()
            with LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - das Protokoll darf nie selbst stören
        pass


def record_exception(source: str, kind: str, exc: BaseException, context: dict | None = None) -> None:
    record(
        source, kind, f"{type(exc).__name__}: {exc}",
        stack="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), context=context,
    )


def read(limit: int = 200) -> list[dict]:
    """Die letzten Einträge (neueste zuletzt)."""
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
