"""Роли субагентов и валидация глубины вложенности."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Роль субагента."""

    #: Исполнитель без права делегировать.
    LEAF = "leaf"
    #: Получает инструмент делегирования обратно.
    ORCHESTRATOR = "orchestrator"


class RoleError(Exception):
    """Ошибка роли или глубины вложенности."""


class DepthError(RoleError):
    """Превышена разрешённая глубина вложенности."""


def normalize_max_depth(value: int) -> int:
    """Привести глубину к нижней границе 1."""
    return max(1, int(value))


def resolve_role(requested: str | Role | None, *, orchestration_enabled: bool) -> Role:
    """Определить фактическую роль субагента.

    Неизвестная роль трактуется как лист. Роль оркестратора при выключенном
    оркестраторстве молча понижается до листа.
    """
    try:
        role = Role(requested)
    except (ValueError, TypeError):
        role = Role.LEAF
    if role is Role.ORCHESTRATOR and not orchestration_enabled:
        return Role.LEAF
    return role


def validate_depth(child_depth: int, max_depth: int) -> None:
    """Отклонить порождение глубже разрешённой глубины."""
    if child_depth > normalize_max_depth(max_depth):
        raise DepthError(
            f"Глубина вложенности {child_depth} превышает разрешённую "
            f"{normalize_max_depth(max_depth)}"
        )
