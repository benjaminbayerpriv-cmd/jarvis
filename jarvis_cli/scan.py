"""Network search for LM Studio (or another OpenAI-compatible local LLM
server) in the LAN.

Mirrors what POST /model/scan does in the backend — sweep the local /24 for
open ports, then confirm each hit really is an LLM server by reading its
model list — but on the standard library's thread pool instead of asyncio, so
`jarvis scan` also works before the virtualenv exists.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from . import context as ctx
from . import lmstudio
from .ui import ui

QUICK_PORTS = [1234]
EXTENDED_PORTS = [1234, 11434, 5000, 5001, 7860, 8000, 8080, 4891, 1337]
CONNECT_TIMEOUT = 0.35
VALIDATE_TIMEOUT = 2.5
WORKERS = 192


def local_subnet() -> ipaddress.IPv4Network | None:
    """The /24 this machine is on, via the classic UDP-connect trick:
    connect() on a datagram socket sends nothing, it only makes the OS report
    the source address it would use — exactly the LAN-facing IP needed."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return ipaddress.ip_network(f"{probe.getsockname()[0]}/24", strict=False)
    except OSError:
        return None
    finally:
        probe.close()


def _port_open(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def _validate(ip: str, port: int, token: str) -> dict | None:
    """Confirm a host answering on that port really is an LLM server. The
    configured token is only ever sent to the IP currently being checked."""
    url = f"http://{ip}:{port}/v1/models"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    payload, _ = ctx.http_json(url, timeout=VALIDATE_TIMEOUT, headers=headers)
    if payload is None:
        return None
    models = [m.get("id") for m in payload.get("data", []) if m.get("id")]
    return {"ip": ip, "port": port, "url": f"http://{ip}:{port}/v1", "models": models}


def scan(ports: list[int], on_progress=None) -> list[dict]:
    """Returns every confirmed LLM server in the /24. on_progress(done, total)
    is called as the sweep advances so the caller can draw a bar."""
    network = local_subnet()
    if network is None:
        return []
    hosts = [str(h) for h in network.hosts()]
    targets = [(ip, port) for ip in hosts for port in ports]
    total = len(targets)
    open_hits: list[tuple[str, int]] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_port_open, ip, port): (ip, port) for ip, port in targets}
        for done, future in enumerate(futures, 1):
            if future.result():
                open_hits.append(futures[future])
            if on_progress:
                on_progress(done, total)

    token = lmstudio.token()
    found: list[dict] = []
    for ip, port in open_hits:
        result = _validate(ip, port, token)
        if result:
            found.append(result)
    return found


def _run(ports: list[int], extended: bool, apply: bool) -> list[dict]:
    network = local_subnet()
    ui.heading("Netzwerksuche")
    if network is None:
        ui.fail("Konnte das lokale Netzwerk nicht bestimmen (keine Route zu 8.8.8.8?).")
        return []
    label = "erweiterte Suche (9 Ports)" if extended else "Schnellsuche (Port 1234)"
    ui.status("info", "Subnetz", str(network))
    ui.status("info", "Modus", label)
    ui.status("info", "Ziele", f"{len(list(network.hosts())) * len(ports)}")
    ui.out()

    started = time.monotonic()
    with ui.progress("Suche läuft …", total=len(list(network.hosts())) * len(ports)) as bar:
        found = scan(ports, on_progress=bar.set)
    bar.finish(f"{len(list(network.hosts())) * len(ports)} Ziele in {time.monotonic() - started:.1f}s geprüft")

    ui.out()
    if not found:
        ui.warn("Kein LM-Studio-Server im Netz gefunden.")
        ui.note("Geprüft wurde das /24 dieses Geräts. Prüfen: Läuft auf dem anderen Rechner "
                "tatsächlich der LM-Studio-Server (Developer → Start Server)? Ist er für "
                "andere Geräte freigegeben? Bei aktivem „Require Authentication“ braucht die "
                "Suche das Token — es wird die hier konfigurierte LM-Studio-Adresse geprüft.")
        if not extended:
            if ui.confirm("Erweiterte Suche über alle üblichen LLM-Ports starten?", default=True):
                return _run(EXTENDED_PORTS, True, apply)
        return []

    rows = []
    for host in found:
        rows.append((
            "ok" if host["ip"] == lmstudio.base_url_host() else "info",
            host["ip"],
            host["port"],
            len(host["models"]),
            ", ".join(host["models"][:2]) + (" …" if len(host["models"]) > 2 else ""),
        ))
    ui.table(("OK", "Adresse", "Port", "Modelle", "Geladen"), rows, mark_col=0)

    if not apply:
        return found
    if not ui.confirm(f"Adresse {found[0]['url']} verwenden?", default=True):
        return found
    lmstudio.set_base_url(found[0]["url"])
    ui.ok(f"{ctx.ENV_FILE.name} aktualisiert: LM_STUDIO_BASE_URL={found[0]['url']}")
    if found[0]["models"]:
        ui.note("Nächstes Modell wählen:  jarvis model")
    return found


def run(extended: bool = False, apply: bool = True) -> list[dict]:
    return _run(EXTENDED_PORTS if extended else QUICK_PORTS, extended, apply)


def describe() -> str:
    network = local_subnet()
    if network is None:
        return "Netzwerk unbekannt"
    host = urlparse(lmstudio.base_url()).hostname or "?"
    return f"{network} · eigener Rechner {ctx.local_ip()} · LM Studio {host}"
