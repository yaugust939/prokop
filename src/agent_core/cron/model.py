"""Модель задания планировщика и валидация."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from agent_core.cron.schedule import ScheduleSpec


class JobError(Exception):
    """Ошибка задания планировщика."""


@dataclass
class Job:
    """Задание планировщика."""

    id: str
    name: str
    prompt: Optional[str] = None
    schedule: Optional[ScheduleSpec] = None
    next_run: Optional[str] = None          # ISO-время
    repeat_count: int = 1                   # -1 = бесконечно
    delivery_target: str = "локально"
    source: Optional[str] = None
    no_agent: bool = False
    script: Optional[str] = None
    paused: bool = False
    error_count: int = 0
    created_at: Optional[str] = None
    last_run_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schedule"] = self.schedule.to_dict() if self.schedule else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        schedule = None
        if data.get("schedule"):
            schedule = ScheduleSpec.from_dict(data["schedule"])
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**{**filtered, "schedule": schedule})


def new_job_id() -> str:
    """Короткое шестнадцатеричное имя задания."""
    return secrets.token_hex(4)


def validate_job(job: Job) -> None:
    """Валидация при создании.

    Пустой полезный груз запрещён; «без агента» требует скрипт; задание
    должно иметь расписание.
    """
    if not job.prompt and not job.script:
        raise JobError("Пустой полезный груз: нужен промпт или скрипт")
    if job.no_agent and not job.script:
        raise JobError("Режим «без агента» требует скрипт")
    if job.schedule is None:
        raise JobError("Задание должно иметь расписание")
