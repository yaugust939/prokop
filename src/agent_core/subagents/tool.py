"""Инструмент делегирования (OpenAI function-calling).

Один инструмент с управляющими действиями: породить (одиночную цель или
пакет задач), список активных субагентов, подрулить, остановить.
Делегирование всегда асинхронно: вызов сразу возвращает идентификатор
делегирования и субагентов, результат приходит позже через очередь.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from agent_core.tools.registry import Tool

DELEGATION_TOOL_NAME = "delegate"

DELEGATION_TOOL_DESCRIPTION = (
    "Поручи подзадачу другому агенту или управляй активными субагентами. "
    "Действия: spawn — породить субагента (одиночная цель либо пакет задач, "
    "исполняемый параллельно); list — список активных субагентов; steer — "
    "подрулить субагента по id; stop — остановить субагента по id. "
    "Делегирование асинхронно: результат приходит отдельно."
)

DELEGATION_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["spawn", "list", "steer", "stop"],
            "description": "Управляющее действие.",
        },
        "goal": {
            "type": "string",
            "description": "Цель одной порождаемой задачи (для action=spawn).",
        },
        "context": {
            "type": "string",
            "description": "Дополнительный контекст для задачи.",
        },
        "role": {
            "type": "string",
            "enum": ["leaf", "orchestrator"],
            "description": "Роль субагента (по умолчанию leaf).",
        },
        "tasks": {
            "type": "array",
            "description": "Пакет задач для параллельного исполнения.",
            "items": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "context": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": ["leaf", "orchestrator"],
                    },
                },
                "required": ["goal"],
            },
        },
        "subagent_id": {
            "type": "string",
            "description": "Идентификатор субагента (для action=steer/stop).",
        },
        "steer": {
            "type": "string",
            "description": "Текст подруливания (для action=steer).",
        },
    },
    "required": ["action"],
}


def delegation_tool_schema() -> dict[str, Any]:
    """Полная схема инструмента в формате OpenAI function-calling."""
    return {
        "type": "function",
        "function": {
            "name": DELEGATION_TOOL_NAME,
            "description": DELEGATION_TOOL_DESCRIPTION,
            "parameters": DELEGATION_PARAMETERS,
        },
    }


def build_delegation_handler(engine: Any) -> Callable[..., Awaitable[str]]:
    """Собрать обработчик инструмента, привязанный к движку делегирования."""

    async def handler(**kwargs: Any) -> str:
        action = kwargs.pop("action", "list")
        payload = await engine.handle_action(action, **kwargs)
        return json.dumps(payload, ensure_ascii=False)

    return handler


def make_delegation_tool(engine: Any, *, toolset: str = "core") -> Tool:
    """Запись инструмента делегирования для реестра инструментов."""
    return Tool(
        name=DELEGATION_TOOL_NAME,
        toolset=toolset,
        schema={
            "description": DELEGATION_TOOL_DESCRIPTION,
            "parameters": DELEGATION_PARAMETERS,
        },
        handler=build_delegation_handler(engine),
        is_async=True,
    )
