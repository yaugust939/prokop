"""Изоляция ребёнка: заблокированные инструменты, тулсеты и промпт.

Ребёнок не видит историю родителя и получает собственный системный промпт
из цели и контекста. Тулсеты ребёнка — это тулсеты родителя за вычетом
заблокированных инструментов; оркестратору (при включённом оркестраторстве)
инструмент делегирования возвращается.
"""

from __future__ import annotations

from typing import Iterable, Optional

from prokop.subagents.roles import Role

#: Инструменты, всегда заблокированные у детей (по имени функции).
#: Делегирование, уточнение у пользователя, запись в общую память, отправка
#: сообщений на платформы и создание заданий планировщика.
BLOCKED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "delegate",
        "delegate_task",
        "ask_user",
        "clarify",
        "memory_write",
        "memory_remember",
        "memory_set",
        "send_message",
        "post_message",
        "schedule_job",
        "create_job",
        "schedule",
    }
)


def _tool_name(tool: dict) -> str:
    function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    return str(function.get("name") or "")


def filter_child_tools(
    parent_tools: Iterable[dict],
    *,
    role: str | Role = Role.LEAF.value,
    orchestration_enabled: bool = False,
    delegation_tool: Optional[dict] = None,
    blocked: Optional[Iterable[str]] = None,
) -> list[dict]:
    """Тулсеты ребёнка: родительские за вычетом заблокированных.

    Оркестратору (при включённом оркестраторстве) добавляется инструмент
    делегирования обратно в конец списка.
    """
    blocked_names = set(blocked if blocked is not None else BLOCKED_TOOL_NAMES)
    tools: list[dict] = []
    for tool in parent_tools:
        if _tool_name(tool) in blocked_names:
            continue
        tools.append(tool)
    if str(role) == Role.ORCHESTRATOR.value and orchestration_enabled and delegation_tool is not None:
        tools.append(delegation_tool)
    return tools


def build_child_system_prompt(
    *,
    goal: str,
    context: str = "",
    role: str | Role = Role.LEAF.value,
) -> str:
    """Системный промпт ребёнка: цель + контекст + роль."""
    sections: list[str] = [f"Цель: {goal.strip()}"]
    if context and context.strip():
        sections.append(f"Контекст:\n{context.strip()}")
    sections.append(f"Роль: {str(role)}")
    return "\n\n".join(sections)
