"""Клиент MCP: подключение внешних серверов к ядру.

Пакет даёт ядру возможность быть MCP-**клиентом**: поднимать внешние
MCP-серверы по stdio, получать их инструменты и отдавать их модели тем же
диспетчером, что и встроенные инструменты.

Модули:
- :mod:`prokop.mcp.client` — JSON-RPC 2.0 клиент к одному серверу;
- :mod:`prokop.mcp.config` — разбор секции ``mcp.servers`` профиля;
- :mod:`prokop.mcp.runtime` — владение клиентами и мост в реестр инструментов.
"""

from __future__ import annotations

from prokop.mcp.client import McpClient, McpError, McpTool
from prokop.mcp.config import McpServerConfig, parse_servers
from prokop.mcp.runtime import MCP_TOOLSET, McpRuntime, tool_name

__all__ = [
    "MCP_TOOLSET",
    "McpClient",
    "McpError",
    "McpRuntime",
    "McpServerConfig",
    "McpTool",
    "parse_servers",
    "tool_name",
]
