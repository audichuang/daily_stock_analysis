#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Expose the existing DSA ToolSurface over MCP stdio."""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

from src.agent.factory import get_tool_registry
from src.agent.stock_scope import StockScope
from src.agent.tool_surface import ToolSurface
from src.agent.tools.execution import ToolAccessContext


PROTOCOL_VERSION = "2025-06-18"


def _response(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _tool_context(arguments: dict) -> ToolAccessContext:
    stock_code = arguments.get("stock_code")
    stock_scope = None
    if isinstance(stock_code, str) and stock_code.strip():
        stock_scope = StockScope(
            expected_stock_code=stock_code,
            allowed_stock_codes={stock_code},
            mode="switch",
        )
    return ToolAccessContext(
        stock_scope=stock_scope,
        backend="mcp_stdio",
        redact_result=True,
    )


def handle_message(message: Any, surface: ToolSurface) -> Optional[dict]:
    """Handle one MCP JSON-RPC message."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid Request")

    request_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return _error(request_id, -32600, "Invalid Request")
    if "id" not in message:
        return None

    if method == "initialize":
        return _response(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "daily-stock-analysis", "version": "1"},
        })
    if method == "ping":
        return _response(request_id, {})
    if method == "tools/list":
        return _response(request_id, {
            "tools": surface.list_tools("mcp_descriptor"),
        })
    if method == "tools/call":
        params = message.get("params")
        if not isinstance(params, dict):
            return _error(request_id, -32602, "Invalid params")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(request_id, -32602, "Invalid params")
        if name not in {item["name"] for item in surface.list_tools("mcp_descriptor")}:
            return _error(request_id, -32602, "Unknown tool")

        execution = surface.execute_tool(name, arguments, _tool_context(arguments))
        result = {
            "content": [{"type": "text", "text": execution["result_text"]}],
            "isError": not execution["ok"],
        }
        if execution["ok"] and isinstance(execution["result"], dict):
            result["structuredContent"] = execution["result"]
        return _response(request_id, result)

    return _error(request_id, -32601, "Method not found")


def main() -> None:
    surface = ToolSurface(get_tool_registry())
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = handle_message(message, surface)
        except json.JSONDecodeError:
            response = _error(None, -32700, "Parse error")
        except Exception:
            response = _error(None, -32603, "Internal error")
        if response is not None:
            print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
