"""Разбор расписаний и вычисление следующего запуска.

Поддерживаются четыре формы строки расписания: длительность (разовое),
фраза «каждые …» (повторное с интервалом), пяти-полевое крон-выражение и
ISO-отметка времени. Произвольные фразы вне этих форм отклоняются.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional


class ScheduleKind(Enum):
    ONCE = "once"          # разовое «через столько-то»
    INTERVAL = "interval"  # повторное с интервалом
    CRON = "cron"          # крон-выражение
    AT = "at"              # разовое в момент


class ScheduleError(Exception):
    """Ошибка разбора расписания."""


@dataclass
class ScheduleSpec:
    """Структура расписания."""

    kind: ScheduleKind
    minutes: Optional[int] = None          # для once/interval
    cron_expr: Optional[str] = None        # для cron
    at: Optional[str] = None               # ISO для at
    display: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "minutes": self.minutes,
            "cron_expr": self.cron_expr,
            "at": self.at,
            "display": self.display,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleSpec":
        return cls(
            kind=ScheduleKind(data["kind"]),
            minutes=data.get("minutes"),
            cron_expr=data.get("cron_expr"),
            at=data.get("at"),
            display=data.get("display", ""),
        )


#: Единицы длительности (русские и английские) в минутах.
_UNITS = {
    "м": 1, "мин": 1, "минута": 1, "минуты": 1,
    "m": 1, "min": 1,
    "ч": 60, "час": 60, "часа": 60, "часов": 60,
    "h": 60, "hr": 60,
    "д": 1440, "день": 1440, "дня": 1440, "дней": 1440,
    "d": 1440, "day": 1440, "days": 1440,
}

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([а-яА-ЯёЁa-zA-Z]+)\s*$")
_EVERY_RE = re.compile(r"^\s*(?:каждые|каждый|каждая)\s+(\d+)\s*([а-яА-ЯёЁa-zA-Z]+)\s*$", re.IGNORECASE)


def _parse_duration_minutes(text: str) -> Optional[int]:
    """«30м», «2ч», «1д» → минуты; ``None``, если не длительность."""
    match = _DURATION_RE.match(text)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2).lower()
    if unit not in _UNITS:
        return None
    return value * _UNITS[unit]


def _is_cron_expr(text: str) -> bool:
    """Пяти- (и более) полевое крон-выражение."""
    parts = text.split()
    return len(parts) >= 5


def _validate_cron_expr(expr: str) -> None:
    """Валидация формы крон-выражения (5 полей)."""
    parts = expr.split()
    if len(parts) != 5:
        raise ScheduleError(f"Крон-выражение должно иметь 5 полей, получено {len(parts)}")
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    for part, (lo, hi) in zip(parts, ranges):
        _validate_cron_field(part, lo, hi)


def _validate_cron_field(field: str, lo: int, hi: int) -> None:
    for atom in field.split(","):
        atom = atom.strip()
        if atom == "*":
            continue
        if atom.startswith("*/"):
            step = atom[2:]
            if not step.isdigit() or int(step) < 1:
                raise ScheduleError(f"Неверный шаг в крон-поле: {atom}")
            continue
        if "-" in atom:
            a, b = atom.split("-")
            if not (a.isdigit() and b.isdigit()):
                raise ScheduleError(f"Неверный диапазон в крон-поле: {atom}")
            if not (lo <= int(a) <= hi and lo <= int(b) <= hi):
                raise ScheduleError(f"Диапазон вне пределов в крон-поле: {atom}")
            continue
        if not atom.isdigit() or not (lo <= int(atom) <= hi):
            raise ScheduleError(f"Неверное значение в крон-поле: {atom}")


def parse_schedule(text: str, now: Optional[datetime] = None) -> ScheduleSpec:
    """Разобрать строку расписания в структуру.

    Порядок распознавания: «каждые …» → длительность → крон-выражение →
    ISO-время. Всё остальное отклоняется.
    """
    text = (text or "").strip()
    if not text:
        raise ScheduleError("Пустая строка расписания")
    now = now or datetime.now()

    every = _EVERY_RE.match(text)
    if every:
        minutes = int(every.group(1)) * _UNITS.get(every.group(2).lower(), 0)
        if not minutes:
            raise ScheduleError(f"Неизвестная единица в «каждые»: {text}")
        return ScheduleSpec(
            kind=ScheduleKind.INTERVAL,
            minutes=minutes,
            display=f"каждые {every.group(1)} {every.group(2)}",
        )

    duration = _parse_duration_minutes(text)
    if duration is not None:
        return ScheduleSpec(
            kind=ScheduleKind.ONCE,
            minutes=duration,
            display=f"через {text}",
        )

    if _is_cron_expr(text):
        _validate_cron_expr(text)
        return ScheduleSpec(kind=ScheduleKind.CRON, cron_expr=text, display=f"cron: {text}")

    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ScheduleError(f"Не удалось распознать расписание: {text}") from exc
    return ScheduleSpec(kind=ScheduleKind.AT, at=moment.isoformat(), display=f"в {text}")


def next_run(spec: ScheduleSpec, from_dt: datetime) -> Optional[datetime]:
    """Вычислить следующий запуск от структуры и опорного момента."""
    if spec.kind is ScheduleKind.ONCE:
        return from_dt + timedelta(minutes=spec.minutes or 0)
    if spec.kind is ScheduleKind.INTERVAL:
        return from_dt + timedelta(minutes=spec.minutes or 0)
    if spec.kind is ScheduleKind.AT:
        return datetime.fromisoformat(spec.at) if spec.at else None
    if spec.kind is ScheduleKind.CRON:
        return _next_cron(spec.cron_expr or "", from_dt)
    return None


# --- крон-итератор --------------------------------------------------------


def _cron_field_values(field: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for atom in field.split(","):
        atom = atom.strip()
        if atom == "*":
            values.update(range(lo, hi + 1))
        elif atom.startswith("*/"):
            values.update(range(lo, hi + 1, int(atom[2:])))
        elif "-" in atom:
            a, b = atom.split("-")
            values.update(range(int(a), int(b) + 1))
        elif atom.isdigit():
            values.add(int(atom))
    return {v for v in values if lo <= v <= hi}


def _next_cron(expr: str, from_dt: datetime, horizon_days: int = 400) -> Optional[datetime]:
    """Следующий момент, удовлетворяющий крон-выражению (перебор по дням)."""
    parts = expr.split()
    if len(parts) != 5:
        return None
    minutes = _cron_field_values(parts[0], 0, 59)
    hours = _cron_field_values(parts[1], 0, 23)
    days = _cron_field_values(parts[2], 1, 31)
    months = _cron_field_values(parts[3], 1, 12)
    weekdays = _cron_field_values(parts[4], 0, 7)
    # Крон: 0 и 7 = воскресенье; приводим 7 к 0.
    if 7 in weekdays:
        weekdays.add(0)
    if not minutes or not hours:
        return None

    start = from_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    day = start
    for _ in range(horizon_days):
        day = day.replace(hour=0, minute=0) if day != start else day
        if day.month in months and day.day in days and _cron_weekday(day) in weekdays:
            for hour in sorted(hours):
                for minute in sorted(minutes):
                    candidate = day.replace(hour=hour, minute=minute)
                    if candidate >= start:
                        return candidate
        day = day + timedelta(days=1)
    return None


def _cron_weekday(day: datetime) -> int:
    """День недели в крон-конвенции (0 = воскресенье)."""
    return (day.weekday() + 1) % 7
