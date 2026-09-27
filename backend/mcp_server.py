"""MCP server that exposes Jarvis's tools to LM Studio's native chat API.

LM Studio's /api/v1/chat has no `tools` field for client-side function
definitions — the only way to give a model tools there is an MCP server
passed per request as an `ephemeral_mcp` integration. LM Studio then runs
the tool loop itself: it connects here, lists the tools, calls them and
feeds the results back to the model, while streaming what happens
(`tool_call.start/success/failure`, plus model-load and prompt-processing
progress) to Jarvis.

Every call still ends up in tools.call_tool — only the transport changed.

The server listens on all interfaces because LM Studio may run on another
machine in the LAN; a per-process bearer token (sent by LM Studio via the
integration's `headers`) keeps everyone else out — run_shell must never be
reachable for arbitrary devices on the network.
"""

from __future__ import annotations

import hmac
import json
import secrets
import socket
import threading
import time
import uuid
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
_PATH = "/mcp"
_REQUEST_HEADER = "x-jarvis-request"
_TOKEN = secrets.token_urlsafe(32)

# Chat request key -> "may tools still run for it?". A key only exists while
# its LM Studio request is being streamed, so a call arriving after the
# stream was closed (Stop button, pending confirmation, tool budget used up)
# is refused instead of acting on a turn nobody is listening to anymore.
_requests: dict[str, Callable[[], bool]] = {}
_requests_lock = threading.Lock()


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


def _may_run(request_key: str | None) -> bool:
    with _requests_lock:
        allowed = _requests.get(request_key or "")
    return allowed is not None and allowed()


async def _on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    request_key = ctx.request.headers.get(_REQUEST_HEADER) if ctx.request is not None else None
    if not _may_run(request_key):
        print(f"[mcp] {params.name} abgelehnt: zugehörige Anfrage ist beendet oder abgebrochen.")
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
        # LAN connects via this machine's LAN IP. The bearer token below is
        # the actual protection.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    expected = f"Bearer {_TOKEN}".encode()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(auth, expected):
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Unauthorized"})
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


def _address_seen_by_lm_studio() -> str:
    """This machine's IP as LM Studio has to dial it: loopback when LM Studio
    runs here, otherwise the local interface that routes to LM Studio's host
    — resolved per request, since the machine may switch networks."""
    host = urlparse(hardware.lm_studio_root()).hostname or "127.0.0.1"
    if host in ("127.0.0.1", "localhost", "::1"):
        return "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((host, 1))  # UDP connect sends nothing, it only picks the route
        return probe.getsockname()[0]


def server_url() -> str:
    return f"http://{_address_seen_by_lm_studio()}:{config.JARVIS_MCP_PORT}{_PATH}"


@contextmanager
def request_scope(may_run: Callable[[], bool]) -> Iterator[dict]:
    """The `ephemeral_mcp` integration for one LM Studio chat request. Tool
    calls carrying it only run while this scope is open and `may_run()`
    holds."""
    ensure_started()
    key = uuid.uuid4().hex
    with _requests_lock:
        _requests[key] = may_run
    try:
        yield {
            "type": "ephemeral_mcp",
            "server_label": SERVER_LABEL,
            "server_url": server_url(),
            "headers": {"Authorization": f"Bearer {_TOKEN}", "X-Jarvis-Request": key},
        }
    finally:
        with _requests_lock:
            _requests.pop(key, None)


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
