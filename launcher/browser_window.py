"""Jarvis-Browser im Launcher: ein zweites pywebview-Fenster, das Befehle vom
Backend ausführt (WebSocket /jarvis-browser/ws, siehe backend/jarvis_browser.py).

Läuft in einem eigenen Thread neben webview.start(). Bedient wird die Seite
über das Skript frontend/jarvis-browser-inject.js (nummerierte Elementliste,
Klick/Eingabe per Nummer) — nie über Bildschirmkoordinaten.

Bewusst nur run_js() statt evaluate_js(): evaluate_js wartet auf pywebviews
eigene JS-Brücke und führt das Skript per eval() aus, was bei Seiten mit
strenger Content-Security-Policy scheitert.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

BROWSER_WIDTH, BROWSER_HEIGHT = 1100, 760
PAGE_LOAD_TIMEOUT = 25.0
JS_TIMEOUT = 10.0


class BrowserError(Exception):
    """Wird dem Backend als Fehlermeldung (auf Deutsch) zurückgegeben."""


class JarvisBrowserWindow:
    def __init__(self, webview, ws_url: str, root_dir: Path, state_file: Path | None = None) -> None:
        self.webview = webview
        self.ws_url = ws_url
        self.inject_path = root_dir / "frontend" / "jarvis-browser-inject.js"
        self.state_file = state_file
        self.window = None
        self._loaded = 0
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._size = list(self._load_size())
        self._save_timer: threading.Timer | None = None

    # ------------------------------------------------------------ Lebenszyklus
    def start(self) -> None:
        threading.Thread(target=self._run, name="jarvis-browser", daemon=True).start()

    def shutdown(self) -> None:
        """Beim Schließen des Hauptfensters: sonst hielte das offene Browser-
        Fenster webview.start() am Leben und das Backend liefe unsichtbar weiter."""
        self._stop.set()
        window, self.window = self.window, None
        if window is not None:
            try:
                window.destroy()
            except Exception:  # noqa: BLE001 - schon zu
                pass

    # ----------------------------------------------------------- Größe merken
    def _load_size(self) -> tuple[int, int]:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file else {}
            w, h = int(data["width"]), int(data["height"])
            if 400 <= w <= 6000 and 300 <= h <= 6000:
                return w, h
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return BROWSER_WIDTH, BROWSER_HEIGHT

    def _on_resized(self, width: int, height: int) -> None:
        self._size[:] = [width, height]
        if self._save_timer:
            self._save_timer.cancel()
        timer = threading.Timer(0.6, self._save_size)
        timer.daemon = True
        self._save_timer = timer
        timer.start()

    def _save_size(self) -> None:
        if not self.state_file:
            return
        try:
            self.state_file.write_text(json.dumps({"width": self._size[0], "height": self._size[1]}), encoding="utf-8")
        except OSError:
            pass

    # --------------------------------------------------------------- Fenster
    def _on_loaded(self) -> None:
        with self._cond:
            self._loaded += 1
            self._cond.notify_all()

    def _on_closed(self) -> None:
        self.window = None

    def _ensure_window(self, url: str):
        if self.window is not None:
            return self.window
        with self._cond:
            before = self._loaded
        window = self.webview.create_window(
            "Jarvis-Browser", url, width=self._size[0], height=self._size[1], min_size=(480, 360), text_select=True,
        )
        if window is None:
            raise BrowserError("Das Browser-Fenster konnte nicht geöffnet werden.")
        window.events.loaded += self._on_loaded
        window.events.closed += self._on_closed
        window.events.resized += self._on_resized
        if not window.events.shown.wait(15):
            raise BrowserError("Das Browser-Fenster ist nicht rechtzeitig erschienen.")
        self.window = window
        self._wait_loaded(before)
        return window

    def _wait_loaded(self, before: int, timeout: float = PAGE_LOAD_TIMEOUT) -> bool:
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._loaded <= before:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
        return True

    # ------------------------------------------------------------------- JS
    def _js(self, script: str, timeout: float = JS_TIMEOUT):
        """Skript ausführen, mit Zeitlimit (mitten in einer Navigation kann
        der Aufruf sonst ewig hängen). Gibt None bei Fehler/Zeitüberschreitung."""
        window = self.window
        if window is None:
            raise BrowserError("Das Browser-Fenster ist geschlossen. Mit browser_open eine Seite öffnen.")
        box: dict = {}

        def run() -> None:
            try:
                box["value"] = window.run_js(script)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or "error" in box:
            return None
        return box.get("value")

    def _call(self, expression: str, retries: int = 3) -> dict:
        """Eine __jb-Funktion aufrufen; fehlt das Skript (neue Seite), erst einspeisen."""
        last = ""
        for attempt in range(retries):
            # Die __jb-Funktionen liefern selbst schon einen JSON-String.
            raw = self._js(f"(window.__jb && window.__jb.v === 3) ? {expression} : 'NOINJECT'")
            if raw == "NOINJECT" or raw is None:
                self._inject()
                time.sleep(0.25 * (attempt + 1))
                continue
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(data, str):  # doppelt kodiert
                    data = json.loads(data)
            except ValueError:
                last = str(raw)[:120]
                continue
            if isinstance(data, dict):
                return data
            last = str(raw)[:120]
        raise BrowserError("Die Seite lässt sich gerade nicht auslesen (sie lädt noch oder blockiert Skripte)." + (f" [{last}]" if last else ""))

    def _inject(self) -> None:
        try:
            script = self.inject_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BrowserError(f"Elementfinder nicht lesbar: {exc}") from exc
        self._js(script, timeout=15)

    # ------------------------------------------------------------- Aktionen
    def _after_action(self, loaded_before: int) -> dict:
        """Nach Klick/Eingabe: kurz warten, ob eine neue Seite lädt, dann frisch ansehen."""
        time.sleep(0.45)
        with self._cond:
            navigating = self._loaded != loaded_before
        if not navigating:
            state = self._js("document.readyState")
            navigating = state not in ("complete", "interactive") and state is not None
        if navigating:
            self._wait_loaded(loaded_before, timeout=12)
            time.sleep(0.4)
        return self._call("window.__jb.look()")

    def do_open(self, payload: dict) -> tuple[str, dict]:
        url = str(payload.get("url") or "").strip()
        if not url:
            raise BrowserError("Welche Adresse soll ich öffnen?")
        # Zweite Absicherung (das Backend prüft schon): nur Webadressen laden.
        if not url.lower().startswith(("http://", "https://")):
            raise BrowserError("Der Jarvis-Browser öffnet nur http- und https-Adressen.")
        with self._cond:
            before = self._loaded
        if self.window is None:
            self._ensure_window(url)
        else:
            self.window.load_url(url)
            self._wait_loaded(before)
        time.sleep(0.4)
        return "Seite geöffnet.", self._call("window.__jb.look()")

    def do_look(self, payload: dict) -> tuple[str, dict]:
        if self.window is None:
            raise BrowserError("Es ist noch keine Seite offen. Mit browser_open eine Adresse öffnen.")
        return "", self._call("window.__jb.look()")

    def do_click(self, payload: dict) -> tuple[str, dict]:
        with self._cond:
            before = self._loaded
        res = self._call(f"window.__jb.click({int(payload['nr'])}, {int(payload['epoch'])})")
        if not res.get("ok"):
            raise BrowserError(res.get("error") or "Klick fehlgeschlagen.")
        return "Geklickt.", self._after_action(before)

    def do_type(self, payload: dict) -> tuple[str, dict]:
        with self._cond:
            before = self._loaded
        res = self._call(
            f"window.__jb.type({int(payload['nr'])}, {int(payload['epoch'])}, "
            f"{json.dumps(str(payload.get('text', '')))}, {'true' if payload.get('enter') else 'false'})"
        )
        if not res.get("ok"):
            raise BrowserError(res.get("error") or "Eingabe fehlgeschlagen.")
        return "Getippt.", self._after_action(before)

    def do_select(self, payload: dict) -> tuple[str, dict]:
        with self._cond:
            before = self._loaded
        res = self._call(
            f"window.__jb.select({int(payload['nr'])}, {int(payload['epoch'])}, {json.dumps(str(payload.get('value', '')))})"
        )
        if not res.get("ok"):
            raise BrowserError(res.get("error") or "Auswahl fehlgeschlagen.")
        return "Ausgewählt.", self._after_action(before)

    def do_scroll(self, payload: dict) -> tuple[str, dict]:
        res = self._call(f"window.__jb.scroll({json.dumps(str(payload.get('direction', 'unten')))})")
        if not res.get("ok"):
            raise BrowserError(res.get("error") or "Scrollen fehlgeschlagen.")
        time.sleep(0.3)
        return "Gescrollt.", self._call("window.__jb.look()")

    def do_read(self, payload: dict) -> tuple[str, dict]:
        if self.window is None:
            raise BrowserError("Es ist noch keine Seite offen. Mit browser_open eine Adresse öffnen.")
        res = self._call(f"window.__jb.read({int(payload.get('max_chars') or 5000)})")
        return "", res

    def do_back(self, payload: dict) -> tuple[str, dict]:
        if self.window is None:
            raise BrowserError("Es ist noch keine Seite offen.")
        with self._cond:
            before = self._loaded
        self._js("history.back()")
        return "Zurück.", self._after_action(before)

    def do_close(self, payload: dict) -> tuple[str, dict]:
        window, self.window = self.window, None
        if window is not None:
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass
        return "Browser-Fenster geschlossen.", {}

    # --------------------------------------------------------------- Kanal
    def _handle(self, command: dict) -> dict:
        cid = command.get("id")
        action = str(command.get("action") or "")
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        handler = getattr(self, "do_" + action, None) if action.isidentifier() else None
        if handler is None:
            return {"id": cid, "ok": False, "error": f"Unbekannte Browser-Aktion: {action}"}
        try:
            message, data = handler(payload)
            return {"id": cid, "ok": True, "message": message, "data": data}
        except BrowserError as exc:
            return {"id": cid, "ok": False, "error": str(exc)}
        except (KeyError, ValueError, TypeError) as exc:
            return {"id": cid, "ok": False, "error": f"Ungültige Angaben für {action}: {exc}"}
        except Exception as exc:  # noqa: BLE001 - nie den Kanal beenden
            return {"id": cid, "ok": False, "error": f"Browser-Fehler bei {action}: {exc}"}

    def _run(self) -> None:
        from websockets.sync.client import connect

        while not self._stop.is_set():
            try:
                with connect(
                    self.ws_url, additional_headers={"Origin": self.ws_url.replace("ws://", "http://").split("/jarvis")[0]},
                    open_timeout=5, close_timeout=2, max_size=16 * 1024 * 1024,
                ) as ws:
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv(timeout=10)
                        except TimeoutError:
                            ws.send(json.dumps({"type": "heartbeat"}))
                            continue
                        try:
                            command = json.loads(raw)
                        except ValueError:
                            continue
                        if isinstance(command, dict) and command.get("action"):
                            ws.send(json.dumps(self._handle(command)))
            except Exception:  # noqa: BLE001 - Backend noch nicht da/neu gestartet: wieder versuchen
                pass
            self._stop.wait(2)
