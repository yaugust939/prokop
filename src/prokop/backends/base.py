"""Абстрактный контракт терминального бэкенда."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from prokop.backends.result import CommandResult


class TerminalBackend(ABC):
    """Базовое окружение исполнения команд/файлов/кода.

    Одна команда — один новый процесс (спавн на вызов), без долгоживущего
    шелла. Конкретные бэкенды (локальный, контейнерный, удалённый,
    серверлесс) реализуют :meth:`run`.
    """

    name: str = "abstract"

    def __init__(
        self,
        *,
        workdir: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.workdir = workdir
        self.timeout = timeout

    @abstractmethod
    def run(
        self,
        command: str,
        *,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        env: Optional[dict[str, str]] = None,
    ) -> CommandResult:
        """Исполнить команду и вернуть результат.

        Инфраструктурный сбой поднимается как
        :class:`prokop.backends.errors.InfrastructureError` — он не
        кодируется кодом выхода команды.
        """
