"""MCP Server with HTTP/SSE transport for CueSheet"""

import json
import logging
import asyncio
from fastapi import Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from .. import auth
from .tools import get_all_tools

logger = logging.getLogger("uvicorn.error")

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "cuesheet-mcp", "version": "1.0.0"}


def _jsonrpc_result(request_id, result):
    # JSON-RPC errors should ride on HTTP 200; non-2xx breaks compliant clients.
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _jsonrpc_error(request_id, code, message, http_status=200):
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=http_status,
    )


class MCPServer:
    """MCP Server for CueSheet - exposes CRUD operations as MCP tools."""

    def __init__(self):
        self.tools = get_all_tools()
        self.tool_map = {tool["name"]: tool for tool in self.tools}
        logger.info(f"MCP Server initialized with {len(self.tools)} tools")

    async def handle_request(self, request: Request) -> JSONResponse:
        """Handle MCP JSON-RPC request.

        Supports: initialize, tools/list, tools/call, ping, notifications/initialized.
        """
        auth_response = await auth.require_auth(request)
        if auth_response:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _jsonrpc_error(None, -32700, "Parse error: Invalid JSON", 400)

        method = body.get("method")
        params = body.get("params", {}) or {}
        request_id = body.get("id")

        try:
            if method == "initialize":
                return _jsonrpc_result(
                    request_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": SERVER_INFO,
                    },
                )

            if method in ("notifications/initialized", "notifications/cancelled"):
                # Notifications have no id and expect no response, but we return
                # 200 with an empty body if the client used a request shape.
                return JSONResponse({}, status_code=200)

            if method == "ping":
                return _jsonrpc_result(request_id, {})

            if method == "tools/list":
                return _jsonrpc_result(
                    request_id,
                    {
                        "tools": [
                            {
                                "name": tool["name"],
                                "description": tool["description"],
                                "inputSchema": tool["inputSchema"],
                                "annotations": tool.get(
                                    "annotations",
                                    {"readOnlyHint": False, "destructiveHint": False},
                                ),
                            }
                            for tool in self.tools
                        ]
                    },
                )

            if method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {}) or {}

                if tool_name not in self.tool_map:
                    return _jsonrpc_error(
                        request_id, -32601, f"Tool not found: {tool_name}"
                    )

                tool = self.tool_map[tool_name]
                handler = tool["handler"]
                try:
                    result = await handler(arguments)
                    return _jsonrpc_result(
                        request_id, {"content": result, "isError": False}
                    )
                except Exception as e:
                    logger.exception("Tool execution error (%s)", tool_name)
                    # MCP convention: tool-level errors come back as content
                    # with isError=true, not JSON-RPC errors.
                    return _jsonrpc_result(
                        request_id,
                        {
                            "content": [
                                {"type": "text", "text": f"Tool execution failed: {e}"}
                            ],
                            "isError": True,
                        },
                    )

            return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")

        except Exception:
            logger.exception("MCP request error")
            return _jsonrpc_error(request_id, -32603, "Internal error")

    async def handle_sse(self, request: Request):
        """SSE connection for streaming updates (kept for backward compat)."""
        auth_response = await auth.require_auth(request)
        if auth_response:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        async def event_generator():
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {"serverInfo": SERVER_INFO},
                    }
                ),
            }
            try:
                while True:
                    await asyncio.sleep(30)
                    yield {"event": "ping", "data": json.dumps({"type": "ping"})}
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SSE stream error")

        return EventSourceResponse(event_generator())


mcp_server = MCPServer()
