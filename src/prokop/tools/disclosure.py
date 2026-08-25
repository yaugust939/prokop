"""Прогрессивное раскрытие инструментов.

Когда «откладываемая» поверхность (не-ядровые инструменты) превышает
порог контекстного окна, они сворачиваются за три «мостовых» инструмента:
поиск каталога, описание инструмента и вызов инструмента. Ядро никогда не
откладывается.
"""

from __future__ import annotations

import json
from typing import Any

from prokop.tools.registry import Tool

#: Доля контекстного окна, после которой начинается откладывание.
DEFAULT_DEFERRAL_THRESHOLD = 0.10

#: Приблизительная цена одной схемы в символах.
SCHEMA_COST_CHARS = 120


def estimate_surface(schemas: list[dict[str, Any]]) -> int:
    """Оценка размера поверхности (в символах)."""
    return sum(len(json.dumps(s, ensure_ascii=False)) for s in schemas)


def should_defer(
    schemas: list[dict[str, Any]],
    context_window_chars: int,
    *,
    threshold: float = DEFAULT_DEFERRAL_THRESHOLD,
) -> bool:
    """Нужно ли сворачивать не-ядровые инструменты."""
    if context_window_chars <= 0:
        return False
    return estimate_surface(schemas) > threshold * context_window_chars


def split_schemas(
    schemas: list[dict[str, Any]],
    core_tools: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Разделить схемы на ядро (всегда развёрнуто) и откладываемые."""
    core = [s for s in schemas if s["function"]["name"] in core_tools]
    deferred = [s for s in schemas if s["function"]["name"] not in core_tools]
    return core, deferred


def bridge_tool_schemas() -> list[dict[str, Any]]:
    """Схемы трёх мостовых инструментов."""
    return [
        {
            "type": "function",
            "function": {
                "name": "tool_search",
                "description": "Найти доступные инструменты по запросу.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_describe",
                "description": "Показать полную схему инструмента.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_invoke",
                "description": "Вызвать отложенный инструмент по имени.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "args": {"type": "object"},
                    },
                    "required": ["name"],
                },
            },
        },
    ]


def apply_disclosure(
    schemas: list[dict[str, Any]],
    context_window_chars: int,
    core_tools: set[str],
    *,
    threshold: float = DEFAULT_DEFERRAL_THRESHOLD,
) -> list[dict[str, Any]]:
    """Применить прогрессивное раскрытие к списку схем.

    Если порог не превышен, возвращается исходный список. Иначе не-ядровые
    схемы заменяются тремя мостовыми инструментами.
    """
    core, deferred = split_schemas(schemas, core_tools)
    if not deferred or not should_defer(deferred, context_window_chars, threshold=threshold):
        return schemas
    return core + bridge_tool_schemas()
