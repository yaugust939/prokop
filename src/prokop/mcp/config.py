"""Разбор секции ``mcp`` конфигурации профиля.

Формат (``config.yaml`` профиля):

```yaml
mcp:
  servers:
    files:
      command: ["python", "-m", "my_mcp_server"]   # список аргументов
      enabled: true
      env: {TOKEN: "..."}                          # необязательно
      cwd: "/path/to/workdir"                      # необязательно
      timeout: 30                                  # необязательно, секунды
```

Сервер считается выключенным, если признак ``enabled`` не задан явно.
Команда запуска задаётся списком аргументов: строковая форма не
принимается (никакой склейки в командную строку).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from prokop.logging_setup import get_logger
from prokop.mcp.client import DEFAULT_TIMEOUT

log = get_logger("mcp.config")

#: Ключ списка серверов внутри секции ``mcp``.
SERVERS_KEY = "servers"


@dataclass
class McpServerConfig:
    """Описание одного MCP-сервера из конфигурации профиля."""

    name: str
    command: list[str]
    enabled: bool = False
    env: dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    timeout: float = DEFAULT_TIMEOUT


def parse_servers(section: Any) -> dict[str, McpServerConfig]:
    """Разобрать секцию ``mcp`` в описания серверов.

    Битые описания пропускаются с предупреждением и не влияют на остальные.
    """
    if not isinstance(section, Mapping):
        return {}
    raw = section.get(SERVERS_KEY)
    if not isinstance(raw, Mapping):
        return {}

    servers: dict[str, McpServerConfig] = {}
    for name, spec in raw.items():
        if not isinstance(spec, Mapping):
            log.warning("MCP-сервер %s пропущен: описание не объект", name)
            continue

        command = spec.get("command")
        if isinstance(command, str):
            log.warning(
                "MCP-сервер %s пропущен: команда должна быть списком аргументов "
                "(склейка в строку не поддерживается)",
                name,
            )
            continue
        if not isinstance(command, (list, tuple)) or not command:
            log.warning("MCP-сервер %s пропущен: нет команды запуска", name)
            continue

        env = spec.get("env")
        timeout = spec.get("timeout")
        cwd = spec.get("cwd")

        servers[str(name)] = McpServerConfig(
            name=str(name),
            command=[str(part) for part in command],
            enabled=bool(spec.get("enabled", False)),
            env={str(k): str(v) for k, v in env.items()} if isinstance(env, Mapping) else {},
            cwd=str(cwd) if cwd else None,
            timeout=(
                float(timeout)
                if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0
                else DEFAULT_TIMEOUT
            ),
        )
    return servers
