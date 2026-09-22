"""Рантайм MCP: владение клиентами и мост инструментов в реестр ядра.

Инструменты внешних серверов регистрируются в общем реестре инструментов
под именами ``mcp__<сервер>__<инструмент>`` и вызываются тем же
диспетчером, что и встроенные инструменты. Соответствие имени в реестре и
исходного имени на сервере сохраняется, поэтому вызов уходит под исходным
именем.

Недоступный сервер не ломает ядро: он пропускается с предупреждением, его
инструменты не регистрируются, остальные серверы продолжают работать.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from prokop.logging_setup import get_logger
from prokop.mcp.client import McpClient, McpError
from prokop.mcp.config import McpServerConfig
from prokop.tools.registry import Tool, ToolRegistry, get_registry
from prokop.tools.toolsets import Toolset, register_toolset

log = get_logger("mcp.runtime")

#: Имя набора инструментов для внешних MCP-инструментов.
MCP_TOOLSET = "mcp"

#: Префикс имени инструмента в реестре.
NAME_PREFIX = "mcp__"

#: Разделитель между сервером и инструментом.
NAME_SEPARATOR = "__"

#: Символы, недопустимые в имени функции модели.
_INVALID_RE = re.compile(r"[^A-Za-z0-9_-]")


def sanitize(part: str) -> str:
    """Привести часть имени к допустимым символам."""
    cleaned = _INVALID_RE.sub("_", part)
    return cleaned or "unnamed"


def tool_name(server: str, tool: str) -> str:
    """Имя инструмента в реестре: ``mcp__<сервер>__<инструмент>``."""
    return f"{NAME_PREFIX}{sanitize(server)}{NAME_SEPARATOR}{sanitize(tool)}"


@dataclass
class McpRuntime:
    """Владеет клиентами включённых серверов и регистрирует их инструменты."""

    servers: dict[str, McpServerConfig] = field(default_factory=dict)
    registry: Optional[ToolRegistry] = None
    #: Переопределение таймаута для всех серверов.
    timeout: Optional[float] = None
    _clients: dict[str, McpClient] = field(default_factory=dict, init=False)
    #: Имя в реестре → (сервер, исходное имя инструмента).
    _routes: dict[str, tuple[str, str]] = field(default_factory=dict, init=False)

    async def start(self) -> list[str]:
        """Поднять включённые серверы и зарегистрировать их инструменты."""
        registered: list[str] = []
        for server in self.servers.values():
            if not server.enabled:
                continue
            try:
                registered.extend(await self._start_server(server))
            except Exception as exc:  # noqa: BLE001 — недоступный сервер не роняет ядро
                log.warning("MCP-сервер %s недоступен: %s", server.name, exc)
        return registered

    async def _start_server(self, server: McpServerConfig) -> list[str]:
        client = McpClient(
            server.name,
            server.command,
            env=server.env,
            cwd=server.cwd,
            timeout=self.timeout or server.timeout,
        )
        await client.start()
        await client.initialize()
        tools = await client.list_tools()
        self._clients[server.name] = client

        registry = self.registry or get_registry()
        names: list[str] = []
        for tool in tools:
            registry_name = tool_name(server.name, tool.name)
            self._routes[registry_name] = (server.name, tool.name)
            registry.register(
                Tool(
                    name=registry_name,
                    toolset=MCP_TOOLSET,
                    schema={
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                    handler=self._make_handler(server.name, tool.name),
                    is_async=True,
                ),
                override=True,
            )
            names.append(registry_name)

        self._publish_toolset(names)
        return names

    def _make_handler(self, server: str, tool: str):
        async def handler(**kwargs: Any) -> str:
            return await self.call(server, tool, kwargs)

        return handler

    @staticmethod
    def _publish_toolset(names: list[str]) -> None:
        """Опубликовать зарегистрированные имена в наборе ``mcp``."""
        from prokop.tools.toolsets import DEFAULT_TOOLSETS

        existing = DEFAULT_TOOLSETS.get(MCP_TOOLSET)
        current = list(existing.tools) if existing else []
        for name in names:
            if name not in current:
                current.append(name)
        register_toolset(
            Toolset(
                name=MCP_TOOLSET,
                description="Инструменты внешних MCP-серверов.",
                tools=current,
            )
        )

    async def call(
        self,
        server: str,
        tool: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> str:
        """Вызвать инструмент сервера (исходное имя инструмента)."""
        client = self._clients.get(server)
        if client is None:
            raise McpError(f"{server}: сервер не запущен")
        return await client.call_tool(tool, arguments or {})

    async def call_registered(
        self, registry_name: str, arguments: Optional[dict[str, Any]] = None
    ) -> str:
        """Вызвать инструмент по имени в реестре."""
        route = self._routes.get(registry_name)
        if route is None:
            raise McpError(f"неизвестный инструмент MCP: {registry_name}")
        server, tool = route
        return await self.call(server, tool, arguments)

    @property
    def routes(self) -> dict[str, tuple[str, str]]:
        """Карта «имя в реестре → (сервер, инструмент)»."""
        return dict(self._routes)

    @property
    def running(self) -> list[str]:
        """Имена поднятых серверов."""
        return sorted(self._clients)

    async def aclose(self) -> None:
        """Закрыть все клиенты (идемпотентно)."""
        for client in list(self._clients.values()):
            try:
                await client.close()
            except Exception as exc:  # noqa: BLE001 — закрытие не должно падать
                log.warning("MCP-сервер %s: ошибка закрытия: %s", client.name, exc)
        self._clients.clear()
