"""Утилита времени: timezone-aware «сейчас».

Порядок разрешения часового пояса: переменная окружения → конфигурация →
локальное время сервера. Результат кэшируется с возможностью сброса.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

ENV_TZ = "TZ"


@lru_cache(maxsize=None)
def _cached_tz(tz_key: str | None) -> ZoneInfo | timezone:
    """Разрешить IANA-пояс по ключу (кэшируется по ключу).

    При недоступности пояса (например, отсутствие данных tzdata в ОС)
    возвращается фиксированный UTC — код не должен падать на времени.
    """
    if tz_key:
        try:
            return ZoneInfo(tz_key)
        except (KeyError, ValueError):
            pass
    try:
        return ZoneInfo(os.environ.get(ENV_TZ) or "UTC")
    except (KeyError, ValueError):
        return timezone.utc


def configured_tz_name(config_tz: str | None = None) -> str:
    """Имя активного пояса: env TZ → config → UTC."""
    return os.environ.get(ENV_TZ) or config_tz or "UTC"


def now(config_tz: str | None = None) -> datetime:
    """Текущее время с часовым поясом.

    Порядок: переменная окружения ``TZ`` → пояс из конфигурации →
    локальное время сервера (аппроксимируется ``UTC``).
    """
    tz = _cached_tz(configured_tz_name(config_tz))
    return datetime.now(tz=tz)


def utcnow() -> datetime:
    """Текущее время в UTC."""
    return datetime.now(tz=timezone.utc)


def reset_cache() -> None:
    """Сбросить кэш поясов (для тестов)."""
    _cached_tz.cache_clear()
