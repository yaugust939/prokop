"""Настройка логирования ядра — реэкспорт из :mod:`prokop.log`.

Модуль сохранён как тонкая совместимая обёртка: единая реализация живёт в
``prokop/log.py``, чтобы конфигурация логгера не расходилась между модулями.
"""

from __future__ import annotations

from .log import configure, get_logger

#: Корневой логгер ядра.
LOGGER_NAME = "prokop"

__all__ = ["LOGGER_NAME", "configure", "get_logger"]
