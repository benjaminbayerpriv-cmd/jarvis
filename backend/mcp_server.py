"""MCP server that exposes Jarvis's tools to LM Studio's native chat API.

LM Studio's /api/v1/chat has no `tools` field for client-side function
definitions — the only way to give a model tools there is through an MCP
server, listed under `integrations`. LM Studio then runs the tool loop
itself: it connects here, lists the tools, calls them and feeds the
results back to the model, while streaming what happens
(`tool_call.start/success/failure`, plus model-load and prompt-processing
progress) to Jarvis.

Every call still ends up in tools.call_tool — only the transport changed.

Registered in LM Studio's own `mcp.json`, NOT as a per-request
`ephemeral_mcp` integration: LM Studio >= 0.4.15 rejects any ephemeral MCP
server whose URL resolves to a non-public address — confirmed live even
for `http://127.0.0.1:...` on the SAME machine (an SSRF guard against a
chat request dynamically pointing LM Studio at an internal address; see
https://github.com/lmstudio-ai/lms/issues/574). A server pre-registered by
the user in mcp.json isn't affected — the address was never
attacker-suppliable in the first place. See mcp_json_snippet() for the
one-time entry the user adds, and SETUP.md for the full instructions.

The server listens on all interfaces because LM Studio may run on another
machine in the LAN; a bearer token keeps everyone else out — run_shell
must never be reachable for arbitrary devices on the network. Loopback
(127.0.0.1) is exempt because LM Studio (as observed in 0.4.25+1) does
not forward mcp.json's Authorization header to this server, and a local
connection is the user's own machine anyway. The token is persisted
(config.JARVIS_MCP_TOKEN), not regenerated per start: mcp.json is a
one-time, human-edited entry, so a token that changed on every restart
would make it go stale immediately.
"""

from __future__ import annotations

import hmac
import json
import socket
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator
from urllib.parse import urlparse

import anyio
import uvicorn
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings

from . import config, hardware, tools

SERVER_LABEL = "jarvis"
INTEGRATION_ID = f"mcp/{SERVER_LABEL}"
_PATH = "/mcp"

# Whether a tool call may run right now, and for whom — set by whichever
# native chat round (backend/llm_client.py) is currently talking to LM
# Studio, cleared the moment that round ends (normally, cancelled, or a
# warm-up that must never let a tool actually run). A single slot, not a
# per-request registry, is safe here because LM Studio itself only ever
# processes one chat request at a time (its "single-slot" completion
# queue — already relied on elsewhere in this codebase) and mcp.json's
# static headers give a tool call no per-request identifier to key a
# registry on in the first place.
_active_lock = threading.Lock()
_active_may_run: Callable[[], bool] | None = None


def _tool_list() -> list[types.Tool]:
    return [
        types.Tool(
            name=schema["function"]["name"],
            description=schema["function"].get("description", ""),
            input_schema=schema["function"].get("parameters") or {"type": "object", "properties": {}},
        )
        for schema in tools.TOOL_SCHEMAS
    ]


async def _on_list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=_tool_list())


async def _on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    with _active_lock:
        may_run = _active_may_run
    if may_run is None or not may_run():
        print(f"[mcp] {params.name} abgelehnt: keine aktive Anfrage erlaubt das gerade.")
        text = "Abgebrochen — dieses Werkzeug wurde nicht ausgeführt."
    else:
        # tools.call_tool blocks (subprocesses, HTTP, the browser agent) —
        # keep it off the event loop so parallel MCP requests still flow.
        text = await anyio.to_thread.run_sync(tools.call_tool, params.name, params.arguments or {})
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def _build_app():
    server = Server(SERVER_LABEL, on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)
    mcp_app = server.streamable_http_app(
        streamable_http_path=_PATH,
        stateless_http=True,
        host="0.0.0.0",
        # The SDK's Host-header check only knows localhost; LM Studio in the
        # LAN connects via this machine's LAN IP. Loopback is the trust
        # boundary, the bearer token below protects everything beyond it.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    expected = f"Bearer {config.ensure_mcp_token()}".encode()

    # LM Studio >= 0.4.25 (observed 0.4.25+1) does NOT forward a static
    # `Authorization` header from mcp.json to this server — its chat started
    # sending the connect without it, and this server's 401 then crashed
    # LM Studio's MCP bridge (libuv assertion, exit 0xC0000409). Loopback
    # connections are the user's own machine (and the very child of a local
    # process), so they may connect without a token; every other host — any
    # device on the LAN, which is the threat the token exists for — must
    # still present it.
    _LOOPBACK_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

    async def app(scope, receive, send):
        if scope["type"] == "http":
            client_host = (scope.get("client") or ("", 0))[0]
            auth = dict(scope["headers"]).get(b"authorization", b"")
            authorized = client_host in _LOOPBACK_HOSTS or hmac.compare_digest(auth, expected)
            if not authorized:
                # LM Studio's MCP bridge expects the 401 body to be a JSON
                # OAuth-style error (it parses it before deciding how to
                # proceed). A plain-text body crashed its libuv bridge with
                # an assertion (exit code 3221226505 = 0xC0000409). Send a
                # JSON error instead so a token-less connect degrades to a
                # readable error rather than a crash.
                body = json.dumps({
                    "error": "unauthorized",
                    "error_description": "Ungültiges Jarvis-MCP-Token (JARVIS_MCP_TOKEN). "
                    "Prüfe den Wert in mcp.json gegen die .env.",
                }).encode()
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ]})
                await send({"type": "http.response.body", "body": body})
                return
        await mcp_app(scope, receive, send)

    return app


class ToolServerError(RuntimeError):
    """The server couldn't start; the message is meant for the user."""


_start_lock = threading.Lock()
_uvicorn_server: uvicorn.Server | None = None


def ensure_started() -> None:
    """Start the server on first use. Raises if the port can't be bound —
    without this server LM Studio has no tools at all."""
    global _uvicorn_server
    with _start_lock:
        if _uvicorn_server is not None and _uvicorn_server.started:
            return
        server = uvicorn.Server(uvicorn.Config(
            _build_app(), host="0.0.0.0", port=config.JARVIS_MCP_PORT, log_level="warning",
        ))
        thread = threading.Thread(target=server.run, name="jarvis-mcp", daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise ToolServerError(
                    f"Jarvis' Werkzeug-Server (MCP) konnte nicht auf Port {config.JARVIS_MCP_PORT} "
                    "starten — ist der Port belegt? JARVIS_MCP_PORT in der .env ändern."
                )
            time.sleep(0.02)
        _uvicorn_server = server
        print(f"[mcp] Werkzeug-Server läuft auf Port {config.JARVIS_MCP_PORT}.")
        print(f"[mcp] Einmalig in LM Studios mcp.json eintragen:\n{mcp_json_snippet()}")


def _address_seen_by_lm_studio() -> str:
    """This machine's IP as LM Studio has to dial it: loopback when LM Studio
    runs here, otherwise the local interface that routes to LM Studio's host
    — resolved fresh each time, since the machine may switch networks. Only
    matters for the mcp.json snippet shown to the user; unlike the old
    ephemeral_mcp path this is no longer sent to LM Studio automatically."""
    host = urlparse(hardware.lm_studio_root()).hostname or "127.0.0.1"
    if host in ("127.0.0.1", "localhost", "::1"):
        return "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((host, 1))  # UDP connect sends nothing, it only picks the route
        return probe.getsockname()[0]


def server_url() -> str:
    return f"http://{_address_seen_by_lm_studio()}:{config.JARVIS_MCP_PORT}{_PATH}"


def mcp_json_snippet() -> str:
    """The one-time entry the user pastes into LM Studio's mcp.json (Program
    tab -> Install -> Edit mcp.json). Re-print this (e.g. after a network
    change moved server_url(), or a fresh JARVIS_MCP_TOKEN) rather than
    assuming the previous entry still matches."""
    return json.dumps(
        {
            "mcpServers": {
                SERVER_LABEL: {
                    "url": server_url(),
                    "headers": {"Authorization": f"Bearer {config.ensure_mcp_token()}"},
                }
            }
        },
        indent=2,
        ensure_ascii=False,
    )


@contextmanager
def request_scope(may_run: Callable[[], bool]) -> Iterator[dict]:
    """The integration entry for one LM Studio chat request — referencing
    the mcp.json server above by its plugin id, not carrying a URL/token of
    its own (LM Studio's /api/v1/chat has no headers field for the
    "plugin" integration type; only its own ephemeral_mcp type does, and
    that one is what's blocked — see module docstring). Tool calls arriving
    while this scope is open run only as long as `may_run()` holds."""
    ensure_started()
    global _active_may_run
    with _active_lock:
        _active_may_run = may_run
    try:
        yield {"type": "plugin", "id": INTEGRATION_ID}
    finally:
        with _active_lock:
            if _active_may_run is may_run:
                _active_may_run = None


def output_text(raw: str) -> str:
    """LM Studio reports a tool's output as the raw MCP content list
    (`[{"type":"text","text":"..."}]`) — back to the plain string
    tools.call_tool returned."""
    try:
        content = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw or ""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return raw
