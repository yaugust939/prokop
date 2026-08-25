"""Планировщик отложенных и периодических заданий (обвес, Фаза 1).

Подсистемы: модель задания, файловый магазин, разбор расписаний,
вычисление следующего запуска, тикер, исполнение «без агента»,
доставка результата. Реализовано по ``specs/cron`` без обращения к эталону.
"""

from agent_core.cron.model import Job, JobError, validate_job
from agent_core.cron.schedule import ScheduleSpec, ScheduleKind, parse_schedule, next_run
from agent_core.cron.store import JobStore
from agent_core.cron.ticker import Ticker, TickResult

__all__ = [
    "Job",
    "JobError",
    "validate_job",
    "ScheduleSpec",
    "ScheduleKind",
    "parse_schedule",
    "next_run",
    "JobStore",
    "Ticker",
    "TickResult",
]
