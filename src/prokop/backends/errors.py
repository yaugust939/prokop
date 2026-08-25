"""Ошибки бэкендов.

Инфраструктурный сбой (хост недоступен, демон не запущен) — отдельный тип,
который никогда не путается с «команда вышла с кодом N».
"""

from __future__ import annotations


class InfrastructureError(Exception):
    """Ошибка подключения/инфраструктуры бэкенда."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause
