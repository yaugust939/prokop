"""Планировщик отложенных и периодических заданий (обвес, Фаза 1).

Подсистемы: модель задания, файловый магазин, разбор расписаний,
вычисление следующего запуска, тикер, исполнение «без агента»,
доставка результата. Реализовано по ``specs/cron`` без обращения к эталону.
"""

from prokop.cron.model import Job, JobError, validate_job
from prokop.cron.schedule import ScheduleSpec, ScheduleKind, parse_schedule, next_run
from prokop.cron.store import JobStore
from prokop.cron.ticker import Ticker, TickResult

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
