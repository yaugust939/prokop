"""Наборы инструментов (toolsets) и их разрешение.

Наборы описываются декларативно: описание, список инструментов и
включаемые под-наборы. Поддерживаются композиция, рекурсивное разрешение,
детекция циклов, псевдонимы ``all``/``*`` и вычитание отключённых наборов.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from prokop.logging_setup import get_logger
from prokop.tools.registry import Tool, ToolRegistry, get_registry

log = get_logger("tools.toolsets")

#: Псевдоним «все наборы».
ALL_ALIASES = ("all", "*")


@dataclass
class Toolset:
    """Декларативное описание набора инструментов."""

    name: str
    description: str = ""
    tools: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)


class ToolsetError(Exception):
    """Ошибка композиции наборов."""


#: Базовые наборы. Ядро наследуется платформенными наборами.
DEFAULT_TOOLSETS: dict[str, Toolset] = {
    "core": Toolset(
        name="core",
        description="Общее ядро инструментов.",
        tools=[],
    ),
    "coding": Toolset(
        name="coding",
        description="Сценарий программирования.",
        includes=["core"],
        tools=[],
    ),
    "safe": Toolset(
        name="safe",
        description="Минимальный защищённый набор.",
        tools=[],
    ),
}


def register_toolset(toolset: Toolset, *, table: Optional[dict[str, Toolset]] = None) -> None:
    """Зарегистрировать набор в таблице (по умолчанию — глобальная)."""
    _active_table(table)[toolset.name] = toolset


def _active_table(table: Optional[dict[str, Toolset]]) -> dict[str, Toolset]:
    return table if table is not None else DEFAULT_TOOLSETS


def resolve_toolset(
    name: str,
    *,
    table: Optional[dict[str, Toolset]] = None,
    _seen: Optional[frozenset[str]] = None,
) -> list[str]:
    """Разрешить набор в плоский список имён инструментов.

    Рекурсивно раскрывает ``includes`` с детекцией циклов; дубли убираются
    с сохранением порядка.
    """
    active = _active_table(table)
    if name in ALL_ALIASES:
        names: list[str] = []
        for toolset in active.values():
            for tool in resolve_toolset(toolset.name, table=table):
                if tool not in names:
                    names.append(tool)
        return names
    toolset = active.get(name)
    if toolset is None:
        raise ToolsetError(f"Неизвестный набор: {name}")
    seen = _seen or frozenset()
    if name in seen:
        raise ToolsetError(f"Цикл в композиции наборов: {name}")
    seen = seen | {name}
    result: list[str] = []
    for included in toolset.includes:
        for tool in resolve_toolset(included, table=active, _seen=seen):
            if tool not in result:
                result.append(tool)
    for tool in toolset.tools:
        if tool not in result:
            result.append(tool)
    return result


def get_tool_definitions(
    enabled_toolsets: Optional[list[str]] = None,
    disabled_toolsets: Optional[list[str]] = None,
    *,
    registry: Optional[ToolRegistry] = None,
    table: Optional[dict[str, Toolset]] = None,
) -> list[dict]:
    """Собрать схемы инструментов по включённым/отключённым наборам.

    Включённые наборы объединяются, отключённые вычитаются в конце. В
    итоговую схему попадают только инструменты, чей ``check_fn`` вернул
    истину.
    """
    reg = registry or get_registry()
    enabled = enabled_toolsets or []
    disabled = disabled_toolsets or []

    names: list[str] = []
    for toolset_name in enabled:
        for tool in resolve_toolset(toolset_name, table=table):
            if tool not in names:
                names.append(tool)

    disabled_names: set[str] = set()
    for toolset_name in disabled:
        try:
            disabled_names.update(resolve_toolset(toolset_name, table=table))
        except ToolsetError:
            disabled_names.add(toolset_name)

    schemas: list[dict] = []
    for tool_name in names:
        if tool_name in disabled_names:
            continue
        tool = reg.get(tool_name)
        if tool is None:
            log.warning("Инструмент %s из набора не найден в реестре", tool_name)
            continue
        if not tool.is_available():
            continue
        schemas.append(tool.openai_schema())
    return schemas


def select_toolset_for_source(source: str, *, table: Optional[dict[str, Toolset]] = None) -> str:
    """Выбрать платформенный набор по источнику сессии.

    Возвращает платформенный набор, если он зарегистрирован, иначе ядро.
    """
    active = _active_table(table)
    platform_name = f"agent-cli" if source == "cli" else f"agent-{source}"
    if platform_name in active:
        return platform_name
    return "core"
