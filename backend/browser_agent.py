"""Bridge between Jarvis tools and the locally installed Chrome extension."""

from __future__ import annotations

import asyncio
import itertools
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from . import panel


@dataclass
class _Request:
    id: str
    action: str
    payload: dict
    created: float = field(default_factory=time.monotonic)
    result: dict | None = None
    done: threading.Event = field(default_factory=threading.Event)


class BrowserAgent:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[str, _Request] = {}
        self._pending: list[str] = []
        self._counter = itertools.count(1)
        self._last_seen = 0.0
        self._socket = None
        self._loop = None

    def connected(self) -> bool:
        return self._socket is not None and time.monotonic() - self._last_seen < 20

    def connect(self, socket, loop) -> None:
        self._socket, self._loop, self._last_seen = socket, loop, time.monotonic()

    def disconnect(self, socket) -> None:
        if self._socket is socket:
            self._socket, self._loop = None, None

    def poll(self) -> list[dict]:
        self._last_seen = time.monotonic()
        with self._lock:
            ids, self._pending = self._pending, []
            return [
                {"id": request.id, "action": request.action, "payload": request.payload}
                for request_id in ids
                if (request := self._requests.get(request_id)) and not request.done.is_set()
            ]

    def resolve(self, request_id: str, result: dict) -> bool:
        self._last_seen = time.monotonic()
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False
            request.result = result
            request.done.set()
            return True

    def heartbeat(self) -> None:
        """Keep the extension connection alive when no command is pending."""
        self._last_seen = time.monotonic()

    def command(self, action: str, payload: dict, timeout: float = 20) -> str:
        if not self.connected():
            return "Browser-Agent nicht verbunden. Installiere oder aktiviere die Jarvis-Chrome-Erweiterung."
        request = _Request(id=f"browser-{next(self._counter)}", action=action, payload=payload)
        with self._lock:
            self._requests[request.id] = request
            self._pending.append(request.id)
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._socket.send_json({"id": request.id, "action": action, "payload": payload}), self._loop
            )
            future.result(timeout=3)
        except Exception as exc:
            with self._lock:
                self._requests.pop(request.id, None)
            return f"Browser-Aktion fehlgeschlagen: Verbindung verloren ({exc})"
        panel.push("action", id=request.id, action=action, status="läuft", target=payload)
        if not request.done.wait(timeout):
            with self._lock:
                self._requests.pop(request.id, None)
            panel.push("action", id=request.id, action=action, status="fehlgeschlagen", detail="Zeitüberschreitung")
            return "Browser-Aktion hat keine Antwort erhalten."
        with self._lock:
            self._requests.pop(request.id, None)
        result = request.result or {}
        if not result.get("ok"):
            detail = result.get("error", "Unbekannter Browserfehler")
            panel.push("action", id=request.id, action=action, status="fehlgeschlagen", detail=detail)
            return f"Browser-Aktion fehlgeschlagen: {detail}"
        detail = result.get("message", "Ausgeführt.")
        panel.push("action", id=request.id, action=action, status="erfolgreich", detail=detail, data=result.get("data", {}))
        return detail

    def youtube_search(self, query: str) -> str:
        return self.command("open_url", {"url": f"https://www.youtube.com/results?search_query={quote_plus(query)}"})

    def web_search(self, query: str) -> str:
        return self.command("open_url", {"url": f"https://www.google.com/search?q={quote_plus(query)}"})


agent = BrowserAgent()
