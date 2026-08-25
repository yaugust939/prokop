"""Конфигурация подсистемы субагентов.

Параметры: максимальная глубина вложенности (нижняя граница 1), включено
ли оркестраторство (роль «оркестратор» получает инструмент делегирования)
и потолок одновременных детей.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SubagentsConfig:
    """Конфигурация делегирования."""

    #: Максимальная глубина вложенности; нижняя граница — 1.
    max_depth: int = 1
    #: Разрешена ли роль «оркестратор» (повторное делегирование вниз).
    orchestration_enabled: bool = False
    #: Потолок одновременных активных детей.
    max_children: int = 4

    def __post_init__(self) -> None:
        self.max_depth = max(1, int(self.max_depth))
        self.max_children = max(1, int(self.max_children))
