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

import base64
import json
import re
import threading
import time
from pathlib import Path

BROWSER_WIDTH, BROWSER_HEIGHT = 1100, 760
PAGE_LOAD_TIMEOUT = 25.0
JS_TIMEOUT = 10.0
# Screenshots gehen an das lokale Bildmodell: breiter bringt nichts mehr,
# kostet aber spürbar Rechenzeit.
SCREENSHOT_MAX_WIDTH = 1024


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
        # Seitenleiste im Hauptfenster: Die Jarvis-Oberfläche meldet über
        # PaneApi, wo die Browser-Ansicht liegen soll; die WebView2-Ansicht des
        # (unsichtbaren) Browser-Fensters wird dort ins Hauptfenster gehängt.
        self.main_window = None
        self.api = PaneApi(self)
        self._control = None
        self._pane = {"x": 0, "y": 0, "w": 0, "h": 0, "visible": False}
        self._state = {"url": "", "title": "", "back": False, "forward": False, "loading": False}
        # Befehle vom Backend und Eingaben in der Adressleiste laufen auf
        # verschiedenen Threads: ohne Sperre legten beide gleichzeitig ein
        # Browser-Fenster an.
        self._nav_lock = threading.RLock()
        self._own_ports = _own_ports(ws_url)

    # ------------------------------------------------------------ Lebenszyklus
    def start(self) -> None:
        threading.Thread(target=self._run, name="jarvis-browser", daemon=True).start()

    def shutdown(self) -> None:
        """Beim Schließen des Hauptfensters: sonst hielte das offene Browser-
        Fenster webview.start() am Leben und das Backend liefe unsichtbar weiter."""
        self._stop.set()
        self._destroy_window()

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
        if self._control is not None and not getattr(self, "_hooked", False):
            self._ui(self._hook_state)
        with self._cond:
            self._loaded += 1
            self._cond.notify_all()

    def _on_closed(self) -> None:
        self.window = None
        self._control = None
        self._state.update(url="", title="", back=False, forward=False, loading=False)

    def _ensure_window(self, url: str):
        if self.window is not None:
            return self.window
        with self._cond:
            before = self._loaded
        # Mit Hauptfenster: unsichtbar anlegen, die Ansicht wandert gleich in
        # die Seitenleiste. Ohne (Fallback): wie früher ein eigenes Fenster.
        docked = self.main_window is not None and getattr(self.main_window, "native", None) is not None
        window = self.webview.create_window(
            "Jarvis-Browser", url, width=self._size[0], height=self._size[1], min_size=(480, 360),
            text_select=True, hidden=docked,
        )
        if window is None:
            raise BrowserError("Das Browser-Fenster konnte nicht geöffnet werden.")
        window.events.loaded += self._on_loaded
        window.events.closed += self._on_closed
        window.events.resized += self._on_resized
        if not window.events.shown.wait(15):
            raise BrowserError("Das Browser-Fenster ist nicht rechtzeitig erschienen.")
        self.window = window
        if docked and not self._dock(window):
            window.show()  # Einhängen gescheitert: dann eben als eigenes Fenster
        self._wait_loaded(before)
        return window

    # ------------------------------------------------------- Seitenleiste
    def _ui(self, fn, wait: float = 0) -> bool:
        """fn auf dem UI-Thread ausführen (alle pywebview-Fenster teilen ihn).
        BeginInvoke statt Invoke: ein hängender UI-Thread darf nie den
        Befehlskanal blockieren. Mit wait>0 wird bis dahin auf fn gewartet."""
        main = getattr(self.main_window, "native", None)
        if main is None:
            return False
        from System import Action

        done = threading.Event()

        def run() -> None:
            try:
                fn()
            except Exception:  # noqa: BLE001 - UI-Thread nie mit Fehlern abschießen
                pass
            finally:
                done.set()

        try:
            main.BeginInvoke(Action(run))
        except Exception:  # noqa: BLE001 - Hauptfenster schon zu
            return False
        return done.wait(wait) if wait else True

    def _dock(self, window) -> bool:
        """Die WebView2-Ansicht aus dem unsichtbaren Browser-Fenster ins
        Hauptfenster hängen (Position setzt die Jarvis-Oberfläche)."""
        main = self.main_window.native
        ok: list[bool] = []

        def run() -> None:
            from System.Windows.Forms import DockStyle

            control = window.native.browser.webview
            control.Parent.Controls.Remove(control)
            control.Dock = getattr(DockStyle, "None")
            control.Visible = False
            main.Controls.Add(control)
            self._control = control
            self._hooked = False
            self._hook_state()
            self._apply_bounds()
            ok.append(True)

        self._ui(run, wait=10)
        return bool(ok)

    def _undock(self) -> None:
        """Ansicht zurück ins Browser-Fenster, damit pywebview sie beim
        Schließen wie gewohnt aufräumt."""
        control, window = self._control, self.window
        self._control = None
        if control is None or window is None:
            return

        def run() -> None:
            from System.Windows.Forms import DockStyle

            control.Visible = False
            control.Parent.Controls.Remove(control)
            window.native.Controls.Add(control)
            control.Dock = DockStyle.Fill
            control.Visible = True

        self._ui(run, wait=5)

    def _destroy_window(self) -> None:
        self._undock()
        window, self.window = self.window, None
        if window is not None:
            try:
                window.destroy()
            except Exception:  # noqa: BLE001 - schon zu
                pass

    def _hook_state(self) -> None:
        """Adresse, Titel und Verlauf für die Leiste mitschreiben — direkt aus
        den WebView2-Ereignissen, damit die Abfrage den UI-Thread nie braucht.
        Nur auf dem UI-Thread; ist WebView2 noch nicht fertig, holt _on_loaded
        das nach."""
        control = self._control
        core = control.CoreWebView2 if control is not None else None
        if core is None or getattr(self, "_hooked", False):
            return
        self._hooked = True

        def update(*_args) -> None:
            try:
                self._state.update(
                    url=str(core.Source or ""), title=str(core.DocumentTitle or ""),
                    back=bool(core.CanGoBack), forward=bool(core.CanGoForward),
                )
            except Exception:  # noqa: BLE001
                pass

        def started(_sender=None, args=None) -> None:
            try:
                if args is not None and _is_own_server(str(args.Uri), self._own_ports):
                    args.Cancel = True
                    return
            except Exception:  # noqa: BLE001
                pass
            self._state["loading"] = True

        def finished(*_args) -> None:
            self._state["loading"] = False
            update()

        core.SourceChanged += update
        core.DocumentTitleChanged += update
        core.HistoryChanged += update
        core.NavigationStarting += started
        core.NavigationCompleted += finished
        update()

    def _apply_bounds(self) -> None:
        """Nur auf dem UI-Thread aufrufen."""
        control, pane = self._control, self._pane
        if control is None:
            return
        from System.Drawing import Rectangle

        if pane["visible"] and pane["w"] > 20 and pane["h"] > 20:
            control.Bounds = Rectangle(pane["x"], pane["y"], pane["w"], pane["h"])
            control.Visible = True
            control.BringToFront()
        else:
            control.Visible = False

    def set_bounds(self, x, y, w, h, visible) -> None:
        new = {"x": int(x), "y": int(y), "w": int(w), "h": int(h), "visible": bool(visible)}
        if new == self._pane:
            return
        self._pane.update(new)
        if self._control is not None:
            self._ui(self._apply_bounds)

    def reveal(self) -> None:
        """Die Seitenleiste in der Jarvis-Oberfläche aufziehen (z. B. wenn das
        Modell eine Seite öffnet). Läuft nebenher, blockiert nie."""
        main = self.main_window
        if main is None or self._pane["visible"]:
            return

        def run() -> None:
            try:
                main.run_js("window.jarvisBrowserPane && window.jarvisBrowserPane.open()")
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=run, daemon=True).start()

    def navigate(self, text: str) -> None:
        url = _url_from_input(text)
        if not url:
            return
        if _is_own_server(url, self._own_ports):
            raise BrowserError("Jarvis' eigene Oberfläche lässt sich hier nicht öffnen.")
        self.reveal()
        with self._nav_lock:
            if self.window is None:
                self._ensure_window(url)
            else:
                self.window.load_url(url)

    def history(self, action: str) -> None:
        control = self._control
        if control is None:
            return

        def run() -> None:
            core = control.CoreWebView2
            if action == "back" and core.CanGoBack:
                core.GoBack()
            elif action == "forward" and core.CanGoForward:
                core.GoForward()
            elif action == "reload":
                core.Reload()
            elif action == "stop":
                core.Stop()

        self._ui(run)

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
        version = self._script_version()
        for attempt in range(retries):
            # Die __jb-Funktionen liefern selbst schon einen JSON-String.
            raw = self._js(f"(window.__jb && window.__jb.v === {version}) ? {expression} : 'NOINJECT'")
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

    def _script(self) -> str:
        try:
            return self.inject_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BrowserError(f"Elementfinder nicht lesbar: {exc}") from exc

    def _script_version(self) -> int:
        """Versionsnummer aus dem Skript selbst ("v: 4") — das Skript wird live
        von der Platte gelesen, diese Datei steckt in der gebauten Jarvis.exe;
        eine hier fest eingetragene Nummer liefe nach jedem Skript-Update auseinander."""
        m = re.search(r"window\.__jb\s*=\s*\{\s*v:\s*(\d+)", self._script())
        return int(m.group(1)) if m else 0

    def _inject(self) -> None:
        self._js(self._script(), timeout=15)

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
        # browser_research liest mehrere Seiten nacheinander und wartet nicht
        # die vollen 25 s auf eine lahme Quelle.
        timeout = max(3.0, min(float(payload.get("timeout") or PAGE_LOAD_TIMEOUT), PAGE_LOAD_TIMEOUT))
        # Man soll sehen, was Jarvis gerade aufruft: Seitenleiste aufziehen.
        if _is_own_server(url, self._own_ports):
            raise BrowserError("Jarvis' eigene Oberfläche öffne ich nicht im Jarvis-Browser.")
        self.reveal()
        with self._nav_lock:
            with self._cond:
                before = self._loaded
            if self.window is None:
                self._ensure_window(url)
            else:
                self.window.load_url(url)
                self._wait_loaded(before, timeout)
        time.sleep(0.4)
        return "Seite geöffnet.", self._call("window.__jb.look()")

    def do_links(self, payload: dict) -> tuple[str, dict]:
        if self.window is None:
            raise BrowserError("Es ist noch keine Seite offen.")
        return "", self._call("window.__jb.links()")

    def do_screenshot(self, payload: dict) -> tuple[str, dict]:
        """Bild des sichtbaren Seitenbereichs als JPEG (base64). Nur für Seiten,
        die sich nicht als Elementliste lesen lassen (Canvas, Karten, Spiele)."""
        window = self.window
        if window is None:
            raise BrowserError("Es ist noch keine Seite offen. Mit browser_open eine Adresse öffnen.")
        try:
            control = window.native.browser.webview
        except AttributeError as exc:
            raise BrowserError("Screenshots gehen nur mit dem WebView2-Fenster unter Windows.") from exc
        if self._control is not None and not self._pane["visible"]:
            # Eine eingeklappte Ansicht zeichnet WebView2 nicht: erst aufziehen.
            self.reveal()
            deadline = time.monotonic() + 3
            while not self._pane["visible"] and time.monotonic() < deadline:
                time.sleep(0.1)
            if not self._pane["visible"]:
                # Ein Dialog (z. B. Einstellungen) liegt darüber: WebView2
                # lieferte dann ein schwarzes Bild, das das Modell "beschreibt".
                raise BrowserError("Die Browser-Ansicht ist gerade verdeckt. Schließe den offenen Dialog in Jarvis und versuch es noch einmal.")
            time.sleep(0.5)
        import clr  # pythonnet, von pywebview ohnehin geladen

        clr.AddReference("System.Drawing")
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        from System import Action, Func, Object
        from System.IO import MemoryStream
        from System.Threading.Tasks import Task

        stream = MemoryStream()
        done = threading.Event()
        failed: list[str] = []

        def finish(task) -> None:
            if task.IsFaulted:
                failed.append(str(task.Exception))
            done.set()

        def begin():
            # CapturePreviewAsync muss auf dem UI-Thread des Fensters starten.
            try:
                control.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Jpeg, stream).ContinueWith(Action[Task](finish))
            except Exception as exc:  # noqa: BLE001
                failed.append(str(exc))
                done.set()
            return None

        # BeginInvoke statt Invoke: hängt der UI-Thread, blockiert sonst dieser
        # Aufruf für immer und mit ihm der ganze Browser-Kanal.
        control.BeginInvoke(Func[Object](begin))
        if not done.wait(12) or failed:
            raise BrowserError("Der Screenshot ist fehlgeschlagen." + (f" ({failed[0][:120]})" if failed else ""))
        data = bytes(stream.ToArray())
        if not data:
            raise BrowserError("Der Screenshot ist leer (Fenster minimiert?).")
        width = height = 0
        try:
            from System.Drawing import Bitmap, Size
            from System.Drawing.Imaging import ImageFormat

            stream.Position = 0
            image = Bitmap(stream)
            width, height = int(image.Width), int(image.Height)
            if width > SCREENSHOT_MAX_WIDTH:
                height = max(1, round(height * SCREENSHOT_MAX_WIDTH / width))
                width = SCREENSHOT_MAX_WIDTH
                small = Bitmap(image, Size(width, height))
                out = MemoryStream()
                small.Save(out, ImageFormat.Jpeg)
                data = bytes(out.ToArray())
                small.Dispose()
                out.Dispose()
            image.Dispose()
        except Exception:  # noqa: BLE001 - dann eben in Originalgröße
            pass
        stream.Dispose()
        info = self._call("window.__jb.read(200)")
        return "", {
            "image": base64.b64encode(data).decode("ascii"), "mime": "image/jpeg", "width": width, "height": height,
            "title": info.get("title", ""), "url": info.get("url", ""),
        }

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
        self._destroy_window()
        self._state.update(url="", title="", back=False, forward=False, loading=False)
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


def _own_ports(ws_url: str) -> set[int]:
    """Ports, auf denen Jarvis selbst lauscht (Oberfläche und MCP)."""
    import os
    from urllib.parse import urlparse

    ports = {urlparse(ws_url).port or 8000}
    try:
        ports.add(int(os.environ.get("JARVIS_MCP_PORT", "8765")))
    except ValueError:
        pass
    return ports


def _is_own_server(url: str, ports: set[int]) -> bool:
    """Jarvis' eigene Adressen: Dort stehen Einstellungen samt Schlüsseln. Eine
    Webseite im Jarvis-Browser darf nie dorthin führen (siehe backend/tools.py)."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host, port = (parsed.hostname or "").lower(), parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False
    local = host in ("localhost", "0.0.0.0", "::1", "::") or host.startswith("127.") or host.endswith(".localhost")
    return local and port in ports


def _url_from_input(text: str) -> str:
    """Eingabe aus der Adressleiste: Adresse oder Suchbegriff. Nur http(s) —
    javascript:, file: und Co. werden zur Suche statt ausgeführt zu werden."""
    text = str(text or "").strip()
    if not text:
        return ""
    if re.match(r"^https?://", text, re.IGNORECASE):
        return text
    if " " not in text and re.match(r"^(localhost|[\w-]+(\.[\w-]+)+)(:\d+)?([/?#].*)?$", text, re.IGNORECASE):
        local = text.lower().startswith(("localhost", "127.", "192.168.", "10."))
        return ("http://" if local else "https://") + text
    from urllib.parse import quote_plus

    return "https://duckduckgo.com/?q=" + quote_plus(text)


class PaneApi:
    """Über pywebviews js_api für die Jarvis-Oberfläche erreichbar
    (window.pywebview.api.*). Läuft auf Hilfs-Threads, nie auf dem UI-Thread."""

    def __init__(self, browser: JarvisBrowserWindow) -> None:
        self._browser = browser

    def pane_state(self) -> dict:
        b = self._browser
        return {**b._state, "open": b.window is not None}

    def pane_bounds(self, x, y, w, h, visible) -> dict:
        self._browser.set_bounds(x, y, w, h, visible)
        return self.pane_state()

    def pane_navigate(self, text) -> dict:
        try:
            self._browser.navigate(str(text or ""))
        except BrowserError as exc:
            return {**self.pane_state(), "error": str(exc)}
        return self.pane_state()

    def pane_history(self, action) -> dict:
        self._browser.history(str(action or ""))
        return self.pane_state()

    def pane_external(self) -> bool:
        url = self._browser._state.get("url") or ""
        if not url.lower().startswith(("http://", "https://")):
            return False
        import webbrowser

        return bool(webbrowser.open(url))
