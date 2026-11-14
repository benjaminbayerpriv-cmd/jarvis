"""Offline-Test der Alpaca-Werkzeuge gegen einen nachgebauten Alpaca-Server.

Braucht weder Schlüssel noch Netz:  .venv/bin/python test_alpaca.py
"""

import http.server
import json
import threading
from urllib.parse import parse_qs, urlparse

from backend import alpaca_client, config, confirm, panel, tools

CALLS: list[tuple[str, str, dict, dict | None, str]] = []


class FakeAlpaca(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _handle(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        CALLS.append((self.command, url.path, parse_qs(url.query), body, self.headers.get("APCA-API-KEY-ID", "")))
        routes = {
            ("GET", "/v2/stocks/quotes/latest"): {"quotes": {"NVDA": {"bp": 199.5, "ap": 200.5, "t": "2026-11-13T15:00:00Z"}}},
            ("GET", "/v2/stocks/NVDA/trades/latest"): {"trade": {"p": 200.0}},
            ("GET", "/v2/stocks/bars"): {"bars": {"NVDA": [
                {"t": "2026-11-11T05:00:00Z", "o": 100, "h": 112, "l": 99, "c": 110},
                {"t": "2026-11-12T05:00:00Z", "o": 110, "h": 125, "l": 108, "c": 120},
            ]}},
            ("GET", "/v2/account"): {"equity": "10000", "last_equity": "9900", "cash": "5000", "buying_power": "20000"},
            ("GET", "/v2/clock"): {"is_open": False, "next_open": "2026-11-16T09:30:00-05:00"},
            ("POST", "/v2/orders"): {"id": "ord-1", "status": "accepted"},
            ("DELETE", "/v2/orders"): [],
            ("POST", "/v2/watchlists"): {"id": "wl-1"},
        }
        payload = routes.get((self.command, url.path))
        if payload is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"message": "not found"}')
            return
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST = do_DELETE = do_PATCH = do_PUT = _handle


def sent(method: str) -> list:
    return [c for c in CALLS if c[0] == method]


def main() -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAlpaca)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    alpaca_client.PAPER_URL = alpaca_client.DATA_URL = base
    alpaca_client.LIVE_URL = "http://127.0.0.1:9"  # must never be reached in these tests
    panel.push = lambda *a, **k: None

    # Without keys every tool explains what is missing and sends nothing.
    config.ALPACA_PAPER_KEY = config.ALPACA_PAPER_SECRET = config.ALPACA_LIVE_KEY = config.ALPACA_LIVE_SECRET = ""
    config.ALPACA_MODE = "paper"
    for name, args in (("alpaca_data", {"kind": "quote", "symbols": "NVDA"}), ("alpaca_account", {"what": "account"}),
                       ("alpaca_order", {"action": "buy", "symbol": "NVDA", "qty": "1"}),
                       ("alpaca_request", {"method": "POST", "path": "/v2/watchlists", "body": "{}"})):
        assert "ALPACA_PAPER_KEY" in tools.call_tool(name, args), name
    assert not CALLS and not confirm.is_pending()

    config.ALPACA_PAPER_KEY, config.ALPACA_PAPER_SECRET = "PKTEST", "secret"

    # Reading.
    assert "199,50" in tools.call_tool("alpaca_data", {"kind": "quote", "symbols": "nvda"})
    bars = tools.call_tool("alpaca_data", {"kind": "bars", "symbols": "NVDA", "timeframe": "1Day"})
    assert "2 Kerzen" in bars and "Hoch 125,00" in bars and "+20,00 %" in bars, bars
    account = tools.call_tool("alpaca_account", {"what": "account"})
    assert "Paper-Konto" in account and "10.000,00" in account, account
    assert "geschlossen" in tools.call_tool("alpaca_account", {"what": "clock"})
    assert CALLS[0][4] == "PKTEST"

    # An order is only a question until the user says yes.
    question = tools.call_tool("alpaca_order", {"action": "buy", "symbol": "NVDA", "qty": 2})
    assert question.endswith("?") or "Paper-Konto" in question, question
    assert "2 Stück NVDA kaufen" in question and "Paper-Konto" in question and "400 $" in question, question
    assert not sent("POST") and confirm.is_pending()
    assert confirm.resolve("nein") == "Alles klar, abgebrochen."
    assert not sent("POST") and not confirm.is_pending()

    tools.call_tool("alpaca_order", {"action": "buy", "symbol": "NVDA", "qty": "2", "limit_price": "190,5", "stop_loss": "180", "take_profit": "210"})
    assert confirm.resolve("erzähl mir lieber einen Witz") is None and not sent("POST")  # lapses

    tools.call_tool("alpaca_order", {"action": "buy", "symbol": "NVDA", "qty": "2", "limit_price": "190,5", "stop_loss": "180", "take_profit": "210"})
    done = confirm.resolve("ja")
    assert "Order aufgegeben" in done and "ord-1" in done, done
    assert len(sent("POST")) == 1
    body = sent("POST")[0][3]
    assert body == {"symbol": "NVDA", "side": "buy", "type": "limit", "time_in_force": "day", "qty": "2",
                    "limit_price": "190.5", "order_class": "bracket",
                    "take_profit": {"limit_price": "210"}, "stop_loss": {"stop_price": "180"}}, body
    assert confirm.resolve("ja") is None and len(sent("POST")) == 1  # a second "ja" sends nothing

    # Incomplete orders ask instead of guessing.
    assert "Wie viele" in tools.call_tool("alpaca_order", {"action": "sell", "symbol": "NVDA"})
    assert "Limitkurs" in tools.call_tool("alpaca_order", {"action": "buy", "symbol": "NVDA", "qty": "1", "type": "limit"})
    assert not confirm.is_pending()

    # Cancel-all warns about the shared account and waits.
    question = tools.call_tool("alpaca_order", {"action": "cancel_all"})
    assert "ALLE" in question and "anderer Programme" in question and not sent("DELETE")
    assert "storniert" in confirm.resolve("ja") and len(sent("DELETE")) == 1

    # alpaca_request: GET runs, anything else asks, foreign addresses are refused.
    assert "buying_power" in tools.call_tool("alpaca_request", {"method": "GET", "path": "/v2/account"})
    posts = len(sent("POST"))
    question = tools.call_tool("alpaca_request", {"method": "POST", "path": "/v2/watchlists", "body": '{"name": "Tech"}'})
    assert "POST /v2/watchlists" in question and len(sent("POST")) == posts
    assert "wl-1" in confirm.resolve("ja") and len(sent("POST")) == posts + 1
    before = len(CALLS)
    for bad in ("https://evil.example/v2/account", "//evil.example/x", "/v2/../../x", "v2/account"):
        assert "Ungültiger Alpaca-Pfad" in tools.call_tool("alpaca_request", {"method": "GET", "path": bad}), bad
    assert "nur lesende" in tools.call_tool("alpaca_request", {"method": "POST", "path": "/v2/stocks/bars"})
    assert len(CALLS) == before and not confirm.is_pending()

    # Live needs both the switch and live keys.
    config.ALPACA_MODE = "live"
    assert alpaca_client.mode() == "paper" and "Paper-Konto" in tools.call_tool("alpaca_account", {"what": "account"})
    config.ALPACA_LIVE_KEY, config.ALPACA_LIVE_SECRET = "AKLIVE", "secret"
    assert alpaca_client.mode() == "live"
    question = tools.call_tool("alpaca_order", {"action": "sell", "symbol": "NVDA", "notional": "500"})
    assert "ECHTES GELD" in question, question
    assert confirm.resolve("nein") == "Alles klar, abgebrochen."
    config.ALPACA_MODE = "paper"

    # The schemas the model sees match the dispatch table.
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    assert {"alpaca_data", "alpaca_account", "alpaca_order", "alpaca_request"} <= names & set(tools.DISPATCH)

    server.shutdown()
    print(f"test_alpaca: alles bestanden ({len(CALLS)} Aufrufe am nachgebauten Server).")


if __name__ == "__main__":
    main()
