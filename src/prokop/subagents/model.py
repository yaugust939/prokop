"""Модели данных субагентов: статус, результат, запись реестра."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from prokop.subagents.roles import Role


class SubagentStatus(str, Enum):
    """Статус субагента/делегирования."""

    RUNNING = "running"
    DONE = "done"
    #: Бюджет итераций исчерпан, есть частичная сводка.
    TRUNCATED = "truncated"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class SubagentResult:
    """Самодостаточный результат делегирования.

    Не требует истории родителя для интерпретации: цель, контекст, статус,
    сводка, учёт вызовов модели, имя модели и ошибка.
    """

    goal: str
    context: str = ""
    role: str = Role.LEAF.value
    status: str = SubagentStatus.DONE.value
    summary: str = ""
    api_calls: int = 0
    model: str = ""
    error: Optional[str] = None
    subagent_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "goal": self.goal,
            "context": self.context,
            "role": self.role,
            "status": self.status,
            "summary": self.summary,
            "api_calls": self.api_calls,
            "model": self.model,
            "error": self.error,
            "subagent_id": self.subagent_id,
        }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubagentResult":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class SubagentRecord:
    """Запись активного субагента в реестре."""

    id: str
    goal: str
    role: str = Role.LEAF.value
    owner: Optional[str] = None
    status: str = SubagentStatus.RUNNING.value
    progress: str = ""

    #: Потокобезопасное состояние управления (мутируется только под замком).
    steer_texts: list[str] = field(default_factory=list, init=False, repr=False)
    stop_requested: bool = field(default=False, init=False, repr=False)

    def snapshot(self) -> dict[str, Any]:
        """Публичное представление записи (без внутреннего состояния)."""
        return {
            "id": self.id,
            "goal": self.goal,
            "role": self.role,
            "owner": self.owner,
            "status": self.status,
            "progress": self.progress,
            "stop_requested": self.stop_requested,
        }


def new_subagent_id() -> str:
    """Короткое шестнадцатеричное имя субагента."""
    return secrets.token_hex(4)
