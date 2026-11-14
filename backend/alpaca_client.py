"""Alpaca (alpaca.markets) for Jarvis: market data, account and orders.

Thin layer over Alpaca's REST API — one request() for every endpoint plus
formatters that turn the JSON into a few short German lines, because the
whole tool result lands in the context of a small local model.

Paper is the default. Live only counts when ALPACA_MODE=live is set in .env
AND live keys exist; it can't be switched on by voice. Anything that changes
the account (orders, cancels, closing positions) is never sent from here
directly — backend/tools.py routes it through confirm.propose first.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import requests

from . import config

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"

_TIMEOUT = (4, 15)
_MAX_ROWS = 12


class AlpacaError(Exception):
    pass


def mode() -> str:
    """"live" only when asked for AND possible, otherwise "paper"."""
    if config.ALPACA_MODE == "live" and config.ALPACA_LIVE_KEY and config.ALPACA_LIVE_SECRET:
        return "live"
    return "paper"


def account_label() -> str:
    return "LIVE-Konto, ECHTES GELD" if mode() == "live" else "Paper-Konto"


def _keys() -> tuple[str, str]:
    if mode() == "live":
        return config.ALPACA_LIVE_KEY, config.ALPACA_LIVE_SECRET
    return config.ALPACA_PAPER_KEY, config.ALPACA_PAPER_SECRET


def missing_keys_hint() -> str | None:
    """None if usable, else what to put into .env."""
    key, secret = _keys()
    if key and secret:
        return None
    return (
        "Alpaca ist noch nicht eingerichtet: In der .env fehlen ALPACA_PAPER_KEY und "
        "ALPACA_PAPER_SECRET (Paper-Schlüssel aus dem Alpaca-Dashboard). Danach Jarvis neu starten."
    )


def is_data_path(path: str) -> bool:
    """Market data lives on its own host; everything else is the trading API."""
    return path.startswith(("/v2/stocks", "/v1beta"))


def request(method: str, path: str, params: dict | None = None, body: dict | None = None, data: bool | None = None):
    """One Alpaca call; returns the decoded JSON (None for an empty reply).

    `path` must be a path on Alpaca's own hosts ("/v2/account") — never a
    full URL, so a made-up address from the model can't receive the keys.
    """
    hint = missing_keys_hint()
    if hint:
        raise AlpacaError(hint)
    path = (path or "").strip()
    if not path.startswith("/") or path.startswith("//") or "://" in path or ".." in path or "@" in path:
        raise AlpacaError(f"Ungültiger Alpaca-Pfad: {path!r}. Erlaubt sind nur Pfade wie /v2/account.")
    if data is None:
        data = is_data_path(path)
    base = DATA_URL if data else (LIVE_URL if mode() == "live" else PAPER_URL)
    key, secret = _keys()
    try:
        resp = requests.request(
            method.upper(), base + path,
            params={k: v for k, v in (params or {}).items() if v not in (None, "")},
            json=body if body else None,
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise AlpacaError(f"Alpaca nicht erreichbar: {exc}") from None
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("message") or resp.text
        except ValueError:
            detail = resp.text
        raise AlpacaError(f"Alpaca hat abgelehnt ({resp.status_code}): {str(detail).strip()[:300]}")
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


# ------------------------------------------------------------------ helpers

def symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in str(raw or "").replace(";", ",").replace(" ", ",").split(",") if s.strip()]


def _num(value, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(value)


def _pct(value) -> str:
    try:
        return f"{float(value) * 100:+.2f} %".replace(".", ",")
    except (TypeError, ValueError):
        return "?"


def _when(ts) -> str:
    return str(ts or "")[:16].replace("T", " ")


def _clip(rows: list[str], total: int | None = None) -> str:
    total = len(rows) if total is None else total
    shown = rows[:_MAX_ROWS]
    if total > len(shown):
        shown.append(f"… und {total - len(shown)} weitere.")
    return "\n".join(shown)


def compact(payload, limit: int = 1800) -> str:
    """Raw JSON for alpaca_request, cut so it can't flood the context."""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + f" … (gekürzt, {len(text)} Zeichen insgesamt)"


# -------------------------------------------------------------- market data

def latest_price(symbol: str) -> float | None:
    """Last trade price, for the estimate in an order question. Best effort."""
    try:
        if "/" in symbol:
            got = request("GET", "/v1beta3/crypto/us/latest/trades", {"symbols": symbol})
            return float(got["trades"][symbol]["p"])
        got = request("GET", f"/v2/stocks/{quote(symbol)}/trades/latest", {"feed": config.ALPACA_DATA_FEED})
        return float(got["trade"]["p"])
    except (AlpacaError, KeyError, TypeError, ValueError):
        return None


def market_data(kind: str, raw_symbols: str = "", timeframe: str = "", start: str = "", end: str = "", limit: str = "") -> str:
    kind = (kind or "quote").strip().lower()
    syms = symbols(raw_symbols)
    feed = config.ALPACA_DATA_FEED
    try:
        n = max(1, min(int(float(limit)), 1000))
    except (TypeError, ValueError):
        n = 0

    if kind in ("movers", "most_active"):
        if kind == "movers":
            got = request("GET", "/v1beta1/screener/stocks/movers", {"top": n or 5})
            lines = []
            for label, key in (("Gewinner", "gainers"), ("Verlierer", "losers")):
                rows = [f"{r['symbol']} {_num(r.get('price'))} $ ({float(r.get('percent_change', 0)):+.1f} %)" for r in got.get(key, [])]
                lines.append(f"{label}: " + (", ".join(rows) or "keine"))
            return "\n".join(lines)
        got = request("GET", "/v1beta1/screener/stocks/most-actives", {"top": n or 10, "by": "volume"})
        rows = [f"{r['symbol']} (Volumen {_num(r.get('volume'), 0)})" for r in got.get("most_actives", [])]
        return "Meistgehandelt: " + (", ".join(rows) or "keine Daten")

    if kind == "news":
        got = request("GET", "/v1beta1/news", {"symbols": ",".join(syms), "limit": n or 5, "sort": "desc"})
        rows = [f"{_when(a.get('created_at'))} — {a.get('headline', '')} ({a.get('source', '')})" for a in got.get("news", [])]
        return _clip(rows) or "Keine Nachrichten gefunden."

    if not syms:
        return "Für welches Symbol? Zum Beispiel NVDA oder BTC/USD."

    if kind == "option_chain":
        got = request("GET", f"/v1beta1/options/snapshots/{quote(syms[0])}", {"limit": n or 20, "feed": "indicative"})
        rows = []
        for contract, snap in sorted((got.get("snapshots") or {}).items()):
            q = snap.get("latestQuote") or {}
            rows.append(f"{contract}: Geld {_num(q.get('bp'))} / Brief {_num(q.get('ap'))}")
        return _clip(rows) or f"Keine Optionsdaten für {syms[0]}."

    crypto = any("/" in s for s in syms)
    joined = ",".join(syms)

    if kind == "bars":
        params = {"symbols": joined, "timeframe": timeframe or "1Day", "start": start, "end": end, "limit": n or 30}
        if crypto:
            got = request("GET", "/v1beta3/crypto/us/bars", params)
        else:
            got = request("GET", "/v2/stocks/bars", {**params, "feed": feed, "adjustment": "split"})
        out = []
        for sym in syms:
            bars = (got.get("bars") or {}).get(sym) or []
            if not bars:
                out.append(f"{sym}: keine Kerzen im Zeitraum.")
                continue
            first, last = bars[0], bars[-1]
            change = (last["c"] / first["o"] - 1) if first.get("o") else 0
            out.append(
                f"{sym} {params['timeframe']}, {len(bars)} Kerzen {_when(first['t'])} bis {_when(last['t'])}: "
                f"Schluss {_num(last['c'])}, Hoch {_num(max(b['h'] for b in bars))}, "
                f"Tief {_num(min(b['l'] for b in bars))}, Veränderung {_pct(change)}."
            )
            out.append("Letzte: " + "; ".join(f"{_when(b['t'])} {_num(b['c'])}" for b in bars[-5:]))
        return "\n".join(out)

    if kind == "trades":
        path = "/v1beta3/crypto/us/latest/trades" if crypto else "/v2/stocks/trades/latest"
        got = request("GET", path, {"symbols": joined, **({} if crypto else {"feed": feed})})
        rows = [f"{s}: letzter Handel {_num(t.get('p'))} $ um {_when(t.get('t'))}" for s, t in (got.get("trades") or {}).items()]
        return "\n".join(rows) or "Keine Trades gefunden."

    if kind == "snapshot" and not crypto:
        got = request("GET", "/v2/stocks/snapshots", {"symbols": joined, "feed": feed})
        rows = []
        for sym, snap in (got or {}).items():
            day, prev = snap.get("dailyBar") or {}, snap.get("prevDailyBar") or {}
            price = (snap.get("latestTrade") or {}).get("p")
            change = (price / prev["c"] - 1) if price and prev.get("c") else None
            rows.append(
                f"{sym}: {_num(price)} $" + (f" ({_pct(change)} zum Vortag)" if change is not None else "")
                + f", heute Hoch {_num(day.get('h'))} / Tief {_num(day.get('l'))}, Volumen {_num(day.get('v'), 0)}"
            )
        return "\n".join(rows) or "Keine Daten gefunden."

    # quote (default; also the crypto fallback for "snapshot")
    path = "/v1beta3/crypto/us/latest/quotes" if crypto else "/v2/stocks/quotes/latest"
    got = request("GET", path, {"symbols": joined, **({} if crypto else {"feed": feed})})
    rows = [
        f"{s}: Geld {_num(q.get('bp'))} $ / Brief {_num(q.get('ap'))} $ (Stand {_when(q.get('t'))})"
        for s, q in (got.get("quotes") or {}).items()
    ]
    return "\n".join(rows) or "Kein Kurs gefunden."


# ------------------------------------------------------------------ account

def _order_line(o: dict) -> str:
    side = "Kauf" if o.get("side") == "buy" else "Verkauf"
    amount = f"{o['qty']} Stück" if o.get("qty") else f"{_num(o.get('notional'))} $"
    price = "".join(
        f", {name} {_num(o[key])}" for name, key in (("Limit", "limit_price"), ("Stop", "stop_price")) if o.get(key)
    )
    return f"{side} {amount} {o.get('symbol')} ({o.get('type')}{price}), Status {o.get('status')}, ID {o.get('id')}"


def account_info(what: str, symbol: str = "", status: str = "") -> str:
    what = (what or "account").strip().lower()
    label = account_label()

    if what == "account":
        a = request("GET", "/v2/account")
        try:
            day = float(a["equity"]) - float(a["last_equity"])
            day_text = f", heute {day:+,.2f} $".replace(",", "X").replace(".", ",").replace("X", ".")
        except (KeyError, TypeError, ValueError):
            day_text = ""
        return (
            f"{label}: Gesamtwert {_num(a.get('equity'))} $, Bargeld {_num(a.get('cash'))} $, "
            f"Kaufkraft {_num(a.get('buying_power'))} $" + day_text + "."
        )
    if what == "positions":
        pos = request("GET", "/v2/positions") or []
        rows = [
            f"{p['symbol']}: {p['qty']} Stück, Wert {_num(p.get('market_value'))} $, "
            f"Einstand {_num(p.get('avg_entry_price'))}, G/V {_num(p.get('unrealized_pl'))} $ ({_pct(p.get('unrealized_plpc'))})"
            for p in pos
        ]
        return f"{label}, {len(pos)} Positionen:\n" + _clip(rows) if rows else f"{label}: keine offenen Positionen."
    if what == "orders":
        orders = request("GET", "/v2/orders", {"status": status or "open", "limit": 50, "direction": "desc"}) or []
        rows = [_order_line(o) for o in orders]
        return f"{label}, {len(orders)} Orders ({status or 'open'}):\n" + _clip(rows) if rows else f"{label}: keine Orders ({status or 'open'})."
    if what == "activities":
        acts = request("GET", "/v2/account/activities", {"page_size": 20}) or []
        rows = [
            f"{_when(x.get('transaction_time') or x.get('date'))} {x.get('activity_type')} "
            f"{x.get('side', '')} {x.get('qty', '')} {x.get('symbol', '')} {_num(x.get('price') or x.get('net_amount'))}".replace("  ", " ")
            for x in acts
        ]
        return _clip(rows) or "Keine Kontobewegungen."
    if what == "portfolio_history":
        h = request("GET", "/v2/account/portfolio/history", {"period": "1M", "timeframe": "1D"})
        eq = [e for e in (h.get("equity") or []) if e]
        if len(eq) < 2:
            return "Noch kein Depotverlauf vorhanden."
        return (
            f"{label}, letzter Monat: von {_num(eq[0])} $ auf {_num(eq[-1])} $ ({_pct(eq[-1] / eq[0] - 1)}), "
            f"Hoch {_num(max(eq))} $, Tief {_num(min(eq))} $."
        )
    if what == "clock":
        c = request("GET", "/v2/clock")
        state = "geöffnet" if c.get("is_open") else "geschlossen"
        nxt = f"schließt {_when(c.get('next_close'))}" if c.get("is_open") else f"öffnet {_when(c.get('next_open'))}"
        return f"Die US-Börse ist {state}, {nxt} (New Yorker Zeit)."
    if what == "calendar":
        days = request("GET", "/v2/calendar", {"start": _when(request("GET", "/v2/clock").get("timestamp"))[:10]}) or []
        return "Nächste Handelstage: " + ", ".join(f"{d['date']} {d['open']}–{d['close']}" for d in days[:5])
    if what == "asset":
        syms = symbols(symbol)
        if not syms:
            return "Für welches Symbol?"
        a = request("GET", f"/v2/assets/{quote(syms[0], safe='')}")
        flags = [name for name, key in (("handelbar", "tradable"), ("Bruchstücke", "fractionable"), ("leerverkaufbar", "shortable")) if a.get(key)]
        return f"{a.get('symbol')}: {a.get('name')}, Börse {a.get('exchange')}, Klasse {a.get('class')}, {', '.join(flags) or 'nicht handelbar'}."
    if what == "watchlists":
        lists = request("GET", "/v2/watchlists") or []
        rows = []
        for w in lists:
            full = request("GET", f"/v2/watchlists/{w['id']}")
            rows.append(f"{w.get('name')}: " + (", ".join(a["symbol"] for a in full.get("assets") or []) or "leer"))
        return _clip(rows) or "Keine Watchlists angelegt."
    return (
        f"Unbekannte Abfrage '{what}'. Möglich: account, positions, orders, activities, "
        "portfolio_history, clock, calendar, asset, watchlists."
    )
