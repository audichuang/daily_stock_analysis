# MCP 工具介面

DSA 可以作为 MCP 工具服务器，让外部 Agent 查询现有行情、新闻、技术分析、市场与回测能力；这个入口不运行 DSA 自带的 AI Agent，也不调用 LiteLLM。

## 启动

MCP 客户端使用标准 `stdio` transport 启动：

```json
{
  "mcpServers": {
    "daily-stock-analysis": {
      "command": "uv",
      "args": ["run", "python", "-m", "scripts.dsa_mcp_server"],
      "cwd": "/path/to/daily_stock_analysis"
    }
  }
}
```

服务器实现 MCP `initialize`、`ping`、`tools/list` 与 `tools/call`，工具 schema 和执行统一复用 `src.agent.tool_surface.ToolSurface`。DSA 数据源所需的环境变量必须能被该子进程读取。

## 安全边界

- 当前只提供本机 `stdio`，不开放网络端口，也没有额外认证层。
- 工具结果经过既有敏感字段遮罩；股票工具每次只允许请求该次参数明确指定的 `stock_code`。
- 启动此进程等同允许 MCP 客户端读取当前 DSA 环境可访问的数据，包括已配置的数据源和只读投资组合信息。
- 远端 Agent 应在 DSA 主机上启动此进程，或通过受控的进程／SSH 边界连接。不要把 stdio 包装成未经认证的公网服务。

需要跨主机的原生 MCP Streamable HTTP 时，再增加独立 transport，并补齐 Origin 验证、API 身份认证与限流；底层工具仍应复用同一个 `ToolSurface`。
