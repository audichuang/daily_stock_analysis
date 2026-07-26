# -*- coding: utf-8 -*-
"""Tests for the minimal DSA MCP stdio adapter."""

from scripts.dsa_mcp_server import handle_message
from src.agent.tool_surface import ToolSurface
from src.agent.tools.registry import (
    ToolDefinition,
    ToolParameter,
    ToolPolicy,
    ToolRegistry,
)


def test_mcp_lists_and_calls_existing_stock_tool() -> None:
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="quote",
            description="Get a quote.",
            parameters=[
                ToolParameter(
                    name="stock_code",
                    type="string",
                    description="Stock code",
                ),
            ],
            handler=lambda stock_code: calls.append(stock_code) or {"code": stock_code},
            policy=ToolPolicy.declared(
                read_only=True,
                permissions=["market_data:read"],
                scope_dimensions=["stock"],
            ),
        )
    )
    surface = ToolSurface(registry)

    initialized = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        surface,
    )
    listed = handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        surface,
    )
    called = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "quote", "arguments": {"stock_code": "2330.TW"}},
        },
        surface,
    )

    assert initialized["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert listed["result"]["tools"][0]["name"] == "quote"
    assert called["result"]["isError"] is False
    assert called["result"]["structuredContent"] == {"code": "2330.TW"}
    assert calls == ["2330.TW"]
