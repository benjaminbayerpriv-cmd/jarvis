"""Durchklick-Test für die Jarvis-Oberfläche.

Startet einen unsichtbaren Edge (oder Chrome), öffnet die laufende Jarvis-
Oberfläche und geht die Kernabläufe durch: Start, neuer Chat, Chats öffnen,
Eingabefeld, Einstellungen, Code-Tab, Projekte, schmales Fenster. Dabei wird
jeder JavaScript-Fehler mitgeschrieben, und am Ende darf das Fehlerprotokoll
(/errors) keine neuen Einträge der Oberfläche haben.

    python test_ui.py              # ohne Modell (schnell, ~20 s)
    python test_ui.py --model      # zusätzlich eine echte Antwort streamen
                                   # (prüft Mitscrollen; braucht LM Studio)

Braucht einen laufenden Jarvis-Server (jarvis start oder Jarvis.exe). Nur die
Weboberfläche — die Browser-Seitenleiste der Jarvis.exe, Mikrofon und Kamera
deckt der Test nicht ab. Ändert nichts außer: ein mit --model gesendeter
Test-Chat bleibt in der Chatliste stehen.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

BASE = os.environ.get("JARVIS_URL", "http://127.0.0.1:8000")
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


class Page:
    """Minimaler Client für das Chrome DevTools Protocol."""

    def __init__(self, ws_url: str) -> None:
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=10)
        self.next_id = 0
        self.errors: list[str] = []

    def _event(self, msg: dict) -> None:
        method = msg.get("method")
        params = msg.get("params", {})
        if method == "Runtime.exceptionThrown":
            d = params.get("exceptionDetails", {})
            text = (d.get("exception") or {}).get("description") or d.get("text") or "Ausnahme"
            self.errors.append(f"Ausnahme: {text.splitlines()[0][:200]}")
        elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            args = " ".join(str(a.get("value") or a.get("description") or "") for a in params.get("args", []))
            self.errors.append(f"console.error: {args[:200]}")
        elif method == "Network.responseReceived":
            resp = params.get("response", {})
            if resp.get("status", 0) >= 400 and not resp.get("url", "").endswith("/favicon.ico"):
                self.errors.append(f"HTTP {resp.get('status')}: {resp.get('url', '')[:160]}")
        elif method == "Log.entryAdded":
            entry = params.get("entry", {})
            # "Failed to load resource" steht schon mit Adresse über Network da.
            if entry.get("level") == "error" and entry.get("source") != "network" and "favicon" not in entry.get("url", ""):
                self.errors.append(f"{entry.get('source')}: {entry.get('text', '')[:200]}")

    def call(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        self.next_id += 1
        my_id = self.next_id
        self.ws.send(json.dumps({"id": my_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(method)
            msg = json.loads(self.ws.recv(timeout=left))
            if msg.get("id") == my_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self._event(msg)

    def js(self, expression: str, timeout: float = 30):
        """Ausdruck in der Seite auswerten (await erlaubt), Ergebnis als Wert."""
        res = self.call("Runtime.evaluate", {
            "expression": f"(async () => {{ {expression} }})()", "awaitPromise": True, "returnByValue": True,
        }, timeout)
        if res.get("exceptionDetails"):
            d = res["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text"))
        return res.get("result", {}).get("value")

    def pump(self, seconds: float) -> None:
        """Ereignisse (Fehler) eine Weile einsammeln."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            try:
                self._event(json.loads(self.ws.recv(timeout=left)))
            except TimeoutError:
                break


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


FAKE_STREAM = """
  window.__realFetch = window.__realFetch || window.fetch;
  window.fetch = (url, opts) => {
    if (String(url).includes('/chat/stream')) {
      const enc = new TextEncoder();
      const lines = [];
      for (let i = 1; i <= 40; i++) lines.push(JSON.stringify({ type: 'sentence', text: `Satz ${i}: ` + 'Das ist ein langer Testsatz, der den Verlauf sichtbar wachsen lässt. '.repeat(3), audio: '' }) + '\\n');
      lines.push(JSON.stringify({ type: 'done', full_text: 'Test', conversation_id: 'ui-test-fake' }) + '\\n');
      let i = 0;
      const body = new ReadableStream({
        pull(ctrl) {
          return new Promise((r) => setTimeout(() => {
            if (i < lines.length) ctrl.enqueue(enc.encode(lines[i++])); else ctrl.close();
            r();
          }, 60));
        },
      });
      return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
    }
    return window.__realFetch(url, opts);
  };
"""

SLEEP = "await new Promise(r => setTimeout(r, {ms}));"
VISIBLE = "(el => !!el && el.offsetWidth > 0 && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden')"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", action="store_true", help="auch eine echte Antwort streamen (braucht LM Studio)")
    ap.add_argument("--show", action="store_true", help="Browser sichtbar starten")
    args = ap.parse_args()

    try:
        urllib.request.urlopen(BASE + "/settings", timeout=5)
    except OSError:
        print(f"Jarvis-Server unter {BASE} nicht erreichbar — erst starten.")
        return 2
    browser = next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("msedge") or shutil.which("chrome")
    if not browser:
        print("Kein Edge/Chrome gefunden.")
        return 2

    errors_before = len(http_json(BASE + "/errors?limit=2000").get("errors", []))
    port = free_port()
    profile = tempfile.mkdtemp(prefix="jarvis-ui-test-")
    cmd = [browser, f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run",
           "--no-default-browser-check", "--disable-extensions", "--window-size=1400,900", "about:blank"]
    if not args.show:
        cmd.insert(1, "--headless=new")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results: list[tuple[str, bool, str]] = []
    try:
        for _ in range(50):
            try:
                targets = http_json(f"http://127.0.0.1:{port}/json/list")
                page_target = next(t for t in targets if t.get("type") == "page")
                break
            except (OSError, StopIteration, ValueError):
                time.sleep(0.2)
        else:
            print("Browser hat die Debug-Schnittstelle nicht geöffnet.")
            return 2
        page = Page(page_target["webSocketDebuggerUrl"])
        for domain in ("Runtime.enable", "Log.enable", "Page.enable", "Network.enable"):
            page.call(domain)
        page.call("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        # Unsichtbare Fenster haben sonst keinen Fokus: Tippen landete nirgends.
        page.call("Emulation.setFocusEmulationEnabled", {"enabled": True})
        page.call("Page.bringToFront")

        def step(name: str, expression: str, timeout: float = 30) -> None:
            before = len(page.errors)
            try:
                value = page.js(expression, timeout)
                ok = value is True or (isinstance(value, dict) and value.get("ok") is True)
                detail = "" if ok else json.dumps(value, ensure_ascii=False)[:300]
            except Exception as exc:  # noqa: BLE001
                ok, detail = False, f"{type(exc).__name__}: {exc}"[:300]
            page.pump(0.4)
            new = page.errors[before:]
            if new:
                ok = False
                detail = (detail + " | " if detail else "") + "; ".join(new[:3])
            results.append((name, ok, detail))
            print(f"{'OK  ' if ok else 'FEHL'} {name}" + (f"\n       {detail}" if detail else ""))

        page.call("Page.navigate", {"url": BASE + "/"})
        step("Oberfläche lädt", f"""
            for (let i = 0; i < 60; i++) {{ if (document.querySelector('#jsApp .js-composer .js-editor')) return true; {SLEEP.format(ms=250)} }}
            return {{ ok: false, grund: '#jsApp/Eingabefeld nicht gefunden' }};""")
        page.pump(1.5)
        step("Chatliste geladen", f"""
            for (let i = 0; i < 20; i++) {{ if (document.querySelectorAll('.js-chat-item[data-id]').length) return true; {SLEEP.format(ms=250)} }}
            return {{ ok: true, hinweis: 'keine Chats vorhanden' }};""")
        step("Neuer Chat ist leer", f"""
            document.querySelector('.js-new').click(); {SLEEP.format(ms=500)}
            const turns = document.querySelectorAll('.js-thread .js-turn').length;
            return turns === 0 ? true : {{ ok: false, turns }};""")
        page.js("document.querySelector('.js-editor').focus(); return true;")
        time.sleep(0.4)  # Fokus und Cursor müssen gesetzt sein, sonst geht der Text ins Leere
        page.call("Input.insertText", {"text": "Testentwurf"})
        step("Eingabefeld nimmt Text an", f"""
            const ed = document.querySelector('.js-editor');
            {SLEEP.format(ms=200)}
            const send = document.querySelector('.js-send');
            const ok = ed.innerText.includes('Testentwurf') && send && !send.disabled;
            return ok ? true : {{ ok: false, text: ed.innerText, sendDisabled: send && send.disabled }};""")
        step("Entwurf bleibt beim Chat-Wechsel erhalten", f"""
            const items = document.querySelectorAll('.js-chat-item[data-id]');
            if (!items.length) return true;
            items[0].click(); {SLEEP.format(ms=900)}
            const back = document.querySelector('.js-nav-back');
            if (!back || back.disabled) return {{ ok: true, hinweis: 'kein Zurück möglich' }};
            back.click(); {SLEEP.format(ms=900)}
            const text = document.querySelector('.js-editor').innerText;
            return text.includes('Testentwurf') ? true : {{ ok: false, text }};""")
        step("Entwurf wieder leeren", f"""
            const ed = document.querySelector('.js-editor'); ed.focus();
            document.execCommand('selectAll'); document.execCommand('delete'); {SLEEP.format(ms=150)}
            return ed.innerText.trim() === '' ? true : {{ ok: false, text: ed.innerText }};""")
        step("Vorhandene Chats öffnen (bis 5)", f"""
            const items = [...document.querySelectorAll('.js-chat-item[data-id]')].slice(0, 5);
            const leer = [];
            for (const it of items) {{
              it.click(); {SLEEP.format(ms=900)}
              if (!document.querySelectorAll('.js-thread .js-turn').length) leer.push(it.innerText.trim().slice(0, 40));
            }}
            return leer.length ? {{ ok: false, ohneNachrichten: leer }} : true;""", timeout=60)
        step("Verlauf scrollt ans Ende", """
            const th = document.querySelector('.js-thread');
            if (!th || th.scrollHeight <= th.clientHeight) return true;
            const rest = th.scrollHeight - th.scrollTop - th.clientHeight;
            return rest < 160 ? true : { ok: false, abstandZumEnde: Math.round(rest) };""")
        step("Einstellungen öffnen und mit Escape schließen", f"""
            document.querySelector('.js-settings-row').click(); {SLEEP.format(ms=500)}
            const sheet = document.getElementById('jsSettingsSheet');
            if (!{VISIBLE}(sheet)) return {{ ok: false, grund: 'Einstellungen nicht sichtbar' }};
            document.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Escape', bubbles: true }})); {SLEEP.format(ms=500)}
            return !{VISIBLE}(sheet) ? true : {{ ok: false, grund: 'bleibt nach Escape offen' }};""")
        step("Code-Tab und zurück", f"""
            document.querySelector('.js-pill[data-mode="code"]').click(); {SLEEP.format(ms=900)}
            const codeOn = document.getElementById('jsApp').classList.contains('js-code-active');
            document.querySelector('.js-pill[data-mode="chat"]').click(); {SLEEP.format(ms=600)}
            const chatBack = !document.getElementById('jsApp').classList.contains('js-code-active')
              && {VISIBLE}(document.querySelector('.js-composer'));
            return codeOn && chatBack ? true : {{ ok: false, codeOn, chatBack }};""")
        step("Projekte öffnen und zurück", f"""
            document.querySelector('.js-projects').click(); {SLEEP.format(ms=700)}
            const on = document.getElementById('jsApp').classList.contains('js-projects-active');
            document.querySelector('.js-new').click(); {SLEEP.format(ms=600)}
            const off = !document.getElementById('jsApp').classList.contains('js-projects-active');
            return on && off ? true : {{ ok: false, on, off }};""")
        page.call("Emulation.setDeviceMetricsOverride", {"width": 820, "height": 700, "deviceScaleFactor": 1, "mobile": False})
        step("Schmales Fenster: nichts ragt heraus", f"""
            {SLEEP.format(ms=500)}
            const sw = document.scrollingElement.scrollWidth, w = window.innerWidth;
            const comp = document.querySelector('.js-composer').getBoundingClientRect();
            const ok = sw <= w + 1 && comp.right <= w + 1 && comp.width > 200;
            return ok ? true : {{ ok: false, scrollWidth: sw, innerWidth: w, composer: [Math.round(comp.left), Math.round(comp.right)] }};""")
        page.call("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 900, "deviceScaleFactor": 1, "mobile": False})

        page.js(FAKE_STREAM + " return true;")

        def fake_send(text: str) -> str:
            return f"""
                document.querySelector('.js-new').click(); {SLEEP.format(ms=400)}
                const ed = document.querySelector('.js-editor'); ed.focus();
                ed.textContent = '{text}'; ed.dispatchEvent(new InputEvent('input', {{ bubbles: true }}));
                {SLEEP.format(ms=150)} document.querySelector('.js-send').click();"""

        step("Simulierter Stream: Verlauf scrollt mit", fake_send("UI-Test Mitscrollen") + f"""
                const th = document.querySelector('.js-thread'); let maxRest = 0;
                for (let i = 0; i < 70; i++) {{
                  {SLEEP.format(ms=50)}
                  if (th.scrollHeight > th.clientHeight + 50) maxRest = Math.max(maxRest, th.scrollHeight - th.scrollTop - th.clientHeight);
                }}
                const grew = th.scrollHeight > th.clientHeight + 200;
                return grew && maxRest < 120 ? true : {{ ok: false, gewachsen: grew, maxAbstand: Math.round(maxRest) }};""", timeout=40)
        step("Simulierter Stream: hochgescrollt bleibt stehen", fake_send("UI-Test Hochscrollen") + f"""
                const th = document.querySelector('.js-thread');
                for (let i = 0; i < 40 && th.scrollHeight < th.clientHeight + 300; i++) {{ {SLEEP.format(ms=60)} }}
                th.scrollTop = 0; {SLEEP.format(ms=50)}
                let maxTop = 0;
                for (let i = 0; i < 30; i++) {{ {SLEEP.format(ms=60)} maxTop = Math.max(maxTop, th.scrollTop); }}
                return maxTop < 40 ? true : {{ ok: false, sprangZurueckBis: Math.round(maxTop) }};""", timeout=40)
        page.js("if (window.__realFetch) window.fetch = window.__realFetch; return true;")
        page.pump(3.0)  # Rest des simulierten Stroms auslaufen lassen

        if args.model:
            step("Antwort streamt und Verlauf scrollt mit", f"""
                document.querySelector('.js-new').click(); {SLEEP.format(ms=500)}
                const ed = document.querySelector('.js-editor'); ed.focus();
                ed.textContent = 'UI-Test: Schreib zwanzig nummerierte Sätze über Wolken, jeder Satz in eine eigene Zeile.';
                ed.dispatchEvent(new InputEvent('input', {{ bubbles: true }}));
                {SLEEP.format(ms=200)} document.querySelector('.js-send').click();
                const th = document.querySelector('.js-thread'); let maxRest = 0, grew = false, h0 = th.scrollHeight;
                for (let i = 0; i < 240; i++) {{
                  {SLEEP.format(ms=500)}
                  if (th.scrollHeight > th.clientHeight) maxRest = Math.max(maxRest, th.scrollHeight - th.scrollTop - th.clientHeight);
                  if (th.scrollHeight > h0 + 200) grew = true;
                  const send = document.querySelector('.js-send');
                  if (grew && send && send.title === 'Senden') break;
                }}
                const answer = [...document.querySelectorAll('.js-thread .js-jarvis .js-text')].pop();
                const text = answer ? answer.innerText.trim() : '';
                return text.length > 40 && grew && maxRest < 120 ? true : {{ ok: false, laenge: text.length, gewachsen: grew, maxAbstand: Math.round(maxRest) }};""",
                 timeout=150)

        page.pump(1.0)
        later = http_json(BASE + "/errors?limit=2000").get("errors", [])
        fresh = [e for e in later[errors_before:] if e.get("source") == "frontend"]
        results.append(("Fehlerprotokoll ohne neue Oberflächen-Fehler", not fresh,
                        "; ".join(f"{e.get('kind')}: {e.get('message')}"[:160] for e in fresh[:3])))
        print(f"{'OK  ' if not fresh else 'FEHL'} Fehlerprotokoll ohne neue Oberflächen-Fehler"
              + (f"\n       {results[-1][2]}" if fresh else ""))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} bestanden.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
